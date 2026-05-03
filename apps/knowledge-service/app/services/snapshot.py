from functools import lru_cache

from app.core.config import get_settings
from app.models.admin import AdminKnowledgeBaseRecord, KnowledgeBaseProfile
from app.models.snapshot import KnowledgeRuntimeSnapshot
from app.services.admin_audit import KnowledgeAdminAuditService, get_admin_audit_service
from app.services.analytics import KnowledgeAnalyticsService, get_analytics_service
from app.core.tracing import start_span
from app.services.ingestion import utc_now
from app.services.runtime_sync import KnowledgeRuntimeSyncService, get_runtime_sync_service
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository


class KnowledgeSnapshotService:
    def __init__(
        self,
        repository: KnowledgeStoreRepository,
        analytics_service: KnowledgeAnalyticsService,
        audit_service: KnowledgeAdminAuditService,
        runtime_sync_service: KnowledgeRuntimeSyncService,
    ) -> None:
        self.analytics_service = analytics_service
        self.repository = (
            analytics_service.repository
            if getattr(analytics_service, "repository", None) is not None
            else repository
        )
        self.audit_service = audit_service
        self.runtime_sync_service = runtime_sync_service
        self.settings = get_settings()

    def build_snapshot(self, audit_limit: int = 20) -> KnowledgeRuntimeSnapshot:
        with start_span(
            "knowledge.snapshot.export",
            smartcloud_snapshot_audit_limit=audit_limit,
        ):
            self.repository.refresh_runtime_state()
            self.repository.refresh_metadata_state()
            self.repository.reconcile_runtime_state()
            knowledge_base_profiles = sorted(
                self.repository.list_knowledge_base_profiles(),
                key=lambda item: item.updated_at,
                reverse=True,
            )
            document_profiles = sorted(
                self.repository.list_document_profiles(),
                key=lambda item: (item.indexed_at or "", item.doc_id),
                reverse=True,
            )
            return KnowledgeRuntimeSnapshot(
                exportedAt=utc_now(),
                service=self.settings.app_name,
                dataPath=str(self.settings.data_path.expanduser()),
                auditPath=str(self.settings.audit_path.expanduser()),
                importRoot=str(self.settings.import_root.expanduser()),
                counts=self.repository.snapshot_counts(),
                overview=self.analytics_service.build_overview(),
                sources=self.repository.list_sources(),
                documents=self.repository.list_documents(),
                chunks=self.repository.list_chunks(),
                ingestions=self.repository.list_ingestions(),
                knowledgeBases=[
                    self._build_knowledge_base_record(profile)
                    for profile in knowledge_base_profiles
                ],
                documentProfiles=document_profiles,
                adminJobs=self.repository.list_admin_jobs(),
                recentAuditRecords=self.audit_service.list_records()[:audit_limit],
                integrations=self.runtime_sync_service.build_integrations(),
            )

    def _build_knowledge_base_record(
        self,
        profile: KnowledgeBaseProfile,
    ) -> AdminKnowledgeBaseRecord:
        source = self.repository.get_source(profile.kb_id)
        return AdminKnowledgeBaseRecord(
            kb_id=profile.kb_id,
            code=profile.code,
            name=source.name if source else profile.code,
            scene=profile.scene,
            language=profile.language,
            retrieval_mode=profile.retrieval_mode,
            status=profile.status,
            description=source.description if source else None,
            document_count=source.document_count if source else 0,
            chunk_count=source.chunk_count if source else 0,
            created_at=source.created_at if source else profile.created_at,
            updated_at=source.updated_at if source else profile.updated_at,
        )


@lru_cache(maxsize=1)
def get_snapshot_service() -> KnowledgeSnapshotService:
    return KnowledgeSnapshotService(
        get_repository(),
        get_analytics_service(),
        get_admin_audit_service(),
        get_runtime_sync_service(),
    )
