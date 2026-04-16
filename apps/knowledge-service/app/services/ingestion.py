import hashlib
import json
import re
from datetime import UTC, datetime
from functools import lru_cache
from uuid import uuid4

from app.core.config import get_settings
from app.core.metrics import (
    BOOTSTRAP_RUNS_TOTAL,
    CHUNKS_CREATED_TOTAL,
    DUPLICATE_DOCUMENTS_TOTAL,
    INGESTION_DURATION_SECONDS,
    INGESTIONS_TOTAL,
)
from app.core.tracing import start_span
from app.models.knowledge import (
    BootstrapCatalogResponse,
    CreateSourceRequest,
    IngestDocumentRequest,
    IngestionJob,
    IngestionResponse,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SourceSeed,
    StarterCatalog,
)
from app.services.runtime_sync import KnowledgeRuntimeSyncService
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "have",
    "from",
    "your",
    "you",
    "问题",
    "一个",
    "进行",
    "以及",
    "相关",
    "通过",
    "需要",
    "可以",
}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class IngestionService:
    def __init__(self, repository: KnowledgeStoreRepository) -> None:
        self.repository = repository
        self.settings = get_settings()

    def create_source(self, request: CreateSourceRequest) -> KnowledgeSource:
        now = utc_now()
        source = KnowledgeSource(
            id=f"src-{uuid4().hex[:12]}",
            name=request.name.strip(),
            kind=request.kind,
            uri=request.uri.strip() if request.uri else None,
            description=request.description.strip() if request.description else None,
            tags=self._normalize_tags(request.tags),
            createdAt=now,
            updatedAt=now,
        )
        return self.repository.save_source(source)

    def resolve_source(
        self,
        source_id: str | None = None,
        source: SourceSeed | None = None,
    ) -> KnowledgeSource:
        if source_id:
            existing = self.repository.get_source(source_id)
            if existing is None:
                raise ValueError(f"Unknown sourceId: {source_id}")
            return existing
        if source is None:
            raise ValueError("Either sourceId or source must be provided.")

        existing_source = self.repository.find_source_by_seed(source)
        if existing_source is not None:
            merged_tags = self._normalize_tags(existing_source.tags + source.tags)
            updates = {}
            if merged_tags != existing_source.tags:
                updates["tags"] = merged_tags
            if source.description and source.description != existing_source.description:
                updates["description"] = source.description
            if updates:
                updates["updated_at"] = utc_now()
                existing_source = existing_source.model_copy(update=updates)
                return self.repository.save_source(existing_source)
            return existing_source
        return self.create_source(CreateSourceRequest(**source.model_dump()))

    def ingest_document(self, request: IngestDocumentRequest) -> IngestionResponse:
        with start_span(
            "knowledge.ingest_document",
            smartcloud_source_id=request.source_id,
            smartcloud_source_name=request.source.name if request.source else None,
            smartcloud_document_title=request.title.strip(),
            smartcloud_document_language=request.language,
            smartcloud_document_tag_count=len(request.tags),
        ) as span:
            with INGESTION_DURATION_SECONDS.time():
                source = self.resolve_source(request.source_id, request.source)
                runtime_source_type = (
                    request.source_type.strip()
                    if isinstance(request.source_type, str) and request.source_type.strip()
                    else "inline"
                )
                runtime_source_uri = (
                    request.source_uri.strip()
                    if isinstance(request.source_uri, str) and request.source_uri.strip()
                    else source.uri
                )
                now = utc_now()
                normalized_content = request.content.strip()
                checksum = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()[:16]
                existing_document = self.repository.find_document(
                    source_id=source.id,
                    checksum=checksum,
                    title=request.title,
                )
                if existing_document is not None:
                    job = IngestionJob(
                        id=f"ing-{uuid4().hex[:12]}",
                        sourceId=source.id,
                        documentId=existing_document.id,
                        status="completed",
                        documentsReceived=1,
                        chunksCreated=0,
                        warnings=["duplicate document reused"],
                        createdAt=now,
                        completedAt=now,
                    )
                    self.repository.save_ingestion_job(job)
                    INGESTIONS_TOTAL.inc()
                    DUPLICATE_DOCUMENTS_TOTAL.inc()
                    if span is not None:
                        span.set_attribute("smartcloud.ingestion.duplicate_reused", True)
                        span.set_attribute("smartcloud.ingestion.chunk_count", 0)
                    return IngestionResponse(
                        job=job,
                        source=source,
                        document=existing_document,
                        chunksCreated=0,
                    )

                chunk_texts = self._split_text(normalized_content)
                chunk_ids = [f"chk-{uuid4().hex[:12]}" for _ in chunk_texts]
                document = KnowledgeDocument(
                    id=f"doc-{uuid4().hex[:12]}",
                    sourceId=source.id,
                    title=request.title.strip(),
                    content=normalized_content,
                    tags=self._normalize_tags(request.tags),
                    language=request.language,
                    checksum=checksum,
                    chunkIds=chunk_ids,
                    createdAt=now,
                    updatedAt=now,
                )
                chunks = [
                    KnowledgeChunk(
                        id=chunk_id,
                        sourceId=source.id,
                        documentId=document.id,
                        documentTitle=document.title,
                        ordinal=index,
                        content=chunk_text,
                        tokenEstimate=max(1, len(chunk_text) // 4),
                        keywords=self._extract_keywords(chunk_text),
                        tags=sorted(set(source.tags + document.tags)),
                        createdAt=now,
                    )
                    for index, (chunk_id, chunk_text) in enumerate(zip(chunk_ids, chunk_texts), start=1)
                ]
                job = IngestionJob(
                    id=f"ing-{uuid4().hex[:12]}",
                    sourceId=source.id,
                    documentId=document.id,
                    status="completed",
                    documentsReceived=1,
                    chunksCreated=len(chunks),
                    createdAt=now,
                    completedAt=now,
                )
                updated_source = source.model_copy(
                    update={
                        "document_count": source.document_count + 1,
                        "chunk_count": source.chunk_count + len(chunks),
                        "updated_at": now,
                    }
                )
                self.repository.save_document(document, chunks, job, updated_source)
                job = self._publish_runtime_sync(
                    document=document,
                    source=updated_source,
                    job=job,
                    chunks=chunks,
                    span=span,
                    source_type=runtime_source_type,
                    source_uri=runtime_source_uri,
                )
                INGESTIONS_TOTAL.inc()
                CHUNKS_CREATED_TOTAL.inc(len(chunks))
                if span is not None:
                    span.set_attribute("smartcloud.ingestion.duplicate_reused", False)
                    span.set_attribute("smartcloud.ingestion.chunk_count", len(chunks))
                    span.set_attribute("smartcloud.ingestion.document_id", document.id)
                    span.set_attribute("smartcloud.ingestion.source_id", updated_source.id)
                return IngestionResponse(
                    job=job,
                    source=updated_source,
                    document=document,
                    chunksCreated=len(chunks),
                )

    def bootstrap_catalog(self) -> BootstrapCatalogResponse:
        with start_span(
            "knowledge.bootstrap_catalog",
            smartcloud_starter_catalog_path=str(self.settings.starter_catalog_path),
        ) as span:
            starter_catalog_path = self.settings.starter_catalog_path
            catalog = StarterCatalog.model_validate(
                json.loads(starter_catalog_path.read_text(encoding="utf-8"))
            )
            BOOTSTRAP_RUNS_TOTAL.inc()
            seeded_documents = 0
            reused_documents = 0

            for item in catalog.documents:
                response = self.ingest_document(
                    IngestDocumentRequest(
                        source=item.source,
                        title=item.title,
                        content=item.content,
                        tags=item.tags,
                        language=item.language,
                    )
                )
                if response.chunks_created > 0:
                    seeded_documents += 1
                else:
                    reused_documents += 1

            counts = self.repository.snapshot_counts()
            if span is not None:
                span.set_attribute("smartcloud.bootstrap.seeded_documents", seeded_documents)
                span.set_attribute("smartcloud.bootstrap.reused_documents", reused_documents)
                span.set_attribute("smartcloud.bootstrap.source_count", counts["sources"])
                span.set_attribute("smartcloud.bootstrap.document_count", counts["documents"])
            return BootstrapCatalogResponse(
                seededDocuments=seeded_documents,
                reusedDocuments=reused_documents,
                sourceCount=counts["sources"],
                documentCount=counts["documents"],
                chunkCount=counts["chunks"],
            )

    def reindex_document(self, document_id: str) -> IngestionResponse:
        with start_span(
            "knowledge.reindex_document",
            smartcloud_document_id=document_id,
        ) as span:
            with INGESTION_DURATION_SECONDS.time():
                document = self.repository.get_document(document_id)
                if document is None:
                    raise ValueError(f"Unknown documentId: {document_id}")
                source = self.repository.get_source(document.source_id)
                if source is None:
                    raise ValueError(f"Unknown sourceId: {document.source_id}")
                profile = self.repository.get_document_profile(document_id)

                now = utc_now()
                chunk_texts = self._split_text(document.content)
                chunk_ids = [f"chk-{uuid4().hex[:12]}" for _ in chunk_texts]
                updated_document = document.model_copy(
                    update={
                        "chunk_ids": chunk_ids,
                        "updated_at": now,
                    }
                )
                chunks = [
                    KnowledgeChunk(
                        id=chunk_id,
                        sourceId=source.id,
                        documentId=updated_document.id,
                        documentTitle=updated_document.title,
                        ordinal=index,
                        content=chunk_text,
                        tokenEstimate=max(1, len(chunk_text) // 4),
                        keywords=self._extract_keywords(chunk_text),
                        tags=sorted(set(source.tags + updated_document.tags)),
                        createdAt=now,
                    )
                    for index, (chunk_id, chunk_text) in enumerate(zip(chunk_ids, chunk_texts), start=1)
                ]
                previous_chunk_count = len(document.chunk_ids)
                job = IngestionJob(
                    id=f"ing-{uuid4().hex[:12]}",
                    sourceId=source.id,
                    documentId=updated_document.id,
                    status="completed",
                    documentsReceived=1,
                    chunksCreated=len(chunks),
                    warnings=["document reindexed"],
                    createdAt=now,
                    completedAt=now,
                )
                updated_source = source.model_copy(
                    update={
                        "chunk_count": max(
                            0,
                            source.chunk_count - previous_chunk_count + len(chunks),
                        ),
                        "updated_at": now,
                    }
                )
                self.repository.replace_document_chunks(updated_document, chunks, job, updated_source)
                job = self._publish_runtime_sync(
                    document=updated_document,
                    source=updated_source,
                    job=job,
                    chunks=chunks,
                    operation="reindex",
                    span=span,
                    source_type=profile.source_type if profile and profile.source_type else "inline",
                    source_uri=profile.source_uri if profile and profile.source_uri else source.uri,
                )
                INGESTIONS_TOTAL.inc()
                CHUNKS_CREATED_TOTAL.inc(len(chunks))
                if span is not None:
                    span.set_attribute("smartcloud.reindex.previous_chunk_count", previous_chunk_count)
                    span.set_attribute("smartcloud.reindex.new_chunk_count", len(chunks))
                    span.set_attribute("smartcloud.reindex.source_id", updated_source.id)
                return IngestionResponse(
                    job=job,
                    source=updated_source,
                    document=updated_document,
                    chunksCreated=len(chunks),
                )

    def _publish_runtime_sync(
        self,
        *,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        job: IngestionJob,
        chunks: list[KnowledgeChunk],
        operation: str = "upsert",
        span=None,
        source_type: str | None = None,
        source_uri: str | None = None,
    ) -> IngestionJob:
        try:
            event = KnowledgeRuntimeSyncService(self.repository).enqueue_document_sync(
                document,
                source,
                job,
                chunks=chunks,
                operation=operation,
                source_type=source_type,
                source_uri=source_uri,
            )
        except Exception as exc:  # noqa: BLE001 - ingestion should still complete when outbox staging degrades
            warning = f"indexing outbox enqueue failed: {exc}"
            updated_job = job.model_copy(update={"warnings": job.warnings + [warning]})
            self.repository.save_ingestion_job(updated_job)
            if span is not None:
                span.set_attribute("smartcloud.indexing.outbox_status", "failed")
                span.set_attribute("smartcloud.indexing.outbox_error", str(exc))
            return updated_job

        if span is not None:
            span.set_attribute("smartcloud.indexing.outbox_status", event.status)
            span.set_attribute("smartcloud.indexing.outbox_event_id", event.event_id)
            span.set_attribute("smartcloud.indexing.queue_name", event.queue_name)
            span.set_attribute("smartcloud.indexing.raw_object_key", event.raw_object.object_key)
        return job

    def _split_text(self, content: str) -> list[str]:
        content = content.strip()
        if len(content) <= self.settings.max_chunk_chars:
            return [content]

        paragraphs = [item.strip() for item in re.split(r"\n{2,}", content) if item.strip()]
        if not paragraphs:
            paragraphs = [content]

        chunks: list[str] = []
        buffer = ""
        for paragraph in paragraphs:
            candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
            if len(candidate) <= self.settings.max_chunk_chars:
                buffer = candidate
                continue
            if buffer:
                chunks.append(buffer)
                overlap = buffer[-self.settings.chunk_overlap_chars :]
                buffer = f"{overlap}\n{paragraph}".strip()
            else:
                buffer = paragraph
            while len(buffer) > self.settings.max_chunk_chars:
                chunk = buffer[: self.settings.max_chunk_chars].strip()
                chunks.append(chunk)
                start = max(0, self.settings.max_chunk_chars - self.settings.chunk_overlap_chars)
                buffer = buffer[start:].strip()
        if buffer:
            chunks.append(buffer)
        return [chunk for chunk in chunks if chunk]

    def _extract_keywords(self, content: str) -> list[str]:
        tokens = re.findall(r"[A-Za-z0-9_+-]+|[\u4e00-\u9fff]{2,}", content.lower())
        scored: dict[str, int] = {}
        for token in tokens:
            if token in STOPWORDS:
                continue
            scored[token] = scored.get(token, 0) + 1
        return [
            token
            for token, _count in sorted(scored.items(), key=lambda item: (-item[1], item[0]))[:8]
        ]

    @staticmethod
    def _normalize_tags(tags: list[str]) -> list[str]:
        normalized = {tag.strip().lower() for tag in tags if tag.strip()}
        return sorted(normalized)


@lru_cache(maxsize=1)
def get_ingestion_service() -> IngestionService:
    return IngestionService(get_repository())
