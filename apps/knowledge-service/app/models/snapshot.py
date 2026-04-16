from pydantic import BaseModel, Field

from app.models.admin import (
    AdminAsyncJob,
    AdminAuditRecord,
    AdminKnowledgeBaseRecord,
    KnowledgeDocumentProfile,
)
from app.models.knowledge import (
    IngestionJob,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeOverviewResponse,
    KnowledgeSource,
)
from app.models.runtime import KnowledgeRuntimeIntegrations


class KnowledgeRuntimeSnapshot(BaseModel):
    exported_at: str = Field(alias="exportedAt")
    service: str
    data_path: str = Field(alias="dataPath")
    audit_path: str = Field(alias="auditPath")
    import_root: str = Field(alias="importRoot")
    counts: dict[str, int] = Field(default_factory=dict)
    overview: KnowledgeOverviewResponse
    sources: list[KnowledgeSource] = Field(default_factory=list)
    documents: list[KnowledgeDocument] = Field(default_factory=list)
    chunks: list[KnowledgeChunk] = Field(default_factory=list)
    ingestions: list[IngestionJob] = Field(default_factory=list)
    knowledge_bases: list[AdminKnowledgeBaseRecord] = Field(
        default_factory=list,
        alias="knowledgeBases",
    )
    document_profiles: list[KnowledgeDocumentProfile] = Field(
        default_factory=list,
        alias="documentProfiles",
    )
    admin_jobs: list[AdminAsyncJob] = Field(default_factory=list, alias="adminJobs")
    recent_audit_records: list[AdminAuditRecord] = Field(
        default_factory=list,
        alias="recentAuditRecords",
    )
    integrations: KnowledgeRuntimeIntegrations

    model_config = {
        "populate_by_name": True,
    }
