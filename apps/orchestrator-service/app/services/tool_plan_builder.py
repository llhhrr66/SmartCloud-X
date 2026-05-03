from __future__ import annotations

from collections.abc import Callable, Iterable

from app.core.business_tools_sdk import ToolDefinition, ToolExecutionContext, is_missing_tool_value
from app.models.orchestration import AgentDescriptor, AgentName, RouteRequest, ToolPlanItem
from app.services.tool_context import available_session_context_keys, session_context_input_keys

from .tool_payload_builder import ToolPayloadBuilder
from .tool_suggestion import ToolSuggestionEngine


def _confirmed_tool_names(request: RouteRequest) -> set[str]:
    confirmed = set(request.session_context.confirmed_tool_names)
    extra = request.session_context.attributes.get("confirmed_tool_names", [])
    if isinstance(extra, str):
        extra = [extra]
    confirmed.update(extra)
    return confirmed


def _dedupe_strings(values: Iterable[object]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _tool_readiness(
    *,
    missing_payload: list[str],
    dependency_ids: list[str],
    missing_auth: list[str],
    confirmation_pending: bool,
) -> str:
    if missing_payload or missing_auth or confirmation_pending:
        return "needs_user_input"
    if dependency_ids:
        return "ready_after_dependencies"
    return "ready"


def _missing_auth_context(
    definition: ToolDefinition,
    request: RouteRequest,
    *,
    operation: str = "execute",
) -> list[str]:
    if operation != "execute":
        return []
    return ToolExecutionContext(
        user_id=request.user_profile.user_id,
        account_id=request.user_profile.account_id,
        roles=request.user_profile.roles,
        permissions=request.user_profile.permissions,
        tenant_id=request.user_profile.tenant_id,
    ).missing_auth(definition.auth_requirements)


def _resolve_payload_requirements(
    *,
    definition: ToolDefinition | None,
    payload: dict[str, object],
    required_fields: list[str],
    available_context_keys: set[str],
    produced_context_keys: dict[str, str],
    selected_tools: list[ToolPlanItem],
) -> tuple[list[str], list[str], list[str]]:
    if definition is None:
        return [], [], []
    missing_payload: list[str] = []
    deferred_payload: list[str] = []
    dependency_ids = _dedupe_strings(
        item.tool_call_id
        for item in selected_tools
        if item.tool_name in definition.prerequisite_tool_names
    )
    for field in required_fields:
        if not is_missing_tool_value(payload.get(field)):
            continue
        binding_keys = definition.session_context_bindings.get(field, [])
        if any(binding_key in available_context_keys for binding_key in binding_keys):
            continue
        binding_dependency_ids = _dedupe_strings(
            produced_context_keys[binding_key]
            for binding_key in binding_keys
            if binding_key in produced_context_keys
        )
        if binding_dependency_ids:
            deferred_payload.append(field)
            dependency_ids.extend(binding_dependency_ids)
            continue
        missing_payload.append(field)
    return missing_payload, deferred_payload, _dedupe_strings(dependency_ids)


def _order_tools_for_dependencies(
    tool_names: list[str],
    tool_definitions: dict[str, ToolDefinition],
) -> list[str]:
    deduped = _dedupe_strings(tool_names)
    if len(deduped) <= 1:
        return deduped
    remaining = list(deduped)
    ordered: list[str] = []
    while remaining:
        progressed = False
        for tool_name in list(remaining):
            definition = tool_definitions.get(tool_name)
            prerequisites = [
                prerequisite
                for prerequisite in (definition.prerequisite_tool_names if definition else [])
                if prerequisite in deduped
            ]
            if all(prerequisite in ordered for prerequisite in prerequisites):
                ordered.append(tool_name)
                remaining.remove(tool_name)
                progressed = True
        if progressed:
            continue
        ordered.extend(remaining)
        break
    return ordered


def build_tool_plan(
    request: RouteRequest,
    primary: AgentName,
    ordered_agents: list[AgentName],
    text: str,
    tool_candidates: list[str],
    *,
    tool_definitions: dict[str, ToolDefinition],
    agent_descriptor: Callable[[AgentName], AgentDescriptor],
    max_tool_calls_per_agent: int,
) -> list[ToolPlanItem]:
    """Compose the per-agent tool execution plan.

    Pure function — every router-specific dependency (catalog, settings,
    descriptor lookup) is passed in. Returns a deduplicated list of plan
    items ready for the agent runtime.
    """
    selected_tools: list[ToolPlanItem] = []
    available_context_keys = available_session_context_keys(request.session_context)
    produced_context_keys: dict[str, str] = {}
    confirmed_tool_names = _confirmed_tool_names(request)
    for agent in ordered_agents:
        suggested_tools = _order_tools_for_dependencies(
            ToolSuggestionEngine.suggest(agent, request, text, tool_candidates),
            tool_definitions,
        )[: min(request.constraints.max_tool_calls, agent_descriptor(agent).max_tool_calls)]
        for index, tool_name in enumerate(suggested_tools, start=1):
            definition = tool_definitions.get(tool_name)
            operation = "execute" if definition is not None else "preview"
            payload = ToolPayloadBuilder.build(tool_name, request, text, definition)
            required_fields = (
                list(definition.operation_required_fields.get("execute", []))
                if definition is not None
                else []
            )
            missing_payload, deferred_payload, dependency_ids = _resolve_payload_requirements(
                definition=definition,
                payload=payload,
                required_fields=required_fields,
                available_context_keys=available_context_keys,
                produced_context_keys=produced_context_keys,
                selected_tools=selected_tools,
            )
            missing_auth = (
                _missing_auth_context(definition, request, operation=operation)
                if definition
                else []
            )
            confirmation_pending = bool(
                definition
                and operation == "execute"
                and definition.auth_requirements.confirmation_required
                and tool_name not in confirmed_tool_names
            )
            if (
                definition is not None
                and operation == "execute"
                and confirmation_pending
                and not missing_payload
                and not missing_auth
            ):
                operation = "preview"
                confirmation_pending = False
            selected_tools.append(
                ToolPlanItem(
                    tool_call_id=f"tc-{agent}-{index}",
                    tool_name=tool_name,
                    assigned_agent=agent,
                    operation=operation,
                    reason=f"{agent} needs {tool_name} for baseline orchestration.",
                    payload=payload,
                    required_payload_fields=required_fields,
                    missing_payload_fields=missing_payload,
                    deferred_payload_fields=deferred_payload,
                    missing_payload_hints={
                        field: definition.input_field_hints[field]
                        for field in [*missing_payload, *deferred_payload]
                        if definition and field in definition.input_field_hints
                    },
                    depends_on_tool_call_ids=dependency_ids,
                    session_context_input_keys=session_context_input_keys(definition),
                    session_context_output_keys=list(definition.session_context_output_keys) if definition else [],
                    readiness=_tool_readiness(
                        missing_payload=missing_payload,
                        dependency_ids=dependency_ids,
                        missing_auth=missing_auth,
                        confirmation_pending=confirmation_pending,
                    ),
                    auth_required=bool(missing_auth),
                    requires_account_context=bool(
                        definition and definition.auth_requirements.require_account_id
                    ),
                    required_permissions=list(
                        definition.auth_requirements.required_permissions if definition else []
                    ),
                    high_risk=bool(definition and definition.high_risk),
                    tool_mode=definition.mode if definition else None,
                    timeout_ms=definition.timeout_ms if definition else None,
                    idempotent=definition.idempotent if definition else None,
                    cache_ttl_seconds=definition.cache_ttl_seconds if definition else None,
                )
            )
            if definition is not None:
                for context_key in definition.session_context_output_keys:
                    produced_context_keys.setdefault(context_key, f"tc-{agent}-{index}")
    deduped: list[ToolPlanItem] = []
    seen: set[tuple[str, AgentName]] = set()
    for item in selected_tools:
        key = (
            (item.tool_name, primary)
            if item.tool_name == "support.handoff_brief"
            else (item.tool_name, item.assigned_agent)
        )
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped[: max_tool_calls_per_agent * max(len(ordered_agents), 1)]


def has_confirmation_pending(
    tool_plan: list[ToolPlanItem],
    request: RouteRequest,
    tool_definitions: dict[str, ToolDefinition],
) -> bool:
    confirmed = _confirmed_tool_names(request)
    for item in tool_plan:
        definition = tool_definitions.get(item.tool_name)
        if definition is None:
            continue
        if (
            definition.auth_requirements.confirmation_required
            and item.tool_name not in confirmed
        ):
            return True
    return False


def expand_tool_candidates(
    tool_candidates: list[str],
    tool_definitions: dict[str, ToolDefinition],
) -> list[str]:
    expanded: list[str] = []
    visiting: set[str] = set()

    def _visit(tool_name: str) -> None:
        normalized = str(tool_name).strip()
        if not normalized or normalized in expanded or normalized in visiting:
            return
        definition = tool_definitions.get(normalized)
        if definition is None:
            return
        visiting.add(normalized)
        for prerequisite in definition.prerequisite_tool_names:
            _visit(prerequisite)
        visiting.remove(normalized)
        if normalized not in expanded:
            expanded.append(normalized)

    for tool_name in tool_candidates:
        _visit(str(tool_name))
    return expanded
