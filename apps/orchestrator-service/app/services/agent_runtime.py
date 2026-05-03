from __future__ import annotations

from collections.abc import Callable
import logging
import time

from app.core.business_tools_sdk import build_catalog
from app.core.config import Settings, get_settings
from app.models.common import TraceContext
from app.models.orchestration import (
    AgentName,
    AgentTask,
    AgentExecutionResult,
    MessageRequest,
    RetrievalResult,
    RouteDecision,
    ToolInvocation,
)
from app.services.agent_config_store import AgentConfigStore
from app.services.agent_answer_generator import AgentAnswerGenerator, OpenAICompatibleAgentAnswerGenerator
from app.services.llm_tool_call_loop import LLMToolCallLoop
from app.services.rag_client import RagClient
from app.services.tool_hub_client import ToolHubClient

from ._agent_answer_renderer import render_baseline_final_answer
from ._agent_retrieval_mixin import _AgentRetrievalMixin
from ._agent_tool_execution_mixin import _AgentToolExecutionMixin


logger = logging.getLogger(__name__)


class AgentRuntime(_AgentToolExecutionMixin, _AgentRetrievalMixin):
    """Coordinates per-task agent execution: tool invocation, retrieval, answer.

    The class composes three specialised mixins:
    - ``_AgentToolExecutionMixin`` — tool-plan invocation, payload hydration,
      handoff payload construction, and blocked-invocation shaping.
    - ``_AgentRetrievalMixin`` — RAG/Knowledge retrieval and result mapping.
    - The local methods drive the per-task loop, baseline status/risk-flag
      derivation, and final-answer rendering (delegated to
      ``_agent_answer_renderer``).
    """

    def __init__(
        self,
        tool_hub_client: ToolHubClient | None = None,
        agent_config_store: AgentConfigStore | None = None,
        agent_answer_generator: AgentAnswerGenerator | None = None,
        rag_client: RagClient | None = None,
        settings: Settings | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.tool_hub_client = tool_hub_client or ToolHubClient()
        self._agent_config_store = agent_config_store or AgentConfigStore()
        self._settings = settings or get_settings()
        self._catalog = build_catalog()
        self._clock = clock or time.perf_counter
        self._agent_answer_generator = agent_answer_generator or OpenAICompatibleAgentAnswerGenerator(
            settings=self._settings
        )
        self._rag_client = rag_client or RagClient()
        self._llm_tool_call_loop: LLMToolCallLoop | None = None

    def invalidate_llm_client_cache(self) -> None:
        self._agent_answer_generator.invalidate_cache()

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    def execute(
        self,
        route: RouteDecision,
        request: MessageRequest,
        trace: TraceContext | None = None,
        cancel_check: Callable[[], None] | None = None,
        *,
        start_task_index: int = 0,
        pause_on_agent_handoff: bool = False,
        incoming_handoff_from: AgentName | None = None,
    ) -> list[AgentExecutionResult]:
        executions: list[AgentExecutionResult] = []
        if start_task_index >= len(route.tasks):
            return executions
        working_context = request.session_context.model_copy(deep=True)
        for absolute_index in range(start_task_index, len(route.tasks)):
            task = route.tasks[absolute_index]
            if cancel_check is not None:
                cancel_check()
            timeout_seconds = self._agent_timeout_seconds(task.agent)
            started_at = self._clock()

            if self._should_use_llm_tool_calling():
                llm_loop = self._get_llm_tool_call_loop()
                tool_calls, llm_answer = llm_loop.run(
                    agent=task.agent,
                    user_query=request.user_query,
                    request=request,
                    working_context=working_context,
                    trace=trace,
                )
                timed_out = False
            else:
                tool_plan = [item for item in route.tool_plan if item.assigned_agent == task.agent]
                tool_calls, timed_out = self._execute_tool_plan(
                    tool_plan,
                    request,
                    trace,
                    task.agent,
                    working_context,
                    deadline=started_at + timeout_seconds,
                    cancel_check=cancel_check,
                )
            if timed_out:
                executions.append(
                    self._timed_out_execution(
                        task=task,
                        tool_calls=tool_calls,
                        timeout_seconds=timeout_seconds,
                        started_at=started_at,
                        route=route,
                        index=absolute_index,
                    )
                )
                break
            next_task = route.tasks[absolute_index + 1] if absolute_index + 1 < len(route.tasks) else None
            next_agent = next_task.agent if next_task else None
            if not tool_calls and route.requires_tools and request.constraints.disable_tools:
                executions.append(
                    AgentExecutionResult(
                        agent=task.agent,
                        status="failed",
                        reasoning_summary=f"{task.agent} 工具调用被禁用，无法完成当前请求。",
                        tool_calls=[],
                        citations=[],
                        confidence=0.0,
                        final_answer=f"{task.agent} 当前处理失败，请稍后重试。",
                        handoff_received_from=(route.tasks[absolute_index - 1].agent if absolute_index > 0 else None),
                        next_agent=None,
                        action_required="retry-or-escalate",
                        risk_flags=["tool_failure"],
                        trace_tags=[task.agent, "tools_disabled"],
                        handoff_reason=None,
                        handoff_payload={},
                    )
                )
                break
            status = self._determine_status(tool_calls, next_agent, route.needs_human_handoff, absolute_index)
            effective_next_agent = next_agent if status == "handoff" else None
            tool_citations = self._collect_tool_citations(tool_calls)
            retrieval_result: RetrievalResult | None = None
            retrieval_citations: list[str] = []
            retrieval_risk_flags: list[str] = []
            retrieval_trace_tags: list[str] = []
            retrieval_failure_execution: AgentExecutionResult | None = None
            if task.requires_retrieval:
                retrieval_outcome = self._run_retrieval(task, request, trace)
                retrieval_result = retrieval_outcome["result"]
                retrieval_citations = retrieval_outcome["citations"]
                retrieval_risk_flags = retrieval_outcome["risk_flags"]
                retrieval_trace_tags = retrieval_outcome["trace_tags"]
                retrieval_failure_execution = retrieval_outcome["failure_execution"]
                if retrieval_failure_execution is not None:
                    executions.append(retrieval_failure_execution)
                    break
            citations = list(dict.fromkeys([*tool_citations, *retrieval_citations]))
            handoff_received_from = None
            if absolute_index == start_task_index and start_task_index > 0:
                handoff_received_from = incoming_handoff_from or route.tasks[absolute_index - 1].agent
            elif absolute_index > 0:
                handoff_received_from = route.tasks[absolute_index - 1].agent
            fallback_answer = render_baseline_final_answer(
                task.agent, request.user_query, tool_calls, status, effective_next_agent
            )
            final_answer = self._render_final_answer(
                agent=task.agent,
                user_query=request.user_query,
                tool_calls=tool_calls,
                status=status,
                next_agent=effective_next_agent,
                fallback_answer=fallback_answer,
            )
            execution = AgentExecutionResult(
                agent=task.agent,
                status=status,
                reasoning_summary=self._build_reasoning_summary(
                    task.agent, task.requires_retrieval, tool_calls, effective_next_agent, retrieval_result
                ),
                tool_calls=tool_calls,
                citations=citations,
                retrieval_result=retrieval_result,
                confidence=self._confidence_for(tool_calls, status),
                final_answer=final_answer,
                handoff_received_from=handoff_received_from,
                next_agent=effective_next_agent,
                action_required=self._action_required(
                    tool_calls, route.needs_human_handoff, absolute_index, effective_next_agent
                ),
                risk_flags=list(
                    dict.fromkeys(
                        [
                            *self._risk_flags(tool_calls, route.needs_human_handoff, absolute_index),
                            *retrieval_risk_flags,
                        ]
                    )
                ),
                trace_tags=list(
                    dict.fromkeys(
                        [
                            *self._trace_tags(task.agent, tool_calls),
                            *retrieval_trace_tags,
                        ]
                    )
                ),
                handoff_reason=(f"需要切换到 {effective_next_agent} 继续处理。" if effective_next_agent else None),
                handoff_payload=(
                    self._build_handoff_payload(tool_calls, working_context, next_task)
                    if effective_next_agent and next_task is not None
                    else {}
                ),
            )
            executions.append(execution)
            if execution.status in {"failed", "need_user_input"}:
                break
            if pause_on_agent_handoff and execution.status == "handoff" and effective_next_agent is not None:
                break
            if execution.action_required == "handoff-to-human-operator":
                break
        return executions

    # ------------------------------------------------------------------
    # Timeout / status helpers
    # ------------------------------------------------------------------

    def _agent_timeout_seconds(self, agent: AgentName) -> int:
        override = self._agent_config_store.get(agent)
        if override and override.timeout_seconds is not None:
            return override.timeout_seconds
        return self._settings.default_agent_timeout_seconds

    def _timed_out_execution(
        self,
        *,
        task: AgentTask,
        tool_calls: list[ToolInvocation],
        timeout_seconds: int,
        started_at: float,
        route: RouteDecision,
        index: int,
    ) -> AgentExecutionResult:
        elapsed_ms = int((self._clock() - started_at) * 1000)
        citations = self._collect_tool_citations(tool_calls)
        return AgentExecutionResult(
            agent=task.agent,
            status="failed",
            reasoning_summary=(
                f"{task.agent} 超过配置超时 {timeout_seconds}s；retrieval={task.requires_retrieval}，"
                f"tool_calls={len(tool_calls)}，elapsed_ms={elapsed_ms}。"
            ),
            tool_calls=tool_calls,
            citations=citations,
            confidence=0.2,
            final_answer=f"{task.agent} 在 {timeout_seconds} 秒内未完成当前阶段，已停止后续编排。",
            handoff_received_from=route.tasks[index - 1].agent if index > 0 else None,
            next_agent=None,
            action_required="retry-or-escalate",
            risk_flags=self._risk_flags(tool_calls, route.needs_human_handoff, index, timed_out=True),
            trace_tags=self._trace_tags(task.agent, tool_calls, timed_out=True),
            handoff_reason=None,
            handoff_payload={},
        )

    @staticmethod
    def _determine_status(
        tool_calls: list[ToolInvocation],
        next_agent: str | None,
        needs_human_handoff: bool,
        absolute_index: int,
    ) -> str:
        if any(_AgentToolExecutionMixin._requires_user_follow_up(tool_call) for tool_call in tool_calls):
            return "need_user_input"
        if any(
            (tool_call.success is False)
            and tool_call.status not in {"auth-required", "confirmation-required", "clarification-required"}
            for tool_call in tool_calls
        ):
            return "failed"
        if next_agent or (needs_human_handoff and absolute_index == 0):
            return "handoff"
        return "success"

    @staticmethod
    def _build_reasoning_summary(
        agent: str,
        requires_retrieval: bool,
        tool_calls: list[ToolInvocation],
        next_agent: str | None,
        retrieval_result: RetrievalResult | None = None,
    ) -> str:
        successful_tools = [tool_call.tool_name for tool_call in tool_calls if tool_call.success]
        summary = f"{agent} 根据当前路由完成处理"
        if requires_retrieval:
            if retrieval_result is None:
                summary += "，未获得可用检索结果"
            elif retrieval_result.degraded:
                summary += f"，检索已降级（backend={retrieval_result.backend_used}）"
            else:
                summary += f"，已完成真实检索（sources={len(retrieval_result.sources)}）"
        if successful_tools:
            summary += f"，调用工具：{', '.join(successful_tools)}"
        if next_agent:
            summary += f"，下一阶段交由 {next_agent}"
        return f"{summary}。"

    @staticmethod
    def _collect_tool_citations(tool_calls: list[ToolInvocation]) -> list[str]:
        citations: list[str] = []
        for tool_call in tool_calls:
            for citation in tool_call.citations:
                if isinstance(citation, str) and citation.strip() and citation not in citations:
                    citations.append(citation)
        return citations

    def _render_final_answer(
        self,
        *,
        agent: AgentName,
        user_query: str,
        tool_calls: list[ToolInvocation],
        status: str,
        next_agent: str | None,
        fallback_answer: str | None,
    ) -> str | None:
        try:
            generated = self._agent_answer_generator.generate(
                agent=agent,
                user_query=user_query,
                status=status,
                next_agent=next_agent,
                fallback_answer=fallback_answer,
                tool_calls=tool_calls,
            )
        except Exception:
            return fallback_answer
        return generated or fallback_answer

    @staticmethod
    def _final_answer(
        agent: AgentName,
        user_query: str,
        tool_calls: list[ToolInvocation],
        status: str,
        next_agent: str | None,
    ) -> str | None:
        return render_baseline_final_answer(agent, user_query, tool_calls, status, next_agent)

    # ------------------------------------------------------------------
    # Risk / trace metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _action_required(
        tool_calls: list[ToolInvocation],
        needs_human_handoff: bool,
        absolute_index: int,
        next_agent: str | None,
    ) -> str | None:
        if any(
            tool_call.status == "clarification-required"
            or (
                tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "clarify-tool-input"
            )
            for tool_call in tool_calls
        ):
            return "clarify-tool-input"
        if any(
            tool_call.status == "confirmation-required"
            or (
                tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "user-confirmation"
            )
            for tool_call in tool_calls
        ):
            return "user-confirmation"
        if any(
            tool_call.status == "auth-required"
            or (
                tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "collect-auth-context"
            )
            for tool_call in tool_calls
        ):
            return "collect-auth-context"
        if needs_human_handoff and next_agent is None:
            return "handoff-to-human-operator"
        return None

    @staticmethod
    def _risk_flags(
        tool_calls: list[ToolInvocation],
        needs_human_handoff: bool,
        absolute_index: int,
        *,
        timed_out: bool = False,
    ) -> list[str]:
        flags: list[str] = []
        if any(
            tool_call.status == "clarification-required"
            or (
                tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "clarify-tool-input"
            )
            for tool_call in tool_calls
        ):
            flags.append("missing_tool_input")
        if any(
            tool_call.status == "auth-required"
            or (
                tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "collect-auth-context"
            )
            for tool_call in tool_calls
        ):
            flags.append("missing_auth_context")
        if any(
            tool_call.status == "confirmation-required"
            or (
                tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "user-confirmation"
            )
            for tool_call in tool_calls
        ):
            flags.append("confirmation_required")
        if any(tool_call.status == "idempotency-conflict" for tool_call in tool_calls):
            flags.append("idempotency_conflict")
        if any(
            (tool_call.success is False)
            and tool_call.status not in {"clarification-required", "auth-required", "confirmation-required"}
            for tool_call in tool_calls
        ):
            flags.append("tool_failure")
        if timed_out:
            flags.append("agent_timeout")
        if needs_human_handoff and absolute_index == 0:
            flags.append("human_handoff_requested")
        return flags

    @staticmethod
    def _trace_tags(agent: str, tool_calls: list[ToolInvocation], *, timed_out: bool = False) -> list[str]:
        tags = [agent]
        tags.extend(tool_call.tool_name for tool_call in tool_calls)
        if any(tool_call.success for tool_call in tool_calls):
            tags.append("tool_used")
        if timed_out:
            tags.append("agent_timeout")
        return tags

    def _should_use_llm_tool_calling(self) -> bool:
        return self._settings.tool_call_enabled and self._settings.llm_ready()

    def _get_llm_tool_call_loop(self) -> LLMToolCallLoop:
        if self._llm_tool_call_loop is None:
            self._llm_tool_call_loop = LLMToolCallLoop(
                answer_generator=self._agent_answer_generator,
                tool_hub_client=self.tool_hub_client,
                catalog=self._catalog,
                settings=self._settings,
            )
        return self._llm_tool_call_loop

    @staticmethod
    def _confidence_for(tool_calls: list[ToolInvocation], status: str) -> float:
        if status == "failed":
            return 0.2
        if status == "need_user_input":
            return 0.45
        if any(tool_call.success for tool_call in tool_calls):
            return 0.82
        return 0.6
