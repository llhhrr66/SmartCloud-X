from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request, status

from app.core.config import Settings
from app.models.common import ErrorInfo, TraceContext
from app.models.orchestration import OrchestratorResponse
from app.services.conversation_store import ConversationStoreError


def request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id")


def coerce_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def coerce_positive_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def tool_candidates_from_option(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def merge_tool_candidates(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group:
            normalized = str(candidate).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def preferred_agents_from_hint(value: Any) -> list[str]:
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    preferred: list[str] = []
    alias_map = {
        "product_tech": "product_tech_agent",
        "finance_order": "finance_order_agent",
        "icp_service": "icp_service_agent",
        "ops_marketing": "ops_marketing_agent",
        "deep_research": "deep_research_agent",
    }
    for item in values:
        text = str(item).strip().lower()
        if not text:
            continue
        normalized = text.replace("-", "_")
        preferred.append(alias_map.get(normalized, normalized))
    return preferred


def build_trace_context(
    request: Request,
    conversation_id: str | None,
    trace: TraceContext | None = None,
    *,
    default_request_id: str | None = None,
) -> TraceContext:
    rid = request_id(request) or (trace.request_id if trace else None) or default_request_id or str(uuid4())
    return TraceContext(
        request_id=rid,
        trace_id=request.headers.get("x-trace-id") or (trace.trace_id if trace else None) or rid,
        conversation_id=conversation_id or (trace.conversation_id if trace else None),
    )


def raise_conversation_error(exc: ConversationStoreError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=ErrorInfo(code=exc.code, message=exc.message).model_dump(),
    )


def require_allowed_internal_caller(request: Request, settings: Settings | None) -> None:
    caller = request.headers.get((settings.caller_service_header if settings else "X-Caller-Service"), "")
    caller = caller.strip()
    allowed = set(settings.allowed_internal_callers if settings else ["gateway-service"])
    if caller not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ErrorInfo(code="FORBIDDEN", message="Caller service is not allowed.").model_dump(),
        )


def aggregate_citations(response: OrchestratorResponse) -> list[str]:
    citations: list[str] = []
    for execution in response.executions:
        for citation in execution.citations:
            if citation not in citations:
                citations.append(citation)
    return citations


def response_message_status(response: OrchestratorResponse) -> str:
    if response.next_action == "collect-user-input":
        return "need_user_input"
    if response.next_action == "retry-or-escalate":
        return "failed"
    if response.next_action in {"continue-agent-handoff", "handoff-to-human"}:
        return "handoff"
    return "completed"


def resolve_next_action(response: OrchestratorResponse) -> tuple[str, list[str]]:
    pending_actions = list(response.pending_actions)
    if any(action == "handoff-to-human" for action in pending_actions):
        return "handoff-to-human", pending_actions
    if response.state_snapshot is not None and response.state_snapshot.pending_agent_handoff is not None:
        return "continue-agent-handoff", pending_actions or ["continue-agent-handoff"]
    if response.executions:
        for execution in response.executions:
            if execution.status == "failed":
                return "retry-or-escalate", pending_actions or ["retry-or-escalate"]
        for execution in response.executions:
            if execution.status == "need_user_input":
                return "collect-user-input", pending_actions or [execution.action_required or "collect-user-input"]
        last_execution = response.executions[-1]
        if last_execution.action_required == "handoff-to-human-operator":
            return "handoff-to-human", ["handoff-to-human"]
        if last_execution.status == "handoff":
            return "continue-agent-handoff", pending_actions or ["continue-agent-handoff"]
    return response.next_action or "respond-with-agent-summary", pending_actions
