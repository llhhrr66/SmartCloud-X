from __future__ import annotations

from app.core.config import Settings, get_settings
from app.models.orchestration import (
    AgentExecutionResult,
    ResponseReview,
    ResponseReviewIssue,
    RouteDecision,
)


class ResponseReviewService:
    """Lightweight response guardrails for the FastAPI baseline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def review(
        self,
        route: RouteDecision,
        executions: list[AgentExecutionResult],
        final_summary: str,
    ) -> ResponseReview:
        if not self._settings.response_review_enabled:
            return ResponseReview(status="warning", summary="已跳过响应复核。", requires_escalation=False)

        issues: list[ResponseReviewIssue] = []
        suggested_tools_by_agent = {
            task.agent: set(task.suggested_tools)
            for task in route.tasks
        }

        for execution in executions:
            if len(execution.reasoning_summary) > self._settings.review_reasoning_summary_max_chars:
                issues.append(
                    ResponseReviewIssue(
                        code="reasoning-summary-too-long",
                        severity="warning",
                        message=(
                            f"{execution.agent} 的 reasoning_summary 超过 "
                            f"{self._settings.review_reasoning_summary_max_chars} 字符。"
                        ),
                    )
                )

            if execution.status == "handoff" and execution.next_agent and not execution.handoff_reason:
                issues.append(
                    ResponseReviewIssue(
                        code="handoff-reason-missing",
                        severity="error",
                        message=f"{execution.agent} 发生 handoff，但缺少 handoff_reason。",
                    )
                )

            allowed_tools = suggested_tools_by_agent.get(execution.agent, set())
            if not allowed_tools:
                from .agent_registry import allowed_tools_for
                allowed_tools = set(allowed_tools_for(execution.agent))
            unauthorized_tools = [
                tool_call.tool_name
                for tool_call in execution.tool_calls
                if tool_call.tool_name not in allowed_tools
            ]
            if unauthorized_tools:
                issues.append(
                    ResponseReviewIssue(
                        code="agent-tool-policy-violation",
                        severity="error",
                        message=(
                            f"{execution.agent} 调用了未在计划白名单中的工具："
                            f"{', '.join(unauthorized_tools)}。"
                        ),
                    )
                )

        citations = [
            citation
            for execution in executions
            for citation in execution.citations
        ]
        if (
            self._settings.review_require_citations_when_retrieval
            and route.requires_retrieval
            and not citations
        ):
            issues.append(
                ResponseReviewIssue(
                    code="citations-required",
                    severity="error",
                    message="当前路由要求检索/引用，但最终响应未输出任何 citations。",
                )
            )

        if len(final_summary) > self._settings.review_final_answer_max_chars:
            issues.append(
                ResponseReviewIssue(
                    code="final-summary-too-long",
                    severity="warning",
                    message=(
                        f"final_response_summary 超过 "
                        f"{self._settings.review_final_answer_max_chars} 字符。"
                    ),
                )
            )

        has_error = any(issue.severity == "error" for issue in issues)
        has_warning = any(issue.severity == "warning" for issue in issues)
        if has_error:
            return ResponseReview(
                status="blocked",
                summary="响应复核未通过，需重试或升级处理。",
                issues=[item.model_copy(deep=True) for item in issues],
                requires_escalation=True,
            )
        if has_warning:
            return ResponseReview(
                status="warning",
                summary="响应复核通过，但存在告警项。",
                issues=[item.model_copy(deep=True) for item in issues],
                requires_escalation=False,
            )
        return ResponseReview(
            status="approved",
            summary="响应复核通过。",
            issues=[],
            requires_escalation=False,
        )
