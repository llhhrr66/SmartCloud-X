from __future__ import annotations

from pydantic import BaseModel, Field


class LlmProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    api_key: str = Field(..., min_length=1)
    api_url: str = Field(..., min_length=1)
    model_name: str = Field(..., min_length=1)
    provider_type: str = Field(default="openai-compatible", max_length=64)
    is_active: bool = Field(default=False)


class LlmProviderUpdate(BaseModel):
    name: str | None = None
    api_key: str | None = None
    api_url: str | None = None
    model_name: str | None = None
    provider_type: str | None = None
    is_active: bool | None = None


class LlmProviderRecord(BaseModel):
    provider_id: str
    name: str
    api_key: str
    api_url: str
    model_name: str
    provider_type: str
    is_active: bool
    created_at: str
    updated_at: str


class LlmProviderTestRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    api_url: str = Field(..., min_length=1)
    model_name: str | None = None


class LlmProviderTestResult(BaseModel):
    success: bool
    message: str
    model_id: str | None = None
    latency_ms: int | None = None


class LlmProviderModelsResult(BaseModel):
    success: bool
    message: str
    models: list[str] = Field(default_factory=list)
