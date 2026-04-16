import math
import re
from functools import lru_cache

from app.core.metrics import (
    ADMIN_WRITE_REQUESTS_TOTAL,
    DOCUMENT_REINDEX_RUNS_TOTAL,
)
from app.models.admin import (
    AdminAsyncJob,
    AdminAuditListData,
    AdminKnowledgeBaseCreateRequest,
    AdminKnowledgeBaseListData,
    AdminKnowledgeBaseRecord,
    AdminKnowledgeBaseUpdateRequest,
    AdminKnowledgeChunkStats,
    AdminKnowledgeChunkListData,
    AdminKnowledgeChunkRecord,
    AdminKnowledgeDocumentDetailData,
    AdminKnowledgeDocumentCreateRequest,
    AdminKnowledgeDocumentListData,
    AdminKnowledgeDocumentRecord,
    AdminKnowledgeReindexRequest,
    AdminRetrievalSearchPreviewData,
    AdminRetrievalSearchPreviewRequest,
    AdminRetrievalSearchSource,
    KnowledgeBaseProfile,
    KnowledgeDocumentProfile,
)
from app.models.knowledge import CreateSourceRequest, IngestDocumentRequest, SearchRequest
from app.services.admin_audit import KnowledgeAdminAuditService, get_admin_audit_service
from app.services.file_import import FileImportService, get_file_import_service
from app.services.ingestion import IngestionService, get_ingestion_service, utc_now
from app.services.search import SearchService, get_search_service
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository

SOURCE_KIND_BY_SCENE = {
    "faq": "faq",
    "playbook": "playbook",
    "policy": "policy",
    "product": "product",
    "manual": "manual",
    "note": "note",
}


class AdminNotFoundError(ValueError):
    pass


class AdminConflictError(ValueError):
    pass


class AdminValidationError(ValueError):
    pass


def _slugify(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    normalized = normalized.strip("-")
    return normalized or fallback


class KnowledgeAdminService:
    def __init__(
        self,
        repository: KnowledgeStoreRepository,
        ingestion_service: IngestionService,
        search_service: SearchService,
        file_import_service: FileImportService,
        audit_service: KnowledgeAdminAuditService,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.repository = ingestion_service.repository
        self.search_service = (
            search_service
            if getattr(search_service, "repository", None) is self.repository
            else SearchService(self.repository)
        )
        self.file_import_service = (
            file_import_service
            if getattr(file_import_service, "ingestion_service", None) is self.ingestion_service
            else FileImportService(self.ingestion_service)
        )
        self.audit_service = audit_service

    def list_knowledge_bases(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        scene: str | None = None,
    ) -> AdminKnowledgeBaseListData:
        records = [self._build_knowledge_base_record(source.id) for source in self.repository.list_sources()]
        if status:
            records = [record for record in records if record.status == status]
        if scene:
            records = [record for record in records if record.scene == scene]
        return self._paginate(
            records,
            page=page,
            page_size=page_size,
            factory=AdminKnowledgeBaseListData,
            sort_by="updated_at",
            sort_order="desc",
        )

    def create_knowledge_base(
        self,
        payload: AdminKnowledgeBaseCreateRequest,
        *,
        operator_id: str,
        operator_ip: str | None,
        reason: str,
    ) -> AdminKnowledgeBaseRecord:
        if self.repository.find_knowledge_base_profile_by_code(payload.code) is not None:
            ADMIN_WRITE_REQUESTS_TOTAL.labels(action="create_kb", outcome="conflict").inc()
            raise AdminConflictError(f"Knowledge base code already exists: {payload.code}")

        scene = payload.scene.strip()
        kind = SOURCE_KIND_BY_SCENE.get(scene.lower(), "manual")
        source = self.ingestion_service.create_source(
            CreateSourceRequest(
                name=payload.name,
                kind=kind,
                uri=f"kb://{payload.code}",
                description=payload.description,
                tags=[scene.lower(), payload.language.lower()],
            )
        )
        profile = KnowledgeBaseProfile(
            kb_id=source.id,
            code=payload.code.strip(),
            scene=scene,
            language=payload.language.strip(),
            retrieval_mode=payload.retrieval_mode.strip(),
            embedding_model=payload.embedding_model.strip(),
            status="ready",
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self.repository.save_knowledge_base_profile(profile)
        record = AdminKnowledgeBaseRecord(
            kb_id=source.id,
            code=profile.code,
            name=source.name,
            scene=profile.scene,
            language=profile.language,
            retrieval_mode=profile.retrieval_mode,
            status=profile.status,
            description=source.description,
            document_count=source.document_count,
            chunk_count=source.chunk_count,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        self.audit_service.record(
            operator_id=operator_id,
            resource_type="knowledge_base",
            resource_id=record.kb_id,
            action="create",
            reason=reason,
            before_json=None,
            after_json=record.model_dump(mode="json"),
            operator_ip=operator_ip,
            created_at=utc_now(),
        )
        ADMIN_WRITE_REQUESTS_TOTAL.labels(action="create_kb", outcome="success").inc()
        return record

    def update_knowledge_base(
        self,
        kb_id: str,
        payload: AdminKnowledgeBaseUpdateRequest,
        *,
        operator_id: str,
        operator_ip: str | None,
        reason: str,
    ) -> AdminKnowledgeBaseRecord:
        self._require_source(kb_id)
        self._ensure_knowledge_base_profile(kb_id)
        before = self._build_knowledge_base_record(kb_id)
        fields_set = set(payload.model_fields_set)
        if not fields_set:
            ADMIN_WRITE_REQUESTS_TOTAL.labels(action="update_kb", outcome="rejected").inc()
            raise AdminValidationError("At least one knowledge-base field must be provided.")

        now = utc_now()
        source = self._require_source(kb_id)
        profile = self._ensure_knowledge_base_profile(kb_id)
        source_updates: dict[str, str | None] = {}
        profile_updates: dict[str, str] = {}

        if "name" in fields_set:
            name = (payload.name or "").strip()
            if not name:
                ADMIN_WRITE_REQUESTS_TOTAL.labels(action="update_kb", outcome="rejected").inc()
                raise AdminValidationError("name must not be empty")
            source_updates["name"] = name
        if "description" in fields_set:
            description = payload.description.strip() if isinstance(payload.description, str) else None
            source_updates["description"] = description or None
        if "retrieval_mode" in fields_set:
            retrieval_mode = (payload.retrieval_mode or "").strip()
            if not retrieval_mode:
                ADMIN_WRITE_REQUESTS_TOTAL.labels(action="update_kb", outcome="rejected").inc()
                raise AdminValidationError("retrieval_mode must not be empty")
            profile_updates["retrieval_mode"] = retrieval_mode
        if "status" in fields_set and payload.status is not None:
            profile_updates["status"] = payload.status

        if not source_updates and not profile_updates:
            ADMIN_WRITE_REQUESTS_TOTAL.labels(action="update_kb", outcome="rejected").inc()
            raise AdminValidationError("At least one non-null knowledge-base field must be provided.")

        if source_updates:
            source = source.model_copy(update={**source_updates, "updated_at": now})
            self.repository.save_source(source)
        if profile_updates:
            profile = profile.model_copy(update={**profile_updates, "updated_at": now})
            self.repository.save_knowledge_base_profile(profile)

        record = self._build_knowledge_base_record(kb_id)
        self.audit_service.record(
            operator_id=operator_id,
            resource_type="knowledge_base",
            resource_id=record.kb_id,
            action="update",
            reason=reason,
            before_json=before.model_dump(mode="json"),
            after_json=record.model_dump(mode="json"),
            operator_ip=operator_ip,
            created_at=utc_now(),
        )
        ADMIN_WRITE_REQUESTS_TOTAL.labels(action="update_kb", outcome="success").inc()
        return record

    def list_documents(
        self,
        kb_id: str,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        keyword: str | None = None,
    ) -> AdminKnowledgeDocumentListData:
        self._require_source(kb_id)
        records = [
            self._build_document_record(document.id)
            for document in self.repository.list_documents(source_id=kb_id)
        ]
        if status:
            records = [record for record in records if record.status == status]
        if keyword:
            lowered = keyword.strip().lower()
            records = [record for record in records if lowered in record.title.lower()]
        return self._paginate(
            records,
            page=page,
            page_size=page_size,
            factory=AdminKnowledgeDocumentListData,
            sort_by="indexed_at",
            sort_order="desc",
        )

    def create_document(
        self,
        kb_id: str,
        payload: AdminKnowledgeDocumentCreateRequest,
        *,
        operator_id: str,
        operator_ip: str | None,
        reason: str,
    ) -> AdminKnowledgeDocumentRecord:
        source = self._require_source(kb_id)
        kb_profile = self._ensure_knowledge_base_profile(source.id)
        path, content = self.file_import_service.load_import_file(payload.file_id)
        source_uri = payload.source_uri or path.as_uri()
        response = self.ingestion_service.ingest_document(
            IngestDocumentRequest(
                sourceId=source.id,
                title=payload.title,
                content=content,
                tags=payload.tags,
                language=kb_profile.language,
                sourceType=payload.source_type.strip(),
                sourceUri=source_uri,
            )
        )
        profile = self.repository.get_document_profile(response.document.id)
        version_no = profile.version_no if profile is not None else 1
        create_job = AdminAsyncJob(
            job_id=response.job.id,
            type="knowledge_document_create",
            status="succeeded",
            progress=100,
            created_at=response.job.created_at,
            params={
                "doc_id": response.document.id,
                "kb_id": kb_id,
                "file_id": payload.file_id,
                "source_type": payload.source_type.strip(),
            },
            finished_at=response.job.completed_at,
        )
        stored_profile = KnowledgeDocumentProfile(
            doc_id=response.document.id,
            kb_id=kb_id,
            status="active",
            parse_status="completed",
            index_status="ready",
            version_no=version_no,
            file_id=self.file_import_service.display_path(path),
            source_type=payload.source_type.strip(),
            source_uri=source_uri,
            indexed_at=response.document.updated_at,
            error_message=None,
            latest_job_id=create_job.job_id,
        )
        self.repository.save_document_profile(stored_profile)
        self.repository.save_admin_job(create_job)
        record = self._build_document_record(response.document.id)
        self.audit_service.record(
            operator_id=operator_id,
            resource_type="knowledge_document",
            resource_id=record.doc_id,
            action="create",
            reason=reason,
            before_json=None,
            after_json=record.model_dump(mode="json"),
            operator_ip=operator_ip,
            created_at=utc_now(),
        )
        ADMIN_WRITE_REQUESTS_TOTAL.labels(action="create_document", outcome="success").inc()
        return record

    def get_document_detail(self, doc_id: str) -> AdminKnowledgeDocumentDetailData:
        record = self._build_document_record(doc_id)
        profile = self._ensure_document_profile(doc_id)
        average_tokens = round(record.token_count / record.chunk_count, 2) if record.chunk_count else 0.0
        return AdminKnowledgeDocumentDetailData(
            document=record,
            chunk_stats=AdminKnowledgeChunkStats(
                chunk_count=record.chunk_count,
                token_count=record.token_count,
                average_tokens_per_chunk=average_tokens,
                latest_job_id=profile.latest_job_id,
            ),
            error_message=profile.error_message,
        )

    def list_document_chunks(
        self,
        doc_id: str,
        *,
        page: int,
        page_size: int,
    ) -> AdminKnowledgeChunkListData:
        self._require_document(doc_id)
        records = [
            AdminKnowledgeChunkRecord(
                chunk_id=chunk.id,
                doc_id=chunk.document_id,
                position=max(0, chunk.ordinal - 1),
                content_preview=chunk.content[:220],
                token_count=chunk.token_estimate,
                tags=chunk.tags,
                updated_at=chunk.created_at,
            )
            for chunk in self.repository.list_chunks(document_id=doc_id)
        ]
        return self._paginate(
            records,
            page=page,
            page_size=page_size,
            factory=AdminKnowledgeChunkListData,
            sort_by="position",
            sort_order="asc",
        )

    def reindex_document(
        self,
        doc_id: str,
        payload: AdminKnowledgeReindexRequest,
        *,
        operator_id: str,
        operator_ip: str | None,
        reason: str,
    ) -> AdminAsyncJob:
        if payload.confirm_token != f"reindex:{doc_id}":
            DOCUMENT_REINDEX_RUNS_TOTAL.labels(outcome="rejected").inc()
            ADMIN_WRITE_REQUESTS_TOTAL.labels(action="reindex", outcome="rejected").inc()
            raise AdminValidationError("confirm_token must match reindex:{doc_id}")

        before = self._build_document_record(doc_id)
        response = self.ingestion_service.reindex_document(doc_id)
        profile = self._ensure_document_profile(response.document.id)
        updated_profile = profile.model_copy(
            update={
                "version_no": profile.version_no + 1,
                "index_status": "ready",
                "indexed_at": response.document.updated_at,
                "error_message": None,
                "latest_job_id": response.job.id,
            }
        )
        self.repository.save_document_profile(updated_profile)
        after = self._build_document_record(doc_id)
        job = AdminAsyncJob(
            job_id=response.job.id,
            type="knowledge_document_reindex",
            status="succeeded",
            progress=100,
            created_at=response.job.created_at,
            params={
                "doc_id": doc_id,
                "kb_id": response.document.source_id,
                "force": payload.force,
            },
            finished_at=response.job.completed_at,
        )
        self.repository.save_admin_job(job)
        self.audit_service.record(
            operator_id=operator_id,
            resource_type="knowledge_document",
            resource_id=doc_id,
            action="reindex",
            reason=reason,
            before_json=before.model_dump(mode="json"),
            after_json=after.model_dump(mode="json"),
            operator_ip=operator_ip,
            created_at=utc_now(),
        )
        DOCUMENT_REINDEX_RUNS_TOTAL.labels(outcome="success").inc()
        ADMIN_WRITE_REQUESTS_TOTAL.labels(action="reindex", outcome="success").inc()
        return job

    def get_job(self, job_id: str) -> AdminAsyncJob:
        job = self.repository.get_admin_job(job_id)
        if job is None:
            raise AdminNotFoundError(f"Unknown admin job: {job_id}")
        return job

    def preview_search(
        self,
        payload: AdminRetrievalSearchPreviewRequest,
    ) -> AdminRetrievalSearchPreviewData:
        if payload.kb_id:
            self._require_source(payload.kb_id)
        result = self.search_service.search(
            SearchRequest(
                query=payload.query,
                topK=payload.top_k,
                sourceIds=[payload.kb_id] if payload.kb_id else [],
                tags=payload.tags,
            )
        )
        items = [
            AdminRetrievalSearchSource(
                doc_id=match.chunk.document_id,
                chunk_id=match.chunk.id,
                kb_id=match.chunk.source_id,
                title=match.chunk.document_title,
                score=match.score,
                content_preview=match.chunk.content[:220],
                source_type=self._ensure_document_profile(match.chunk.document_id).source_type,
                tags=match.chunk.tags,
            )
            for match in result.results
        ]
        return AdminRetrievalSearchPreviewData(
            query=payload.query,
            rewritten_query=payload.query,
            total=result.total,
            items=items,
            degraded=False,
        )

    def list_audit_records(
        self,
        *,
        page: int,
        page_size: int,
        resource_type: str | None = None,
        action: str | None = None,
        operator_id: str | None = None,
    ) -> AdminAuditListData:
        records = self.audit_service.list_records(
            resource_type=resource_type,
            action=action,
            operator_id=operator_id,
        )
        return self._paginate(
            records,
            page=page,
            page_size=page_size,
            factory=AdminAuditListData,
            sort_by="created_at",
            sort_order="desc",
        )

    def _build_knowledge_base_record(self, kb_id: str) -> AdminKnowledgeBaseRecord:
        source = self._require_source(kb_id)
        profile = self._ensure_knowledge_base_profile(kb_id)
        return AdminKnowledgeBaseRecord(
            kb_id=source.id,
            code=profile.code,
            name=source.name,
            scene=profile.scene,
            language=profile.language,
            retrieval_mode=profile.retrieval_mode,
            status=profile.status,
            description=source.description,
            document_count=source.document_count,
            chunk_count=source.chunk_count,
            created_at=source.created_at,
            updated_at=max(source.updated_at, profile.updated_at),
        )

    def _build_document_record(self, doc_id: str) -> AdminKnowledgeDocumentRecord:
        document = self._require_document(doc_id)
        profile = self._ensure_document_profile(doc_id)
        return AdminKnowledgeDocumentRecord(
            doc_id=document.id,
            kb_id=document.source_id,
            title=document.title,
            status=profile.status,
            parse_status=profile.parse_status,
            index_status=profile.index_status,
            version_no=profile.version_no,
            file_id=profile.file_id,
            source_type=profile.source_type,
            source_uri=profile.source_uri,
            chunk_count=len(document.chunk_ids),
            token_count=sum(chunk.token_estimate for chunk in self.repository.list_chunks(document_id=doc_id)),
            error_message=profile.error_message,
            indexed_at=profile.indexed_at or document.updated_at,
        )

    def _ensure_knowledge_base_profile(self, kb_id: str) -> KnowledgeBaseProfile:
        profile = self.repository.get_knowledge_base_profile(kb_id)
        if profile is not None:
            return profile
        source = self._require_source(kb_id)
        fallback = _slugify(source.name, source.id)
        documents = self.repository.list_documents(source_id=kb_id)
        language = documents[0].language if documents else "zh-CN"
        profile = KnowledgeBaseProfile(
            kb_id=source.id,
            code=_slugify((source.uri or fallback).replace("kb://", ""), fallback),
            scene=source.kind,
            language=language,
            retrieval_mode="hybrid-baseline",
            embedding_model="baseline-keyword",
            status="ready",
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
        return self.repository.save_knowledge_base_profile(profile)

    def _ensure_document_profile(self, doc_id: str) -> KnowledgeDocumentProfile:
        profile = self.repository.get_document_profile(doc_id)
        if profile is not None:
            return profile
        document = self._require_document(doc_id)
        source = self._require_source(document.source_id)
        profile = KnowledgeDocumentProfile(
            doc_id=document.id,
            kb_id=document.source_id,
            status="active",
            parse_status="completed",
            index_status="ready",
            version_no=1,
            source_type="inline",
            source_uri=source.uri,
            indexed_at=document.updated_at,
            error_message=None,
            latest_job_id=None,
        )
        return self.repository.save_document_profile(profile)

    def _require_source(self, kb_id: str):
        source = self.repository.get_source(kb_id)
        if source is None:
            raise AdminNotFoundError(f"Unknown knowledge base: {kb_id}")
        return source

    def _require_document(self, doc_id: str):
        document = self.repository.get_document(doc_id)
        if document is None:
            raise AdminNotFoundError(f"Unknown knowledge document: {doc_id}")
        return document

    @staticmethod
    def _paginate(items, *, page: int, page_size: int, factory, sort_by: str, sort_order: str):
        total = len(items)
        total_pages = math.ceil(total / page_size) if total else 0
        start = (page - 1) * page_size
        end = start + page_size
        return factory(
            items=items[start:end],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_by,
            sort_order=sort_order,
        )


@lru_cache(maxsize=1)
def get_admin_service() -> KnowledgeAdminService:
    return KnowledgeAdminService(
        get_repository(),
        get_ingestion_service(),
        get_search_service(),
        get_file_import_service(),
        get_admin_audit_service(),
    )
