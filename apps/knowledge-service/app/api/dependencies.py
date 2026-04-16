from uuid import uuid4

from fastapi import Request

from app.core.config import get_settings
from app.models.common import TraceContext


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
