from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class CanonicalErrorDetail(BaseModel):
    type: str | None = None
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


class TraceContext(BaseModel):
    request_id: str | None = Field(default=None, alias="requestId")
    trace_id: str | None = Field(default=None, alias="traceId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    caller_service: str | None = Field(default=None, alias="callerService")

    model_config = {"populate_by_name": True}


class ServiceError(Exception):
    def __init__(
        self,
        status_code: int,
        code: int,
        message: str,
        *,
        public: bool = False,
        field: str | None = None,
        error_type: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.public = public
        self.field = field
        self.error_type = error_type
        self.details = details


class CurrentUserContext(BaseModel):
    user_id: str
    tenant_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    expires_at: str


class CreateResearchTaskRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=512)
    scope: str = Field(min_length=1, max_length=4000)
    depth: Literal["lite", "standard", "deep"]
    output_format: Literal["markdown", "pdf"]
    reference_urls: list[str] = Field(default_factory=list)


class ResearchCitation(BaseModel):
    title: str
    url: str
    snippet: str | None = None


class ResearchSection(BaseModel):
    title: str
    content: str


class ResearchResult(BaseModel):
    summary: str
    sections: list[ResearchSection] = Field(default_factory=list)
    citations: list[ResearchCitation] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchTask(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    topic: str
    scope: str
    depth: Literal["lite", "standard", "deep"]
    output_format: Literal["markdown", "pdf"]
    progress: int = Field(ge=0, le=100)
    created_at: str
    summary: str | None = None
    report_file_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    updated_at: str | None = None
    reference_urls: list[str] = Field(default_factory=list)


class ResearchTaskStatusData(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: int = Field(ge=0, le=100)
    created_at: str
    updated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result_ready: bool = False
    report_file_id: str | None = None


class ResearchTaskResultData(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    result_ready: bool = False
    output_format: Literal["markdown", "pdf"]
    summary: str | None = None
    report_file_id: str | None = None
    download_url: str | None = None
    preview_text: str | None = None
    citations: list[str] = Field(default_factory=list)
    generated_at: str | None = None
    sections: list[ResearchSection] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchTaskCreateResponseData(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    estimated_minutes: int = Field(ge=0)


class ResearchTaskListData(BaseModel):
    items: list[ResearchTask]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "updated_at"
    sort_order: Literal["asc", "desc"] = "desc"


class ResearchTaskRecord(BaseModel):
    task_id: str
    user_id: str
    tenant_id: str | None = None
    topic: str
    scope: str
    depth: Literal["lite", "standard", "deep"]
    output_format: Literal["markdown", "pdf"]
    reference_urls: list[str] = Field(default_factory=list)
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: int = Field(ge=0, le=100)
    created_at: str
    updated_at: str
    summary: str | None = None
    report_file_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None
    deleted_at: str | None = None
    agent_result: ResearchResult | None = None

    @field_validator("agent_result", mode="before")
    @classmethod
    def _coerce_agent_result(cls, value: Any) -> Any:
        if value in (None, "", {}):
            return None
        return value

    def to_public(self) -> ResearchTask:
        return ResearchTask(
            task_id=self.task_id,
            status=self.status,
            topic=self.topic,
            scope=self.scope,
            depth=self.depth,
            output_format=self.output_format,
            progress=self.progress,
            created_at=self.created_at,
            summary=self.summary,
            report_file_id=self.report_file_id,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error_message=self.error_message,
            updated_at=self.updated_at,
            reference_urls=list(self.reference_urls),
        )


class ResearchTaskMutationResponseData(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    updated_at: str
    error_message: str | None = None
    deleted_at: str | None = None


class ResearchCapabilitiesResponseData(BaseModel):
    provider: str
    active: bool
    capabilities: dict[str, Any]
    configuration: dict[str, Any]


class ResearchIdempotencyRecord(BaseModel):
    key: str
    user_id: str
    tenant_id: str | None = None
    payload_hash: str
    task_id: str
    accepted_status: Literal["queued", "running", "completed", "failed", "cancelled"]
    estimated_minutes: int = Field(ge=0)
    created_at: str


class ResearchStoreSnapshot(BaseModel):
    tasks: list[ResearchTaskRecord] = Field(default_factory=list)
    idempotency_records: list[ResearchIdempotencyRecord] = Field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return utc_now().isoformat()


def now_timestamp_ms() -> int:
    return int(utc_now().timestamp() * 1000)
