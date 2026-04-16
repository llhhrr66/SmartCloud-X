from pathlib import Path

from app.models.common import TraceContext
from app.models.orchestration import (
    AgentRouteRecord,
    ExecutionCheckpoint,
    IntentSummary,
    MessageRequest,
    OrchestratorResponse,
    PendingUserAction,
    RouteDecision,
    SessionCreateRequest,
    SessionStateSnapshot,
    StreamEventRecord,
)
from app.services.conversation_store import ConversationStore
from app.services.sse_event_store import SseEventStore
from app.services.state_store import OrchestrationStateStore


def _route_decision() -> RouteDecision:
    return RouteDecision(
        primary_agent="finance_order_agent",
        intent=IntentSummary(
            domain="finance_order",
            matched_domains=["finance_order_agent"],
            urgency="low",
            needs_human_handoff=False,
            scene="billing",
        ),
        summary="finance_order_agent handled billing baseline.",
    )


def test_conversation_store_reloads_persisted_messages_and_retry_snapshots(tmp_path: Path) -> None:
    store_path = tmp_path / "conversations.json"
    store = ConversationStore(file_path=store_path)
    conversation = store.create(SessionCreateRequest(scene="billing", title="账单会话"))
    request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回账单汇总。",
        pending_actions=[],
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )

    store.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-1",
        assistant_message_id="asst_msg-1",
        message_request=request,
        response=response,
        status="completed",
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )

    reloaded = ConversationStore(file_path=store_path)
    messages = reloaded.list_messages(conversation.conversation_id).items
    retry_request = reloaded.build_retry_request(conversation.conversation_id, message_id="asst_msg-1")

    assert len(messages) == 2
    assert messages[0].content == "帮我查本月账单"
    assert messages[1].content == "已返回账单汇总。"
    assert retry_request.user_query == "帮我查本月账单"
    assert retry_request.message_id is None


def test_state_store_reloads_persisted_snapshots(tmp_path: Path) -> None:
    store_path = tmp_path / "state.json"
    store = OrchestrationStateStore(file_path=store_path)
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[
            AgentRouteRecord(
                step_id="step-1-finance-order-agent",
                order=1,
                agent="finance_order_agent",
                objective="主处理账单问题。",
                status="success",
                tool_names=["billing.query_statement"],
                tool_call_ids=["tc-1"],
                tool_statuses=["completed"],
            )
        ],
        checkpoints=[
            ExecutionCheckpoint(
                name="intent-classified",
                description="完成意图识别与主 agent 路由。",
                status="completed",
            )
        ],
        pending_user_actions=[
            PendingUserAction(
                tool_name="billing.query_statement",
                tool_call_id="tc-1",
                agent="finance_order_agent",
                action="clarify-tool-input",
                message="请提供账单范围。",
                missing_fields=["range"],
            )
        ],
        final_response_summary="已持久化。",
        trace=TraceContext(requestId="req-state-1", conversationId="conv-state-1", traceId="trace-state-1"),
    )

    store.save(snapshot)

    reloaded = OrchestrationStateStore(file_path=store_path)
    persisted = reloaded.get("conv-state-1")

    assert persisted is not None
    assert persisted.version == 1
    assert persisted.agent_routes[0].tool_call_ids == ["tc-1"]
    assert persisted.checkpoints[0].name == "intent-classified"
    assert persisted.pending_user_actions[0].action == "clarify-tool-input"
    assert persisted.trace.trace_id == "trace-state-1"


def test_sse_event_store_reloads_persisted_events(tmp_path: Path) -> None:
    store_path = tmp_path / "stream-events.json"
    store = SseEventStore(file_path=store_path)
    store.save(
        "conv-stream-1",
        "msg-stream-1",
        [
            StreamEventRecord(
                event_id="evt-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-1"},
                created_at="2026-04-16T00:00:00+00:00",
            ),
            StreamEventRecord(
                event_id="evt-0002",
                sequence=2,
                event="done",
                data={"finish_reason": "stop"},
                created_at="2026-04-16T00:00:01+00:00",
            ),
        ],
    )

    reloaded = SseEventStore(file_path=store_path)
    page = reloaded.get_page("conv-stream-1", "msg-stream-1", after_event_id="evt-0001", limit=10)

    assert page is not None
    assert page.conversation_id == "conv-stream-1"
    assert page.message_id == "msg-stream-1"
    assert [item.event for item in page.items] == ["done"]
