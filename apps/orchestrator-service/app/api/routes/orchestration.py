from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.models.common import ApiEnvelope, ErrorInfo, TraceContext
from app.models.orchestration import (
    AgentAdminListResponse,
    AgentConfigUpdateRequest,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ConversationRecord,
    ExecutionEvent,
    InternalChatRequest,
    MessageRequest,
    OrchestratorResponse,
    RouteDecision,
    RouteRequest,
    SessionCancelRequest,
    SessionCancelResponse,
    SessionContinueRequest,
    SessionCreateRequest,
    SessionDeleteResponse,
    SessionListResponse,
    SessionMessagesPage,
    SessionRetryRequest,
    SessionRollbackResponse,
    SessionStateSnapshot,
    StreamEventPage,
    UserProfile,
)
from app.services.agent_config_store import AgentConfigStore
from app.services.agent_runtime import AgentRuntime
from app.services.conversation_store import ConversationStore, ConversationStoreError
from app.services.rag_client import RagClient
from app.services.router import AgentRouter
from app.services.review import ResponseReviewService
from app.services.run_control import (
    ActiveRunConflictError,
    OrchestrationCancelled,
    OrchestrationRunControl,
    RunControlBackendUnavailableError,
)
from app.services.sse_event_store import SseEventStore
from app.services.state_store import OrchestrationStateStore
from app.services.streaming import iter_sse_events

from .orchestration_request_builder import (
    build_continue_user_input_request,
    hydrate_user_profile_from_auth_profile,
    merge_persisted_session_context,
    message_request_from_chat_completion,
    message_request_from_session_message,
    route_request_from_message_request,
)
from .orchestration_handoff import execute_handoff_resume as _execute_handoff_resume_impl
from .orchestration_response_builder import OrchestrationResponseBuilder
from .orchestration_utils import (
    build_trace_context,
    raise_conversation_error,
    require_allowed_internal_caller,
    resolve_next_action,
    response_message_status,
)


router = APIRouter(tags=["orchestration"])
internal_router = APIRouter(tags=["orchestration-internal"])

_settings = get_settings()
_conversation_store = ConversationStore(
    file_path=_settings.conversation_store_path,
    mysql_dsn=_settings.mysql_dsn,
    redis_url=_settings.redis_url,
    redis_namespace=getattr(_settings, "orchestrator_redis_namespace", "smartcloud:orchestrator"),
)
_agent_config_store = AgentConfigStore()
_state_store = OrchestrationStateStore()
_sse_event_store = SseEventStore()
_router = AgentRouter(agent_config_store=_agent_config_store)
_runtime = AgentRuntime(agent_config_store=_agent_config_store)
_review_service = ResponseReviewService()
_run_control = OrchestrationRunControl(
    redis_url=getattr(_settings, "redis_url", None),
    redis_namespace=getattr(_settings, "orchestrator_redis_namespace", "smartcloud:orchestrator"),
    strict_backend=bool(getattr(_settings, "run_control_strict", False)),
)
_response_builder = OrchestrationResponseBuilder(
    state_store=_state_store,
    conversation_store=_conversation_store,
    sse_event_store=_sse_event_store,
)
_rag_client = RagClient()

# --- Session memory store (Redis-backed) ---
_session_memory_store = None
try:
    from app.services.session_memory_store import SessionMemoryStore
    _session_memory_store = SessionMemoryStore(
        redis_url=_settings.redis_url,
        redis_namespace="smartcloud:orchestrator:session-memory",
        ttl_seconds=_settings.session_memory_store_ttl_seconds,
    )
except Exception:
    pass


# ----------------------------------------------------------------------
# Module-level logic functions
#
# These functions are intentionally defined at module scope (not inside a
# class) so that tests can monkeypatch individual services or these functions
# themselves via `monkeypatch.setattr(orchestration_routes, "_xxx", ...)`.
# Each function resolves `_runtime`, `_run_control`, etc. from module globals
# at call time, so a patched module attribute is always picked up.
# ----------------------------------------------------------------------


def _response_message_status(response: OrchestratorResponse) -> str:
    return response_message_status(response)


def _build_state_snapshot(conversation_id: str) -> SessionStateSnapshot | None:
    return _response_builder.get_state_snapshot(conversation_id)


def _cancel_check_for(conversation_id: str, message_id: str):
    def _check() -> None:
        _run_control.ensure_not_cancelled(conversation_id, message_id)
    return _check


def _trigger_session_memory_extraction(
    conversation_id: str,
    message_request: MessageRequest,
    response: OrchestratorResponse,
) -> None:
    """Fire-and-forget session memory extraction in a background thread."""
    if not _settings.session_memory_enabled:
        return
    if _session_memory_store is None:
        return

    try:
        import asyncio
        from app.services.session_memory import SessionMemoryExtractor
        from app.services.token_counter import TokenCounter

        counter = TokenCounter()
        extractor = SessionMemoryExtractor(
            settings=_settings,
            token_counter=counter,
        )

        # Build messages list from request/response for token estimation
        messages = [
            {"role": "user", "content": message_request.user_query},
        ]
        for ex in response.executions:
            if ex.reasoning_summary:
                messages.append({"role": "assistant", "content": f"[推理] {ex.reasoning_summary}"})
            for tc in ex.tool_calls:
                tc_summary = tc.summary or ""
                tc_payload = str(tc.payload)[:500] if tc.payload else ""
                messages.append({"role": "tool", "content": f"{tc.tool_name}: {tc_summary} {tc_payload}"})
            if ex.final_answer:
                messages.append({"role": "assistant", "content": ex.final_answer})

        existing = _session_memory_store.get(conversation_id)
        if not extractor.should_extract(existing, messages):
            return

        def _extract_and_store():
            try:
                record = extractor.extract_memory(conversation_id, messages, existing)
                if record is not None:
                    _session_memory_store.put(record)
                    logger.info("session memory extracted for %s (v%d)", conversation_id, record.version)
                    # Also calibrate token counter if LLM returned usage
            except Exception as exc:
                logger.warning("background session memory extraction failed: %s", exc)

        import threading
        thread = threading.Thread(target=_extract_and_store, daemon=True)
        thread.start()
    except Exception as exc:
        logger.warning("session memory extraction setup failed: %s", exc)


def _run_orchestration(
    route_request: RouteRequest,
    message_request: MessageRequest,
    trace: TraceContext | None,
    *,
    cancel_check=None,
) -> OrchestratorResponse:
    # L1 FAQ cache fast-path: if the query matches an FAQ entry, return
    # the cached answer directly — skip routing, tool calls, and RAG.
    faq_hit = _rag_client.faq_match(
        message_request.user_query,
        trace=trace,
        tenant_id=route_request.user_profile.tenant_id,
    )
    if faq_hit is not None:
        from app.models.orchestration import AgentExecutionResult, FaqMetadata, FaqDocumentRef, IntentSummary, RetrievalResult
        faq_answer = faq_hit.get("answer", "")
        token_saved = faq_hit.get("tokenSaved", 0)
        match_reason = faq_hit.get("matchReason", "faq_exact_match")

        # Build structured FAQ metadata for frontend rendering
        doc_refs = [
            FaqDocumentRef(docId=r["docId"], title=r["title"], url=r.get("url"))
            for r in (faq_hit.get("documentRefs") or [])
            if "docId" in r and "title" in r
        ]
        faq_metadata = FaqMetadata(
            category=faq_hit.get("category"),
            prerequisites=faq_hit.get("prerequisites") or [],
            documentRefs=doc_refs,
            relatedTopics=faq_hit.get("relatedTopics") or [],
            matchReason=match_reason,
            tokenSaved=token_saved,
        )

        faq_execution = AgentExecutionResult(
            agent="product_tech_agent",
            status="success",
            reasoning_summary=f"L1 FAQ 命中（{match_reason}），节省约 {token_saved} tokens",
            tool_calls=[],
            citations=[],
            confidence=0.95,
            final_answer=faq_answer,
            handoff_received_from=None,
            next_agent=None,
            action_required=None,
            risk_flags=[],
            trace_tags=["L1_FAQ_CACHE", "faq_exact_match"],
            handoff_reason=None,
            handoff_payload={},
            faq_metadata=faq_metadata,
        )
        faq_route = RouteDecision(
            primary_agent="product_tech_agent",
            supporting_agents=[],
            requires_retrieval=False,
            requires_tools=False,
            needs_human_handoff=False,
            intent=IntentSummary(domain="faq", scene="customer_service", urgency="low"),
            tasks=[],
            handoff_plan=[],
            tool_plan=[],
            checkpoints=[],
            summary=f"L1 FAQ 缓存命中: {message_request.user_query}",
        )
        response = OrchestratorResponse(
            conversation_id=route_request.conversation_id,
            route=faq_route,
            executions=[faq_execution],
            final_response_summary=faq_answer,
            next_action="respond-with-agent-summary",
            pending_actions=[],
            pending_user_actions=[],
            state_snapshot=None,
            review=None,
            trace=trace,
        )
        response.review = _review_service.review(faq_route, [faq_execution], faq_answer)
        return response

    # Retrieve session memory for compacted_history injection
    compacted_history: str | None = None
    if _settings.session_memory_enabled and _session_memory_store is not None:
        try:
            memory_record = _session_memory_store.get(route_request.conversation_id)
            if memory_record is not None and memory_record.sections:
                # Format session memory sections as compacted history text
                from app.services.session_memory import SessionMemoryExtractor
                extractor = SessionMemoryExtractor(settings=_settings)
                compacted_history = extractor._format_sections(memory_record.sections)
        except Exception:
            pass  # Non-critical; continue without compacted history

    route = _router.route(route_request)
    executions = _runtime.execute(
        route,
        message_request,
        trace,
        cancel_check=cancel_check,
        pause_on_agent_handoff=True,
        compacted_history=compacted_history,
    )
    final_summary = executions[-1].final_answer if executions else route.summary

    # Propagate compaction summary from runtime (if auto-compact happened)
    compaction_summary = getattr(_runtime, "_last_compact_summary", None)

    pending_agent_handoff = _response_builder.build_pending_agent_handoff(
        route,
        message_request,
        executions,
        source_user_message_id=message_request.message_id or f"msg_{uuid4().hex}",
    )
    response = OrchestratorResponse(
        conversation_id=route_request.conversation_id,
        route=route,
        executions=executions,
        final_response_summary=final_summary,
        next_action="respond-with-agent-summary",
        pending_actions=[],
        pending_user_actions=[],
        state_snapshot=(
            SessionStateSnapshot(
                conversation_id=route_request.conversation_id,
                primary_agent=route.primary_agent,
                current_agent=route.tasks[pending_agent_handoff.next_task_index].agent,
                session_context=pending_agent_handoff.request_snapshot.session_context.model_copy(deep=True),
                pending_agent_handoff=pending_agent_handoff,
            )
            if pending_agent_handoff is not None
            else None
        ),
        review=None,
        trace=trace,
        compaction_summary=compaction_summary,
    )
    next_action, pending_actions = resolve_next_action(response)
    response.next_action = next_action
    response.pending_actions = pending_actions
    response.pending_user_actions = _response_builder.build_pending_user_actions(response)
    response.review = _review_service.review(route, executions, final_summary or "")
    response.state_snapshot = _response_builder.build_response_state_snapshot(
        route_request.conversation_id, message_request, response, trace
    )
    return response


def _persist_exchange(
    *,
    conversation_id: str,
    user_message_id: str,
    assistant_message_id: str,
    message_request: MessageRequest,
    response: OrchestratorResponse,
    trace: TraceContext | None,
) -> tuple[ConversationRecord, list[Any]]:
    return _conversation_store.store_exchange(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        message_request=message_request,
        response=response,
        status=_response_message_status(response),
        session_context=(
            response.state_snapshot.session_context if response.state_snapshot else message_request.session_context
        ),
        trace=trace,
    )


def _persist_stream_events(
    *,
    conversation_id: str,
    assistant_message_id: str,
    message_request: MessageRequest,
    response: OrchestratorResponse,
    trace: TraceContext | None,
):
    return _response_builder.persist_stream_events(
        conversation_id=conversation_id,
        assistant_message_id=assistant_message_id,
        message_request=message_request,
        response=response,
        trace=trace,
    )


def _streaming_response_for_message(
    *,
    conversation_id: str,
    user_message_id: str,
    assistant_message_id: str,
    message_request: MessageRequest,
    response: OrchestratorResponse,
    trace: TraceContext | None,
) -> StreamingResponse:
    events = _persist_stream_events(
        conversation_id=conversation_id,
        assistant_message_id=assistant_message_id,
        message_request=message_request,
        response=response,
        trace=trace,
    )
    return StreamingResponse(iter_sse_events(events), media_type="text/event-stream")


def _execute_message(
    conversation_id: str,
    message_request: MessageRequest,
    trace: TraceContext | None,
    *,
    strict_session: bool = False,
) -> tuple[ConversationRecord, str, str, OrchestratorResponse]:
    conversation = _conversation_store.mark_running(conversation_id, scene=message_request.scene)
    message_id = message_request.message_id or f"msg_{uuid4().hex}"
    message_request.message_id = message_id
    if trace is not None:
        trace.conversation_id = conversation.conversation_id
        message_request.trace = trace

    # --- Compaction checkpoint: micro-compact recent messages before orchestration ---
    if _settings.micro_compact_enabled:
        from app.services.micro_compact import micro_compact_messages
        ctx = message_request.session_context
        if ctx and ctx.recent_messages:
            compacted_recent = micro_compact_messages(
                ctx.recent_messages,
                time_gap_minutes=_settings.micro_compact_time_gap_minutes,
                size_threshold_chars=_settings.micro_compact_size_threshold_chars,
            )
            ctx.recent_messages = compacted_recent

    route_request = route_request_from_message_request(conversation.conversation_id, message_request)
    assistant_message_id = f"asst_{message_id}"
    active_run = _run_control.start(conversation.conversation_id, message_id)
    try:
        response = _run_orchestration(
            route_request,
            message_request,
            trace,
            cancel_check=_cancel_check_for(conversation.conversation_id, message_id),
        )
        persisted_response = response.model_copy(deep=True)
        _persist_exchange(
            conversation_id=conversation.conversation_id,
            user_message_id=message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            response=persisted_response,
            trace=trace,
        )
        persisted_response.state_snapshot = _build_state_snapshot(conversation.conversation_id)

        # --- Background session memory extraction ---
        _trigger_session_memory_extraction(
            conversation_id=conversation.conversation_id,
            message_request=message_request,
            response=persisted_response,
        )

        return conversation, message_id, assistant_message_id, persisted_response
    except OrchestrationCancelled as exc:
        _conversation_store.store_cancelled_exchange(
            conversation_id=conversation.conversation_id,
            user_message_id=message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            reason="生成已取消。",
            trace=trace,
        )
        _response_builder.build_cancelled_state_snapshot(
            conversation.conversation_id, message_request, trace, summary="生成已取消。"
        )
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(code="CHAT_MESSAGE_CANCELLED", message=str(exc)).model_dump(),
        ) from exc
    except ActiveRunConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_MESSAGE_ALREADY_RUNNING",
                message=f"Conversation '{exc.conversation_id}' is already running message '{exc.message_id}'.",
            ).model_dump(),
        ) from exc
    finally:
        _run_control.finish(active_run.conversation_id, active_run.message_id)


def _execute_handoff_resume(
    conversation_id: str,
    snapshot: SessionStateSnapshot,
    payload: SessionContinueRequest,
    trace: TraceContext,
) -> tuple[OrchestratorResponse, str]:
    return _execute_handoff_resume_impl(
        conversation_id, snapshot, payload, trace,
        runtime=_runtime,
        run_control=_run_control,
        conversation_store=_conversation_store,
        review_service=_review_service,
        response_builder=_response_builder,
        cancel_check_for=_cancel_check_for,
    )


def _require_conversation(conversation_id: str | None) -> ConversationRecord:
    if not conversation_id:
        raise HTTPException(
            status_code=400,
            detail=ErrorInfo(code="CHAT_CONVERSATION_NOT_FOUND", message="Conversation id is required.").model_dump(),
        )
    try:
        return _conversation_store.require(conversation_id)
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


@internal_router.post("/orchestrator/chat")
def internal_chat(request: Request, payload: InternalChatRequest):
    require_allowed_internal_caller(request, _settings)
    conversation = _conversation_store.ensure(
        payload.chat_request.conversation_id, scene=payload.chat_request.scene
    )
    trace = build_trace_context(
        request,
        conversation.conversation_id,
        TraceContext(
            request_id=payload.request_id,
            trace_id=payload.trace_id,
            conversation_id=conversation.conversation_id,
        ),
    )
    message_request = MessageRequest(
        user_query=payload.chat_request.user_input,
        message_id=payload.chat_request.message_id,
        scene=payload.chat_request.scene,
        user_profile=UserProfile(
            user_id=payload.user.user_id,
            tenant_id=payload.user.tenant_id,
            roles=list(payload.user.roles),
            permissions=list(payload.user.permissions),
            account_id=payload.user.account_id,
        ),
        session_context=payload.chat_request.session_context,
        attachments=list(payload.chat_request.attachments),
        tool_candidates=list(payload.chat_request.tool_candidates),
        retrieval_required=payload.chat_request.retrieval_required,
        trace=trace,
    )
    # Merge persisted conversation history into the request context
    persisted_ctx = _conversation_store.get_context(conversation.conversation_id)
    if persisted_ctx is not None:
        message_request.session_context = merge_persisted_session_context(
            persisted_ctx, message_request.session_context,
        )
    try:
        conversation, message_id, assistant_message_id, persisted_response = _execute_message(
            conversation.conversation_id, message_request, trace, strict_session=True
        )
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    except RunControlBackendUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump(),
        ) from exc
    if payload.chat_request.stream:
        return _streaming_response_for_message(
            conversation_id=conversation.conversation_id,
            user_message_id=message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            response=persisted_response,
            trace=trace,
        )
    return _response_builder.build_internal_chat_response(
        conversation_id=conversation.conversation_id,
        message_id=message_id,
        response=persisted_response,
    )


@router.post("/chat/sessions")
def create_chat_session(payload: SessionCreateRequest) -> ApiEnvelope[ConversationRecord]:
    return ApiEnvelope(success=True, data=_conversation_store.create(payload))


@router.get("/chat/sessions")
def list_chat_sessions(
    page: int = 1,
    page_size: int = 20,
    scene: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> ApiEnvelope[SessionListResponse]:
    items, total = _conversation_store.list(
        page=page,
        page_size=page_size,
        scene=scene,
        status=status,
        keyword=keyword,
    )
    return ApiEnvelope(success=True, data=SessionListResponse(items=items, total=total, page=page, page_size=page_size))


@router.get("/chat/sessions/{conversation_id}")
def get_chat_session(conversation_id: str) -> ApiEnvelope[ConversationRecord]:
    try:
        return ApiEnvelope(success=True, data=_conversation_store.require(conversation_id))
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise


@router.delete("/chat/sessions/{conversation_id}")
def delete_chat_session(conversation_id: str) -> ApiEnvelope[SessionDeleteResponse]:
    _conversation_store.soft_delete(conversation_id)
    return ApiEnvelope(success=True, data=SessionDeleteResponse(conversation_id=conversation_id))


@router.get("/chat/sessions/{conversation_id}/messages")
def list_chat_messages(conversation_id: str, cursor: str | None = None, page_size: int = 100) -> ApiEnvelope[SessionMessagesPage]:
    try:
        return ApiEnvelope(success=True, data=_conversation_store.list_messages(conversation_id, cursor=cursor, page_size=page_size))
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise


@router.post("/sessions/{conversation_id}/messages")
def orchestrate_message(conversation_id: str, payload: MessageRequest, request: Request) -> ApiEnvelope[ChatCompletionResponse]:
    message_request = message_request_from_session_message(payload)
    message_request.message_id = message_request.message_id or f"msg_{uuid4().hex}"
    trace = build_trace_context(request, conversation_id, payload.trace, default_request_id=message_request.message_id)
    message_request.trace = trace
    persisted_ctx = _conversation_store.get_context(conversation_id)
    if persisted_ctx is not None:
        message_request.session_context = merge_persisted_session_context(persisted_ctx, message_request.session_context)
    hydrate_user_profile_from_auth_profile(message_request)
    try:
        conversation, message_id, _, persisted_response = _execute_message(
            conversation_id, message_request, trace, strict_session=True
        )
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    except RunControlBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump()) from exc
    return ApiEnvelope(
        success=True,
        data=_response_builder.build_chat_completion_response(
            conversation_id=conversation.conversation_id, user_message_id=message_id, response=persisted_response
        ),
    )


@router.post("/sessions/{conversation_id}/messages/stream")
def stream_orchestrated_message(conversation_id: str, payload: MessageRequest, request: Request):
    message_request = message_request_from_session_message(payload)
    message_request.message_id = message_request.message_id or f"msg_{uuid4().hex}"
    trace = build_trace_context(request, conversation_id, payload.trace, default_request_id=message_request.message_id)
    message_request.trace = trace
    persisted_ctx = _conversation_store.get_context(conversation_id)
    if persisted_ctx is not None:
        message_request.session_context = merge_persisted_session_context(persisted_ctx, message_request.session_context)
    try:
        conversation, message_id, assistant_message_id, persisted_response = _execute_message(
            conversation_id, message_request, trace, strict_session=True
        )
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    except RunControlBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump()) from exc
    return _streaming_response_for_message(
        conversation_id=conversation.conversation_id, user_message_id=message_id,
        assistant_message_id=assistant_message_id, message_request=message_request,
        response=persisted_response, trace=trace,
    )


@router.get("/sessions/{conversation_id}/state")
def get_session_state(conversation_id: str) -> ApiEnvelope[Any]:
    _require_conversation(conversation_id)
    snapshot = _build_state_snapshot(conversation_id)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(code="CHAT_SESSION_STATE_NOT_FOUND", message=f"State snapshot for conversation '{conversation_id}' was not found.").model_dump(),
        )
    return ApiEnvelope(success=True, data=snapshot)


@router.post("/sessions/{conversation_id}/rollback")
def rollback_session(conversation_id: str, request: Request) -> ApiEnvelope[SessionRollbackResponse]:
    _require_conversation(conversation_id)
    snapshot = _build_state_snapshot(conversation_id)
    if snapshot is None or not snapshot.compensation_stack:
        raise HTTPException(
            status_code=404,
            detail=ErrorInfo(code="CHAT_SESSION_STATE_NOT_FOUND", message=f"No compensation stack found for conversation '{conversation_id}'.").model_dump(),
        )
    trace = build_trace_context(request, conversation_id, None)
    armed_steps = [step for step in snapshot.compensation_stack if step.status == "armed"]
    compensation_records = _runtime.tool_hub_client.execute_compensations(list(reversed(armed_steps)), trace=trace)
    updated_stack = list(snapshot.compensation_stack)
    step_id_to_record = {rec.step_id: rec for rec in compensation_records}
    for i, step in enumerate(updated_stack):
        rec = step_id_to_record.get(step.step_id)
        if rec is not None:
            updated_stack[i] = step.model_copy(update={"status": rec.status})
    new_events = list(snapshot.events)
    seq = (new_events[-1].sequence + 1) if new_events else 1
    for rec in compensation_records:
        new_events.append(ExecutionEvent(
            sequence=seq, event="compensation_result",
            message=f"补偿操作 '{rec.action_name}' 执行{'成功' if rec.success else '失败'}。",
            tool_name=rec.tool_name,
            data={"step_id": rec.step_id, "status": rec.status, "action_name": rec.action_name},
        ))
        seq += 1
    updated_snapshot = snapshot.model_copy(update={"compensation_stack": updated_stack, "events": new_events})
    updated_snapshot.events.append(ExecutionEvent(
        sequence=seq, event="state_persisted", message="补偿完成，状态已持久化。",
        data={"conversation_id": conversation_id},
    ))
    _state_store.save(updated_snapshot)
    all_success = all(rec.status == "completed" for rec in compensation_records)
    return ApiEnvelope(
        success=True,
        data=SessionRollbackResponse(
            conversation_id=conversation_id,
            status="completed" if all_success else "partial",
            restored=all_success,
            summary=f"已执行 {len(compensation_records)} 项补偿操作。",
            compensated_steps=list(compensation_records),
            state_snapshot=updated_snapshot,
        ),
    )


@router.get("/chat/sessions/{conversation_id}/agent-routes")
def get_chat_session_agent_routes(conversation_id: str) -> ApiEnvelope[list[Any]]:
    _require_conversation(conversation_id)
    snapshot = _build_state_snapshot(conversation_id)
    return ApiEnvelope(success=True, data=[] if snapshot is None else list(snapshot.agent_routes))


@router.post("/chat/completions")
def chat_completions(request: Request, payload: ChatCompletionRequest):
    try:
        conversation = _conversation_store.ensure(
            payload.conversation_id or f"conv_{uuid4().hex}", scene=payload.scene or "customer_service"
        )
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    message_request = message_request_from_chat_completion(payload)
    persisted_ctx = _conversation_store.get_context(conversation.conversation_id)
    if persisted_ctx is not None:
        message_request.session_context = merge_persisted_session_context(persisted_ctx, message_request.session_context)
    message_id = message_request.message_id or f"msg_{uuid4().hex}"
    message_request.message_id = message_id
    trace = build_trace_context(request, conversation.conversation_id, payload.trace, default_request_id=message_id)
    message_request.trace = trace
    try:
        conversation, message_id, assistant_message_id, persisted_response = _execute_message(
            conversation.conversation_id, message_request, trace
        )
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    except RunControlBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump()) from exc
    if payload.stream:
        return _streaming_response_for_message(
            conversation_id=conversation.conversation_id, user_message_id=message_id,
            assistant_message_id=assistant_message_id, message_request=message_request,
            response=persisted_response, trace=trace,
        )
    _persist_stream_events(
        conversation_id=conversation.conversation_id, assistant_message_id=assistant_message_id,
        message_request=message_request, response=persisted_response, trace=trace,
    )
    return ApiEnvelope(
        success=True,
        data=_response_builder.build_chat_completion_response(
            conversation_id=conversation.conversation_id, user_message_id=message_id, response=persisted_response
        ),
    )


@router.post("/chat/sessions/{conversation_id}/continue")
def continue_chat_session(conversation_id: str, payload: SessionContinueRequest, request: Request):
    _require_conversation(conversation_id)
    snapshot = _build_state_snapshot(conversation_id)
    if snapshot is None:
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(code="CHAT_AGENT_HANDOFF_NOT_PENDING", message=f"Conversation '{conversation_id}' does not have a pending agent handoff.").model_dump(),
        )
    if snapshot.pending_agent_handoff is None:
        if (
            not snapshot.pending_user_actions and not payload.field_values
            and not payload.confirm_tool_names and not payload.session_context_patch
            and not (payload.user_input and payload.user_input.strip())
            and payload.user_profile_patch.model_dump(exclude_none=True) == {}
        ):
            raise HTTPException(
                status_code=409,
                detail=ErrorInfo(code="CHAT_AGENT_HANDOFF_NOT_PENDING", message=f"Conversation '{conversation_id}' does not have a pending agent handoff.").model_dump(),
            )
        try:
            user_message_request = build_continue_user_input_request(
                _conversation_store, conversation_id, snapshot, payload
            )
        except ConversationStoreError as exc:
            raise_conversation_error(exc)
            raise
        trace = build_trace_context(request, conversation_id, user_message_request.trace, default_request_id=user_message_request.message_id)
        user_message_request.trace = trace
        try:
            _, message_id, _, persisted_response = _execute_message(
                conversation_id, user_message_request, trace, strict_session=True
            )
        except ConversationStoreError as exc:
            raise_conversation_error(exc)
            raise
        except RunControlBackendUnavailableError as exc:
            raise HTTPException(status_code=503, detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump()) from exc
        return ApiEnvelope(
            success=True,
            data=_response_builder.build_chat_completion_response(
                conversation_id=conversation_id, user_message_id=message_id, response=persisted_response
            ),
        )
    trace = build_trace_context(
        request, conversation_id,
        snapshot.trace or snapshot.pending_agent_handoff.request_snapshot.trace,
        default_request_id=snapshot.pending_agent_handoff.source_user_message_id,
    )
    persisted_response, source_user_message_id = _execute_handoff_resume(
        conversation_id, snapshot, payload, trace
    )
    return ApiEnvelope(
        success=True,
        data=_response_builder.build_chat_completion_response(
            conversation_id=conversation_id, user_message_id=source_user_message_id, response=persisted_response
        ),
    )


@router.post("/chat/sessions/{conversation_id}/retry")
def retry_chat_session(conversation_id: str, payload: SessionRetryRequest, request: Request):
    try:
        message_request = _conversation_store.build_retry_request(
            conversation_id, message_id=payload.message_id, override_input=payload.override_input
        )
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    trace = build_trace_context(request, conversation_id, message_request.trace, default_request_id=payload.message_id)
    message_request.trace = trace
    try:
        _, message_id, _, persisted_response = _execute_message(conversation_id, message_request, trace, strict_session=True)
    except RunControlBackendUnavailableError as exc:
        raise HTTPException(status_code=503, detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump()) from exc
    return ApiEnvelope(
        success=True,
        data=_response_builder.build_chat_completion_response(
            conversation_id=conversation_id, user_message_id=message_id, response=persisted_response
        ),
    )


@router.post("/chat/sessions/{conversation_id}/cancel")
def cancel_chat_session(conversation_id: str, payload: SessionCancelRequest) -> ApiEnvelope[SessionCancelResponse]:
    try:
        message_id = payload.message_id or _conversation_store.latest_message_id(conversation_id, role="user")
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise
    if not _run_control.is_running(conversation_id, message_id):
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(code="CHAT_MESSAGE_NOT_RUNNING", message=f"Message '{message_id}' is not running in conversation '{conversation_id}'.").model_dump(),
        )
    _run_control.cancel(conversation_id, message_id)
    return ApiEnvelope(success=True, data=SessionCancelResponse(conversation_id=conversation_id, message_id=message_id))


@router.post("/chat/sessions/{conversation_id}/archive")
def archive_chat_session(conversation_id: str) -> ApiEnvelope[ConversationRecord]:
    try:
        return ApiEnvelope(success=True, data=_conversation_store.archive(conversation_id))
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise


@router.post("/chat/sessions/{conversation_id}/restore")
def restore_chat_session(conversation_id: str) -> ApiEnvelope[ConversationRecord]:
    try:
        return ApiEnvelope(success=True, data=_conversation_store.restore(conversation_id))
    except ConversationStoreError as exc:
        raise_conversation_error(exc)
        raise


@router.get("/chat/sessions/{conversation_id}/messages/{message_id}/events")
def list_message_events(conversation_id: str, message_id: str, after_event_id: str | None = None, limit: int = 100) -> ApiEnvelope[StreamEventPage]:
    page = _sse_event_store.get_page(conversation_id, message_id, after_event_id=after_event_id, limit=limit)
    if page is None:
        page = StreamEventPage(conversation_id=conversation_id, message_id=message_id, items=[], next_event_id=None, has_more=False)
    return ApiEnvelope(success=True, data=page)


@router.get("/chat/sessions/{conversation_id}/messages/{message_id}/events/stream")
def stream_message_events(conversation_id: str, message_id: str, request: Request):
    last_event_id = request.headers.get("Last-Event-ID")
    normalized_id = f"asst_{message_id}" if not message_id.startswith("asst_") else message_id
    page = _sse_event_store.get_page(conversation_id, normalized_id, after_event_id=last_event_id, limit=1000)
    if page is None:
        page = StreamEventPage(conversation_id=conversation_id, message_id=message_id, items=[], next_event_id=None, has_more=False)
    return StreamingResponse(iter_sse_events(page.items), media_type="text/event-stream")


@router.post("/route")
def decide_route(payload: RouteRequest) -> ApiEnvelope[RouteDecision]:
    return ApiEnvelope(success=True, data=_router.route(payload))


@router.get("/admin/agents")
def list_admin_agents(scene: str | None = None, status: str | None = None) -> ApiEnvelope[AgentAdminListResponse]:
    items = _router.available_admin_agents(scene=scene, status=status)
    return ApiEnvelope(success=True, data=AgentAdminListResponse(items=items, total=len(items)))


@router.patch("/admin/agents/{agent_code}")
def update_admin_agent(agent_code: str, payload: AgentConfigUpdateRequest):
    return ApiEnvelope(success=True, data=_router.update_agent_config(agent_code, payload))
