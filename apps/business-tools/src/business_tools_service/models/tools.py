from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from business_tools import (
    ToolDefinition,
    ToolExecutionResult,
    ToolPreflightResult,
)


class OperatorContext(BaseModel):
    type: Literal["agent", "user", "admin", "system"] = "agent"
    id: str


class SubjectContext(BaseModel):
    user_id: str | None = None
    account_id: str | None = None
    tenant_id: str = "default"
    roles: list[str] = Field(default_factory=lambda: ["user"])
    permissions: list[str] = Field(default_factory=list)
    locale: str = "zh-CN"


class BusinessToolExecuteRequest(BaseModel):
    operator: OperatorContext
    subject: SubjectContext = Field(default_factory=SubjectContext)
    payload: dict[str, Any] = Field(default_factory=dict)
    operation: Literal["preview", "execute"] = "execute"


class BusinessToolExecuteResponse(ToolExecutionResult):
    data: dict[str, Any] = Field(default_factory=dict)


class BusinessCompensationExecuteRequest(BaseModel):
    compensation_id: str
    conversation_id: str
    action_name: str
    operator: OperatorContext
    payload: dict[str, Any] = Field(default_factory=dict)


class BusinessCompensationExecuteResponse(BaseModel):
    success: bool
    code: int
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    compensation_id: str
    action_name: str
    latency_ms: int
    retryable: bool = False
    provider: str = "business-tools"
    error_detail: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class BusinessToolDescriptor(ToolDefinition):
    pass


class BusinessToolCatalogResponse(BaseModel):
    tools: list[BusinessToolDescriptor] = Field(default_factory=list)


class BusinessToolPreflightResponse(ToolPreflightResult):
    session_context_bindings: dict[str, list[str]] = Field(default_factory=dict)
