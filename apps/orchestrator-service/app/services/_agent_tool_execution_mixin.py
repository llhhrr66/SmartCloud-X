from __future__ import annotations

from collections.abc import Callable

from app.models.common import TraceContext
from app.models.orchestration import (
    AgentTask,
    MessageRequest,
    SessionContext,
    ToolInvocation,
    ToolPlanItem,
)
from app.services.conversation_store import ConversationStore
from app.services.tool_context import hydrate_payload_from_session_context, read_session_context_key


class _AgentToolExecutionMixin:
    """Tool-plan execution helpers used by ``AgentRuntime``.

    Expects the host class to provide ``self.tool_hub_client``, ``self._catalog``,
    and ``self._clock``.
    """

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
                merged_patch = _AgentToolExecutionMixin._merge_payload_dicts(
                    merged_patch, tool_call.session_context_patch
                )
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
                merged[key] = _AgentToolExecutionMixin._merge_payload_dicts(existing, value)
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
                summary=_AgentToolExecutionMixin._clarification_summary(
                    preflight.missing_payload_hints, preflight.missing_payload_fields
                ),
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
