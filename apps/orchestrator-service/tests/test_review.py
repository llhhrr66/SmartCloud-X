from app.core.config import Settings
from app.models.orchestration import (
    AgentExecutionResult,
    AgentTask,
    IntentSummary,
    RouteDecision,
    ToolInvocation,
)
from app.services.review import ResponseReviewService


def _route_decision(*, requires_retrieval: bool = False) -> RouteDecision:
    return RouteDecision(
        primary_agent="ops_marketing_agent",
        requires_retrieval=requires_retrieval,
        intent=IntentSummary(
            domain="ops_marketing",
            matched_domains=["ops_marketing_agent"],
            urgency="low",
            needs_human_handoff=False,
            scene="marketing",
        ),
        tasks=[
            AgentTask(
                agent="ops_marketing_agent",
                reason="生成营销内容",
                suggested_tools=["marketing.campaign_lookup", "marketing.generate_copy"],
            )
        ],
        summary="ops_marketing_agent handled marketing baseline.",
    )


def test_review_service_blocks_agent_tool_policy_violation() -> None:
    service = ResponseReviewService(Settings.model_validate({"APP_ENV": "dev"}))
    review = service.review(
        _route_decision(),
        [
            AgentExecutionResult(
                agent="ops_marketing_agent",
                status="success",
                reasoning_summary="按计划生成营销文案。",
                tool_calls=[
                    ToolInvocation(
                        tool_name="billing.query_statement",
                        tool_call_id="tc-1",
                        operation="execute",
                        status="completed",
                        payload={"billing_cycle": "2026-04"},
                        success=True,
                    )
                ],
                final_answer="已完成处理。",
            )
        ],
        "已完成处理。",
    )

    assert review.status == "blocked"
    assert review.requires_escalation is True
    assert review.issues[0].code == "agent-tool-policy-violation"


def test_review_service_warns_on_long_reasoning_summary() -> None:
    service = ResponseReviewService(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "REVIEW_REASONING_SUMMARY_MAX_CHARS": 32,
            }
        )
    )
    review = service.review(
        _route_decision(),
        [
            AgentExecutionResult(
                agent="ops_marketing_agent",
                status="success",
                reasoning_summary="这是一段明显超过限制的 reasoning summary，用来验证复核器会给出 warning。",
                tool_calls=[
                    ToolInvocation(
                        tool_name="marketing.generate_copy",
                        tool_call_id="tc-2",
                        operation="execute",
                        status="completed",
                        payload={"headline": "GPU 新客满减 | GPU 实例 专属优惠"},
                        success=True,
                    )
                ],
                final_answer="已生成营销文案。",
            )
        ],
        "已生成营销文案。",
    )

    assert review.status == "warning"
    assert review.requires_escalation is False
    assert review.issues[0].code == "reasoning-summary-too-long"


def test_review_service_requires_citations_for_retrieval_routes() -> None:
    service = ResponseReviewService(Settings.model_validate({"APP_ENV": "dev"}))
    review = service.review(
        _route_decision(requires_retrieval=True),
        [
            AgentExecutionResult(
                agent="ops_marketing_agent",
                status="success",
                reasoning_summary="已完成营销分析。",
                tool_calls=[],
                final_answer="已完成营销分析。",
            )
        ],
        "已完成营销分析。",
    )

    assert review.status == "blocked"
    assert review.requires_escalation is True
    assert review.issues[0].code == "citations-required"
