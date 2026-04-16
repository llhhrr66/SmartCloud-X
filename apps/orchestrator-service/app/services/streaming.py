from __future__ import annotations

import json
from datetime import datetime, timezone
from collections.abc import Iterator

from app.models.common import TraceContext
from app.models.orchestration import OrchestratorResponse, StreamEventRecord


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

    def _append(event: str, payload: dict) -> None:
        sequence = len(records) + 1
        records.append(
            StreamEventRecord(
                event_id=f"evt-{sequence:04d}",
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
    emitted_citations: list[str] = []
    retrieval_emitted = False

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
            sources = _build_retrieval_sources(execution.citations)
            _append(
                "retrieval",
                {
                    "query": user_query,
                    "top_k": len(sources),
                    "sources": sources,
                },
            )
            retrieval_emitted = True
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
        fresh_citations = [citation for citation in execution.citations if citation not in emitted_citations]
        if fresh_citations:
            emitted_citations.extend(fresh_citations)
            _append("citation", {"citations": _build_citation_entries(emitted_citations)})

    if not response.executions and response.final_response_summary:
        _append("delta", {"content": response.final_response_summary})

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


def _build_retrieval_sources(citations: list[str]) -> list[dict[str, object]]:
    normalized = citations or ["baseline://router-retrieval"]
    sources = []
    for index, citation in enumerate(dict.fromkeys(normalized), start=1):
        slug = citation.replace("baseline://", "").replace("/", "-")
        sources.append(
            {
                "doc_id": f"doc_{index:03d}",
                "chunk_id": f"chunk_{index:03d}",
                "score": round(max(0.6, 0.98 - (index * 0.05)), 2),
                "title": slug.replace("-", " "),
            }
        )
    return sources


def _build_citation_entries(citations: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for index, citation in enumerate(citations, start=1):
        slug = citation.replace("baseline://", "").replace("/", "-")
        entries.append(
            {
                "id": f"cite_{index:03d}",
                "title": slug.replace("-", " "),
                "source_type": "knowledge_base" if "retrieval" in slug or "playbook" in slug else "tool",
                "doc_id": f"doc_{index:03d}",
                "chunk_id": f"chunk_{index:03d}",
            }
        )
    return entries


def _finish_reason(next_action: str) -> str:
    return {
        "respond-with-agent-summary": "stop",
        "collect-user-input": "need_user_input",
        "continue-agent-handoff": "handoff",
        "handoff-to-human": "handoff",
        "retry-or-escalate": "error",
    }.get(next_action, next_action)
