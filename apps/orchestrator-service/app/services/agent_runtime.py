from __future__ import annotations

from collections.abc import Callable
import time

from app.core.business_tools_sdk import build_catalog
from app.core.config import Settings, get_settings
from app.models.common import TraceContext
from app.models.orchestration import (
    AgentName,
    AgentTask,
    AgentExecutionResult,
    MessageRequest,
    RouteDecision,
    SessionContext,
    ToolInvocation,
    ToolPlanItem,
)
from app.services.agent_config_store import AgentConfigStore
from app.services.conversation_store import ConversationStore
from app.services.tool_context import hydrate_payload_from_session_context, read_session_context_key
from app.services.tool_hub_client import ToolHubClient


class AgentRuntime:
    def __init__(
        self,
        tool_hub_client: ToolHubClient | None = None,
        agent_config_store: AgentConfigStore | None = None,
        settings: Settings | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.tool_hub_client = tool_hub_client or ToolHubClient()
        self._agent_config_store = agent_config_store or AgentConfigStore()
        self._settings = settings or get_settings()
        self._catalog = build_catalog()
        self._clock = clock or time.perf_counter

    def execute(
        self,
        route: RouteDecision,
        request: MessageRequest,
        trace: TraceContext | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> list[AgentExecutionResult]:
        executions: list[AgentExecutionResult] = []
        working_context = request.session_context.model_copy(deep=True)
        for index, task in enumerate(route.tasks):
            if cancel_check is not None:
                cancel_check()
            tool_plan = [item for item in route.tool_plan if item.assigned_agent == task.agent]
            timeout_seconds = self._agent_timeout_seconds(task.agent)
            started_at = self._clock()
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
                execution = self._timed_out_execution(
                    task=task,
                    tool_calls=tool_calls,
                    timeout_seconds=timeout_seconds,
                    started_at=started_at,
                    route=route,
                    index=index,
                )
                executions.append(execution)
                break
            next_task = route.tasks[index + 1] if index + 1 < len(route.tasks) else None
            next_agent = next_task.agent if next_task else None
            status = self._determine_status(tool_calls, next_agent, route.needs_human_handoff, index)
            effective_next_agent = next_agent if status == "handoff" else None
            citations = sorted({citation for tool_call in tool_calls for citation in tool_call.citations})
            if task.requires_retrieval:
                citations.append("baseline://router-retrieval")
            execution = AgentExecutionResult(
                agent=task.agent,
                status=status,
                reasoning_summary=self._build_reasoning_summary(task.agent, task.requires_retrieval, tool_calls, effective_next_agent),
                tool_calls=tool_calls,
                citations=citations,
                confidence=self._confidence_for(tool_calls, status),
                final_answer=self._final_answer(task.agent, tool_calls, status, effective_next_agent),
                handoff_received_from=route.tasks[index - 1].agent if index > 0 else None,
                next_agent=effective_next_agent,
                action_required=self._action_required(
                    tool_calls,
                    route.needs_human_handoff,
                    index,
                    effective_next_agent,
                ),
                risk_flags=self._risk_flags(tool_calls, route.needs_human_handoff, index),
                trace_tags=self._trace_tags(task.agent, tool_calls),
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
            if execution.action_required == "handoff-to-human-operator":
                break
        return executions

    def _execute_tool_plan(
        self,
        tool_plan: list[ToolPlanItem],
        request: MessageRequest,
        trace: TraceContext | None,
        agent: str,
        working_context: SessionContext,
        deadline: float | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> tuple[list[ToolInvocation], bool]:
        tool_calls: list[ToolInvocation] = []
        for item in tool_plan:
            if cancel_check is not None:
                cancel_check()
            if self._deadline_exceeded(deadline):
                return tool_calls, True
            hydrated_item = item.model_copy(
                deep=True,
                update={"payload": self._hydrate_payload(item, working_context)},
            )
            preflight = self.tool_hub_client.preflight(
                hydrated_item,
                request.user_profile,
                trace,
                operator_id=agent,
                message_id=request.message_id,
            )
            if self._deadline_exceeded(deadline):
                return tool_calls, True
            if not preflight.ready:
                tool_calls.append(self._blocked_tool_invocation(hydrated_item, preflight))
                return tool_calls, False
            if cancel_check is not None:
                cancel_check()
            if self._deadline_exceeded(deadline):
                return tool_calls, True
            invocation = self.tool_hub_client.invoke_plan(
                [hydrated_item],
                request.user_profile,
                trace,
                operator_id=agent,
                message_id=request.message_id,
            )[0]
            if cancel_check is not None:
                cancel_check()
            tool_calls.append(invocation)
            if invocation.success and invocation.session_context_patch:
                ConversationStore._apply_session_context_patch(working_context, invocation.session_context_patch)
            if self._deadline_exceeded(deadline):
                return tool_calls, True
            if self._requires_user_follow_up(invocation):
                return tool_calls, False
            if invocation.status in {"auth-required", "confirmation-required"}:
                return tool_calls, False
            if invocation.success is False:
                return tool_calls, False
        return tool_calls, False

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
        citations = sorted({citation for tool_call in tool_calls for citation in tool_call.citations})
        if task.requires_retrieval:
            citations.append("baseline://router-retrieval")
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
            action_required=None,
            risk_flags=self._risk_flags(tool_calls, route.needs_human_handoff, index, timed_out=True),
            trace_tags=self._trace_tags(task.agent, tool_calls, timed_out=True),
            handoff_reason=None,
            handoff_payload={},
        )

    def _deadline_exceeded(self, deadline: float | None) -> bool:
        if deadline is None:
            return False
        return self._clock() > deadline

    def _hydrate_payload(
        self,
        item: ToolPlanItem,
        working_context: SessionContext,
    ) -> dict[str, object]:
        definition = self._catalog.get(item.tool_name).definition if item.tool_name in self._catalog else None
        payload = hydrate_payload_from_session_context(
            item.payload,
            definition,
            working_context,
        )
        if item.tool_name in working_context.confirmed_tool_names and "_confirmed" not in payload:
            payload["_confirmed"] = True
        return payload

    @staticmethod
    def _build_handoff_payload(
        tool_calls: list[ToolInvocation],
        working_context: SessionContext,
        next_task: AgentTask,
    ) -> dict[str, object]:
        merged_patch: dict[str, object] = {}
        for tool_call in tool_calls:
            if tool_call.session_context_patch:
                merged_patch = AgentRuntime._merge_payload_dicts(merged_patch, tool_call.session_context_patch)
        resolved_inputs: dict[str, object] = {}
        for context_key in next_task.session_context_inputs:
            value = read_session_context_key(working_context, context_key)
            if value is not None:
                resolved_inputs[context_key] = value
        return {
            "tool_calls": [tool_call.tool_name for tool_call in tool_calls],
            "session_context_patch": merged_patch,
            "next_agent_inputs": list(next_task.session_context_inputs),
            "resolved_session_context": resolved_inputs,
            "suggested_tools": list(next_task.suggested_tools),
        }

    @staticmethod
    def _merge_payload_dicts(
        left: dict[str, object],
        right: dict[str, object],
    ) -> dict[str, object]:
        merged = dict(left)
        for key, value in right.items():
            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, dict):
                merged[key] = AgentRuntime._merge_payload_dicts(existing, value)
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _blocked_tool_invocation(item, preflight) -> ToolInvocation:
        if preflight.status == "missing-payload":
            details = {
                "missing_fields": preflight.missing_payload_fields,
                "missing_hints": preflight.missing_payload_hints,
            }
            return ToolInvocation(
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                operation=item.operation,
                status="clarification-required",
                payload=details,
                summary=AgentRuntime._clarification_summary(preflight.missing_payload_hints, preflight.missing_payload_fields),
                auth_required=False,
                success=False,
                error_detail=details,
                user_action_hint=preflight.user_action_hint,
            )
        if preflight.status == "auth-required":
            details = {
                "missing_context": preflight.missing_auth_context,
                "required_permissions": preflight.required_permissions,
            }
            return ToolInvocation(
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                operation=item.operation,
                status="auth-required",
                payload=details,
                summary=f"{item.tool_name} 执行前需补充鉴权上下文。",
                auth_required=True,
                success=False,
                code=4030001,
                error_detail=details,
                user_action_hint=preflight.user_action_hint,
            )
        if preflight.status == "confirmation-required":
            return ToolInvocation(
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                operation=item.operation,
                status="confirmation-required",
                payload={"confirmation_required": True},
                summary=f"{item.tool_name} 属于高风险写操作，需先完成显式确认。",
                auth_required=False,
                success=False,
                code=4090002,
                error_detail={"reason": "confirmation_required"},
                user_action_hint=preflight.user_action_hint,
            )
        if preflight.status == "missing-tool":
            return ToolInvocation(
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                operation=item.operation,
                status="missing-tool",
                payload=item.payload,
                summary="Tool is not registered in tool-hub.",
                auth_required=False,
                success=False,
                code=4040001,
            )
        return ToolInvocation(
            tool_name=item.tool_name,
            tool_call_id=item.tool_call_id,
            operation=item.operation,
            status="failed",
            payload=item.payload,
            summary=f"{item.tool_name} 当前不可执行。",
            auth_required=False,
            success=False,
            code=5003000,
        )

    @staticmethod
    def _clarification_summary(
        hints: dict[str, str],
        missing_fields: list[str],
    ) -> str:
        if hints:
            ordered_hints = [hints[field] for field in missing_fields if field in hints]
            if ordered_hints:
                return "；".join(ordered_hints)
        if missing_fields:
            return f"继续执行前请补充：{', '.join(missing_fields)}。"
        return "继续执行前需要补充更多信息。"

    @staticmethod
    def _determine_status(
        tool_calls: list[ToolInvocation],
        next_agent: str | None,
        needs_human_handoff: bool,
        index: int,
    ) -> str:
        if any(AgentRuntime._requires_user_follow_up(tool_call) for tool_call in tool_calls):
            return "need_user_input"
        if any((tool_call.success is False) and tool_call.status not in {"auth-required", "confirmation-required", "clarification-required"} for tool_call in tool_calls):
            return "failed"
        if next_agent or (needs_human_handoff and index == 0):
            return "handoff"
        return "success"

    @staticmethod
    def _build_reasoning_summary(
        agent: str,
        requires_retrieval: bool,
        tool_calls: list[ToolInvocation],
        next_agent: str | None,
    ) -> str:
        return (
            f"{agent} 完成基础编排；retrieval={requires_retrieval}，"
            f"tool_calls={len(tool_calls)}，next_agent={next_agent or 'none'}。"
        )

    def _final_answer(
        self,
        agent: str,
        tool_calls: list[ToolInvocation],
        status: str,
        next_agent: str | None,
    ) -> str | None:
        if not tool_calls:
            return f"{agent} 已准备处理当前问题。"
        clarification_call = next(
            (tool_call for tool_call in tool_calls if tool_call.status == "clarification-required"),
            None,
        )
        if clarification_call is not None:
            return clarification_call.summary
        preview_confirmation_call = next(
            (
                tool_call
                for tool_call in reversed(tool_calls)
                if tool_call.user_action_hint is not None
                and tool_call.user_action_hint.action == "user-confirmation"
            ),
            None,
        )
        if preview_confirmation_call is not None:
            summary = preview_confirmation_call.summary or f"{preview_confirmation_call.tool_name} 已生成预览草稿。"
            return f"{summary} 请确认后继续执行。"
        final_tool_call = next((tool_call for tool_call in reversed(tool_calls) if tool_call.success), tool_calls[-1])
        payload = final_tool_call.payload
        if final_tool_call.tool_name == "billing.query_statement" and final_tool_call.success:
            return (
                f"账单周期 {payload.get('billing_cycle')} 总额 {payload.get('total_amount')} "
                f"{payload.get('currency', 'CNY')}。"
            )
        if final_tool_call.tool_name == "order.query_order":
            refund_no = payload.get("refund_no")
            refund_status = payload.get("refund_status")
            if refund_no and refund_status and refund_status != "not_requested":
                return (
                    f"订单 {payload.get('order_no')} 当前状态 {payload.get('order_status')}，"
                    f"退款申请 {refund_no} 进度 {refund_status}。"
                )
            return (
                f"订单 {payload.get('order_no')} 当前状态 {payload.get('order_status')}，"
                f"支付金额 {payload.get('paid_amount')} {payload.get('currency', 'CNY')}。"
            )
        if final_tool_call.tool_name == "billing.create_invoice":
            if final_tool_call.success:
                return f"开票申请 {payload.get('invoice_no')} 已提交，金额 {payload.get('amount')} CNY。"
            return "已生成开票申请草稿，需用户确认后再提交。"
        if final_tool_call.tool_name == "invoice.query_invoice":
            return (
                f"发票申请 {payload.get('invoice_no')} 当前状态 {payload.get('status')}，"
                f"金额 {payload.get('amount')} CNY。"
            )
        if final_tool_call.tool_name == "order.create_refund":
            if final_tool_call.success:
                return f"退款申请 {payload.get('refund_no')} 已提交，金额 {payload.get('requested_amount')} CNY。"
            return "已生成退款申请草稿，需用户确认金额和原因。"
        if final_tool_call.tool_name == "billing.query_instance_cost":
            return (
                f"实例 {payload.get('instance_id')} 在 {payload.get('billing_cycle')} 的费用为 "
                f"{payload.get('total_amount')} CNY（计算 {payload.get('compute_amount')} / "
                f"存储 {payload.get('storage_amount')} / 网络 {payload.get('network_amount')}）。"
            )
        if final_tool_call.tool_name == "ticket.create":
            if final_tool_call.success:
                summary = f"工单 {payload.get('ticket_no')} 已创建，主题：{payload.get('subject')}。"
                if payload.get("queue"):
                    summary += f" 已分配到 {payload.get('queue')}。"
                if payload.get("incident_code"):
                    summary += f" 关联事件 {payload.get('incident_code')}。"
                return summary
            return f"已准备创建工单，主题：{payload.get('subject')}。"
        if final_tool_call.tool_name == "ticket.query_ticket":
            summary = f"工单 {payload.get('ticket_no')} 当前状态 {payload.get('status')}"
            if payload.get("latest_action"):
                summary += f"，最新进展：{payload.get('latest_action')}"
            return f"{summary}。"
        if final_tool_call.tool_name == "icp.material_check":
            if payload.get("passed"):
                return "备案材料已通过基线检查，可继续准备提交。"
            return f"备案材料仍有缺口：{'；'.join(payload.get('issues', []))}"
        if final_tool_call.tool_name == "icp.verify_subject":
            if payload.get("verified"):
                return (
                    f"备案实名认证基线核验已通过，主体 {payload.get('subject_name')}，"
                    "可继续补充材料或提交申请。"
                )
            return "备案实名认证仍需补充主体信息后再继续。"
        if final_tool_call.tool_name == "icp.submit_application":
            if final_tool_call.success:
                return f"备案申请 {payload.get('application_no')} 已提交，当前环节 {payload.get('current_step')}。"
            return "已生成备案申请草稿，需用户确认后再提交。"
        if final_tool_call.tool_name == "icp.query_application":
            summary = f"备案申请 {payload.get('application_no')} 当前状态 {payload.get('status')}"
            if payload.get("current_step"):
                summary += f"，当前环节 {payload.get('current_step')}"
            if payload.get("latest_action"):
                summary += f"，最新进展：{payload.get('latest_action')}"
            return f"{summary}。"
        if final_tool_call.tool_name == "marketing.campaign_lookup":
            campaigns = payload.get("campaigns", [])
            if campaigns:
                return f"已匹配 {len(campaigns)} 个营销活动候选，优先推荐 {campaigns[0].get('name')}。"
        if final_tool_call.tool_name == "marketing.generate_copy":
            return f"已生成营销文案：{payload.get('headline')}。"
        if final_tool_call.tool_name == "marketing.generate_promotion_link":
            return f"已生成推广链接 {payload.get('short_url')}，对应活动 {payload.get('campaign_name')}。"
        if final_tool_call.tool_name == "marketing.generate_poster":
            return (
                f"已生成海报资产 {payload.get('poster_asset_id')}，"
                f"下载路径 {payload.get('download_path')}。"
            )
        if final_tool_call.tool_name == "research.generate_report":
            return str(payload.get("executive_summary", "已生成调研报告结构。"))
        if final_tool_call.tool_name == "research.export_report":
            export_format = str(payload.get("format", "markdown")).upper()
            return f"已导出 {export_format} 报告，路径 {payload.get('download_path')}。"
        if final_tool_call.tool_name == "product.catalog_lookup":
            families = payload.get("product_families", [])
            if families:
                return f"建议优先关注：{'、'.join(families[:3])}。"
        if final_tool_call.tool_name == "product.recommend_instance":
            workload_label = {
                "training": "训练/微调",
                "inference": "推理/部署",
                "general": "通用",
            }.get(str(payload.get("workload")), str(payload.get("workload") or "当前"))
            return (
                f"建议先使用 {payload.get('recommended_instance_type')} "
                f"（{payload.get('gpu_model')} x{payload.get('gpu_count')}，"
                f"{payload.get('vcpu')} vCPU / {payload.get('memory_gb')}GB）"
                f"承载 {workload_label} 场景。"
            )
        if final_tool_call.tool_name == "support.query_service_status":
            resource_label = payload.get("instance_id") or payload.get("service_name")
            summary = payload.get("summary")
            incident_code = payload.get("incident_code")
            if incident_code:
                return f"{resource_label} 状态检查结果：{summary} 关联事件 {incident_code}。"
            return f"{resource_label} 状态检查结果：{summary}"
        if final_tool_call.tool_name == "support.handoff_brief":
            queue = payload.get("queue")
            severity = payload.get("severity")
            summary = payload.get("summary") or "已生成转人工交接摘要。"
            if queue and severity:
                return f"{summary} 建议分配到 {queue} 队列，优先级 {severity}。"
            return str(summary)
        if status == "handoff" and next_agent:
            return f"{agent} 已完成当前阶段，准备交接给 {next_agent}。"
        return final_tool_call.summary or f"{agent} 已完成当前阶段处理。"

    @staticmethod
    def _action_required(
        tool_calls: list[ToolInvocation],
        needs_human_handoff: bool,
        index: int,
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
        if needs_human_handoff and index == 0 and next_agent is None:
            return "handoff-to-human-operator"
        return None

    @staticmethod
    def _risk_flags(
        tool_calls: list[ToolInvocation],
        needs_human_handoff: bool,
        index: int,
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
        if any((tool_call.success is False) and tool_call.status not in {"clarification-required", "auth-required", "confirmation-required"} for tool_call in tool_calls):
            flags.append("tool_failure")
        if timed_out:
            flags.append("agent_timeout")
        if needs_human_handoff and index == 0:
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

    @staticmethod
    def _confidence_for(tool_calls: list[ToolInvocation], status: str) -> float:
        if status == "failed":
            return 0.2
        if status == "need_user_input":
            return 0.45
        if any(tool_call.success for tool_call in tool_calls):
            return 0.82
        return 0.6

    @staticmethod
    def _requires_user_follow_up(tool_call: ToolInvocation) -> bool:
        if tool_call.status in {"auth-required", "confirmation-required", "clarification-required"}:
            return True
        if tool_call.user_action_hint is None:
            return False
        return tool_call.user_action_hint.action in {
            "clarify-tool-input",
            "collect-auth-context",
            "user-confirmation",
        }
