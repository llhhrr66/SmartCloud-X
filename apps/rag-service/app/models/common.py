from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    retryable: bool = False


T = TypeVar("T")


class TraceContext(BaseModel):
    request_id: str | None = Field(default=None, alias="requestId")
    trace_id: str | None = Field(default=None, alias="traceId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    caller_service: str | None = Field(default=None, alias="callerService")

    model_config = {
        "populate_by_name": True,
    }


class ApiEnvelope(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    request_id: str | None = Field(default=None, alias="requestId")
    trace: TraceContext | None = None
    error: ErrorInfo | None = None
    meta: dict[str, Any] | None = None

    model_config = {
        "populate_by_name": True,
    }
