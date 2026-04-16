from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


T = TypeVar("T")


class ApiEnvelope(BaseModel, Generic[T]):
    success: bool = True
    data: Optional[T] = None
    request_id: str | None = Field(default=None, alias="requestId")
    error: ErrorInfo | None = None

    model_config = {"populate_by_name": True}
