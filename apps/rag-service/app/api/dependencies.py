from uuid import uuid4

from fastapi import Request

from app.core.config import get_settings
from app.models.common import TraceContext
from app.core.tracing import inject_current_context


def build_trace_context(request: Request) -> TraceContext:
    existing = getattr(request.state, "trace_context", None)
    if existing is not None:
        return existing

    settings = get_settings()
    headers = request.headers
    request_id = headers.get(settings.request_id_header) or str(uuid4())
    trace = TraceContext(
        requestId=request_id,
        traceId=headers.get(settings.trace_id_header) or request_id,
        conversationId=headers.get(settings.conversation_id_header),
        tenantId=headers.get(settings.tenant_id_header),
        callerService=headers.get(settings.caller_service_header),
    )
    request.state.trace_context = trace
    return trace


def build_upstream_headers(
    trace: TraceContext,
    conversation_id: str | None = None,
) -> dict[str, str]:
    settings = get_settings()
    headers = {
        settings.request_id_header: trace.request_id or str(uuid4()),
        settings.caller_service_header: settings.app_name,
    }
    if trace.trace_id:
        headers[settings.trace_id_header] = trace.trace_id
    if conversation_id or trace.conversation_id:
        headers[settings.conversation_id_header] = conversation_id or trace.conversation_id or ""
    if trace.tenant_id:
        headers[settings.tenant_id_header] = trace.tenant_id
    return inject_current_context(headers)
