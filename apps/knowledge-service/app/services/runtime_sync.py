from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from threading import RLock
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import get_settings
from app.core.metrics import (
    INDEX_OUTBOX_EVENTS_TOTAL,
    INDEX_OUTBOX_PENDING_EVENTS,
    INDEX_OUTBOX_STATUS_COUNT,
    RAW_OBJECT_WRITES_TOTAL,
)
from app.models.admin import KnowledgeBaseProfile
from app.models.knowledge import IngestionJob, KnowledgeChunk, KnowledgeDocument, KnowledgeSource
from app.models.runtime import (
    ConnectorWriteResult,
    IndexingOutboxEvent,
    KnowledgeRuntimeIntegrations,
    RawObjectMirrorRecord,
    RuntimeConnectorStatus,
)
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository

try:
    import redis
except ImportError:  # pragma: no cover - exercised in integration environments
    redis = None


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _slugify(value: str, fallback: str = "document") -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in value.strip())
    normalized = "-".join(part for part in cleaned.split("-") if part)
    return normalized or fallback


def _sanitize_endpoint(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme:
        return value
    host = parsed.hostname or parsed.netloc or parsed.path
    if not host:
        return f"{parsed.scheme}://"
    port = f":{parsed.port}" if parsed.port else ""
    suffix = parsed.path if parsed.path not in {"", "/"} else ""
    return f"{parsed.scheme}://{host}{port}{suffix}"


OUTBOX_EVENT_STATUSES = ("queued", "processing", "failed", "completed")


class KnowledgeRuntimeSyncService:
    def __init__(self, repository: KnowledgeStoreRepository) -> None:
        self.repository = repository
        self.settings = get_settings()
        self._lock = RLock()
        self.settings.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.raw_mirror_root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._sync_metrics_locked(self._load_events_locked())

    def enqueue_document_sync(
        self,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        job: IngestionJob,
        *,
        chunks: list[KnowledgeChunk] | None = None,
        operation: str = "upsert",
        source_type: str | None = None,
        source_uri: str | None = None,
    ) -> IndexingOutboxEvent:
        chunk_rows = chunks if chunks is not None else self.repository.list_chunks(document_id=document.id)
        knowledge_base_profile = self.repository.get_knowledge_base_profile(source.id)
        raw_object = self._write_raw_mirror(
            document=document,
            source=source,
            knowledge_base_profile=knowledge_base_profile,
            source_type=source_type,
            source_uri=source_uri,
        )
        event = IndexingOutboxEvent(
            eventId=f"evt-{uuid4().hex[:12]}",
            eventType="knowledge.document.index.requested",
            operation=operation,
            status="queued",
            queueName=self.settings.task_queue_name,
            docId=document.id,
            kbId=knowledge_base_profile.kb_id if knowledge_base_profile else source.id,
            sourceId=source.id,
            jobId=job.id,
            chunkCount=len(chunk_rows),
            warnings=job.warnings,
            rawObject=raw_object,
            metadataTarget=self._metadata_target(),
            vectorTarget=self.settings.qdrant_collection if self.settings.qdrant_url else None,
            bm25Target=self.settings.opensearch_index if self.settings.opensearch_url else None,
            cacheNamespace=self.settings.redis_namespace if self.settings.redis_url else None,
            attemptCount=0,
            createdAt=utc_now(),
        )
        with self._lock:
            events = self._load_events_locked()
            events.append(event)
            self._persist_events_locked(events)
            self._sync_metrics_locked(events)
        self._enqueue_redis_event(event.event_id)
        INDEX_OUTBOX_EVENTS_TOTAL.labels(operation=operation, status="queued").inc()
        return event

    def claim_next_event(
        self,
        processor_id: str,
        *,
        allowed_statuses: tuple[str, ...] = ("queued", "failed"),
    ) -> IndexingOutboxEvent | None:
        redis_claimed = self._claim_next_event_from_redis(
            processor_id,
            allowed_statuses=allowed_statuses,
        )
        if redis_claimed is not None:
            return redis_claimed
        with self._lock:
            events = self._load_events_locked()
            for index, event in enumerate(events):
                if event.status not in allowed_statuses:
                    continue
                updated = event.model_copy(
                    update={
                        "status": "processing",
                        "processor_id": processor_id,
                        "reserved_at": utc_now(),
                        "completed_at": None,
                        "last_error": None,
                        "attempt_count": event.attempt_count + 1,
                    }
                )
                events[index] = updated
                self._persist_events_locked(events)
                self._sync_metrics_locked(events)
                INDEX_OUTBOX_EVENTS_TOTAL.labels(
                    operation=updated.operation,
                    status="processing",
                ).inc()
                return updated
        return None

    def mark_event_completed(
        self,
        event_id: str,
        *,
        connector_results: list[ConnectorWriteResult] | None = None,
    ) -> IndexingOutboxEvent | None:
        return self._update_event(
            event_id,
            status="completed",
            completed_at=utc_now(),
            last_error=None,
            connector_results=connector_results,
        )

    def mark_event_failed(
        self,
        event_id: str,
        error_message: str,
        *,
        connector_results: list[ConnectorWriteResult] | None = None,
    ) -> IndexingOutboxEvent | None:
        return self._update_event(
            event_id,
            status="failed",
            completed_at=None,
            last_error=error_message,
            connector_results=connector_results,
        )

    def build_integrations(self, recent_limit: int = 5) -> KnowledgeRuntimeIntegrations:
        raw_storage_backend = "minio" if self.settings.minio_endpoint and self.settings.minio_bucket else "local-mirror"
        cache_backend = "redis-configured" if self.settings.redis_url else "local-memory-fallback"
        queue_backend = "redis-list-primary" if self.settings.redis_url else "jsonl-outbox"
        event_counters = self.event_counters()
        return KnowledgeRuntimeIntegrations(
            rawStorage=RuntimeConnectorStatus(
                backend=raw_storage_backend,
                configured=bool(self.settings.minio_endpoint and self.settings.minio_bucket),
                endpoint=self.settings.minio_endpoint,
                target=self.settings.minio_bucket or str(self.settings.raw_mirror_root),
                notes=[
                    "MinIO bucket/object key is the formal raw-object target while a local mirror remains for migration safety",
                ],
            ),
            metadataStore=RuntimeConnectorStatus(
                backend="mysql" if self.settings.mysql_dsn else "json-runtime-store",
                configured=bool(self.settings.mysql_dsn),
                endpoint=_sanitize_endpoint(self.settings.mysql_dsn),
                target=self.settings.mysql_table,
                notes=[
                    "knowledge-base, document-profile, and admin-job metadata prefer MySQL-backed runtime storage when configured, with local JSON retained as a fallback mirror",
                ],
            ),
            vectorStore=RuntimeConnectorStatus(
                backend="qdrant" if self.settings.qdrant_url else "planner-only",
                configured=bool(self.settings.qdrant_url),
                endpoint=self.settings.qdrant_url,
                target=self.settings.qdrant_collection,
                notes=[
                    "chunk payloads are indexed asynchronously and queried as the preferred vector backend when available",
                ],
            ),
            bm25Store=RuntimeConnectorStatus(
                backend="opensearch" if self.settings.opensearch_url else "keyword-baseline",
                configured=bool(self.settings.opensearch_url),
                endpoint=self.settings.opensearch_url,
                target=self.settings.opensearch_index,
                notes=[
                    "lexical chunk documents are indexed asynchronously and used as the preferred BM25 backend when available",
                ],
            ),
            cache=RuntimeConnectorStatus(
                backend=cache_backend,
                configured=bool(self.settings.redis_url),
                endpoint=_sanitize_endpoint(self.settings.redis_url),
                target=self.settings.redis_namespace,
                notes=[
                    "shared namespace reserved for retrieval caches and worker coordination",
                ],
            ),
            taskQueue=RuntimeConnectorStatus(
                backend=queue_backend,
                configured=bool(self.settings.redis_url),
                endpoint=_sanitize_endpoint(self.settings.redis_url),
                target=self.settings.task_queue_name,
                notes=[
                    "Redis pending/processing lists are used as the active queue path when configured, with the JSONL outbox retained as an auditable fallback log",
                ],
            ),
            outboxPath=str(self.settings.outbox_path.expanduser()),
            rawMirrorRoot=str(self.settings.raw_mirror_root.expanduser()),
            pendingEvents=event_counters["pending"],
            eventCounters=event_counters,
            recentEvents=self.list_events(limit=recent_limit),
        )

    def pending_events(self) -> int:
        with self._lock:
            return self._summarize_events(self._load_events_locked())["pending"]

    def event_counters(self) -> dict[str, int]:
        with self._lock:
            return self._summarize_events(self._load_events_locked())

    def list_events(self, limit: int = 5) -> list[IndexingOutboxEvent]:
        if limit <= 0:
            return []
        with self._lock:
            events = self._load_events_locked()
        return list(reversed(events[-limit:]))

    def _write_raw_mirror(
        self,
        *,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        knowledge_base_profile: KnowledgeBaseProfile | None,
        source_type: str | None,
        source_uri: str | None,
    ) -> RawObjectMirrorRecord:
        kb_segment = knowledge_base_profile.code if knowledge_base_profile else source.id
        file_name = f"{_slugify(document.title)}.md"
        object_key = str(PurePosixPath(kb_segment) / document.id / file_name)
        mirror_path = self.settings.raw_mirror_root / object_key
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        mirror_path.write_text(document.content, encoding="utf-8")
        RAW_OBJECT_WRITES_TOTAL.inc()
        return RawObjectMirrorRecord(
            docId=document.id,
            kbId=knowledge_base_profile.kb_id if knowledge_base_profile else source.id,
            sourceId=source.id,
            storageKind="minio" if self.settings.minio_endpoint and self.settings.minio_bucket else "local-mirror",
            bucket=self.settings.minio_bucket or None,
            objectKey=object_key,
            mirrorPath=str(mirror_path),
            checksum=document.checksum,
            contentType="text/markdown; charset=utf-8",
            sizeBytes=len(document.content.encode("utf-8")),
            sourceType=source_type or "inline",
            sourceUri=source_uri or source.uri,
            createdAt=utc_now(),
        )

    def _metadata_target(self) -> str | None:
        if not self.settings.mysql_dsn:
            return None
        return f"{self.settings.mysql_table}@{_sanitize_endpoint(self.settings.mysql_dsn)}"

    def _update_event(
        self,
        event_id: str,
        *,
        status: str,
        completed_at: str | None,
        last_error: str | None,
        connector_results: list[ConnectorWriteResult] | None = None,
    ) -> IndexingOutboxEvent | None:
        with self._lock:
            events = self._load_events_locked()
            for index, event in enumerate(events):
                if event.event_id != event_id:
                    continue
                updated = event.model_copy(
                    update={
                        "status": status,
                        "completed_at": completed_at,
                        "last_error": last_error,
                        "connector_results": (
                            connector_results
                            if connector_results is not None
                            else event.connector_results
                        ),
                    }
                )
                events[index] = updated
                self._persist_events_locked(events)
                self._sync_metrics_locked(events)
                if status == "completed":
                    self._ack_redis_event(event_id)
                elif status == "failed":
                    self._requeue_redis_event(event_id)
                INDEX_OUTBOX_EVENTS_TOTAL.labels(operation=updated.operation, status=status).inc()
                return updated
        return None

    def _load_events_locked(self) -> list[IndexingOutboxEvent]:
        if not self.settings.outbox_path.exists():
            return []
        events: list[IndexingOutboxEvent] = []
        for line in self.settings.outbox_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(IndexingOutboxEvent.model_validate(json.loads(line)))
            except (ValueError, json.JSONDecodeError):
                continue
        return events

    def _persist_events_locked(self, events: list[IndexingOutboxEvent]) -> None:
        self.settings.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(
            json.dumps(event.model_dump(mode="json", by_alias=True), ensure_ascii=False)
            for event in events
        )
        if payload:
            payload = f"{payload}\n"
        self.settings.outbox_path.write_text(payload, encoding="utf-8")

    def _sync_metrics_locked(self, events: list[IndexingOutboxEvent]) -> None:
        counters = self._summarize_events(events)
        INDEX_OUTBOX_PENDING_EVENTS.set(counters["pending"])
        for status in OUTBOX_EVENT_STATUSES:
            INDEX_OUTBOX_STATUS_COUNT.labels(status=status).set(counters.get(status, 0))

    @staticmethod
    def _summarize_events(events: list[IndexingOutboxEvent]) -> dict[str, int]:
        counters = {status: 0 for status in OUTBOX_EVENT_STATUSES}
        for event in events:
            counters[event.status] = counters.get(event.status, 0) + 1
        counters["total"] = len(events)
        counters["pending"] = sum(
            count for status, count in counters.items() if status in {"queued", "processing", "failed"}
        )
        return counters

    def _redis_client(self):
        if not self.settings.redis_url or redis is None:
            return None
        try:
            return redis.from_url(  # type: ignore[union-attr]
                self.settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        except Exception:
            return None

    def _queue_keys(self) -> tuple[str, str]:
        prefix = f"{self.settings.redis_namespace}:{self.settings.task_queue_name}"
        return f"{prefix}:pending", f"{prefix}:processing"

    def _enqueue_redis_event(self, event_id: str) -> None:
        client = self._redis_client()
        if client is None:
            return
        pending_key, _ = self._queue_keys()
        try:
            client.lrem(pending_key, 0, event_id)
            client.lpush(pending_key, event_id)
        except Exception:
            return

    def _claim_next_event_from_redis(
        self,
        processor_id: str,
        *,
        allowed_statuses: tuple[str, ...],
    ) -> IndexingOutboxEvent | None:
        client = self._redis_client()
        if client is None:
            return None
        pending_key, processing_key = self._queue_keys()
        try:
            claimed_id = client.rpoplpush(pending_key, processing_key)
        except Exception:
            return None
        while claimed_id:
            with self._lock:
                events = self._load_events_locked()
                for index, event in enumerate(events):
                    if event.event_id != claimed_id:
                        continue
                    if event.status not in allowed_statuses:
                        break
                    updated = event.model_copy(
                        update={
                            "status": "processing",
                            "processor_id": processor_id,
                            "reserved_at": utc_now(),
                            "completed_at": None,
                            "last_error": None,
                            "attempt_count": event.attempt_count + 1,
                        }
                    )
                    events[index] = updated
                    self._persist_events_locked(events)
                    self._sync_metrics_locked(events)
                    INDEX_OUTBOX_EVENTS_TOTAL.labels(
                        operation=updated.operation,
                        status="processing",
                    ).inc()
                    return updated
            try:
                client.lrem(processing_key, 0, claimed_id)
                claimed_id = client.rpoplpush(pending_key, processing_key)
            except Exception:
                return None
        return None

    def _ack_redis_event(self, event_id: str) -> None:
        client = self._redis_client()
        if client is None:
            return
        _, processing_key = self._queue_keys()
        try:
            client.lrem(processing_key, 0, event_id)
        except Exception:
            return

    def _requeue_redis_event(self, event_id: str) -> None:
        client = self._redis_client()
        if client is None:
            return
        pending_key, processing_key = self._queue_keys()
        try:
            client.lrem(processing_key, 0, event_id)
            client.lrem(pending_key, 0, event_id)
            client.lpush(pending_key, event_id)
        except Exception:
            return


@lru_cache(maxsize=1)
def get_runtime_sync_service() -> KnowledgeRuntimeSyncService:
    return KnowledgeRuntimeSyncService(get_repository())
