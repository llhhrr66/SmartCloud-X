from typing import Any, Literal

from pydantic import BaseModel, Field


class CanonicalErrorDetail(BaseModel):
    type: str
    field: str | None = None
    reason: str | None = None
    details: dict[str, Any] | None = None


class CanonicalSuccessEnvelope(BaseModel):
    code: int = 0
    message: str
    data: Any
    request_id: str
    timestamp: int


class CanonicalErrorEnvelope(BaseModel):
    code: int
    message: str
    request_id: str
    timestamp: int
    data: None = None
    error: CanonicalErrorDetail | None = None


class KnowledgeBaseProfile(BaseModel):
    kb_id: str
    code: str
    scene: str
    language: str
    retrieval_mode: str
    embedding_model: str
    status: str = "ready"
    created_at: str
    updated_at: str


class KnowledgeDocumentProfile(BaseModel):
    doc_id: str
    kb_id: str
    status: str = "active"
    parse_status: str = "completed"
    index_status: str = "ready"
    version_no: int = 1
    file_id: str | None = None
    source_type: str = "inline"
    source_uri: str | None = None
    indexed_at: str | None = None
    error_message: str | None = None
    latest_job_id: str | None = None


class AdminAsyncJob(BaseModel):
    job_id: str
    type: str
    status: str
    progress: int = Field(ge=0, le=100)
    created_at: str
    params: dict[str, Any] | None = None
    result_file_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    finished_at: str | None = None


class AdminKnowledgeBaseRecord(BaseModel):
    kb_id: str
    code: str
    name: str
    scene: str
    language: str
    retrieval_mode: str
    status: str
    description: str | None = None
    document_count: int = 0
    chunk_count: int = 0
    created_at: str
    updated_at: str


class AdminKnowledgeBaseListData(BaseModel):
    items: list[AdminKnowledgeBaseRecord]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "updated_at"
    sort_order: Literal["asc", "desc"] = "desc"


class AdminKnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    code: str = Field(min_length=1)
    scene: str = Field(min_length=1)
    language: str = Field(min_length=1)
    retrieval_mode: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    description: str | None = None


class AdminKnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    retrieval_mode: str | None = Field(default=None, min_length=1)
    status: Literal["ready", "disabled"] | None = None


class AdminKnowledgeDocumentRecord(BaseModel):
    doc_id: str
    kb_id: str
    title: str
    status: str
    parse_status: str
    index_status: str
    version_no: int
    file_id: str | None = None
    source_type: str | None = None
    source_uri: str | None = None
    chunk_count: int = 0
    token_count: int = 0
    error_message: str | None = None
    indexed_at: str | None = None


class AdminKnowledgeDocumentListData(BaseModel):
    items: list[AdminKnowledgeDocumentRecord]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "indexed_at"
    sort_order: Literal["asc", "desc"] = "desc"


class AdminKnowledgeDocumentCreateRequest(BaseModel):
    file_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_type: str = Field(min_length=1)
    source_uri: str | None = None


class AdminKnowledgeChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    position: int
    content_preview: str
    token_count: int
    score: float | None = None
    tags: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class AdminKnowledgeChunkListData(BaseModel):
    items: list[AdminKnowledgeChunkRecord]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "position"
    sort_order: Literal["asc", "desc"] = "asc"


class AdminKnowledgeChunkStats(BaseModel):
    chunk_count: int = 0
    token_count: int = 0
    average_tokens_per_chunk: float = 0.0
    latest_job_id: str | None = None


class AdminKnowledgeDocumentDetailData(BaseModel):
    document: AdminKnowledgeDocumentRecord
    chunk_stats: AdminKnowledgeChunkStats
    error_message: str | None = None


class AdminKnowledgeReindexRequest(BaseModel):
    force: bool
    confirm_token: str = Field(min_length=1)


class AdminRetrievalSearchPreviewRequest(BaseModel):
    query: str = Field(min_length=1)
    kb_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    tags: list[str] = Field(default_factory=list)


class AdminRetrievalSearchSource(BaseModel):
    doc_id: str
    chunk_id: str
    kb_id: str | None = None
    title: str
    score: float
    content_preview: str
    source_type: str | None = None
    tags: list[str] = Field(default_factory=list)


class AdminRetrievalSearchPreviewData(BaseModel):
    query: str
    rewritten_query: str | None = None
    total: int
    items: list[AdminRetrievalSearchSource]
    degraded: bool = False


class AdminAuditRecord(BaseModel):
    audit_id: str
    operator_type: str
    operator_id: str
    resource_type: str
    resource_id: str
    action: str
    reason: str
    before_json: dict[str, Any] | None = None
    after_json: dict[str, Any] | None = None
    operator_ip: str | None = None
    created_at: str


class AdminAuditListData(BaseModel):
    items: list[AdminAuditRecord]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"
