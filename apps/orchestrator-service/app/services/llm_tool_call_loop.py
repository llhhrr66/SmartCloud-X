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
from app.services.agent_registry import allowed_tools_for, tool_permission_for
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
        # Reusable instances (avoid recreating each round)
        from app.services.token_counter import TokenCounter
        from app.services.compact import AutoCompactTrigger
        self._counter = TokenCounter()
        self._auto_compact_trigger = AutoCompactTrigger(settings=self._settings, token_counter=self._counter)
        self._last_compact_summary: str | None = None

    def run(
        self,
        agent: AgentName,
        user_query: str,
        request: MessageRequest,
        working_context: SessionContext,
        trace: TraceContext | None = None,
        *,
        compacted_history: str | None = None,
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

        # Build initial messages list with conversation history
        messages: list[dict[str, Any]] = []

        # Inject recent conversation history so the LLM has context
        recent = getattr(working_context, "recent_messages", None) or []
        # Limit to the last 20 messages (10 turns) to avoid blowing the context window
        for hist_msg in recent[-20:]:
            role = hist_msg.get("role", "user")
            content = hist_msg.get("content", "")
            if not content:
                continue
            # Only include user and assistant messages (skip tool/system)
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": str(content)})

        messages.append({"role": "user", "content": user_query})

        tool_calls: list[ToolInvocation] = []
        max_rounds = self._settings.max_tool_call_rounds

        # Reset per-run state
        self._last_compact_summary = None

        # Micro-compact state
        micro_enabled = self._settings.micro_compact_enabled

        for round_idx in range(max_rounds):
            # At each round start, apply micro-compact to shrink old tool results
            if micro_enabled and round_idx > 0:
                from app.services.micro_compact import micro_compact_messages
                messages = micro_compact_messages(messages)

            # Auto-compact check: if messages have grown too large, compact them
            if round_idx > 0 and self._settings.compact_enabled:
                should, estimated, threshold = self._auto_compact_trigger.should_compact(messages)
                if should:
                    from app.services.compact import compact_conversation
                    from app.models.compact import CompactionStrategy
                    try:
                        strategy = CompactionStrategy(self._settings.compact_strategy)
                    except ValueError:
                        strategy = CompactionStrategy.FULL
                    try:
                        compacted_msgs, compact_meta = compact_conversation(
                            messages,
                            strategy=strategy,
                            settings=self._settings,
                            token_counter=self._counter,
                        )
                        # Replace messages but keep the original user query at the front
                        if compacted_msgs:
                            # Ensure the first message is still the user query
                            if compacted_msgs[0].get("role") != "user":
                                messages = [{"role": "user", "content": user_query}, *compacted_msgs]
                            else:
                                messages = compacted_msgs
                            self._auto_compact_trigger.record_success()
                            # Store compaction summary for session context derivation
                            if compact_meta.compact_summary:
                                self._last_compact_summary = compact_meta.compact_summary
                        else:
                            self._auto_compact_trigger.record_failure()
                    except Exception:
                        logger.warning("auto-compact failed in round %d; continuing with original messages", round_idx + 1)
                        self._auto_compact_trigger.record_failure()

            completion = self._answer_generator.create_with_tools(
                agent=agent,
                messages=messages,
                tools=openai_tools,
                compacted_history=compacted_history,
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

                # Build tool result message with timestamp for micro-compact
                tool_msg: dict[str, Any] = {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result_str,
                }
                # Add created_at for micro-compact time-gap detection
                from datetime import UTC, datetime
                tool_msg["created_at"] = datetime.now(UTC).isoformat()
                messages.append(tool_msg)

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

        # ── Three-tier permission check (allow / ask / deny) ──
        permission = tool_permission_for(agent, tool_name)
        if permission == "deny":
            invocation = ToolInvocation(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                operation=operation,
                payload=payload,
                status="permission-denied",
                success=False,
                summary=f"工具 {tool_name} 不允许当前 Agent 调用。",
            )
            result_str = json.dumps(
                {"error": f"permission denied: tool '{tool_name}' not available for agent '{agent}'"},
                ensure_ascii=False,
            )
            return invocation, result_str
        if permission == "ask" and not payload.get("_confirmed"):
            operation = "preview"  # Downgrade to preview unless confirmed

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
