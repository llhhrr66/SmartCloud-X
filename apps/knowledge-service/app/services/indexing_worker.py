from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

try:
    import pymysql
except ImportError:  # pragma: no cover - exercised in integration environments
    pymysql = None

try:
    import redis
except ImportError:  # pragma: no cover - exercised in integration environments
    redis = None

try:
    from minio import Minio
except ImportError:  # pragma: no cover - exercised in integration environments
    Minio = None

from app.core.config import Settings, get_settings
from app.core.metrics import INDEX_CONNECTOR_WRITES_TOTAL, INDEX_WORKER_RUNS_TOTAL
from app.core.tracing import get_tracer_provider, start_span
from app.models.admin import KnowledgeDocumentProfile
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.models.runtime import ConnectorWriteResult, IndexingOutboxEvent
from app.services.embeddings import build_embedding_provider
from app.services.index_targets import KnowledgeIndexTargetResolver
from app.services.runtime_sync import KnowledgeRuntimeSyncService, get_runtime_sync_service, utc_now
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository



@dataclass(frozen=True)
class EventContext:
    event: IndexingOutboxEvent
    source: KnowledgeSource
    document: KnowledgeDocument
    document_profile: KnowledgeDocumentProfile | None
    chunks: list[KnowledgeChunk]


def _default_processor_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _sanitize_mysql_identifier(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]", "_", value.strip())
    if not normalized:
        raise ValueError("MySQL table name is empty after sanitization")
    return normalized


def _normalized_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme and parsed.netloc:
        return endpoint.rstrip("/")
    return f"http://{endpoint.strip().rstrip('/')}"


def _target_label(value: str | None, fallback: str) -> str:
    return value if isinstance(value, str) and value.strip() else fallback


class KnowledgeIndexingWorkerService:
    def __init__(
        self,
        repository: KnowledgeStoreRepository,
        runtime_sync_service: KnowledgeRuntimeSyncService,
        *,
        settings: Settings | None = None,
    ) -> None:
        self.repository = repository
        self.runtime_sync_service = runtime_sync_service
        self.settings = settings or get_settings()
        self.embedding_provider = build_embedding_provider(self.settings)
        self.target_resolver = KnowledgeIndexTargetResolver(self.settings)

    def process_next_event(self, processor_id: str | None = None) -> IndexingOutboxEvent | None:
        event = self.runtime_sync_service.claim_next_event(processor_id or _default_processor_id())
        if event is None:
            return None

        connector_results: list[ConnectorWriteResult] = []
        with start_span(
            "knowledge.indexing.process_event",
            smartcloud_index_event_id=event.event_id,
            smartcloud_index_operation=event.operation,
            smartcloud_index_doc_id=event.doc_id,
            smartcloud_index_kb_id=event.kb_id,
            smartcloud_index_queue_name=event.queue_name,
        ):
            try:
                context = self._load_event_context(event)
            except Exception as exc:  # noqa: BLE001 - worker must fail the event, not crash
                INDEX_WORKER_RUNS_TOTAL.labels(outcome="failed").inc()
                return self.runtime_sync_service.mark_event_failed(
                    event.event_id,
                    f"event context unavailable: {exc}",
                    connector_results=connector_results,
                )

            for connector_name, backend, target, handler in self._connector_steps(context):
                with start_span(
                    f"knowledge.indexing.{connector_name}",
                    smartcloud_connector_name=connector_name,
                    smartcloud_connector_backend=backend,
                    smartcloud_connector_target=target,
                ):
                    try:
                        result = handler(context)
                    except Exception as exc:  # noqa: BLE001 - connector failure should be persisted on the event
                        result = self._build_result(
                            connector=connector_name,
                            backend=backend,
                            status="failed",
                            target=target,
                            detail=str(exc),
                        )
                        connector_results.append(result)
                        INDEX_CONNECTOR_WRITES_TOTAL.labels(
                            connector=connector_name,
                            outcome="failed",
                        ).inc()
                        INDEX_WORKER_RUNS_TOTAL.labels(outcome="failed").inc()
                        return self.runtime_sync_service.mark_event_failed(
                            event.event_id,
                            f"{connector_name} failed: {exc}",
                            connector_results=connector_results,
                        )

                connector_results.append(result)
                INDEX_CONNECTOR_WRITES_TOTAL.labels(
                    connector=connector_name,
                    outcome=result.status,
                ).inc()

        INDEX_WORKER_RUNS_TOTAL.labels(outcome="success").inc()
        return self.runtime_sync_service.mark_event_completed(
            event.event_id,
            connector_results=connector_results,
        )

    def process_available(
        self,
        *,
        limit: int | None = None,
        processor_id: str | None = None,
    ) -> int:
        processed = 0
        max_events = limit if isinstance(limit, int) and limit > 0 else self.settings.index_worker_batch_size
        for _ in range(max_events):
            event = self.process_next_event(processor_id=processor_id)
            if event is None:
                break
            processed += 1
        return processed

    @staticmethod
    def flush_traces() -> None:
        provider = get_tracer_provider()
        if provider is None:
            return
        provider.force_flush()

    def _connector_steps(self, context: EventContext):
        queue_target = f"{self.settings.redis_namespace}:{self.settings.task_queue_name}"
        targets = self.target_resolver.resolve_for_document(
            context.document,
            context.source,
            context.chunks,
        )
        return (
            (
                "raw_object_sync",
                "minio" if self.settings.minio_endpoint and self.settings.minio_bucket else "local-mirror",
                _target_label(self.settings.minio_bucket, str(self.settings.raw_mirror_root)),
                self._sync_raw_object,
            ),
            (
                "metadata_upsert",
                "mysql" if self.settings.mysql_dsn else "json-runtime-store",
                _target_label(self.settings.mysql_table, "knowledge_documents"),
                self._sync_metadata_store,
            ),
            (
                "vector_upsert",
                "qdrant" if self.settings.qdrant_url else "planner-only",
                targets.qdrant_collection,
                self._sync_vector_store,
            ),
            (
                "bm25_upsert",
                "opensearch" if self.settings.opensearch_url else "keyword-baseline",
                targets.opensearch_index,
                self._sync_bm25_store,
            ),
            (
                "queue_publish",
                "redis-list" if self.settings.redis_url else "jsonl-outbox",
                queue_target,
                self._publish_queue_state,
            ),
        )

    def _load_event_context(self, event: IndexingOutboxEvent) -> EventContext:
        document = self.repository.get_document(event.doc_id)
        if document is None:
            raise ValueError(f"unknown document {event.doc_id}")
        source = self.repository.get_source(document.source_id)
        if source is None:
            raise ValueError(f"unknown source {document.source_id}")
        return EventContext(
            event=event,
            source=source,
            document=document,
            document_profile=self.repository.get_document_profile(document.id),
            chunks=self.repository.list_chunks(document_id=document.id),
        )

    def _sync_raw_object(self, context: EventContext) -> ConnectorWriteResult:
        if not (self.settings.minio_endpoint and self.settings.minio_bucket):
            return self._build_result(
                connector="raw_object_sync",
                backend="local-mirror",
                status="skipped",
                target=str(self.settings.raw_mirror_root),
                detail="raw mirror already written during ingestion",
                item_count=1,
            )
        if Minio is None:
            raise RuntimeError("minio client dependency is unavailable")
        if not (self.settings.minio_access_key and self.settings.minio_secret_key):
            raise RuntimeError("SMARTCLOUD_MINIO_ACCESS_KEY and SMARTCLOUD_MINIO_SECRET_KEY are required")

        parsed = urlparse(_normalized_endpoint(self.settings.minio_endpoint))
        client = Minio(
            parsed.netloc,
            access_key=self.settings.minio_access_key,
            secret_key=self.settings.minio_secret_key,
            secure=parsed.scheme == "https",
        )
        bucket = self.settings.minio_bucket
        mirror_path = Path(context.event.raw_object.mirror_path)
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        client.fput_object(
            bucket,
            context.event.raw_object.object_key,
            str(mirror_path),
            content_type=context.event.raw_object.content_type,
        )
        return self._build_result(
            connector="raw_object_sync",
            backend="minio",
            status="succeeded",
            target=f"{bucket}/{context.event.raw_object.object_key}",
            detail="uploaded raw document mirror to MinIO",
            item_count=1,
        )

    def _sync_metadata_store(self, context: EventContext) -> ConnectorWriteResult:
        if not self.settings.mysql_dsn:
            return self._build_result(
                connector="metadata_upsert",
                backend="json-runtime-store",
                status="skipped",
                target=self.settings.mysql_table,
                detail="mysql metadata store is not configured",
                item_count=1,
            )
        if pymysql is None:
            raise RuntimeError("PyMySQL dependency is unavailable")

        table_name = _sanitize_mysql_identifier(self.settings.mysql_table)
        params = self._mysql_connection_params()
        connection = pymysql.connect(**params)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS `{table_name}` (
                      doc_id VARCHAR(64) PRIMARY KEY,
                      kb_id VARCHAR(64) NOT NULL,
                      source_id VARCHAR(64) NOT NULL,
                      title VARCHAR(255) NOT NULL,
                      language VARCHAR(32) NOT NULL,
                      source_type VARCHAR(64) NOT NULL,
                      source_uri TEXT NULL,
                      tags_json JSON NOT NULL,
                      chunk_count INT NOT NULL,
                      latest_job_id VARCHAR(64) NULL,
                      checksum VARCHAR(64) NOT NULL,
                      raw_object_bucket VARCHAR(255) NULL,
                      raw_object_key TEXT NOT NULL,
                      raw_storage_kind VARCHAR(64) NOT NULL,
                      operation_name VARCHAR(64) NOT NULL,
                      indexed_at VARCHAR(64) NOT NULL,
                      synced_at VARCHAR(64) NOT NULL
                    )
                    """
                )
                cursor.execute(
                    f"""
                    INSERT INTO `{table_name}` (
                      doc_id,
                      kb_id,
                      source_id,
                      title,
                      language,
                      source_type,
                      source_uri,
                      tags_json,
                      chunk_count,
                      latest_job_id,
                      checksum,
                      raw_object_bucket,
                      raw_object_key,
                      raw_storage_kind,
                      operation_name,
                      indexed_at,
                      synced_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                      kb_id = VALUES(kb_id),
                      source_id = VALUES(source_id),
                      title = VALUES(title),
                      language = VALUES(language),
                      source_type = VALUES(source_type),
                      source_uri = VALUES(source_uri),
                      tags_json = VALUES(tags_json),
                      chunk_count = VALUES(chunk_count),
                      latest_job_id = VALUES(latest_job_id),
                      checksum = VALUES(checksum),
                      raw_object_bucket = VALUES(raw_object_bucket),
                      raw_object_key = VALUES(raw_object_key),
                      raw_storage_kind = VALUES(raw_storage_kind),
                      operation_name = VALUES(operation_name),
                      indexed_at = VALUES(indexed_at),
                      synced_at = VALUES(synced_at)
                    """,
                    (
                        context.document.id,
                        context.document.source_id,
                        context.source.id,
                        context.document.title,
                        context.document.language,
                        self._event_source_type(context),
                        self._event_source_uri(context),
                        json.dumps(context.document.tags, ensure_ascii=False),
                        len(context.chunks),
                        context.event.job_id,
                        context.document.checksum,
                        context.event.raw_object.bucket,
                        context.event.raw_object.object_key,
                        context.event.raw_object.storage_kind,
                        context.event.operation,
                        context.document_profile.indexed_at if context.document_profile else context.document.updated_at,
                        utc_now(),
                    ),
                )
            connection.commit()
        finally:
            connection.close()

        return self._build_result(
            connector="metadata_upsert",
            backend="mysql",
            status="succeeded",
            target=self.settings.mysql_table,
            detail="upserted document metadata row",
            item_count=1,
        )

    def _sync_vector_store(self, context: EventContext) -> ConnectorWriteResult:
        targets = self.target_resolver.resolve_for_document(
            context.document,
            context.source,
            context.chunks,
        )
        if not self.settings.qdrant_url:
            return self._build_result(
                connector="vector_upsert",
                backend="planner-only",
                status="skipped",
                target=targets.qdrant_collection,
                detail="qdrant is not configured",
                item_count=len(context.chunks),
            )
        if not context.chunks:
            return self._build_result(
                connector="vector_upsert",
                backend="qdrant",
                status="skipped",
                target=targets.qdrant_collection,
                detail="document has no chunks to index",
                item_count=0,
            )

        base_url = _normalized_endpoint(self.settings.qdrant_url)
        point_texts = [
            "\n".join([context.document.title, chunk.content, " ".join(chunk.keywords)])
            for chunk in context.chunks
        ]
        vectors = self.embedding_provider.embed(point_texts)
        points = [
            {
                "id": chunk.id,
                "vector": vector,
                "payload": {
                    "kb_id": context.document.source_id,
                    "source_id": chunk.source_id,
                    "source_name": context.source.name,
                    "document_id": chunk.document_id,
                    "document_title": chunk.document_title,
                    "chunk_id": chunk.id,
                    "ordinal": chunk.ordinal,
                    "tags": chunk.tags,
                    "keywords": chunk.keywords,
                    "content": chunk.content,
                    "created_at": chunk.created_at,
                    "source_type": self._event_source_type(context),
                    "source_uri": self._event_source_uri(context),
                    "index_target_mode": targets.mode,
                    "index_target_domain": targets.domain,
                    "index_target_collection": targets.qdrant_collection,
                    "index_target_fallback_collection": targets.fallback_qdrant_collection,
                },
            }
            for chunk, vector in zip(context.chunks, vectors, strict=True)
        ]

        with httpx.Client(
            timeout=self.settings.connector_timeout_ms / 1000,
            trust_env=False,
        ) as client:
            collection_url = f"{base_url}/collections/{targets.qdrant_collection}"
            check_response = client.get(collection_url)
            if check_response.status_code == 404:
                create_response = client.put(
                    collection_url,
                    json={
                        "vectors": {
                            "size": self.settings.qdrant_vector_size,
                            "distance": "Cosine",
                        }
                    },
                )
                create_response.raise_for_status()
            elif check_response.status_code >= 400:
                check_response.raise_for_status()

            upsert_response = client.put(
                f"{collection_url}/points?wait=true",
                json={"points": points},
            )
            upsert_response.raise_for_status()

        return self._build_result(
            connector="vector_upsert",
            backend="qdrant",
            status="succeeded",
            target=targets.qdrant_collection,
            detail=f"upserted chunk vectors into Qdrant ({targets.mode})",
            item_count=len(points),
        )

    def _sync_bm25_store(self, context: EventContext) -> ConnectorWriteResult:
        targets = self.target_resolver.resolve_for_document(
            context.document,
            context.source,
            context.chunks,
        )
        if not self.settings.opensearch_url:
            return self._build_result(
                connector="bm25_upsert",
                backend="keyword-baseline",
                status="skipped",
                target=targets.opensearch_index,
                detail="opensearch is not configured",
                item_count=len(context.chunks),
            )
        if not context.chunks:
            return self._build_result(
                connector="bm25_upsert",
                backend="opensearch",
                status="skipped",
                target=targets.opensearch_index,
                detail="document has no chunks to index",
                item_count=0,
            )

        base_url = _normalized_endpoint(self.settings.opensearch_url)
        with httpx.Client(
            timeout=self.settings.connector_timeout_ms / 1000,
            trust_env=False,
        ) as client:
            index_url = f"{base_url}/{targets.opensearch_index}"
            head_response = client.head(index_url)
            if head_response.status_code == 404:
                create_response = client.put(
                    index_url,
                    json={
                        "mappings": {
                            "properties": {
                                "kb_id": {"type": "keyword"},
                                "source_id": {"type": "keyword"},
                                "document_id": {"type": "keyword"},
                                "document_title": {"type": "text"},
                                "chunk_id": {"type": "keyword"},
                                "content": {"type": "text"},
                                "keywords": {"type": "keyword"},
                                "tags": {"type": "keyword"},
                                "ordinal": {"type": "integer"},
                                "source_type": {"type": "keyword"},
                                "source_uri": {"type": "keyword"},
                                "index_target_mode": {"type": "keyword"},
                                "index_target_domain": {"type": "keyword"},
                            }
                        }
                    },
                )
                create_response.raise_for_status()
            elif head_response.status_code >= 400:
                head_response.raise_for_status()

            bulk_lines: list[str] = []
            for chunk in context.chunks:
                bulk_lines.append(
                    json.dumps(
                        {
                            "index": {
                                "_index": targets.opensearch_index,
                                "_id": chunk.id,
                            }
                        },
                        ensure_ascii=False,
                    )
                )
                bulk_lines.append(
                    json.dumps(
                        {
                            "kb_id": context.document.source_id,
                            "source_id": chunk.source_id,
                            "document_id": chunk.document_id,
                            "document_title": chunk.document_title,
                            "chunk_id": chunk.id,
                            "content": chunk.content,
                            "keywords": chunk.keywords,
                            "tags": chunk.tags,
                            "ordinal": chunk.ordinal,
                            "source_name": context.source.name,
                            "created_at": chunk.created_at,
                            "source_type": (
                                self._event_source_type(context)
                            ),
                            "source_uri": (
                                self._event_source_uri(context)
                            ),
                            "index_target_mode": targets.mode,
                            "index_target_domain": targets.domain,
                        },
                        ensure_ascii=False,
                    )
                )
            bulk_response = client.post(
                f"{base_url}/_bulk?refresh=true",
                content="\n".join(bulk_lines) + "\n",
                headers={"Content-Type": "application/x-ndjson"},
            )
            bulk_response.raise_for_status()
            payload = bulk_response.json()
            if payload.get("errors"):
                raise RuntimeError(f"OpenSearch bulk response reported errors: {payload}")

        return self._build_result(
            connector="bm25_upsert",
            backend="opensearch",
            status="succeeded",
            target=targets.opensearch_index,
            detail=f"upserted chunk documents into OpenSearch ({targets.mode})",
            item_count=len(context.chunks),
        )

    def _publish_queue_state(self, context: EventContext) -> ConnectorWriteResult:
        if not self.settings.redis_url:
            return self._build_result(
                connector="queue_publish",
                backend="jsonl-outbox",
                status="skipped",
                target=self.settings.task_queue_name,
                detail="redis is not configured",
                item_count=0,
            )
        if redis is None:
            raise RuntimeError("redis dependency is unavailable")

        client = redis.from_url(  # type: ignore[union-attr]
            self.settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        channel = f"{self.settings.redis_namespace}:events"
        completed_list = f"{self.settings.redis_namespace}:{self.settings.task_queue_name}:completed"
        payload = json.dumps(
            {
                "eventId": context.event.event_id,
                "docId": context.document.id,
                "kbId": context.document.source_id,
                "jobId": context.event.job_id,
                "operation": context.event.operation,
                "queuedAt": context.event.created_at,
                "processedAt": utc_now(),
            },
            ensure_ascii=False,
        )
        client.publish(channel, payload)
        client.lpush(completed_list, context.event.event_id)
        client.setex(
            f"{self.settings.redis_namespace}:document:{context.document.id}:last-processed",
            600,
            payload,
        )
        return self._build_result(
            connector="queue_publish",
            backend="redis-list",
            status="succeeded",
            target=completed_list,
            detail=f"published connector event on {channel}",
            item_count=3,
        )

    def _mysql_connection_params(self) -> dict[str, object]:
        parsed = urlparse(self.settings.mysql_dsn or "")
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise ValueError(f"unsupported mysql dsn scheme: {parsed.scheme}")
        database = parsed.path.lstrip("/")
        if not database:
            raise ValueError("mysql dsn is missing a database name")
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": database,
            "autocommit": False,
            "charset": "utf8mb4",
        }

    @staticmethod
    def _build_result(
        *,
        connector: str,
        backend: str,
        status: str,
        target: str | None,
        detail: str,
        item_count: int | None = None,
    ) -> ConnectorWriteResult:
        return ConnectorWriteResult(
            connector=connector,
            backend=backend,
            status=status,
            target=target,
            detail=detail,
            itemCount=item_count,
            attemptedAt=utc_now(),
        )

    @staticmethod
    def _event_source_type(context: EventContext) -> str:
        if context.document_profile is not None and context.document_profile.source_type.strip():
            return context.document_profile.source_type
        if context.event.raw_object.source_type and context.event.raw_object.source_type.strip():
            return context.event.raw_object.source_type
        return "inline"

    @staticmethod
    def _event_source_uri(context: EventContext) -> str | None:
        if context.document_profile is not None and context.document_profile.source_uri:
            return context.document_profile.source_uri
        if context.event.raw_object.source_uri:
            return context.event.raw_object.source_uri
        return context.source.uri


@lru_cache(maxsize=1)
def get_indexing_worker_service() -> KnowledgeIndexingWorkerService:
    return KnowledgeIndexingWorkerService(get_repository(), get_runtime_sync_service())
