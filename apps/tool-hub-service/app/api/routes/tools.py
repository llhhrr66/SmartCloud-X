from __future__ import annotations

import httpx
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.core.business_tools_sdk import ToolInvocationRequest, ToolMode, preflight_tool_invocation
from app.core.observability import (
    annotate_current_span,
    mark_cache_hit,
    mark_cache_miss,
    mark_idempotency_hit,
    mark_idempotency_store,
    mark_request_metric,
    mark_upstream_error,
    span_or_noop,
)
from app.core.config import get_settings
from app.models.common import ApiEnvelope, ErrorInfo
from app.models.tools import (
    CompensationCallRequest,
    CompensationCallResponse,
    McpToolsListResponse,
    ToolCallAuditRecord,
    ToolCallError,
    ToolCallRequest,
    ToolCallResponse,
    ToolDescriptor,
    ToolInvokeRequest,
    ToolInvokeResponse,
    ToolPreflightResponse,
)
from app.services.audit_store import ToolCallAuditStore
from app.services.business_tools_client import (
    BusinessToolsClient,
    BusinessToolsDiscoveryUnavailableError,
    BusinessToolsInvokeHttpError,
)
from app.services.dispatcher import ToolDispatcher, ToolInvocationError
from app.services.idempotency import IdempotencyConflictError, IdempotencyKeyValidationError, coordinator as idempotency_coordinator
from app.services.registry import ToolRegistry

router = APIRouter(tags=["tools"])
internal_router = APIRouter(tags=["internal-tools"])
mcp_router = APIRouter(tags=["mcp"])
_registry = ToolRegistry()
_dispatcher = ToolDispatcher()
_business_tools_client = BusinessToolsClient()
_settings = get_settings()
_audit_store = ToolCallAuditStore(
    file_path=_settings.audit_store_path,
    mysql_dsn=_settings.mysql_dsn,
)


def _list_tools(
    request: Request,
    *,
    capability: str | None = None,
    mode: ToolMode | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> ApiEnvelope[list[ToolDescriptor]]:
    try:
        data = _registry.list_tools(
            capability=capability,
            mode=mode,
            tag=tag,
            query=query,
        )
    except BusinessToolsDiscoveryUnavailableError as exc:
        _raise_discovery_unavailable(exc)
    return ApiEnvelope(success=True, data=data, requestId=_request_id(request))


def _describe_tool(tool_name: str, request: Request) -> ApiEnvelope[ToolDescriptor]:
    try:
        descriptor = _registry.describe_tool(tool_name)
    except BusinessToolsDiscoveryUnavailableError as exc:
        _raise_discovery_unavailable(exc)
    if descriptor is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {tool_name}").model_dump(),
        )
    return ApiEnvelope(success=True, data=descriptor, requestId=_request_id(request))


@router.get("/tools", response_model=ApiEnvelope[list[ToolDescriptor]])
def list_tools(
    request: Request,
    capability: str | None = Query(default=None),
    mode: ToolMode | None = Query(default=None),
    tag: str | None = Query(default=None),
    query: str | None = Query(default=None),
) -> ApiEnvelope[list[ToolDescriptor]]:
    return _list_tools(request, capability=capability, mode=mode, tag=tag, query=query)


@internal_router.get("/tools", response_model=ApiEnvelope[list[ToolDescriptor]])
def list_tools_internal(
    request: Request,
    capability: str | None = Query(default=None),
    mode: ToolMode | None = Query(default=None),
    tag: str | None = Query(default=None),
    query: str | None = Query(default=None),
) -> ApiEnvelope[list[ToolDescriptor]]:
    _validate_internal_caller(request)
    return _list_tools(request, capability=capability, mode=mode, tag=tag, query=query)


@router.get("/tools/{tool_name}", response_model=ApiEnvelope[ToolDescriptor])
def get_tool(tool_name: str, request: Request) -> ApiEnvelope[ToolDescriptor]:
    return _describe_tool(tool_name, request)


@internal_router.get("/tools/{tool_name}", response_model=ApiEnvelope[ToolDescriptor])
def get_tool_internal(tool_name: str, request: Request) -> ApiEnvelope[ToolDescriptor]:
    _validate_internal_caller(request)
    return _describe_tool(tool_name, request)


@router.post("/tools/{tool_name}/invoke", response_model=ApiEnvelope[ToolInvokeResponse])
def invoke_tool(
    tool_name: str,
    request: ToolInvokeRequest,
    http_request: Request,
) -> ApiEnvelope[ToolInvokeResponse]:
    try:
        descriptor = _registry.describe_tool(tool_name)
    except BusinessToolsDiscoveryUnavailableError as exc:
        _raise_discovery_unavailable(exc)
    if descriptor is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {tool_name}").model_dump(),
        )
    public_call_request = _public_invoke_call_request(tool_name, request)
    started = time.perf_counter()
    try:
        if _settings.business_tools_transport == "http":
            result = _dispatcher.invoke(
                descriptor,
                request,
                executor=_business_tools_client.invoke_tool,
            )
        else:
            tool = _registry.get_tool(tool_name)
            if tool is None:
                raise HTTPException(
                    status_code=404,
                    detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {tool_name}").model_dump(),
                )
            result = _dispatcher.invoke(tool, request)
    except ToolInvocationError as exc:
        _audit_store.record(
            public_call_request,
            _tool_call_response_from_public_error(
                public_call_request,
                exc.status_code,
                exc.code,
                exc.message,
                details=exc.details or {},
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail=ErrorInfo(code=exc.code, message=exc.message, details=exc.details).model_dump(),
        ) from exc
    except BusinessToolsInvokeHttpError as exc:
        _audit_store.record(
            public_call_request,
            _tool_call_response_from_public_error(
                public_call_request,
                502,
                "ORCH_TOOL_DOWNSTREAM_ERROR",
                f"Tool provider unavailable for '{tool_name}'.",
                details=dict(exc.details),
                latency_ms=int((time.perf_counter() - started) * 1000),
                retryable=exc.retryable,
                status=exc.status or "failed",
                provider=exc.provider,
                attempts=exc.attempts,
            ),
        )
        raise HTTPException(
            status_code=502,
            detail=ErrorInfo(
                code="ORCH_TOOL_DOWNSTREAM_ERROR",
                message=f"Tool provider unavailable for '{tool_name}'.",
                details=dict(exc.details),
            ).model_dump(),
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        _audit_store.record(
            public_call_request,
            _tool_call_response_from_public_error(
                public_call_request,
                502,
                "ORCH_TOOL_DOWNSTREAM_ERROR",
                f"Tool provider unavailable for '{tool_name}'.",
                details={"exception": exc.__class__.__name__},
                latency_ms=int((time.perf_counter() - started) * 1000),
                retryable=isinstance(exc, httpx.TimeoutException),
                status="timeout" if isinstance(exc, httpx.TimeoutException) else "failed",
                provider=descriptor.provider,
            ),
        )
        raise HTTPException(
            status_code=502,
            detail=ErrorInfo(
                code="ORCH_TOOL_DOWNSTREAM_ERROR",
                message=f"Tool provider unavailable for '{tool_name}'.",
                details={"exception": exc.__class__.__name__},
            ).model_dump(),
        ) from exc
    _audit_store.record(
        public_call_request,
        _tool_call_response_from_invoke_result(
            public_call_request,
            result,
            latency_ms=int((time.perf_counter() - started) * 1000),
        ),
    )
    return ApiEnvelope(
        success=True,
        data=result.model_copy(update={"tool_call_id": public_call_request.tool_call_id}),
        requestId=_request_id(http_request),
    )


@router.get("/tool-calls", response_model=ApiEnvelope[list[ToolCallAuditRecord]])
def list_tool_calls(
    request: Request,
    tool_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    message_id: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    idempotency_key: str | None = Query(default=None),
    audit_tag: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiEnvelope[list[ToolCallAuditRecord]]:
    return ApiEnvelope(
        success=True,
        data=_audit_store.list(
            tool_name=tool_name,
            status=status,
            trace_id=trace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            audit_tag=audit_tag,
            limit=limit,
        ),
        requestId=_request_id(request),
    )


@router.get("/tool-calls/{tool_call_id}", response_model=ApiEnvelope[ToolCallAuditRecord])
def get_tool_call(
    tool_call_id: str,
    request: Request,
) -> ApiEnvelope[ToolCallAuditRecord]:
    record = _audit_store.get(tool_call_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="ORCH_TOOL_CALL_NOT_FOUND",
                message=f"Unknown tool call: {tool_call_id}",
            ).model_dump(),
    )
    return ApiEnvelope(success=True, data=record, requestId=_request_id(request))


@router.post("/tools/call", response_model=ToolCallResponse)
def call_tool_public(request: ToolCallRequest, http_request: Request, response: Response) -> ToolCallResponse:
    return _invoke_call(request, http_request=http_request, response=response)


@internal_router.post("/tools/call", response_model=ToolCallResponse)
def call_tool(request: ToolCallRequest, http_request: Request, response: Response) -> ToolCallResponse:
    _validate_internal_caller(http_request)
    return _invoke_call(request, http_request=http_request, response=response)


@router.post("/tools/preflight", response_model=ToolPreflightResponse)
def preflight_tool_public(request: ToolCallRequest) -> ToolPreflightResponse:
    return _preflight_response(request)


@internal_router.post("/tools/preflight", response_model=ToolPreflightResponse)
def preflight_tool(request: ToolCallRequest, http_request: Request) -> ToolPreflightResponse:
    _validate_internal_caller(http_request)
    return _preflight_response(request)


def _preflight_response(request: ToolCallRequest) -> ToolPreflightResponse:
    try:
        descriptor = _registry.describe_tool(request.tool_name)
    except BusinessToolsDiscoveryUnavailableError as exc:
        _raise_discovery_unavailable(exc)
    if descriptor is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {request.tool_name}").model_dump(),
        )
    if _settings.business_tools_transport == "http":
        preflight = _business_tools_client.preflight_call(
            request.tool_name,
            request,
            definition=descriptor,
        )
    else:
        tool = _registry.get_tool(request.tool_name)
        if tool is None:
            raise HTTPException(
                status_code=404,
                detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {request.tool_name}").model_dump(),
            )
        invocation = _tool_invocation_request(request)
        preflight = _preflight(tool, invocation)
    return ToolPreflightResponse(
        **preflight.model_dump(),
        downstream_target=descriptor.downstream_target,
        provider=descriptor.provider,
        session_context_bindings=dict(descriptor.session_context_bindings),
    )


@internal_router.post("/tool-compensations/call", response_model=CompensationCallResponse)
def call_compensation(request: CompensationCallRequest, http_request: Request) -> CompensationCallResponse:
    _validate_internal_caller(http_request)
    return _business_tools_client.invoke_compensation(request)


@mcp_router.get("/list", response_model=McpToolsListResponse)
def mcp_list_tools() -> McpToolsListResponse:
    try:
        with span_or_noop("tool_hub.mcp.list", attributes={"operation": "list", "tool_name": "*"}):
            tools = _registry.list_tools()
    except BusinessToolsDiscoveryUnavailableError as exc:
        _raise_discovery_unavailable(exc)
    return McpToolsListResponse(tools=tools)


@mcp_router.get("/describe/{tool_name}", response_model=ToolDescriptor)
def mcp_describe_tool(tool_name: str) -> ToolDescriptor:
    try:
        with span_or_noop("tool_hub.mcp.describe", attributes={"operation": "describe", "tool_name": tool_name}):
            descriptor = _registry.describe_tool(tool_name)
    except BusinessToolsDiscoveryUnavailableError as exc:
        _raise_discovery_unavailable(exc)
    if descriptor is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {tool_name}").model_dump(),
        )
    return descriptor


@mcp_router.post("/call", response_model=ToolCallResponse)
def mcp_call_tool(request: ToolCallRequest, http_request: Request, stream: bool = Query(default=False)):
    if stream:
        def _event_stream():
            yield 'event: status\ndata: {"status":"accepted","tool_name":"%s"}\n\n' % request.tool_name
            response = _invoke_call(request, http_request=http_request)
            yield 'event: result\ndata: %s\n\n' % response.model_dump_json()
        return StreamingResponse(_event_stream(), media_type="text/event-stream")
    return _invoke_call(request, http_request=http_request)


def _invoke_call(request: ToolCallRequest, http_request: Request | None = None, response: Response | None = None) -> ToolCallResponse:
    started = time.perf_counter()
    try:
        reservation = idempotency_coordinator.reserve(request.idempotency_key)
    except IdempotencyKeyValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=ErrorInfo(code="ORCH_TOOL_IDEMPOTENCY_INVALID", message=str(exc)).model_dump(),
        ) from exc
    except IdempotencyConflictError as exc:
        mark_upstream_error("tool-hub-service", "idempotency-conflict")
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(code="ORCH_TOOL_IDEMPOTENCY_CONFLICT", message=str(exc)).model_dump(),
        ) from exc

    if reservation.state == "replay" and reservation.response is not None:
        mark_idempotency_hit()
        if response is not None and reservation.expires_at is not None:
            response.headers["X-Idempotency-Expires-At"] = reservation.expires_at.isoformat()
        annotate_current_span(idempotency_key=request.idempotency_key, status="replayed")
        return reservation.response

    try:
        with span_or_noop(
            "tool_hub.call",
            attributes={
                "tool_name": request.tool_name,
                "operation": request.operation,
                "idempotency_key": request.idempotency_key,
            },
        ):
            try:
                descriptor = _registry.describe_tool(request.tool_name)
            except BusinessToolsDiscoveryUnavailableError as exc:
                _raise_discovery_unavailable(exc)
            if descriptor is None:
                raise HTTPException(
                    status_code=404,
                    detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {request.tool_name}").model_dump(),
                )
            tool = _registry.get_tool(request.tool_name)
            if tool is None and _settings.business_tools_transport != "http":
                raise HTTPException(
                    status_code=404,
                    detail=ErrorInfo(code="ORCH_TOOL_NOT_FOUND", message=f"Unknown tool: {request.tool_name}").model_dump(),
                )
            call_response = _business_tools_client.invoke_call(tool, request, definition=descriptor)
            _audit_store.record(request, call_response)
            if "cache-hit" in call_response.audit_tags:
                mark_cache_hit()
            else:
                mark_cache_miss()
            if reservation.state == "reserved":
                expires_at = idempotency_coordinator.store(request.idempotency_key, call_response)
                if expires_at is not None:
                    mark_idempotency_store()
                    if response is not None:
                        response.headers["X-Idempotency-Expires-At"] = expires_at.isoformat()
            duration_seconds = time.perf_counter() - started
            mark_request_metric(
                tool_name=request.tool_name,
                operation=request.operation,
                status=call_response.status or "unknown",
                provider=call_response.provider,
                duration_seconds=duration_seconds,
            )
            annotate_current_span(
                tool_name=request.tool_name,
                operation=request.operation,
                status=call_response.status,
                provider=call_response.provider,
                idempotency_key=request.idempotency_key,
            )
            return call_response
    except Exception as exc:
        idempotency_coordinator.release(request.idempotency_key)
        if isinstance(exc, HTTPException):
            raise
        mark_upstream_error("tool-hub-service", exc.__class__.__name__)
        raise


def _public_invoke_call_request(
    tool_name: str,
    request: ToolInvokeRequest,
) -> ToolCallRequest:
    context = request.context
    tool_call_id = context.request_id or f"public-{tool_name}-{uuid4().hex[:12]}"
    operator_type = context.operator_type if context.operator_type in {"agent", "user", "admin", "system"} else "agent"
    return ToolCallRequest(
        trace_id=context.trace_id or tool_call_id,
        conversation_id=context.conversation_id or f"public-{tool_name}",
        message_id=context.message_id,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        operator={"type": operator_type, "id": context.operator_id or "public-direct-invoke"},
        user_context={
            "user_id": context.user_id,
            "account_id": context.account_id,
            "permissions": list(context.permissions),
            "roles": list(context.roles),
            "tenant_id": context.tenant_id,
            "locale": context.locale,
        },
        payload=dict(request.payload),
        idempotency_key=context.idempotency_key,
        operation=request.operation,
    )


def _tool_call_response_from_invoke_result(
    request: ToolCallRequest,
    result: ToolInvokeResponse,
    *,
    latency_ms: int,
) -> ToolCallResponse:
    error = None
    if not result.success:
        error = ToolCallError(
            retryable=bool(result.retryable),
            provider=result.provider,
            details=dict(result.error_detail),
        )
    return ToolCallResponse(
        success=result.success,
        code=result.code,
        message=result.message,
        status=result.status,
        summary=result.summary,
        result=dict(result.result),
        data=dict(result.result),
        citations=list(result.citations),
        audit_tags=list(dict.fromkeys([*result.audit_tags, "public-direct-invoke"])),
        session_context_patch=dict(result.session_context_patch),
        tool_call_id=request.tool_call_id,
        latency_ms=latency_ms,
        provider=result.provider,
        error=error,
        compensation=result.compensation,
        idempotency_key=result.idempotency_key or request.idempotency_key,
        attempts=result.attempts,
        user_action_hint=result.user_action_hint,
    )


def _tool_call_response_from_public_error(
    request: ToolCallRequest,
    status_code: int,
    error_code: str,
    message: str,
    *,
    details: dict | None,
    latency_ms: int,
    retryable: bool = False,
    status: str | None = None,
    provider: str = "tool-hub-service",
    attempts: int = 1,
) -> ToolCallResponse:
    effective_status = status
    if effective_status is None:
        effective_status = {
            403: "auth-required",
            404: "missing-tool",
            422: "invalid-payload",
        }.get(status_code, "failed")
    return ToolCallResponse(
        success=False,
        code=status_code,
        message=message,
        status=effective_status,
        summary=message,
        result={},
        data={},
        citations=[],
        audit_tags=["public-direct-invoke", "request-rejected"],
        session_context_patch={},
        tool_call_id=request.tool_call_id,
        latency_ms=latency_ms,
        provider=provider,
        error=ToolCallError(
            retryable=retryable,
            provider=provider,
            details={
                "error_code": error_code,
                **(details or {}),
            },
        ),
        idempotency_key=request.idempotency_key,
        attempts=attempts,
    )


def _tool_invocation_request(request: ToolCallRequest) -> ToolInvokeRequest:
    return ToolInvokeRequest(
        operation=request.operation,
        payload=request.payload,
        context={
            "request_id": request.tool_call_id,
            "trace_id": request.trace_id,
            "conversation_id": request.conversation_id,
            "tenant_id": request.user_context.tenant_id,
            "user_id": request.user_context.user_id,
            "account_id": request.user_context.account_id,
            "roles": request.user_context.roles,
            "permissions": request.user_context.permissions,
            "locale": request.user_context.locale,
            "operator_type": request.operator.type,
            "operator_id": request.operator.id,
            "idempotency_key": request.idempotency_key,
        },
    )


def _preflight(tool, request: ToolInvokeRequest):
    return preflight_tool_invocation(
        tool.definition,
        ToolInvocationRequest(
            tool_name=tool.definition.name,
            operation=request.operation,
            payload=request.payload,
            context=request.context,
        ),
    )


def _request_id(request: Request) -> str | None:
    return request.headers.get(_settings.request_id_header)


def _raise_discovery_unavailable(exc: BusinessToolsDiscoveryUnavailableError) -> None:
    raise HTTPException(
        status_code=503,
        detail=ErrorInfo(
            code="ORCH_TOOL_DISCOVERY_UNAVAILABLE",
            message=str(exc),
            details={"transport": "http", "downstream": "business-tools-service"},
        ).model_dump(),
    ) from exc


def _validate_internal_caller(request: Request) -> None:
    caller = request.headers.get(_settings.caller_service_header)
    if caller not in _settings.allowed_internal_callers:
        raise HTTPException(
            status_code=403,
            detail=ErrorInfo(
                code="TOOL_HUB_CALLER_FORBIDDEN",
                message="Internal caller is not allowed to access tool-hub internal routes.",
                details={"allowed_callers": _settings.allowed_internal_callers},
            ).model_dump(),
        )
