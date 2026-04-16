from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Query, Request

from business_tools import (
    CompensationExecutionRequest,
    ToolMode,
    ToolExecutionContext,
    ToolInvocationRequest,
    build_catalog,
    execute_compensation,
    filter_tool_definitions,
    preflight_tool_invocation,
)
from business_tools_service.core.config import get_settings
from business_tools_service.models.tools import (
    BusinessCompensationExecuteRequest,
    BusinessCompensationExecuteResponse,
    BusinessToolCatalogResponse,
    BusinessToolDescriptor,
    BusinessToolExecuteRequest,
    BusinessToolExecuteResponse,
    BusinessToolPreflightResponse,
)

router = APIRouter(tags=["business-tools"])
_catalog = build_catalog()
_settings = get_settings()


@router.get("/tools", response_model=BusinessToolCatalogResponse)
def list_tools(
    request: Request,
    capability: str | None = Query(default=None),
    mode: ToolMode | None = Query(default=None),
    tag: str | None = Query(default=None),
    query: str | None = Query(default=None),
) -> BusinessToolCatalogResponse:
    _validate_internal_caller(request)
    return BusinessToolCatalogResponse(
        tools=[
            BusinessToolDescriptor.model_validate(definition.model_dump())
            for definition in filter_tool_definitions(
                _catalog.values(),
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )
        ]
    )


@router.get("/tools/{tool_name}", response_model=BusinessToolDescriptor)
def get_tool(tool_name: str, request: Request) -> BusinessToolDescriptor:
    _validate_internal_caller(request)
    tool = _catalog.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail={"code": "ORCH_TOOL_NOT_FOUND", "message": f"Unknown tool: {tool_name}"})
    return BusinessToolDescriptor.model_validate(tool.definition.model_dump())


@router.post("/execute/{tool_name}", response_model=BusinessToolExecuteResponse)
def execute_tool(
    tool_name: str,
    payload: BusinessToolExecuteRequest,
    request: Request,
) -> BusinessToolExecuteResponse:
    _validate_internal_caller(request)
    x_trace_id = request.headers.get(_settings.trace_id_header)
    x_tool_call_id = request.headers.get(_settings.tool_call_id_header)
    x_message_id = request.headers.get(_settings.message_id_header)
    x_tenant_id = request.headers.get(_settings.tenant_id_header)
    idempotency_key = request.headers.get(_settings.idempotency_key_header)
    tool = _catalog.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail={"code": "ORCH_TOOL_NOT_FOUND", "message": f"Unknown tool: {tool_name}"})

    result = tool.invoke(
        ToolInvocationRequest(
            tool_name=tool_name,
            operation=payload.operation,
            payload=payload.payload,
            context=_build_execution_context(
                request,
                payload,
                x_trace_id,
                x_tool_call_id,
                x_message_id,
                x_tenant_id,
                idempotency_key,
            ),
        )
    )
    return BusinessToolExecuteResponse(
        **result.model_dump(),
        data=result.result,
    )


@router.post("/preflight/{tool_name}", response_model=BusinessToolPreflightResponse)
def preflight_tool(
    tool_name: str,
    payload: BusinessToolExecuteRequest,
    request: Request,
) -> BusinessToolPreflightResponse:
    _validate_internal_caller(request)
    x_trace_id = request.headers.get(_settings.trace_id_header)
    x_tool_call_id = request.headers.get(_settings.tool_call_id_header)
    x_message_id = request.headers.get(_settings.message_id_header)
    x_tenant_id = request.headers.get(_settings.tenant_id_header)
    idempotency_key = request.headers.get(_settings.idempotency_key_header)
    tool = _catalog.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail={"code": "ORCH_TOOL_NOT_FOUND", "message": f"Unknown tool: {tool_name}"})

    preflight = preflight_tool_invocation(
        tool.definition,
        ToolInvocationRequest(
            tool_name=tool_name,
            operation=payload.operation,
            payload=payload.payload,
            context=_build_execution_context(
                request,
                payload,
                x_trace_id,
                x_tool_call_id,
                x_message_id,
                x_tenant_id,
                idempotency_key,
            ),
        ),
    )
    return BusinessToolPreflightResponse(
        **preflight.model_dump(),
        session_context_bindings=dict(tool.definition.session_context_bindings),
    )


@router.post("/compensations/execute", response_model=BusinessCompensationExecuteResponse)
def execute_tool_compensation(
    payload: BusinessCompensationExecuteRequest,
    request: Request,
) -> BusinessCompensationExecuteResponse:
    _validate_internal_caller(request)
    x_trace_id = request.headers.get(_settings.trace_id_header)
    idempotency_key = request.headers.get(_settings.idempotency_key_header)
    started = time.perf_counter()
    result = execute_compensation(
        CompensationExecutionRequest(
            action_name=payload.action_name,
            payload=payload.payload,
            context=ToolExecutionContext(
                trace_id=x_trace_id,
                request_id=payload.compensation_id,
                conversation_id=payload.conversation_id,
                operator_type=payload.operator.type,
                operator_id=payload.operator.id,
                idempotency_key=idempotency_key,
            ),
        )
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return BusinessCompensationExecuteResponse(
        success=result.success,
        code=result.code,
        message=result.summary,
        data=result.result,
        compensation_id=payload.compensation_id,
        action_name=payload.action_name,
        latency_ms=latency_ms,
        retryable=result.retryable,
        provider=result.provider,
        error_detail=result.error_detail,
        idempotency_key=result.idempotency_key,
    )


def _build_execution_context(
    request: Request,
    payload: BusinessToolExecuteRequest,
    trace_id: str | None,
    request_id: str | None,
    message_id: str | None,
    tenant_id: str | None,
    idempotency_key: str | None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        trace_id=trace_id,
        request_id=request_id,
        conversation_id=request.headers.get(_settings.conversation_id_header),
        message_id=message_id,
        tenant_id=tenant_id or payload.subject.tenant_id,
        user_id=payload.subject.user_id,
        account_id=payload.subject.account_id,
        roles=payload.subject.roles,
        permissions=payload.subject.permissions,
        locale=payload.subject.locale,
        operator_type=payload.operator.type,
        operator_id=payload.operator.id,
        idempotency_key=idempotency_key,
    )


def _validate_internal_caller(request: Request) -> None:
    caller = request.headers.get(_settings.caller_service_header)
    if caller not in _settings.allowed_internal_callers:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "BUSINESS_TOOLS_CALLER_FORBIDDEN",
                "message": "Internal caller is not allowed to access business-tools routes.",
                "details": {"allowed_callers": _settings.allowed_internal_callers},
            },
        )
