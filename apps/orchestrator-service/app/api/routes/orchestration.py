from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.business_tools_sdk import build_catalog
from app.core.config import get_settings
from app.models.common import ApiEnvelope, ErrorInfo, TraceContext
from app.models.orchestration import (
    AgentAdminListResponse,
    AgentAdminRecord,
    AgentDescriptor,
    AgentExecutionResult,
    AgentRouteRecord,
    AgentConfigUpdateRequest,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatUsage,
    ConversationRecord,
    ExecutionCheckpoint,
    ExecutionEvent,
    InternalChatRequest,
    InternalChatResponse,
    MessageRequest,
    OrchestratorResponse,
    PendingUserAction,
    RouteDecision,
    RouteRequest,
    ResponseReview,
    RuntimeConstraints,
    SessionCancelRequest,
    SessionCancelResponse,
    SessionContinueRequest,
    SessionRollbackResponse,
    SagaCompensationStep,
    SceneName,
    SessionCreateRequest,
    SessionContext,
    SessionDeleteResponse,
    SessionListResponse,
    SessionMessagesPage,
    SessionRetryRequest,
    SessionStateSnapshot,
    StreamEventPage,
    SessionUpdateRequest,
    ToolContextItem,
    UserProfile,
)
from app.services.agent_config_store import AgentConfigStore
from app.services.agent_runtime import AgentRuntime
from app.services.conversation_store import ConversationStore, ConversationStoreError
from app.services.router import AgentRouter
from app.services.review import ResponseReviewService
from app.services.run_control import ActiveRunConflictError, OrchestrationCancelled, OrchestrationRunControl
from app.services.sse_event_store import SseEventStore
from app.services.state_store import OrchestrationStateStore
from app.services.streaming import build_sse_event_records, iter_sse_events
from app.services.tool_context import apply_tool_input_bindings, write_session_context_key

router = APIRouter(tags=["orchestration"])
internal_router = APIRouter(tags=["internal-orchestration"])
_settings = get_settings()
_agent_config_store = AgentConfigStore(
    file_path=_settings.agent_config_store_path,
    mysql_dsn=_settings.mysql_dsn,
    redis_url=_settings.redis_url,
    redis_namespace=f"{_settings.redis_namespace}:agent-config",
)
_router = AgentRouter(agent_config_store=_agent_config_store)
_runtime = AgentRuntime(agent_config_store=_agent_config_store)
_reviewer = ResponseReviewService()
_tool_catalog = build_catalog()
_state_store = OrchestrationStateStore(
    file_path=_settings.state_store_path,
    mysql_dsn=_settings.mysql_dsn,
    redis_url=_settings.redis_url,
    redis_namespace=f"{_settings.redis_namespace}:state",
)
_conversation_store = ConversationStore(
    file_path=_settings.conversation_store_path,
    mysql_dsn=_settings.mysql_dsn,
    redis_url=_settings.redis_url,
    redis_namespace=f"{_settings.redis_namespace}:conversation",
)
_sse_event_store = SseEventStore(
    file_path=_settings.sse_event_store_path,
    redis_url=_settings.redis_url,
    redis_namespace=f"{_settings.redis_namespace}:sse",
    ttl_seconds=_settings.sse_event_ttl_seconds,
)
_run_control = OrchestrationRunControl(
    redis_url=_settings.redis_url,
    redis_namespace=f"{_settings.redis_namespace}:run-control",
    lease_seconds=max(
        (_settings.default_agent_timeout_seconds * max(_settings.max_handoff_steps, 1)) + 60,
        max((_settings.request_timeout_ms + 999) // 1000, 1) + 60,
        180,
    ),
)
_AUTH_PROFILE_ATTRIBUTE_KEY = "auth_profile"


@router.get("/agents", response_model=ApiEnvelope[list[AgentDescriptor]])
def list_agents(request: Request) -> ApiEnvelope[list[AgentDescriptor]]:
    agents = _router.available_agents()
    return ApiEnvelope(success=True, data=agents, requestId=_request_id(request))


@router.get("/admin/agents", response_model=ApiEnvelope[AgentAdminListResponse])
def list_admin_agents(
    request: Request,
    scene: SceneName | None = Query(default=None),
    status: str | None = Query(default=None),
) -> ApiEnvelope[AgentAdminListResponse]:
    items = _router.available_admin_agents(scene=scene, status=status)
    return ApiEnvelope(
        success=True,
        data=AgentAdminListResponse(items=items, total=len(items)),
        requestId=_request_id(request),
    )


@router.patch("/admin/agents/{agent_code}", response_model=ApiEnvelope[AgentAdminRecord])
def update_admin_agent(
    agent_code: str,
    payload: AgentConfigUpdateRequest,
    request: Request,
) -> ApiEnvelope[AgentAdminRecord]:
    try:
        agent = _router.update_agent_config(agent_code, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="ORCH_AGENT_NOT_FOUND",
                message=str(exc),
            ).model_dump(),
        ) from exc
    return ApiEnvelope(success=True, data=agent, requestId=_request_id(request))


@router.post("/route", response_model=ApiEnvelope[RouteDecision])
def route_request(
    payload: RouteRequest,
    request: Request,
) -> ApiEnvelope[RouteDecision]:
    decision = _router.route(payload)
    return ApiEnvelope(success=True, data=decision, requestId=_request_id(request))


@router.post("/chat/sessions", response_model=ApiEnvelope[ConversationRecord])
def create_session(
    payload: SessionCreateRequest,
    request: Request,
) -> ApiEnvelope[ConversationRecord]:
    record = _conversation_store.create(payload)
    return ApiEnvelope(success=True, data=record, requestId=_request_id(request))


@router.get("/chat/sessions", response_model=ApiEnvelope[SessionListResponse])
def list_sessions(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    scene: SceneName | None = Query(default=None),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
) -> ApiEnvelope[SessionListResponse]:
    items, total = _conversation_store.list(
        page=page,
        page_size=page_size,
        scene=scene,
        status=status,
        keyword=keyword,
    )
    return ApiEnvelope(
        success=True,
        data=SessionListResponse(items=items, total=total, page=page, page_size=page_size),
        requestId=_request_id(request),
    )


@router.get("/chat/sessions/{conversation_id}", response_model=ApiEnvelope[ConversationRecord])
def get_session(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[ConversationRecord]:
    conversation = _require_conversation(conversation_id)
    return ApiEnvelope(success=True, data=conversation, requestId=_request_id(request))


@router.get("/chat/sessions/{conversation_id}/messages", response_model=ApiEnvelope[SessionMessagesPage])
def list_session_messages(
    conversation_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiEnvelope[SessionMessagesPage]:
    try:
        page = _conversation_store.list_messages(conversation_id, cursor=cursor, page_size=page_size)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    return ApiEnvelope(success=True, data=page, requestId=_request_id(request))


@router.get("/chat/sessions/{conversation_id}/messages/{message_id}/events", response_model=ApiEnvelope[StreamEventPage])
def list_message_stream_events(
    conversation_id: str,
    message_id: str,
    request: Request,
    after_event_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiEnvelope[StreamEventPage]:
    resolved_message_id = _conversation_message_id(conversation_id, message_id)
    page = _sse_event_store.get_page(
        conversation_id,
        resolved_message_id,
        after_event_id=after_event_id,
        limit=limit,
    )
    if page is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="CHAT_STREAM_EVENTS_NOT_FOUND",
                message=(
                    f"No stored stream events were found for message '{message_id}' in "
                    f"conversation '{conversation_id}'."
                ),
            ).model_dump(),
        )
    return ApiEnvelope(success=True, data=page, requestId=_request_id(request))


@router.get("/chat/sessions/{conversation_id}/messages/{message_id}/events/stream")
def replay_message_stream_events(
    conversation_id: str,
    message_id: str,
    request: Request,
    after_event_id: str | None = Query(default=None),
) -> StreamingResponse:
    resolved_message_id = _conversation_message_id(conversation_id, message_id)
    effective_after_event_id = after_event_id or request.headers.get("Last-Event-ID")
    page = _sse_event_store.get_page(
        conversation_id,
        resolved_message_id,
        after_event_id=effective_after_event_id,
        limit=500,
    )
    if page is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="CHAT_STREAM_EVENTS_NOT_FOUND",
                message=(
                    f"No stored stream events were found for message '{message_id}' in "
                    f"conversation '{conversation_id}'."
                ),
            ).model_dump(),
        )
    return StreamingResponse(
        iter_sse_events(page.items),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chat/sessions/{conversation_id}/agent-routes", response_model=ApiEnvelope[list[AgentRouteRecord]])
def list_session_agent_routes(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[list[AgentRouteRecord]]:
    snapshot = _state_store.get(conversation_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="ORCH_SESSION_STATE_NOT_FOUND",
                message=f"No orchestration state found for conversation '{conversation_id}'.",
            ).model_dump(),
        )
    return ApiEnvelope(success=True, data=snapshot.agent_routes, requestId=_request_id(request))


@router.patch("/chat/sessions/{conversation_id}", response_model=ApiEnvelope[ConversationRecord])
def update_session(
    conversation_id: str,
    payload: SessionUpdateRequest,
    request: Request,
) -> ApiEnvelope[ConversationRecord]:
    try:
        conversation = _conversation_store.update_title(conversation_id, payload.title)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    return ApiEnvelope(success=True, data=conversation, requestId=_request_id(request))


@router.post("/chat/sessions/{conversation_id}/archive", response_model=ApiEnvelope[ConversationRecord])
def archive_session(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[ConversationRecord]:
    try:
        conversation = _conversation_store.archive(conversation_id)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    return ApiEnvelope(success=True, data=conversation, requestId=_request_id(request))


@router.post("/chat/sessions/{conversation_id}/restore", response_model=ApiEnvelope[ConversationRecord])
def restore_session(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[ConversationRecord]:
    try:
        conversation = _conversation_store.restore(conversation_id)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    return ApiEnvelope(success=True, data=conversation, requestId=_request_id(request))


@router.delete("/chat/sessions/{conversation_id}", response_model=ApiEnvelope[SessionDeleteResponse])
def delete_session(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[SessionDeleteResponse]:
    try:
        deleted = _conversation_store.delete(conversation_id)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    return ApiEnvelope(
        success=True,
        data=SessionDeleteResponse(conversation_id=deleted.conversation_id),
        requestId=_request_id(request),
    )


@router.post("/chat/sessions/{conversation_id}/retry", response_model=ApiEnvelope[ChatCompletionResponse])
def retry_session_message(
    conversation_id: str,
    payload: SessionRetryRequest,
    request: Request,
) -> ApiEnvelope[ChatCompletionResponse]:
    try:
        replay_request = _conversation_store.build_retry_request(
            conversation_id,
            message_id=payload.message_id,
            override_input=payload.override_input,
        )
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    trace = _build_trace_context(request, conversation_id, replay_request.trace, default_request_id=None)
    response, status, message_id = _execute_message(
        conversation_id,
        replay_request,
        trace,
        strict_session=True,
    )
    return ApiEnvelope(
        success=True,
        data=_build_chat_completion_response(conversation_id, message_id, status, response),
        requestId=trace.request_id,
    )


@router.post("/chat/sessions/{conversation_id}/continue", response_model=ApiEnvelope[ChatCompletionResponse])
def continue_session(
    conversation_id: str,
    payload: SessionContinueRequest,
    request: Request,
) -> ApiEnvelope[ChatCompletionResponse]:
    _require_conversation(conversation_id)
    snapshot = _state_store.get(conversation_id)
    if snapshot is None or not snapshot.pending_actions:
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_CONTINUATION_NOT_AVAILABLE",
                message=f"Conversation '{conversation_id}' has no pending continuation state.",
            ).model_dump(),
        )
    source_message_id = payload.message_id or _conversation_store.latest_message_id(
        conversation_id,
        role="assistant",
    )
    try:
        replay_request = _conversation_store.build_retry_request(
            conversation_id,
            message_id=source_message_id,
            override_input=payload.user_input,
        )
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)

    continuation_request = _build_continue_request(replay_request, payload)
    trace = _build_trace_context(
        request,
        conversation_id,
        default_request_id=f"continue-{conversation_id}",
    )
    response, status, message_id = _execute_message(
        conversation_id,
        continuation_request,
        trace,
        strict_session=True,
    )
    return ApiEnvelope(
        success=True,
        data=_build_chat_completion_response(conversation_id, message_id, status, response),
        requestId=trace.request_id,
    )


@router.post("/chat/sessions/{conversation_id}/cancel", response_model=ApiEnvelope[SessionCancelResponse])
def cancel_session_message(
    conversation_id: str,
    payload: SessionCancelRequest,
    request: Request,
) -> ApiEnvelope[SessionCancelResponse]:
    _require_conversation(conversation_id)
    if not _run_control.cancel(conversation_id, payload.message_id):
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_MESSAGE_NOT_RUNNING",
                message=(
                    f"Message '{payload.message_id}' is not currently running in conversation "
                    f"'{conversation_id}'."
                ),
            ).model_dump(),
        )
    return ApiEnvelope(
        success=True,
        data=SessionCancelResponse(
            conversation_id=conversation_id,
            message_id=payload.message_id,
        ),
        requestId=_request_id(request),
    )


@router.post("/chat/completions")
def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
):
    conversation = _require_conversation(payload.conversation_id)
    trace = _build_trace_context(request, payload.conversation_id, payload.trace, default_request_id=payload.message_id)
    message_request = _build_message_request_from_chat_completion(payload, conversation.scene, trace)
    response, status, message_id = _execute_message(
        payload.conversation_id,
        message_request,
        trace,
        strict_session=True,
    )
    if payload.stream:
        return _streaming_response_for_message(
            payload.conversation_id,
            message_id,
        )
    return ApiEnvelope(
        success=True,
        data=_build_chat_completion_response(payload.conversation_id, message_id, status, response),
        requestId=trace.request_id,
    )


@router.post("/sessions/{conversation_id}/messages", response_model=ApiEnvelope[OrchestratorResponse])
def orchestrate_message(
    conversation_id: str,
    payload: MessageRequest,
    request: Request,
) -> ApiEnvelope[OrchestratorResponse]:
    trace = _build_trace_context(request, conversation_id, payload.trace, default_request_id=payload.message_id)
    response, _, _ = _execute_message(
        conversation_id,
        payload,
        trace,
        strict_session=False,
    )
    return ApiEnvelope(success=True, data=response, requestId=trace.request_id)


@router.post("/sessions/{conversation_id}/messages/stream")
def orchestrate_message_stream(
    conversation_id: str,
    payload: MessageRequest,
    request: Request,
) -> StreamingResponse:
    trace = _build_trace_context(request, conversation_id, payload.trace, default_request_id=payload.message_id)
    response, _, message_id = _execute_message(
        conversation_id,
        payload,
        trace,
        strict_session=False,
    )
    return _streaming_response_for_message(conversation_id, message_id)


@router.get("/sessions/{conversation_id}/state", response_model=ApiEnvelope[SessionStateSnapshot])
def get_session_state(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[SessionStateSnapshot]:
    snapshot = _state_store.get(conversation_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="ORCH_SESSION_STATE_NOT_FOUND",
                message=f"No orchestration state found for conversation '{conversation_id}'.",
            ).model_dump(),
        )
    return ApiEnvelope(success=True, data=snapshot, requestId=_request_id(request))


@router.post("/sessions/{conversation_id}/rollback", response_model=ApiEnvelope[SessionRollbackResponse])
def rollback_session(
    conversation_id: str,
    request: Request,
) -> ApiEnvelope[SessionRollbackResponse]:
    snapshot = _state_store.get(conversation_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="ORCH_SESSION_STATE_NOT_FOUND",
                message=f"No orchestration state found for conversation '{conversation_id}'.",
            ).model_dump(),
        )
    trace = _build_trace_context(request, conversation_id, snapshot.trace, default_request_id=f"rollback-{conversation_id}")
    response = _rollback_session_state(snapshot, trace)
    return ApiEnvelope(success=True, data=response, requestId=trace.request_id)


@internal_router.post("/orchestrator/chat", response_model=InternalChatResponse)
def internal_orchestrator_chat(
    payload: InternalChatRequest,
    request: Request,
) -> InternalChatResponse:
    _validate_internal_caller(request.headers.get(_settings.caller_service_header))
    user_profile = UserProfile(
        user_id=payload.user.user_id,
        roles=payload.user.roles,
        permissions=payload.user.permissions,
        account_id=payload.user.account_id,
        tenant_id=payload.user.tenant_id,
    )
    trace = TraceContext(
        requestId=payload.request_id,
        conversationId=payload.chat_request.conversation_id,
        traceId=payload.trace_id,
    )
    message_request = MessageRequest(
        user_query=payload.chat_request.user_input,
        message_id=payload.chat_request.message_id,
        scene=payload.chat_request.scene,
        user_profile=user_profile,
        session_context=payload.chat_request.session_context,
        attachments=payload.chat_request.attachments,
        tool_candidates=payload.chat_request.tool_candidates,
        constraints=RuntimeConstraints(),
        trace=trace,
    )
    orchestrator_response, status, message_id = _execute_message(
        payload.chat_request.conversation_id,
        message_request,
        trace,
        strict_session=False,
    )
    final_execution = orchestrator_response.executions[-1] if orchestrator_response.executions else None
    return InternalChatResponse(
        conversation_id=payload.chat_request.conversation_id,
        message_id=message_id,
        status=status,
        agent_name=orchestrator_response.route.primary_agent,
        route=orchestrator_response.route,
        executions=orchestrator_response.executions,
        final_answer=orchestrator_response.final_response_summary or orchestrator_response.route.summary,
        citations=list(
            dict.fromkeys(
                citation
                for execution in orchestrator_response.executions
                for citation in execution.citations
            )
        ),
        tool_calls=[tool_call for execution in orchestrator_response.executions for tool_call in execution.tool_calls],
        next_agent=final_execution.next_agent if final_execution else None,
        pending_actions=orchestrator_response.pending_actions,
        pending_user_actions=orchestrator_response.pending_user_actions,
        state_snapshot=orchestrator_response.state_snapshot,
        review=orchestrator_response.review,
        trace=trace,
    )


def _build_message_request_from_chat_completion(
    payload: ChatCompletionRequest,
    default_scene: SceneName,
    trace: TraceContext,
) -> MessageRequest:
    context = payload.context if isinstance(payload.context, dict) else {}
    options = payload.options if isinstance(payload.options, dict) else {}
    context_control = payload.context_control if isinstance(payload.context_control, dict) else {}
    user_profile = payload.user_profile.model_copy(deep=True)
    if context.get("user_id") and not user_profile.user_id:
        user_profile.user_id = str(context["user_id"])
    if context.get("account_id") and not user_profile.account_id:
        user_profile.account_id = str(context["account_id"])
    if context.get("tenant_id"):
        user_profile.tenant_id = str(context["tenant_id"])
    if context.get("locale"):
        user_profile.locale = str(context["locale"])
    if context.get("channel"):
        user_profile.channel = str(context["channel"])
    roles = context.get("roles")
    if isinstance(roles, list) and roles and user_profile.roles == ["user"]:
        user_profile.roles = [str(role) for role in roles if str(role).strip()]
    permissions = context.get("permissions")
    if isinstance(permissions, list) and permissions and not user_profile.permissions:
        user_profile.permissions = [str(permission) for permission in permissions if str(permission).strip()]

    constraints = payload.constraints.model_copy(deep=True)
    if _coerce_bool(context_control.get("must_cite")) is True:
        constraints.must_cite = True
    if _coerce_bool(options.get("use_tools")) is False:
        constraints.max_tool_calls = 0

    session_context = payload.session_context.model_copy(deep=True)
    use_history = _coerce_bool(context_control.get("use_history"), default=True)
    history_limit = _coerce_positive_int(
        context_control.get("history_limit") or options.get("max_history_turns")
    )
    if not use_history:
        session_context.history_summary = None
        session_context.recent_messages = []
    elif history_limit is not None:
        session_context.recent_messages = session_context.recent_messages[-history_limit:]

    preferred_agents = _preferred_agents_from_hint(options.get("agent_hint"))
    tool_candidates = _merge_tool_candidates(
        payload.tool_candidates,
        _tool_candidates_from_option(options.get("tool_candidates")),
        _tool_candidates_from_option(options.get("tool_names")),
    )
    retrieval_required = _coerce_bool(options.get("use_rag")) if "use_rag" in options else None

    return MessageRequest(
        user_query=payload.user_input,
        message_id=payload.message_id,
        scene=payload.scene or default_scene,
        user_profile=user_profile,
        session_context=session_context,
        attachments=payload.attachments,
        tool_candidates=tool_candidates,
        constraints=constraints,
        retrieval_required=retrieval_required,
        preferred_agents=preferred_agents,
        use_history=use_history,
        history_limit=history_limit,
        client_meta=payload.client_meta if isinstance(payload.client_meta, dict) else {},
        trace=trace,
    )


def _build_continue_request(
    base_request: MessageRequest,
    payload: SessionContinueRequest,
) -> MessageRequest:
    session_context = base_request.session_context.model_copy(deep=True)
    if payload.session_context_patch:
        ConversationStore._apply_session_context_patch(
            session_context,
            payload.session_context_patch,
        )
    if payload.confirm_tool_names:
        session_context.confirmed_tool_names = list(
            dict.fromkeys(
                [*session_context.confirmed_tool_names, *payload.confirm_tool_names]
            )
        )
    _apply_continuation_field_values(session_context, payload.field_values)
    user_profile = _apply_user_profile_patch(
        base_request.user_profile,
        payload.user_profile_patch,
    )
    return base_request.model_copy(
        deep=True,
        update={
            "session_context": session_context,
            "user_profile": user_profile,
            "message_id": None,
            "trace": None,
        },
    )


def _apply_continuation_field_values(
    session_context: SessionContext,
    field_values: dict[str, object],
) -> None:
    for field, value in field_values.items():
        if not field:
            continue
        applied = False
        if "." in field or field in SessionContext.model_fields:
            applied = write_session_context_key(session_context, field, value)
        if applied:
            continue
        for tool in _tool_catalog.values():
            applied = apply_tool_input_bindings(
                session_context,
                tool.definition,
                field,
                value,
            ) or applied
        if applied:
            continue
        write_session_context_key(session_context, f"attributes.{field}", value)


def _normalize_effective_session_context(
    conversation_id: str,
    message_request: MessageRequest,
) -> SessionContext:
    if message_request.use_history:
        session_context = _conversation_store.compose_context(
            conversation_id,
            message_request.session_context,
        )
    else:
        session_context = message_request.session_context.model_copy(deep=True)
    if message_request.history_limit is not None and message_request.history_limit > 0:
        session_context.recent_messages = session_context.recent_messages[-message_request.history_limit :]
    return session_context


def _build_chat_completion_response(
    conversation_id: str,
    message_id: str,
    status: str,
    response: OrchestratorResponse,
) -> ChatCompletionResponse:
    tool_calls = [tool_call for execution in response.executions for tool_call in execution.tool_calls]
    citations = _collect_citations(response)
    answer = response.final_response_summary or response.route.summary
    return ChatCompletionResponse(
        conversation_id=conversation_id,
        message_id=message_id,
        status=status,
        answer=answer,
        citations=citations,
        tool_calls=tool_calls,
        pending_user_actions=response.pending_user_actions,
        usage=ChatUsage(),
        finish_reason=_finish_reason(response.next_action),
        response=response,
    )


def _streaming_response_for_message(
    conversation_id: str,
    message_id: str,
) -> StreamingResponse:
    page = _sse_event_store.get_page(conversation_id, message_id, limit=500)
    if page is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(
                code="CHAT_STREAM_EVENTS_NOT_FOUND",
                message=(
                    f"No stored stream events were found for message '{message_id}' in "
                    f"conversation '{conversation_id}'."
                ),
            ).model_dump(),
        )
    return StreamingResponse(
        iter_sse_events(page.items),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _collect_citations(response: OrchestratorResponse) -> list[str]:
    return list(
        dict.fromkeys(
            citation
            for execution in response.executions
            for citation in execution.citations
        )
    )


def _preferred_agents_from_hint(agent_hint: object) -> list[str]:
    if not agent_hint:
        return []
    normalized = str(agent_hint).strip().lower().replace("-", "_")
    mapping = {
        "product_tech_agent": "product_tech_agent",
        "product_tech": "product_tech_agent",
        "producttechagent": "product_tech_agent",
        "finance_order_agent": "finance_order_agent",
        "finance_order": "finance_order_agent",
        "financeorderagent": "finance_order_agent",
        "icp_service_agent": "icp_service_agent",
        "icp_service": "icp_service_agent",
        "icpserviceagent": "icp_service_agent",
        "ops_marketing_agent": "ops_marketing_agent",
        "ops_marketing": "ops_marketing_agent",
        "opsmarketingagent": "ops_marketing_agent",
        "deep_research_agent": "deep_research_agent",
        "deep_research": "deep_research_agent",
        "deepresearchagent": "deep_research_agent",
    }
    collapsed = normalized.replace(" ", "").replace("_", "")
    resolved = mapping.get(normalized) or mapping.get(collapsed)
    return [resolved] if resolved else []


def _tool_candidates_from_option(raw_value: object) -> list[str]:
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    return []


def _merge_tool_candidates(*candidate_lists: list[str]) -> list[str]:
    merged: list[str] = []
    for candidate_list in candidate_lists:
        for tool_name in candidate_list:
            normalized = str(tool_name).strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged


def _coerce_positive_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _coerce_bool(value: object, *, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _conversation_message_id(conversation_id: str, message_id: str) -> str:
    try:
        return _conversation_store.resolve_request_message_id(conversation_id, message_id)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
        return message_id


def _persist_stream_events(
    conversation_id: str,
    message_id: str,
    request: MessageRequest,
    response: OrchestratorResponse,
    trace: TraceContext,
) -> None:
    records = build_sse_event_records(
        conversation_id=conversation_id,
        message_id=message_id,
        user_query=request.user_query,
        response=response,
        trace=trace,
    )
    _sse_event_store.save(conversation_id, message_id, records)



def _execute_message(
    conversation_id: str,
    message_request: MessageRequest,
    trace: TraceContext,
    *,
    strict_session: bool,
) -> tuple[OrchestratorResponse, str, str]:
    message_id = message_request.message_id or _conversation_store.new_message_id()
    effective_request = message_request.model_copy(deep=True, update={"message_id": message_id, "trace": trace})
    if strict_session:
        conversation = _require_conversation(conversation_id)
        scene = effective_request.scene or conversation.scene
        title = conversation.title
        initial_context = conversation.initial_context
    else:
        scene = effective_request.scene
        title = ConversationStore.derive_title(effective_request.user_query)
        initial_context = effective_request.session_context
    try:
        _run_control.start(conversation_id, message_id)
    except ActiveRunConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_CONVERSATION_RUNNING",
                message=(
                    f"Conversation '{conversation_id}' is already processing message "
                    f"'{exc.message_id}'."
                ),
            ).model_dump(),
        ) from exc
    try:
        _conversation_store.mark_running(
            conversation_id,
            scene=scene,
            title=title,
            initial_context=initial_context,
        )
    except ConversationStoreError as exc:
        _run_control.finish(conversation_id, message_id)
        _raise_conversation_error(exc)
    effective_request = effective_request.model_copy(
        deep=True,
        update={
            "session_context": _normalize_effective_session_context(
                conversation_id,
                effective_request,
            ),
        },
    )
    effective_request = effective_request.model_copy(
        deep=True,
        update={
            "user_profile": _hydrate_user_profile_from_session_context(
                effective_request.user_profile,
                effective_request.session_context,
            )
        },
    )

    try:
        response = _run_orchestration(
            RouteRequest(
                user_query=effective_request.user_query,
                conversation_id=conversation_id,
                scene=scene,
                user_profile=effective_request.user_profile,
                session_context=effective_request.session_context,
                retrieval_required=effective_request.retrieval_required,
                tool_candidates=effective_request.tool_candidates,
                preferred_agents=effective_request.preferred_agents,
                constraints=effective_request.constraints,
            ),
            effective_request,
            trace,
            cancel_check=lambda: _run_control.ensure_not_cancelled(conversation_id, message_id),
        )
    except OrchestrationCancelled as exc:
        _persist_cancelled_message(
            conversation_id=conversation_id,
            message_id=exc.message_id,
            request=effective_request,
            trace=trace,
        )
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_MESSAGE_CANCELLED",
                message=(
                    f"Message '{exc.message_id}' in conversation '{conversation_id}' was cancelled."
                ),
            ).model_dump(),
        ) from exc
    except Exception:
        try:
            _conversation_store.activate(conversation_id)
        except ConversationStoreError:
            pass
        raise
    finally:
        _run_control.finish(conversation_id, message_id)
    status = _resolve_overall_status(response.executions, response.route.needs_human_handoff)
    assistant_message_id = _conversation_store.assistant_message_id(message_id)
    try:
        _conversation_store.store_exchange(
            conversation_id=conversation_id,
            user_message_id=message_id,
            assistant_message_id=assistant_message_id,
            message_request=effective_request,
            response=response,
            status=_message_status_for(status),
            session_context=response.state_snapshot.session_context if response.state_snapshot else None,
            trace=trace,
        )
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)
    _persist_stream_events(
        conversation_id,
        message_id,
        effective_request,
        response,
        trace,
    )
    return response, status, message_id



def _run_orchestration(
    route_request: RouteRequest,
    message_request: MessageRequest,
    trace: TraceContext,
    cancel_check=None,
) -> OrchestratorResponse:
    route = _router.route(route_request)
    executions = _runtime.execute(route, message_request, trace, cancel_check=cancel_check)
    pending_actions = [
        execution.action_required
        for execution in executions
        if execution.action_required is not None
    ]
    pending_actions = list(dict.fromkeys(pending_actions))
    pending_user_actions = _collect_pending_user_actions(executions)
    final_summary = "；".join(execution.final_answer for execution in executions if execution.final_answer) or route.summary
    review = _reviewer.review(route, executions, final_summary)
    next_action = _resolve_next_action(executions, route.needs_human_handoff, review)
    if review.requires_escalation and next_action == "retry-or-escalate":
        pending_actions = list(dict.fromkeys([*pending_actions, "review-response"]))
    next_session_context = ConversationStore.derive_next_session_context(
        message_request.session_context,
        message_request,
        OrchestratorResponse(
            conversation_id=route_request.conversation_id,
            route=route,
            executions=executions,
            next_action=next_action,
            final_response_summary=final_summary,
            pending_actions=pending_actions,
            pending_user_actions=pending_user_actions,
            review=review,
            trace=trace,
        ),
        max_recent_messages=_conversation_store.max_recent_messages,
    )
    _persist_user_profile_into_session_context(next_session_context, message_request.user_profile)
    state_snapshot = _state_store.save(
        _build_state_snapshot(
            route_request.conversation_id,
            route,
            executions,
            pending_actions,
            pending_user_actions,
            final_summary,
            next_session_context,
            review,
            trace,
        )
    )
    return OrchestratorResponse(
        conversation_id=route_request.conversation_id,
        route=route,
        executions=executions,
        next_action=next_action,
        final_response_summary=final_summary,
        pending_actions=pending_actions,
        pending_user_actions=pending_user_actions,
        state_snapshot=state_snapshot,
        review=review,
        trace=trace,
    )



def _resolve_overall_status(
    executions: list[AgentExecutionResult],
    needs_human_handoff: bool,
) -> str:
    if not executions:
        return "handoff" if needs_human_handoff else "success"
    statuses = [execution.status for execution in executions]
    if "failed" in statuses:
        return "failed"
    if "need_user_input" in statuses:
        return "need_user_input"
    if needs_human_handoff:
        return "handoff"
    if executions[-1].status == "handoff":
        return "handoff"
    return "success"



def _resolve_next_action(
    executions: list[AgentExecutionResult],
    needs_human_handoff: bool,
    review: ResponseReview | None = None,
) -> str:
    overall_status = _resolve_overall_status(executions, needs_human_handoff)
    if overall_status == "need_user_input":
        return "collect-user-input"
    if overall_status == "failed":
        return "retry-or-escalate"
    if overall_status == "handoff" and needs_human_handoff:
        return "handoff-to-human"
    if review is not None and review.requires_escalation:
        return "retry-or-escalate"
    if overall_status == "handoff":
        return "continue-agent-handoff"
    return "respond-with-agent-summary"



def _build_state_snapshot(
    conversation_id: str,
    route: RouteDecision,
    executions: list[AgentExecutionResult],
    pending_actions: list[str],
    pending_user_actions: list[PendingUserAction],
    final_summary: str,
    session_context: SessionContext,
    review: ResponseReview | None,
    trace: TraceContext,
) -> SessionStateSnapshot:
    checkpoints = _materialize_checkpoints(route.checkpoints, executions, route.needs_human_handoff, review)
    agent_routes = _build_agent_route_records(route, executions)
    tool_results = [tool_call for execution in executions for tool_call in execution.tool_calls]
    tool_context = _build_tool_context(tool_results)
    compensation_stack = _build_compensation_stack(conversation_id, tool_results)
    events = _build_execution_events(route, executions, checkpoints, compensation_stack, final_summary, review)
    current_agent = _resolve_current_agent(route, executions)
    return SessionStateSnapshot(
        conversation_id=conversation_id,
        primary_agent=route.primary_agent,
        current_agent=current_agent,
        session_context=session_context,
        agent_routes=agent_routes,
        checkpoints=checkpoints,
        tool_results=tool_results,
        tool_context=tool_context,
        compensation_stack=compensation_stack,
        events=events,
        pending_actions=pending_actions,
        pending_user_actions=pending_user_actions,
        final_response_summary=final_summary,
        review=review,
        trace=trace,
    )


def _collect_pending_user_actions(
    executions: list[AgentExecutionResult],
) -> list[PendingUserAction]:
    actions: list[PendingUserAction] = []
    seen: set[tuple[str, str, str]] = set()
    for execution in executions:
        for tool_call in execution.tool_calls:
            hint = tool_call.user_action_hint
            if hint is None:
                continue
            key = (tool_call.tool_call_id, tool_call.tool_name, hint.action)
            if key in seen:
                continue
            seen.add(key)
            actions.append(
                PendingUserAction(
                    tool_name=tool_call.tool_name,
                    tool_call_id=tool_call.tool_call_id,
                    agent=execution.agent,
                    action=hint.action,
                    message=hint.message,
                    missing_fields=list(hint.missing_fields),
                    missing_payload_hints=dict(hint.missing_payload_hints),
                    missing_auth_context=list(hint.missing_auth_context),
                    required_permissions=list(hint.required_permissions),
                    requires_account_context=hint.requires_account_context,
                    confirmation_required=hint.confirmation_required,
                    session_context_bindings={
                        field: list(bindings)
                        for field, bindings in hint.session_context_bindings.items()
                    },
                    user_profile_bindings={
                        field: list(bindings)
                        for field, bindings in hint.user_profile_bindings.items()
                    },
                    confirm_tool_names=list(hint.confirm_tool_names),
                )
            )
    return actions


def _hydrate_user_profile_from_session_context(
    user_profile: UserProfile,
    session_context: SessionContext,
) -> UserProfile:
    auth_profile = session_context.attributes.get(_AUTH_PROFILE_ATTRIBUTE_KEY)
    if not isinstance(auth_profile, dict):
        return user_profile

    hydrated = user_profile.model_copy(deep=True)
    if not hydrated.user_id and auth_profile.get("user_id"):
        hydrated.user_id = str(auth_profile["user_id"])
    if not hydrated.account_id and auth_profile.get("account_id"):
        hydrated.account_id = str(auth_profile["account_id"])
    if hydrated.tenant_id == "default" and auth_profile.get("tenant_id"):
        hydrated.tenant_id = str(auth_profile["tenant_id"])
    if hydrated.locale == "zh-CN" and auth_profile.get("locale"):
        hydrated.locale = str(auth_profile["locale"])
    if hydrated.channel == "web" and auth_profile.get("channel"):
        hydrated.channel = str(auth_profile["channel"])
    if hydrated.vip_level == "normal" and auth_profile.get("vip_level"):
        hydrated.vip_level = str(auth_profile["vip_level"])

    roles = auth_profile.get("roles")
    if hydrated.roles == ["user"] and isinstance(roles, list) and roles:
        hydrated.roles = _dedupe_profile_list(roles)

    permissions = auth_profile.get("permissions")
    if not hydrated.permissions and isinstance(permissions, list) and permissions:
        hydrated.permissions = _dedupe_profile_list(permissions)

    return hydrated


def _apply_user_profile_patch(
    base_profile: UserProfile,
    patch,
) -> UserProfile:
    updated = base_profile.model_copy(deep=True)
    values = patch.model_dump(exclude_none=True)
    if "user_id" in values:
        updated.user_id = str(values["user_id"])
    if "account_id" in values:
        updated.account_id = str(values["account_id"])
    if "tenant_id" in values:
        updated.tenant_id = str(values["tenant_id"])
    if "locale" in values:
        updated.locale = str(values["locale"])
    if "channel" in values:
        updated.channel = str(values["channel"])
    if "vip_level" in values:
        updated.vip_level = str(values["vip_level"])
    if "roles" in values and isinstance(values["roles"], list):
        updated.roles = _dedupe_profile_list([*updated.roles, *values["roles"]])
    if "permissions" in values and isinstance(values["permissions"], list):
        updated.permissions = _dedupe_profile_list([*updated.permissions, *values["permissions"]])
    return updated


def _persist_user_profile_into_session_context(
    session_context: SessionContext,
    user_profile: UserProfile,
) -> None:
    auth_profile = session_context.attributes.get(_AUTH_PROFILE_ATTRIBUTE_KEY)
    has_auth_values = bool(
        user_profile.user_id
        or user_profile.account_id
        or user_profile.permissions
        or user_profile.roles != ["user"]
        or isinstance(auth_profile, dict)
    )
    if not has_auth_values:
        return
    merged = dict(auth_profile) if isinstance(auth_profile, dict) else {}
    if user_profile.user_id:
        merged["user_id"] = user_profile.user_id
    if user_profile.account_id:
        merged["account_id"] = user_profile.account_id
    if user_profile.tenant_id:
        merged["tenant_id"] = user_profile.tenant_id
    if user_profile.locale:
        merged["locale"] = user_profile.locale
    if user_profile.channel:
        merged["channel"] = user_profile.channel
    if user_profile.vip_level:
        merged["vip_level"] = user_profile.vip_level
    if user_profile.roles:
        merged["roles"] = _dedupe_profile_list(user_profile.roles)
    if user_profile.permissions:
        merged["permissions"] = _dedupe_profile_list(user_profile.permissions)
    if merged:
        session_context.attributes[_AUTH_PROFILE_ATTRIBUTE_KEY] = merged


def _dedupe_profile_list(values: list[object]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped



def _materialize_checkpoints(
    planned_checkpoints: list[ExecutionCheckpoint],
    executions: list[AgentExecutionResult],
    needs_human_handoff: bool,
    review: ResponseReview | None,
) -> list[ExecutionCheckpoint]:
    tool_statuses = [tool_call.status for execution in executions for tool_call in execution.tool_calls]
    has_successful_tools = any(status in {"completed", "preview-ready"} for status in tool_statuses)
    needs_user_input = any(execution.status == "need_user_input" for execution in executions)
    checkpoints: list[ExecutionCheckpoint] = []
    for checkpoint in planned_checkpoints:
        status = checkpoint.status
        if checkpoint.name == "retrieve-context" and checkpoint.status == "planned":
            status = "completed"
        elif checkpoint.name == "invoke-tools" and checkpoint.status == "planned":
            status = "completed" if has_successful_tools else ("failed" if "failed" in tool_statuses else "pending")
        elif checkpoint.name == "collect-user-input" and checkpoint.status == "planned":
            status = "pending" if needs_user_input else "completed"
        elif checkpoint.name == "review-answer" and checkpoint.status == "planned":
            if review is None or review.status == "skipped":
                status = "skipped"
            else:
                status = "failed" if review.status == "blocked" else "completed"
        elif checkpoint.name == "human-review" and checkpoint.status == "planned":
            status = "pending" if needs_human_handoff else checkpoint.status
        checkpoints.append(
            ExecutionCheckpoint(name=checkpoint.name, description=checkpoint.description, status=status)
        )
    return checkpoints



def _build_compensation_stack(
    conversation_id: str,
    tool_results,
) -> list[SagaCompensationStep]:
    compensation_stack: list[SagaCompensationStep] = []
    for index, tool_call in enumerate(tool_results, start=1):
        if tool_call.status != "completed" or tool_call.compensation is None:
            continue
        compensation_stack.append(
            SagaCompensationStep(
                saga_id=f"saga-{conversation_id}",
                step_id=f"saga-step-{index}",
                tool_name=tool_call.tool_name,
                compensation=tool_call.compensation,
            )
        )
    return compensation_stack


def _build_tool_context(tool_results: list) -> list[ToolContextItem]:
    context_items: list[ToolContextItem] = []
    for tool_call in tool_results[-5:]:
        patch_keys = list(tool_call.session_context_patch.keys()) if tool_call.session_context_patch else []
        context_items.append(
            ToolContextItem(
                tool_name=tool_call.tool_name,
                tool_call_id=tool_call.tool_call_id,
                status=tool_call.status,
                summary=tool_call.summary,
                provider=tool_call.provider,
                data=_preview_payload(tool_call.payload),
                patch_keys=patch_keys,
            )
        )
    return context_items


def _build_execution_events(
    route: RouteDecision,
    executions: list[AgentExecutionResult],
    checkpoints: list[ExecutionCheckpoint],
    compensation_stack: list[SagaCompensationStep],
    final_summary: str,
    review: ResponseReview | None,
) -> list[ExecutionEvent]:
    events: list[ExecutionEvent] = [
        ExecutionEvent(
            sequence=1,
            event="route_selected",
            message=f"primary_agent={route.primary_agent}",
            agent=route.primary_agent,
            data={
                "supporting_agents": route.supporting_agents,
                "requires_retrieval": route.requires_retrieval,
                "requires_tools": route.requires_tools,
                "handoff_steps": [step.model_dump() for step in route.handoff_plan],
                "tool_plan": [
                    {
                        "tool_call_id": item.tool_call_id,
                        "tool_name": item.tool_name,
                        "assigned_agent": item.assigned_agent,
                        "operation": item.operation,
                        "tool_mode": item.tool_mode,
                        "timeout_ms": item.timeout_ms,
                        "idempotent": item.idempotent,
                        "cache_ttl_seconds": item.cache_ttl_seconds,
                        "readiness": item.readiness,
                        "depends_on_tool_call_ids": item.depends_on_tool_call_ids,
                        "missing_payload_fields": item.missing_payload_fields,
                        "deferred_payload_fields": item.deferred_payload_fields,
                        "session_context_input_keys": item.session_context_input_keys,
                        "session_context_output_keys": item.session_context_output_keys,
                    }
                    for item in route.tool_plan
                ],
            },
        )
    ]
    sequence = 2
    for checkpoint in checkpoints:
        events.append(
            ExecutionEvent(
                sequence=sequence,
                event="checkpoint_updated",
                message=f"{checkpoint.name} -> {checkpoint.status}",
                data={"checkpoint": checkpoint.name, "status": checkpoint.status},
            )
        )
        sequence += 1
    for execution in executions:
        for tool_call in execution.tool_calls:
            events.append(
                ExecutionEvent(
                    sequence=sequence,
                    event="tool_call",
                    message=f"{execution.agent} 调用 {tool_call.tool_name}",
                    agent=execution.agent,
                    tool_name=tool_call.tool_name,
                    data={"operation": tool_call.operation, "tool_call_id": tool_call.tool_call_id},
                )
            )
            sequence += 1
            events.append(
                ExecutionEvent(
                    sequence=sequence,
                    event="tool_result",
                    message=f"{tool_call.tool_name} -> {tool_call.status}",
                    agent=execution.agent,
                    tool_name=tool_call.tool_name,
                    data={"status": tool_call.status, "success": tool_call.success},
                )
            )
            sequence += 1
        events.append(
            ExecutionEvent(
                sequence=sequence,
                event="agent_result",
                message=f"{execution.agent} -> {execution.status}",
                agent=execution.agent,
                data={"next_agent": execution.next_agent, "action_required": execution.action_required},
            )
        )
        sequence += 1
    if review is not None:
        events.append(
            ExecutionEvent(
                sequence=sequence,
                event="review_result",
                message=f"response review -> {review.status}",
                data={
                    "status": review.status,
                    "requires_escalation": review.requires_escalation,
                    "issues": [issue.model_dump() for issue in review.issues],
                },
            )
        )
        sequence += 1
    events.append(
        ExecutionEvent(
            sequence=sequence,
            event="state_persisted",
            message="session state persisted",
            data={"compensation_steps": len(compensation_stack), "final_summary": final_summary},
        )
    )
    return events


def _build_agent_route_records(
    route: RouteDecision,
    executions: list[AgentExecutionResult],
) -> list[AgentRouteRecord]:
    records: list[AgentRouteRecord] = []
    blocked = False
    for index, step in enumerate(route.handoff_plan):
        execution = executions[index] if index < len(executions) else None
        if execution is not None:
            context_highlights = execution.handoff_payload.get("resolved_session_context", {})
            if not isinstance(context_highlights, dict):
                context_highlights = {}
            status = execution.status
            blocked = blocked or execution.status in {"need_user_input", "failed"}
            records.append(
                AgentRouteRecord(
                    step_id=step.step_id,
                    order=step.order,
                    agent=step.agent,
                    objective=step.objective,
                    status=status,
                    handoff_received_from=execution.handoff_received_from,
                    handoff_to=execution.next_agent,
                    handoff_reason=execution.handoff_reason,
                    action_required=execution.action_required,
                    tool_names=list(dict.fromkeys([*step.tool_names, *[tool.tool_name for tool in execution.tool_calls]])),
                    tool_call_ids=[tool.tool_call_id for tool in execution.tool_calls],
                    tool_statuses=[tool.status for tool in execution.tool_calls],
                    depends_on=list(step.depends_on),
                    depends_on_tool_call_ids=list(step.depends_on_tool_call_ids),
                    session_context_inputs=list(step.session_context_inputs),
                    session_context_outputs=list(step.session_context_outputs),
                    context_highlights=context_highlights,
                )
            )
            continue

        records.append(
            AgentRouteRecord(
                step_id=step.step_id,
                order=step.order,
                agent=step.agent,
                objective=step.objective,
                status="blocked" if blocked else "planned",
                tool_names=list(step.tool_names),
                depends_on=list(step.depends_on),
                depends_on_tool_call_ids=list(step.depends_on_tool_call_ids),
                session_context_inputs=list(step.session_context_inputs),
                session_context_outputs=list(step.session_context_outputs),
            )
        )
    return records


def _preview_payload(payload: dict) -> dict:
    if len(payload) <= 6:
        return dict(payload)
    keys = list(payload)[:6]
    return {key: payload[key] for key in keys}


def _rollback_session_state(
    snapshot: SessionStateSnapshot,
    trace: TraceContext,
) -> SessionRollbackResponse:
    rollback_steps = [step.model_copy(deep=True) for step in reversed(snapshot.compensation_stack) if step.status == "armed"]
    results = _runtime.tool_hub_client.execute_compensations(rollback_steps, trace)
    updated_snapshot = snapshot.model_copy(deep=True)
    step_by_id = {step.step_id: step for step in updated_snapshot.compensation_stack}
    next_sequence = max((event.sequence for event in updated_snapshot.events), default=0) + 1
    for result in results:
        if result.step_id in step_by_id:
            step_by_id[result.step_id].status = "completed" if result.success else "failed"
        updated_snapshot.events.append(
            ExecutionEvent(
                sequence=next_sequence,
                event="compensation_result",
                message=f"{result.action_name} -> {result.status}",
                tool_name=result.tool_name,
                data={
                    "step_id": result.step_id,
                    "action_name": result.action_name,
                    "status": result.status,
                    "success": result.success,
                    "provider": result.provider,
                },
            )
        )
        next_sequence += 1
    updated_snapshot.events.append(
        ExecutionEvent(
            sequence=next_sequence,
            event="state_persisted",
            message="session rollback state persisted",
            data={
                "rollback_steps": len(rollback_steps),
                "completed_steps": sum(1 for result in results if result.success),
            },
        )
    )
    updated_snapshot.trace = trace
    persisted_snapshot = _state_store.save(updated_snapshot)
    if not rollback_steps:
        status = "noop"
    elif results and all(result.success for result in results):
        status = "completed"
    elif any(result.success for result in results):
        status = "partial"
    else:
        status = "failed"
    return SessionRollbackResponse(
        conversation_id=snapshot.conversation_id,
        status=status,
        compensated_steps=results,
        state_snapshot=persisted_snapshot,
        trace=trace,
    )



def _resolve_current_agent(
    route: RouteDecision,
    executions: list[AgentExecutionResult],
) -> str:
    if not executions:
        return route.primary_agent
    last_execution = executions[-1]
    if last_execution.status == "handoff" and last_execution.next_agent:
        return last_execution.next_agent
    return last_execution.agent


def _persist_cancelled_message(
    *,
    conversation_id: str,
    message_id: str,
    request: MessageRequest,
    trace: TraceContext,
) -> None:
    route = _router.route(
        RouteRequest(
            user_query=request.user_query,
            conversation_id=conversation_id,
            scene=request.scene,
            user_profile=request.user_profile,
            session_context=request.session_context,
            retrieval_required=request.retrieval_required,
            tool_candidates=request.tool_candidates,
            preferred_agents=request.preferred_agents,
            constraints=request.constraints,
        )
    )
    cancelled_summary = "生成已取消。"
    snapshot = SessionStateSnapshot(
        conversation_id=conversation_id,
        primary_agent=route.primary_agent,
        current_agent=route.primary_agent,
        session_context=request.session_context.model_copy(deep=True),
        checkpoints=route.checkpoints,
        tool_results=[],
        tool_context=[],
        compensation_stack=[],
        events=_build_execution_events(route, [], route.checkpoints, [], cancelled_summary, None),
        pending_actions=[],
        final_response_summary=cancelled_summary,
        review=None,
        trace=trace,
    )
    _state_store.save(snapshot)
    try:
        _conversation_store.store_cancelled_exchange(
            conversation_id=conversation_id,
            user_message_id=message_id,
            assistant_message_id=_conversation_store.assistant_message_id(message_id),
            message_request=request,
            reason=cancelled_summary,
            session_context=request.session_context,
            trace=trace,
        )
    except ConversationStoreError:
        pass



def _request_id(request: Request) -> str | None:
    return request.headers.get(_settings.request_id_header)



def _build_trace_context(
    request: Request,
    conversation_id: str,
    explicit_trace: TraceContext | None = None,
    *,
    default_request_id: str | None,
) -> TraceContext:
    request_id = (
        (explicit_trace.request_id if explicit_trace else None)
        or request.headers.get(_settings.request_id_header)
        or default_request_id
    )
    trace_id = (
        (explicit_trace.trace_id if explicit_trace else None)
        or request.headers.get(_settings.trace_id_header)
        or request_id
    )
    effective_conversation_id = (
        (explicit_trace.conversation_id if explicit_trace else None)
        or request.headers.get(_settings.conversation_id_header)
        or conversation_id
    )
    return TraceContext(
        requestId=request_id,
        conversationId=effective_conversation_id,
        traceId=trace_id,
    )



def _message_status_for(status: str) -> str:
    return {
        "success": "completed",
        "handoff": "handoff",
        "need_user_input": "need_user_input",
        "failed": "failed",
    }.get(status, "completed")


def _finish_reason(next_action: str) -> str:
    return {
        "respond-with-agent-summary": "stop",
        "collect-user-input": "need_user_input",
        "continue-agent-handoff": "handoff",
        "handoff-to-human": "handoff",
        "retry-or-escalate": "error",
    }.get(next_action, next_action)



def _require_conversation(conversation_id: str) -> ConversationRecord:
    try:
        return _conversation_store.require(conversation_id)
    except ConversationStoreError as exc:
        _raise_conversation_error(exc)



def _raise_conversation_error(exc: ConversationStoreError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=ErrorInfo(code=exc.code, message=exc.message).model_dump(),
    ) from exc



def _validate_internal_caller(x_caller_service: str | None) -> None:
    if x_caller_service not in _settings.allowed_internal_callers:
        raise HTTPException(
            status_code=403,
            detail=ErrorInfo(
                code="ORCH_CALLER_FORBIDDEN",
                message="Internal caller is not allowed to access orchestrator chat.",
                details={"allowed_callers": _settings.allowed_internal_callers},
            ).model_dump(),
        )
