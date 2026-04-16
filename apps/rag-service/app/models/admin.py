from typing import Any

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


class AdminRetrievalDiagnosticsRequest(BaseModel):
    query: str = Field(min_length=1)
    kb_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    include_citations: bool = True
