from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.business_tools_sdk import (
    ToolAuthRequirements,
    ToolCompensationAction,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolPreflightResult,
    ToolUserActionHint,
)


class ToolDescriptor(ToolDefinition):
    pass


class ToolInvokeRequest(BaseModel):
    operation: str = "preview"
    payload: dict[str, Any] = Field(default_factory=dict)
    context: ToolExecutionContext = Field(default_factory=ToolExecutionContext)
    trace: dict[str, Any] = Field(default_factory=dict)


class ToolInvokeResponse(ToolExecutionResult):
    downstream_target: str = "business-tools"
    auth_requirements: ToolAuthRequirements = Field(default_factory=ToolAuthRequirements)


class ToolCallOperator(BaseModel):
    type: Literal["agent", "user", "admin", "system"] = "agent"
    id: str


class ToolCallUserContext(BaseModel):
    user_id: str | None = None
    account_id: str | None = None
    permissions: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=lambda: ["user"])
    tenant_id: str = "default"
    locale: str = "zh-CN"


class ToolCallRequest(BaseModel):
    trace_id: str
    conversation_id: str
    message_id: str | None = None
    tool_call_id: str
    tool_name: str
    operator: ToolCallOperator
    user_context: ToolCallUserContext = Field(default_factory=ToolCallUserContext)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    operation: Literal["preview", "execute"] = "execute"


class ToolCallError(BaseModel):
    retryable: bool = False
    provider: str = "business-tools"
    details: dict[str, Any] = Field(default_factory=dict)


class ToolCallResponse(BaseModel):
    success: bool
    code: int
    message: str
    status: str | None = None
    summary: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    audit_tags: list[str] = Field(default_factory=list)
    session_context_patch: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str
    latency_ms: int
    provider: str = "business-tools"
    error: ToolCallError | None = None
    compensation: ToolCompensationAction | None = None
    idempotency_key: str | None = None
    attempts: int = 1
    user_action_hint: ToolUserActionHint | None = None


class ToolPreflightResponse(ToolPreflightResult):
    downstream_target: str = "business-tools"
    provider: str = "business-tools"
    session_context_bindings: dict[str, list[str]] = Field(default_factory=dict)


class CompensationCallRequest(BaseModel):
    trace_id: str
    conversation_id: str
    compensation_id: str
    action_name: str
    operator: ToolCallOperator
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class CompensationCallResponse(BaseModel):
    success: bool
    code: int
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    compensation_id: str
    action_name: str
    latency_ms: int
    provider: str = "business-tools"
    error: ToolCallError | None = None
    idempotency_key: str | None = None
    attempts: int = 1


class ToolCallAuditRecord(BaseModel):
    tool_call_id: str
    trace_id: str
    conversation_id: str
    message_id: str | None = None
    tool_name: str
    operation: Literal["preview", "execute"]
    status: str
    success: bool
    code: int
    message: str
    summary: str | None = None
    provider: str = "business-tools"
    retryable: bool = False
    latency_ms: int
    attempts: int = 1
    tenant_id: str = "default"
    operator: ToolCallOperator
    user_context: ToolCallUserContext
    idempotency_key: str | None = None
    audit_tags: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    data_preview: dict[str, Any] = Field(default_factory=dict)
    session_context_patch: dict[str, Any] = Field(default_factory=dict)
    error: ToolCallError | None = None
    user_action_hint: ToolUserActionHint | None = None
    created_at: str
    updated_at: str


class McpToolsListResponse(BaseModel):
    tools: list[ToolDescriptor] = Field(default_factory=list)
