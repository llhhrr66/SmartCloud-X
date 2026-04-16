from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


ToolOperation = Literal["preview", "execute"]
ToolMode = Literal["query", "write"]
ToolUserActionType = Literal["clarify-tool-input", "collect-auth-context", "user-confirmation"]


class ToolAuthRequirements(BaseModel):
    require_user_id: bool = False
    require_account_id: bool = False
    allowed_roles: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    confirmation_required: bool = False


class ToolExecutionContext(BaseModel):
    request_id: str | None = None
    trace_id: str | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    tenant_id: str = "default"
    user_id: str | None = None
    account_id: str | None = None
    roles: list[str] = Field(default_factory=lambda: ["user"])
    permissions: list[str] = Field(default_factory=list)
    locale: str = "zh-CN"
    operator_type: str = "agent"
    operator_id: str | None = None
    idempotency_key: str | None = None

    def missing_auth(self, requirements: ToolAuthRequirements) -> list[str]:
        missing: list[str] = []
        if requirements.require_user_id and not self.user_id:
            missing.append("user_id")
        if requirements.require_account_id and not self.account_id:
            missing.append("account_id")
        if requirements.allowed_roles and not set(self.roles).intersection(requirements.allowed_roles):
            missing.append("roles")
        missing_permissions = [
            permission
            for permission in requirements.required_permissions
            if permission not in self.permissions
        ]
        if missing_permissions:
            missing.extend(f"permission:{permission}" for permission in missing_permissions)
        return missing


class ToolCompensationAction(BaseModel):
    action_name: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolUserActionHint(BaseModel):
    action: ToolUserActionType
    message: str
    missing_fields: list[str] = Field(default_factory=list)
    missing_payload_hints: dict[str, str] = Field(default_factory=dict)
    missing_auth_context: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    requires_account_context: bool = False
    confirmation_required: bool = False
    session_context_bindings: dict[str, list[str]] = Field(default_factory=dict)
    confirm_tool_names: list[str] = Field(default_factory=list)


class ToolDefinition(BaseModel):
    name: str
    capability: str
    description: str
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    owner: str = "apps/business-tools"
    mode: ToolMode = "query"
    supported_operations: list[ToolOperation] = Field(default_factory=lambda: ["preview", "execute"])
    input_schema: dict[str, Any] = Field(default_factory=dict)
    input_schema_hint: dict[str, Any] = Field(default_factory=dict)
    input_field_hints: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema_hint: dict[str, Any] = Field(default_factory=dict)
    session_context_bindings: dict[str, list[str]] = Field(default_factory=dict)
    session_context_output_keys: list[str] = Field(default_factory=list)
    prerequisite_tool_names: list[str] = Field(default_factory=list)
    operation_required_fields: dict[ToolOperation, list[str]] = Field(default_factory=dict)
    auth_requirements: ToolAuthRequirements = Field(default_factory=ToolAuthRequirements)
    downstream_target: str = "business-tools"
    provider: str = "business-tools"
    timeout_ms: int = 5000
    idempotent: bool = True
    idempotency_window_seconds: int | None = None
    high_risk: bool = False
    cache_ttl_seconds: int | None = None


class ToolInvocationRequest(BaseModel):
    tool_name: str
    operation: ToolOperation = "preview"
    payload: dict[str, Any] = Field(default_factory=dict)
    context: ToolExecutionContext = Field(default_factory=ToolExecutionContext)


class ToolExecutionResult(BaseModel):
    tool_name: str
    operation: ToolOperation
    status: str
    summary: str
    result: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    audit_tags: list[str] = Field(default_factory=list)
    session_context_patch: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    code: int = 0
    message: str = "ok"
    retryable: bool = False
    provider: str = "business-tools"
    cache_ttl_seconds: int | None = None
    error_detail: dict[str, Any] = Field(default_factory=dict)
    compensation: ToolCompensationAction | None = None
    idempotency_key: str | None = None
    user_action_hint: ToolUserActionHint | None = None


class ToolPreflightResult(BaseModel):
    tool_name: str
    operation: ToolOperation
    status: Literal[
        "ready",
        "missing-tool",
        "missing-payload",
        "auth-required",
        "confirmation-required",
        "invalid-operation",
    ] = "ready"
    ready: bool = True
    available: bool = True
    high_risk: bool = False
    tool_mode: ToolMode | None = None
    timeout_ms: int | None = None
    idempotent: bool | None = None
    cache_ttl_seconds: int | None = None
    missing_payload_fields: list[str] = Field(default_factory=list)
    missing_payload_hints: dict[str, str] = Field(default_factory=dict)
    missing_auth_context: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    requires_account_context: bool = False
    confirmation_required: bool = False
    user_action_hint: ToolUserActionHint | None = None


class CompensationExecutionRequest(BaseModel):
    action_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    context: ToolExecutionContext = Field(default_factory=ToolExecutionContext)


class CompensationExecutionResult(BaseModel):
    action_name: str
    status: str
    summary: str
    result: dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    code: int = 0
    message: str = "ok"
    retryable: bool = False
    provider: str = "business-tools"
    error_detail: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class BusinessTool(Protocol):
    definition: ToolDefinition

    def invoke(self, request: ToolInvocationRequest) -> ToolExecutionResult:
        ...


def is_missing_tool_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def preflight_tool_invocation(
    definition: ToolDefinition,
    request: ToolInvocationRequest,
) -> ToolPreflightResult:
    if request.operation not in definition.supported_operations:
        return ToolPreflightResult(
            tool_name=definition.name,
            operation=request.operation,
            status="invalid-operation",
            ready=False,
            available=True,
            high_risk=definition.high_risk,
            tool_mode=definition.mode,
            timeout_ms=definition.timeout_ms,
            idempotent=definition.idempotent,
            cache_ttl_seconds=definition.cache_ttl_seconds,
            required_permissions=list(definition.auth_requirements.required_permissions),
            requires_account_context=definition.auth_requirements.require_account_id,
            confirmation_required=definition.auth_requirements.confirmation_required,
        )

    required_fields = definition.operation_required_fields.get(request.operation, [])
    missing_payload_fields = [
        field
        for field in required_fields
        if is_missing_tool_value(request.payload.get(field))
    ]
    missing_auth_context = (
        request.context.missing_auth(definition.auth_requirements)
        if request.operation == "execute"
        else []
    )
    confirmation_required = (
        request.operation == "execute"
        and definition.auth_requirements.confirmation_required
        and not request.payload.get("_confirmed")
    )
    status = "ready"
    if missing_payload_fields:
        status = "missing-payload"
    elif missing_auth_context:
        status = "auth-required"
    elif confirmation_required:
        status = "confirmation-required"
    return ToolPreflightResult(
        tool_name=definition.name,
        operation=request.operation,
        status=status,
        ready=status == "ready",
        available=True,
        high_risk=definition.high_risk,
        tool_mode=definition.mode,
        timeout_ms=definition.timeout_ms,
        idempotent=definition.idempotent,
        cache_ttl_seconds=definition.cache_ttl_seconds,
        missing_payload_fields=missing_payload_fields,
        missing_payload_hints={
            field: definition.input_field_hints[field]
            for field in missing_payload_fields
            if field in definition.input_field_hints
        },
        missing_auth_context=missing_auth_context,
        required_permissions=list(definition.auth_requirements.required_permissions),
        requires_account_context=definition.auth_requirements.require_account_id,
        confirmation_required=definition.auth_requirements.confirmation_required,
        user_action_hint=build_tool_user_action_hint(
            definition,
            status=status,
            missing_payload_fields=missing_payload_fields,
            missing_payload_hints={
                field: definition.input_field_hints[field]
                for field in missing_payload_fields
                if field in definition.input_field_hints
            },
            missing_auth_context=missing_auth_context,
            required_permissions=list(definition.auth_requirements.required_permissions),
            requires_account_context=definition.auth_requirements.require_account_id,
            confirmation_required=definition.auth_requirements.confirmation_required,
        ),
    )


def build_tool_user_action_hint(
    definition: ToolDefinition,
    *,
    status: str,
    missing_payload_fields: list[str] | None = None,
    missing_payload_hints: dict[str, str] | None = None,
    missing_auth_context: list[str] | None = None,
    required_permissions: list[str] | None = None,
    requires_account_context: bool = False,
    confirmation_required: bool = False,
) -> ToolUserActionHint | None:
    payload_fields = list(missing_payload_fields or [])
    payload_hints = dict(missing_payload_hints or {})
    auth_context = list(missing_auth_context or [])
    permissions = list(required_permissions or [])
    if status in {"missing-payload", "invalid-payload"}:
        hints = [payload_hints[field] for field in payload_fields if field in payload_hints]
        message = "；".join(hints) if hints else (
            f"继续执行前请补充：{', '.join(payload_fields)}。"
            if payload_fields
            else f"继续执行 {definition.name} 前需要补充更多信息。"
        )
        return ToolUserActionHint(
            action="clarify-tool-input",
            message=message,
            missing_fields=payload_fields,
            missing_payload_hints=payload_hints,
            session_context_bindings={
                field: list(definition.session_context_bindings.get(field, []))
                for field in payload_fields
                if definition.session_context_bindings.get(field)
            },
        )
    if status == "auth-required":
        return ToolUserActionHint(
            action="collect-auth-context",
            message=f"{definition.name} 执行前需补充鉴权上下文。",
            missing_auth_context=auth_context,
            required_permissions=permissions,
            requires_account_context=requires_account_context,
        )
    if status == "confirmation-required":
        return ToolUserActionHint(
            action="user-confirmation",
            message=f"{definition.name} 属于高风险写操作，需先完成显式确认。",
            confirmation_required=confirmation_required,
            confirm_tool_names=[definition.name],
        )
    return None
