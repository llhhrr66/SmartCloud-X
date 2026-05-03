from __future__ import annotations

import json
import logging
from typing import Any

from app.core.business_tools_sdk import ToolDefinition, build_catalog
from app.core.config import Settings
from app.models.common import TraceContext
from app.models.orchestration import (
    AgentName,
    MessageRequest,
    SessionContext,
    ToolInvocation,
    ToolPlanItem,
    UserProfile,
)
from app.services.agent_answer_generator import AgentAnswerGenerator
from app.services.agent_registry import allowed_tools_for
from app.services.conversation_store import ConversationStore
from app.services.tool_context import hydrate_payload_from_session_context
from app.services.tool_hub_client import ToolHubClient
from app.services.tool_schema_adapter import tool_definitions_to_openai_tools

logger = logging.getLogger(__name__)


class LLMToolCallLoop:
    """LLM-driven tool calling loop following the BetaToolRunner pattern.

    Presents agent-scoped tools to the LLM via the OpenAI ``tools=`` API.
    The LLM decides which tools to call; results are fed back as tool
    messages.  The loop continues until the LLM stops requesting tools
    or the maximum round count is reached.
    """

    def __init__(
        self,
        answer_generator: AgentAnswerGenerator,
        tool_hub_client: ToolHubClient,
        catalog: dict[str, Any] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._answer_generator = answer_generator
        self._tool_hub_client = tool_hub_client
        self._catalog = catalog
        self._settings = settings or self._tool_hub_client.settings

    def run(
        self,
        agent: AgentName,
        user_query: str,
        request: MessageRequest,
        working_context: SessionContext,
        trace: TraceContext | None = None,
    ) -> tuple[list[ToolInvocation], str | None]:
        """Execute the tool-calling loop.

        Returns ``(tool_calls, llm_final_answer)`` where *tool_calls* is the
        list of all tool invocations performed and *llm_final_answer* is the
        LLM's final text response (may be ``None`` if the LLM produced no
        text content).
        """
        allowed = allowed_tools_for(agent)
        definitions = self._tool_definitions()
        if not definitions:
            logger.warning("no tool definitions available; skipping LLM tool loop")
            return [], None
        openai_tools = tool_definitions_to_openai_tools(definitions, allowed)
        if not openai_tools:
            logger.warning("no tools available for %s; skipping LLM tool loop", agent)
            return [], None

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_query},
        ]
        tool_calls: list[ToolInvocation] = []
        max_rounds = self._settings.max_tool_call_rounds

        for round_idx in range(max_rounds):
            completion = self._answer_generator.create_with_tools(
                agent=agent,
                messages=messages,
                tools=openai_tools,
            )
            if completion is None:
                logger.warning("LLM call failed in round %d; breaking loop", round_idx + 1)
                break

            choice = completion.choices[0] if completion.choices else None
            if choice is None:
                break

            message = choice.message
            assistant_tool_calls = getattr(message, "tool_calls", None) or []
            assistant_content = getattr(message, "content", None)

            if not assistant_tool_calls:
                # LLM has stopped calling tools — return results
                return tool_calls, assistant_content

            # Append assistant message with tool_calls to conversation
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if assistant_content:
                assistant_msg["content"] = assistant_content
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_tool_calls
            ]
            messages.append(assistant_msg)

            # Execute each tool call and append results
            for tc in assistant_tool_calls:
                tool_name = tc.function.name
                arguments_str = tc.function.arguments
                invocation, tool_result_str = self._execute_single_tool(
                    tool_name=tool_name,
                    tool_call_id=tc.id,
                    arguments_str=arguments_str,
                    agent=agent,
                    request=request,
                    working_context=working_context,
                    trace=trace,
                    definitions=definitions,
                )
                tool_calls.append(invocation)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result_str,
                })

                # Apply session context patch if tool succeeded
                if invocation.success and invocation.session_context_patch:
                    ConversationStore._apply_session_context_patch(
                        working_context, invocation.session_context_patch
                    )

        logger.info("LLM tool loop completed after %d rounds with %d tool calls", max_rounds, len(tool_calls))
        return tool_calls, None

    def _execute_single_tool(
        self,
        *,
        tool_name: str,
        tool_call_id: str,
        arguments_str: str,
        agent: str,
        request: MessageRequest,
        working_context: SessionContext,
        trace: TraceContext | None,
        definitions: dict[str, ToolDefinition],
    ) -> tuple[ToolInvocation, str]:
        """Execute a single tool call from the LLM.

        Returns ``(invocation, result_str)`` where *invocation* is the
        ``ToolInvocation`` and *result_str* is the serialized result to
        feed back to the LLM.
        """
        try:
            payload = json.loads(arguments_str) if arguments_str else {}
        except json.JSONDecodeError:
            payload = {}

        definition = definitions.get(tool_name)

        # Hydrate missing payload fields from session context
        if definition is not None:
            payload = hydrate_payload_from_session_context(payload, definition, working_context)

        # Determine operation: preview for high-risk tools unless already confirmed
        operation = "execute"
        if definition is not None and definition.high_risk and not payload.get("_confirmed"):
            operation = "preview"

        # Build ToolPlanItem for execution
        plan_item = ToolPlanItem(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            operation=operation,
            reason="llm_tool_call",
            payload=payload,
            assigned_agent=agent,
        )

        # Preflight check
        preflight = self._tool_hub_client.preflight(
            plan_item,
            request.user_profile,
            trace,
            operator_id=agent,
            message_id=request.message_id,
        )

        if not preflight.ready:
            result_str = json.dumps(
                {"error": f"preflight failed: {preflight.status}", "details": _preflight_details(preflight)},
                ensure_ascii=False,
            )
            invocation = _preflight_blocked_invocation(plan_item, preflight, agent)
            return invocation, result_str

        # Invoke tool
        invocations = self._tool_hub_client.invoke_plan(
            [plan_item],
            request.user_profile,
            trace,
            operator_id=agent,
            message_id=request.message_id,
        )
        invocation = invocations[0] if invocations else ToolInvocation(
            tool_name=tool_name,
            operation=operation,
            payload=payload,
            status="failed",
            success=False,
            summary="工具调用未返回结果。",
        )

        # Serialize result for LLM
        result_str = _serialize_tool_result(invocation)
        return invocation, result_str

    def _tool_definitions(self) -> dict[str, ToolDefinition]:
        catalog = self._catalog
        if catalog is None:
            catalog = build_catalog()
        if not catalog:
            return {}
        return {name: tool.definition for name, tool in catalog.items()}


def _preflight_details(preflight: Any) -> dict[str, Any]:
    details: dict[str, Any] = {}
    if preflight.missing_payload_fields:
        details["missing_payload_fields"] = preflight.missing_payload_fields
    if preflight.missing_auth_context:
        details["missing_auth_context"] = preflight.missing_auth_context
    if preflight.missing_payload_hints:
        details["hints"] = preflight.missing_payload_hints
    return details


def _preflight_blocked_invocation(item: ToolPlanItem, preflight: Any, agent: str) -> ToolInvocation:
    return ToolInvocation(
        tool_name=item.tool_name,
        tool_call_id=item.tool_call_id,
        operation=item.operation,
        payload=item.payload,
        status=preflight.status,
        success=False,
        summary=f"工具 {item.tool_name} 预检未通过：{preflight.status}",
    )


def _serialize_tool_result(invocation: ToolInvocation) -> str:
    """Serialize tool invocation result for LLM consumption."""
    result: dict[str, Any] = {
        "tool_name": invocation.tool_name,
        "success": invocation.success,
        "status": invocation.status,
        "summary": invocation.summary,
    }
    if invocation.payload:
        result["data"] = invocation.payload
    if not invocation.success:
        if invocation.user_action_hint:
            result["action_required"] = invocation.user_action_hint.action
            result["message"] = invocation.user_action_hint.message
    return json.dumps(result, ensure_ascii=False)[:4000]
