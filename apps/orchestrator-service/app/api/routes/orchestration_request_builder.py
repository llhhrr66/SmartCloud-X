from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.models.common import ErrorInfo
from app.models.orchestration import (
    ChatCompletionRequest,
    MessageRequest,
    PendingAgentHandoff,
    RouteRequest,
    SessionContext,
    SessionContinueRequest,
    SessionStateSnapshot,
    UserProfile,
)
from app.services.conversation_store import ConversationStore
from app.services.tool_context import (
    read_session_context_key,
    write_session_context_key,
)

from .orchestration_utils import (
    coerce_bool,
    coerce_positive_int,
    merge_tool_candidates,
    preferred_agents_from_hint,
    tool_candidates_from_option,
)


def session_context_from_completion(request_model: ChatCompletionRequest) -> SessionContext:
    base_context = request_model.session_context.model_copy(deep=True)
    if request_model.confirmed_tool_names:
        confirmed = list(dict.fromkeys([*base_context.confirmed_tool_names, *request_model.confirmed_tool_names]))
        base_context.confirmed_tool_names = confirmed
    return base_context


def merge_persisted_session_context(
    persisted: SessionContext,
    incoming: SessionContext,
) -> SessionContext:
    merged = persisted.model_copy(deep=True)
    incoming_attrs = incoming.attributes if isinstance(incoming.attributes, dict) else {}
    for key, value in incoming_attrs.items():
        merged.attributes[key] = value
    if incoming.confirmed_tool_names:
        merged.confirmed_tool_names = list(
            dict.fromkeys([*merged.confirmed_tool_names, *incoming.confirmed_tool_names])
        )
    if incoming.active_products:
        merged.active_products = list(
            dict.fromkeys([*merged.active_products, *incoming.active_products])
        )
    if incoming.history_summary:
        merged.history_summary = incoming.history_summary
    if incoming.open_ticket_id:
        merged.open_ticket_id = incoming.open_ticket_id
    if incoming.recent_messages:
        merged.recent_messages = list(incoming.recent_messages)
    return merged


def message_request_from_chat_completion(request_model: ChatCompletionRequest) -> MessageRequest:
    context = request_model.context if isinstance(request_model.context, dict) else {}
    options = request_model.options if isinstance(request_model.options, dict) else {}
    context_control = request_model.context_control if isinstance(request_model.context_control, dict) else {}
    user_profile = request_model.user_profile.model_copy(deep=True)
    if context:
        if context.get("user_id") is not None:
            user_profile.user_id = str(context.get("user_id"))
        if context.get("tenant_id") is not None:
            user_profile.tenant_id = str(context.get("tenant_id"))
        if context.get("account_id") is not None:
            user_profile.account_id = str(context.get("account_id"))
        if context.get("locale") is not None:
            user_profile.locale = str(context.get("locale"))
        if context.get("channel") is not None:
            user_profile.channel = str(context.get("channel"))
        if isinstance(context.get("roles"), list):
            user_profile.roles = [str(item) for item in context.get("roles", [])]
        if isinstance(context.get("permissions"), list):
            user_profile.permissions = [str(item) for item in context.get("permissions", [])]
    use_rag = coerce_bool(options.get("use_rag"), default=request_model.constraints.must_cite)
    retrieval_required = request_model.retrieval_required if hasattr(request_model, "retrieval_required") else None
    if retrieval_required is None:
        retrieval_required = use_rag
    session_context = session_context_from_completion(request_model)
    preferred_agents = preferred_agents_from_hint(options.get("agent_hint"))
    tool_candidates = merge_tool_candidates(
        list(request_model.tool_candidates),
        tool_candidates_from_option(options.get("tool_candidates")),
    )
    history_limit = coerce_positive_int(options.get("max_history_turns"))
    use_history = coerce_bool(context_control.get("use_history"), default=True)
    use_tools = coerce_bool(options.get("use_tools"), default=True)
    constraints_update: dict[str, object] = {
        "must_cite": coerce_bool(context_control.get("must_cite"), default=request_model.constraints.must_cite) or False,
        "disable_tools": use_tools is False,
    }
    constraints = request_model.constraints.model_copy(update=constraints_update)
    return MessageRequest(
        user_query=request_model.user_input,
        message_id=request_model.message_id,
        scene=request_model.scene or "customer_service",
        user_profile=user_profile,
        session_context=session_context,
        retrieval_context=[],
        attachments=list(request_model.attachments),
        tool_candidates=tool_candidates,
        constraints=constraints,
        retrieval_required=retrieval_required,
        preferred_agents=preferred_agents,
        use_history=True if use_history is None else use_history,
        history_limit=history_limit,
        client_meta=dict(request_model.client_meta),
        trace=request_model.trace,
    )


def route_request_from_message_request(
    conversation_id: str,
    message_request: MessageRequest,
) -> RouteRequest:
    return RouteRequest(
        user_query=message_request.user_query,
        conversation_id=conversation_id,
        scene=message_request.scene,
        user_profile=message_request.user_profile,
        session_context=message_request.session_context,
        retrieval_required=message_request.retrieval_required,
        tool_candidates=list(message_request.tool_candidates),
        preferred_agents=list(message_request.preferred_agents),
        constraints=message_request.constraints,
    )


def message_request_from_session_message(payload: MessageRequest) -> MessageRequest:
    return payload.model_copy(deep=True)


def continue_request_from_pending_handoff(
    pending_handoff: PendingAgentHandoff,
    payload: SessionContinueRequest,
) -> MessageRequest:
    if payload.user_input and payload.user_input.strip():
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_AGENT_HANDOFF_INPUT_NOT_ALLOWED",
                message="Pending agent handoff does not accept overriding user input.",
            ).model_dump(),
        )
    if payload.message_id and payload.message_id != pending_handoff.source_user_message_id:
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_AGENT_HANDOFF_MESSAGE_MISMATCH",
                message="Pending agent handoff message id does not match the source user turn.",
            ).model_dump(),
        )
    return pending_handoff.request_snapshot.model_copy(deep=True)


def continue_assistant_message_id(source_user_message_id: str) -> str:
    return f"{ConversationStore.assistant_message_id(source_user_message_id)}_continue_{uuid4().hex[:8]}"


def hydrate_user_profile_from_auth_profile(message_request: MessageRequest) -> None:
    auth_profile = message_request.session_context.attributes.get("auth_profile")
    if not isinstance(auth_profile, dict):
        return
    profile = message_request.user_profile
    update_values: dict[str, Any] = {}
    if profile.account_id is None and auth_profile.get("account_id"):
        update_values["account_id"] = auth_profile["account_id"]
    if profile.user_id is None and auth_profile.get("user_id"):
        update_values["user_id"] = auth_profile["user_id"]
    if not profile.permissions and auth_profile.get("permissions"):
        update_values["permissions"] = list(auth_profile["permissions"])
    elif auth_profile.get("permissions"):
        merged = list(dict.fromkeys([*profile.permissions, *auth_profile["permissions"]]))
        update_values["permissions"] = merged
    if update_values:
        message_request.user_profile = profile.model_copy(deep=True, update=update_values)


def apply_user_profile_patch(profile: UserProfile, patch) -> UserProfile:
    if patch is None:
        return profile
    update_values: dict[str, Any] = {}
    if patch.user_id is not None:
        update_values["user_id"] = patch.user_id
    if patch.account_id is not None:
        update_values["account_id"] = patch.account_id
    if patch.tenant_id is not None:
        update_values["tenant_id"] = patch.tenant_id
    if patch.locale is not None:
        update_values["locale"] = patch.locale
    if patch.channel is not None:
        update_values["channel"] = patch.channel
    if patch.vip_level is not None:
        update_values["vip_level"] = patch.vip_level
    if patch.roles is not None:
        update_values["roles"] = list(patch.roles)
    if patch.permissions is not None:
        merged_permissions = list(dict.fromkeys([*profile.permissions, *patch.permissions]))
        update_values["permissions"] = merged_permissions
    if not update_values:
        return profile
    return profile.model_copy(deep=True, update=update_values)


def apply_continue_field_values(
    message_request: MessageRequest,
    snapshot: SessionStateSnapshot,
    field_values: dict[str, Any],
) -> None:
    if not field_values:
        return
    bindings_by_field: dict[str, list[str]] = {}
    profile_bindings_by_field: dict[str, list[str]] = {}
    for action in snapshot.pending_user_actions:
        for field, dotted_keys in action.session_context_bindings.items():
            existing = bindings_by_field.setdefault(field, [])
            for dotted_key in dotted_keys:
                if dotted_key not in existing:
                    existing.append(dotted_key)
        for field, dotted_keys in action.user_profile_bindings.items():
            existing = profile_bindings_by_field.setdefault(field, [])
            for dotted_key in dotted_keys:
                if dotted_key not in existing:
                    existing.append(dotted_key)
    prefix_groups: dict[str, dict[str, Any]] = {}
    for field in field_values:
        if "." in field:
            prefix = field.split(".", 1)[0]
            if prefix in bindings_by_field:
                sub_key = field.split(".", 1)[1]
                prefix_groups.setdefault(prefix, {})[sub_key] = field_values[field]
    applied_fields: set[str] = set()
    for prefix, sub_dict in prefix_groups.items():
        existing_obj = read_session_context_key(message_request.session_context, bindings_by_field[prefix][0])
        assembled: dict[str, Any] = {}
        if isinstance(existing_obj, dict):
            assembled.update(existing_obj)
        assembled.update(sub_dict)
        for dotted_key in bindings_by_field[prefix]:
            write_session_context_key(message_request.session_context, dotted_key, assembled)
        for sub_key in sub_dict:
            applied_fields.add(f"{prefix}.{sub_key}")
    profile_updates: dict[str, Any] = {}
    for field, value in field_values.items():
        if field in applied_fields:
            continue
        candidate_fields = [field]
        if "." in field:
            leaf = field.rsplit(".", 1)[-1].strip()
            if leaf and leaf not in candidate_fields:
                candidate_fields.append(leaf)
        applied_to_session = False
        for candidate in candidate_fields:
            for dotted_key in bindings_by_field.get(candidate, []):
                if write_session_context_key(message_request.session_context, dotted_key, value):
                    applied_to_session = True
            for dotted_key in profile_bindings_by_field.get(candidate, []):
                profile_updates.setdefault(dotted_key, value)
        if not applied_to_session and not any(
            candidate in profile_bindings_by_field for candidate in candidate_fields
        ):
            message_request.session_context.attributes[field] = value
    if profile_updates:
        from app.services.tool_context import _coerce_bound_value as _noop  # noqa: F401 - import guard
        attribute_updates: dict[str, Any] = {}
        for dotted_key, value in profile_updates.items():
            segments = [seg for seg in dotted_key.split(".") if seg]
            if not segments:
                continue
            target = segments[0]
            if target == "permissions" and isinstance(value, list):
                merged = list(dict.fromkeys([*message_request.user_profile.permissions, *value]))
                attribute_updates["permissions"] = merged
            elif target == "roles" and isinstance(value, list):
                merged = list(dict.fromkeys([*message_request.user_profile.roles, *value]))
                attribute_updates["roles"] = merged
            elif hasattr(message_request.user_profile, target):
                attribute_updates[target] = value
        if attribute_updates:
            message_request.user_profile = message_request.user_profile.model_copy(
                deep=True, update=attribute_updates
            )


def build_continue_user_input_request(
    conversation_store,
    conversation_id: str,
    snapshot: SessionStateSnapshot,
    payload: SessionContinueRequest,
) -> MessageRequest:
    last_user_message_id = conversation_store.latest_message_id(conversation_id, role="user")
    message_request = conversation_store.build_retry_request(
        conversation_id,
        message_id=last_user_message_id,
    )
    if payload.user_input and payload.user_input.strip():
        message_request.user_query = payload.user_input.strip()
    message_request.message_id = None
    if payload.session_context_patch:
        ConversationStore._apply_session_context_patch(
            message_request.session_context,
            payload.session_context_patch,
        )
    if payload.confirm_tool_names:
        merged = list(
            dict.fromkeys(
                [
                    *message_request.session_context.confirmed_tool_names,
                    *payload.confirm_tool_names,
                ]
            )
        )
        message_request.session_context.confirmed_tool_names = merged
    if payload.field_values:
        apply_continue_field_values(message_request, snapshot, dict(payload.field_values))
    message_request.user_profile = apply_user_profile_patch(
        message_request.user_profile,
        payload.user_profile_patch,
    )
    return message_request
