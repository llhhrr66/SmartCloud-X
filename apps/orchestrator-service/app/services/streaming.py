from __future__ import annotations

import json
from datetime import datetime, timezone
from collections.abc import Iterator
from typing import Any

from app.models.common import TraceContext
from app.models.orchestration import (
    OrchestratorResponse,
    RetrievalResult,
    RetrievalSource,
    StreamEventRecord,
)


def build_sse_event_records(
    *,
    conversation_id: str,
    message_id: str,
    user_query: str,
    response: OrchestratorResponse,
    trace: TraceContext | None = None,
) -> list[StreamEventRecord]:
    created_at = datetime.now(timezone.utc).isoformat()
    records: list[StreamEventRecord] = []

    def _append(event: str, payload: dict[str, Any]) -> None:
        sequence = len(records) + 1
        records.append(
            StreamEventRecord(
                event_id=f"evt-{sequence:04d}",
                message_id=message_id,
                sequence=sequence,
                event=event,  # type: ignore[arg-type]
                data=payload,
                created_at=created_at,
            )
        )

    _append(
        "meta",
        {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "trace_id": trace.trace_id if trace else None,
            "agent": "Orchestrator",
        },
    )

    tool_arguments = {item.tool_call_id: item.payload for item in response.route.tool_plan}
    emitted_citation_ids: list[str] = []
    retrieval_emitted = False
    terminal_error_emitted = False

    for step, execution in enumerate(response.executions, start=1):
        _append(
            "reasoning",
            {
                "agent": execution.agent,
                "summary": execution.reasoning_summary,
                "step": step,
            },
        )
        if response.route.requires_retrieval and not retrieval_emitted:
            retrieval_payload, retrieval_terminal_error = _resolve_retrieval_stream_payload(
                execution=execution,
                fallback_query=user_query,
            )
            if retrieval_payload is not None:
                _append("retrieval", retrieval_payload)
                retrieval_emitted = True
            if retrieval_terminal_error is not None:
                _append("message.error", retrieval_terminal_error)
                terminal_error_emitted = True
                break
        for tool_call in execution.tool_calls:
            _append(
                "tool_call",
                {
                    "tool_name": tool_call.tool_name,
                    "tool_call_id": tool_call.tool_call_id,
                    "status": "started",
                    "arguments": tool_arguments.get(tool_call.tool_call_id, {}),
                },
            )
            _append(
                "tool_result",
                {
                    "tool_name": tool_call.tool_name,
                    "tool_call_id": tool_call.tool_call_id,
                    "status": "success" if tool_call.success else tool_call.status,
                    "latency_ms": tool_call.latency_ms or 0,
                    "data_preview": tool_call.payload,
                    "provider": tool_call.provider,
                    "audit_tags": tool_call.audit_tags,
                },
            )
        if execution.final_answer:
            _append("delta", {"content": execution.final_answer})
        fresh_citations = _build_fresh_citation_entries(execution, emitted_citation_ids)
        if fresh_citations:
            emitted_citation_ids.extend(entry["id"] for entry in fresh_citations)
            _append("citation", {"citations": fresh_citations})

    if not terminal_error_emitted and not response.executions and response.final_response_summary:
        _append("delta", {"content": response.final_response_summary})

    if not terminal_error_emitted:
        _append(
            "done",
            {
                "finish_reason": _finish_reason(response.next_action),
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "next_action": response.next_action,
                "pending_actions": response.pending_actions,
            },
        )
    return records


def iter_sse_events(events: list[StreamEventRecord]) -> Iterator[str]:
    for event in events:
        yield _format_sse_event(event)



def _format_sse_event(event: StreamEventRecord) -> str:
    return (
        f"id: {event.event_id}\n"
        f"event: {event.event}\n"
        f"data: {json.dumps(event.data, ensure_ascii=False)}\n\n"
    )



def _resolve_retrieval_stream_payload(
    *,
    execution,
    fallback_query: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    retrieval_result = execution.retrieval_result
    if retrieval_result is not None:
        return (
            _build_retrieval_event_payload(
                retrieval_result=retrieval_result,
                fallback_query=fallback_query,
            ),
            None,
        )
    if _is_missing_user_context_retrieval_failure(execution):
        return (
            {
                "query": fallback_query,
                "top_k": 0,
                "degraded": True,
                "backend_used": "missing-user-context",
                "sources": [],
            },
            None,
        )
    if execution.status == "failed" and "retrieval_failed" in execution.risk_flags:
        return (
            None,
            _build_message_error_payload(
                code="RAG_RETRIEVAL_UNAVAILABLE",
                message=execution.final_answer or execution.reasoning_summary,
                retryable=True,
                details={
                    "agent": execution.agent,
                    "query": fallback_query,
                    "risk_flags": execution.risk_flags,
                    "trace_tags": execution.trace_tags,
                },
            ),
        )
    return None, None



def _is_missing_user_context_retrieval_failure(execution) -> bool:
    return (
        execution.status == "failed"
        and "missing_user_context" in execution.risk_flags
        and "retrieval_failed" not in execution.risk_flags
    )



def _build_retrieval_event_payload(
    *,
    retrieval_result: RetrievalResult,
    fallback_query: str,
) -> dict[str, Any]:
    sources = [_serialize_retrieval_source(source) for source in retrieval_result.sources]
    return {
        "query": retrieval_result.query or fallback_query,
        "top_k": len(sources),
        "degraded": retrieval_result.degraded,
        "backend_used": retrieval_result.backend_used,
        "sources": sources,
    }



def _serialize_retrieval_source(source: RetrievalSource) -> dict[str, Any]:
    return {
        "sourceId": source.source_id,
        "sourceType": source.source_type,
        "title": source.title,
        "docId": source.doc_id,
        "chunkId": source.chunk_id,
        "score": source.score,
        "uri": source.uri,
        "snippet": source.snippet,
        "backendUsed": source.backend_used,
        "domain": source.domain,
    }



def _build_fresh_citation_entries(
    execution,
    emitted_citation_ids: list[str],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    retrieval_result = execution.retrieval_result
    if retrieval_result is not None:
        for index, source in enumerate(retrieval_result.sources, start=1):
            entry = _build_citation_entry_from_source(source, index=index)
            if entry["id"] in emitted_citation_ids:
                continue
            entries.append(entry)
        return entries
    return []



def _build_citation_entry_from_source(
    source: RetrievalSource,
    *,
    index: int,
) -> dict[str, Any]:
    return {
        "id": _citation_entry_id(source, index=index),
        "title": source.title,
        "source_type": source.source_type,
        "doc_id": source.doc_id,
        "chunk_id": source.chunk_id,
        "source_id": source.source_id,
        "uri": source.uri,
        "backend_used": source.backend_used,
        "domain": source.domain,
    }



def _citation_entry_id(source: RetrievalSource, *, index: int) -> str:
    if source.source_id:
        return source.source_id
    if source.doc_id and source.chunk_id:
        return f"{source.doc_id}:{source.chunk_id}"
    if source.chunk_id:
        return source.chunk_id
    return f"cite_{index:03d}"



def _build_message_error_payload(
    *,
    code: str,
    message: str,
    retryable: bool,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if details:
        payload["details"] = details
    return payload



def _finish_reason(next_action: str | None) -> str:
    if next_action == "respond-with-agent-summary":
        return "stop"
    if next_action == "collect-user-input":
        return "requires_input"
    if next_action == "continue-agent-handoff":
        return "handoff"
    if next_action == "retry-or-escalate":
        return "error"
    return next_action or "stop"
