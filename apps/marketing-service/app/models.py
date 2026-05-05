from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")

    model_config = {"populate_by_name": True}


class ServiceError(Exception):
    def __init__(self, status_code: int, code: int, message: str, *, public: bool = False, field: str | None = None, error_type: str | None = None, details: dict[str, Any] | None = None) -> None:
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


class MarketingCampaign(BaseModel):
    campaign_id: str
    name: str
    product_type: str
    status: Literal["published", "draft", "expired", "pending_review", "rejected", "suspended"]
    start_at: str
    end_at: str
    landing_page_url: str
    highlights: list[str] = Field(default_factory=list)
    discount_type: str | None = None
    discount_value: float | None = None
    discount_description: str | None = None
    target_segment: str | None = None
    region: str | None = None
    description: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    max_redemptions: int | None = None
    budget: float | None = None


class MarketingCampaignListData(BaseModel):
    items: list[MarketingCampaign]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "start_at"
    sort_order: Literal["asc", "desc"] = "desc"


class MarketingCopyRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    tone: Literal["professional", "growth", "launch"]
    keywords: list[str] = Field(default_factory=list)


class MarketingCopyResult(BaseModel):
    copy_id: str
    campaign_id: str
    campaign_name: str
    topic: str
    audience: str
    tone: Literal["professional", "growth", "launch"]
    headline: str
    summary: str
    body: str
    call_to_action: str
    keywords: list[str] = Field(default_factory=list)
    landing_page_url: str | None = None
    created_at: str


class MarketingCopyListData(BaseModel):
    items: list[MarketingCopyResult]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"


class CreatePosterTaskRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    slogan: str = Field(min_length=1)
    size: str = Field(min_length=1)


class PosterTask(BaseModel):
    task_id: str
    user_id: str | None = None
    tenant_id: str | None = None
    status: Literal["queued", "running", "completed", "failed"]
    campaign_id: str
    campaign_name: str | None = None
    theme: str
    slogan: str | None = None
    size: str
    created_at: str
    image_url: str | None = None
    error_message: str | None = None
    estimated_seconds: int | None = None
    updated_at: str | None = None


class PosterResultData(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    result_ready: bool = False
    campaign_id: str
    campaign_name: str | None = None
    theme: str
    slogan: str | None = None
    size: str
    image_url: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    mime_type: str | None = None
    generated_at: str | None = None


class PosterTaskCreateResponseData(BaseModel):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    estimated_seconds: int = Field(ge=0)


class PosterTaskListData(BaseModel):
    items: list[PosterTask]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "updated_at"
    sort_order: Literal["asc", "desc"] = "desc"


class PromotionLinkRequest(BaseModel):
    campaign_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    source: str | None = Field(default=None, min_length=1)
    content_tag: str | None = Field(default=None, min_length=1)


class PromotionLinkResult(BaseModel):
    link_id: str
    campaign_id: str
    campaign_name: str
    channel: str
    short_url: str
    landing_page_url: str
    tracking_code: str
    created_at: str
    note: str


class PromotionLinkListData(BaseModel):
    items: list[PromotionLinkResult]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "created_at"
    sort_order: Literal["asc", "desc"] = "desc"


class MarketingCampaignRecord(MarketingCampaign):
    deleted_at: str | None = None


class MarketingCapabilitiesData(BaseModel):
    copy_provider: dict[str, Any] = Field(alias="copy")
    poster_provider: dict[str, Any] = Field(alias="poster")

    model_config = {"populate_by_name": True}


class AdminCampaignUpsertRequest(BaseModel):
    campaign_id: str | None = None
    name: str = Field(min_length=1)
    product_type: str = Field(min_length=1)
    status: Literal["published", "draft", "expired", "pending_review", "rejected", "suspended"]
    start_at: str
    end_at: str
    landing_page_url: str = Field(min_length=1)
    highlights: list[str] = Field(default_factory=list)
    discount_type: str | None = None
    discount_value: float | None = None
    discount_description: str | None = None
    target_segment: str | None = None
    region: str | None = None
    description: str | None = None
    created_by: str | None = None
    max_redemptions: int | None = None
    budget: float | None = None


class AdminCampaignListData(BaseModel):
    items: list[MarketingCampaign]
    page: int
    page_size: int
    total: int
    total_pages: int
    sort_by: str = "start_at"
    sort_order: Literal["asc", "desc"] = "desc"


class PosterTaskRecord(BaseModel):
    task_id: str
    user_id: str
    tenant_id: str | None = None
    campaign_id: str
    campaign_name: str
    theme: str
    slogan: str
    size: str
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    estimated_seconds: int = Field(ge=0)
    image_url: str | None = None
    error_message: str | None = None
    updated_at: str | None = None

    def to_public(self) -> PosterTask:
        return PosterTask(task_id=self.task_id, user_id=self.user_id, tenant_id=self.tenant_id, status=self.status, campaign_id=self.campaign_id, campaign_name=self.campaign_name, theme=self.theme, slogan=self.slogan, size=self.size, created_at=self.created_at, image_url=self.image_url, error_message=self.error_message, estimated_seconds=self.estimated_seconds, updated_at=self.updated_at)


class PosterIdempotencyRecord(BaseModel):
    key: str
    user_id: str
    tenant_id: str | None = None
    payload_hash: str
    task_id: str
    accepted_status: Literal["queued", "running", "completed", "failed"]
    estimated_seconds: int = Field(ge=0)
    created_at: str


class StoredMarketingCopy(MarketingCopyResult):
    user_id: str
    tenant_id: str | None = None


class StoredPromotionLink(PromotionLinkResult):
    user_id: str
    tenant_id: str | None = None


class MarketingStoreSnapshot(BaseModel):
    campaigns: list[MarketingCampaignRecord] = Field(default_factory=list)
    poster_tasks: list[PosterTaskRecord] = Field(default_factory=list)
    poster_idempotency_records: list[PosterIdempotencyRecord] = Field(default_factory=list)
    generated_copies: list[StoredMarketingCopy] = Field(default_factory=list)
    promotion_links: list[StoredPromotionLink] = Field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return utc_now().isoformat()


def now_timestamp_ms() -> int:
    return int(utc_now().timestamp() * 1000)
