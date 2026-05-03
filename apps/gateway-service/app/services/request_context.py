from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RequestIdentity:
    request_id: str
    trace_id: str
    tenant_id: str | None = None
    subject_type: str = "anonymous"
    subject_id: str | None = None


def get_request_identity(request) -> RequestIdentity:
    return RequestIdentity(
        request_id=getattr(request.state, "request_id", "unknown"),
        trace_id=getattr(request.state, "trace_id", "unknown"),
        tenant_id=getattr(request.state, "tenant_id", None),
        subject_type=getattr(request.state, "subject_type", "anonymous"),
        subject_id=getattr(request.state, "subject_id", None),
    )
