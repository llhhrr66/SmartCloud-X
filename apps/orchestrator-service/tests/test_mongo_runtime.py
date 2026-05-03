from app.models.orchestration import (
    AgentExecutionResult,
    ChatMessageRecord,
    IntentSummary,
    OrchestratorResponse,
    RouteDecision,
    ToolInvocation,
)
from app.services.mongo_runtime import ConversationMongoRuntime


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
        summary="finance baseline",
    )


def _assistant_message(message_id: str) -> ChatMessageRecord:
    return ChatMessageRecord(
        message_id=message_id,
        conversation_id="conv-mongo-runtime",
        role="assistant",
        message_type="assistant_response",
        status="completed",
        created_at="2026-04-20T00:00:00+00:00",
        updated_at="2026-04-20T00:00:00+00:00",
        content="已返回账单摘要。",
    )


def _response(tool_call_id: str) -> OrchestratorResponse:
    return OrchestratorResponse(
        conversation_id="conv-mongo-runtime",
        route=_route_decision(),
        executions=[
            AgentExecutionResult(
                agent="finance_order_agent",
                status="success",
                reasoning_summary="queried billing tool",
                final_answer="done",
                tool_calls=[
                    ToolInvocation(
                        tool_name="billing.query_statement",
                        tool_call_id=tool_call_id,
                        operation="execute",
                        status="completed",
                        payload={"range": "this_month"},
                        summary="billing summary",
                        citations=["billing://statement"],
                        provider="business-tools-service",
                        success=True,
                        code=0,
                    )
                ],
            )
        ],
        next_action="respond-with-agent-summary",
        final_response_summary="done",
    )


def test_build_execution_documents_scopes_raw_tool_payload_ids_by_message() -> None:
    first_reasoning, first_tools = ConversationMongoRuntime._build_execution_documents(
        conversation_id="conv-mongo-runtime",
        assistant_message=_assistant_message("asst-msg-1"),
        response=_response("tc-finance_order_agent-1"),
    )
    second_reasoning, second_tools = ConversationMongoRuntime._build_execution_documents(
        conversation_id="conv-mongo-runtime",
        assistant_message=_assistant_message("asst-msg-2"),
        response=_response("tc-finance_order_agent-1"),
    )

    assert first_reasoning[0]["_id"] != second_reasoning[0]["_id"]
    assert first_tools[0]["tool_call_id"] == "tc-finance_order_agent-1"
    assert second_tools[0]["tool_call_id"] == "tc-finance_order_agent-1"
    assert first_tools[0]["_id"] == "conv-mongo-runtime:asst-msg-1:tc-finance_order_agent-1"
    assert second_tools[0]["_id"] == "conv-mongo-runtime:asst-msg-2:tc-finance_order_agent-1"
    assert first_tools[0]["_id"] != second_tools[0]["_id"]
