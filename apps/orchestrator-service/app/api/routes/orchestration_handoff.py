from __future__ import annotations

from typing import Callable

from fastapi import HTTPException

from app.models.common import ErrorInfo, TraceContext
from app.models.orchestration import (
    MessageRequest,
    OrchestratorResponse,
    SessionContinueRequest,
    SessionStateSnapshot,
)
from app.services.agent_runtime import AgentRuntime
from app.services.conversation_store import ConversationStore
from app.services.review import ResponseReviewService
from app.services.run_control import (
    ActiveRunConflictError,
    OrchestrationRunControl,
    RunControlBackendUnavailableError,
)

from .orchestration_request_builder import (
    continue_assistant_message_id,
    continue_request_from_pending_handoff,
)
from .orchestration_response_builder import OrchestrationResponseBuilder
from .orchestration_utils import resolve_next_action, response_message_status


def execute_handoff_resume(
    conversation_id: str,
    snapshot: SessionStateSnapshot,
    payload: SessionContinueRequest,
    trace: TraceContext,
    *,
    runtime: AgentRuntime,
    run_control: OrchestrationRunControl,
    conversation_store: ConversationStore,
    review_service: ResponseReviewService,
    response_builder: OrchestrationResponseBuilder,
    cancel_check_for: Callable[[str, str], Callable[[], None]],
) -> tuple[OrchestratorResponse, str]:
    """Resume execution of a paused agent handoff.

    Accepts services as explicit parameters so the function can live outside
    orchestration.py without circular references to its module-level singletons.
    """
    pending_handoff = snapshot.pending_agent_handoff
    message_request = continue_request_from_pending_handoff(pending_handoff, payload)
    message_request.message_id = pending_handoff.source_user_message_id
    message_request.trace = trace
    active_run = run_control.start(conversation_id, pending_handoff.source_user_message_id)
    try:
        resumed_executions = runtime.execute(
            pending_handoff.route,
            message_request,
            trace,
            cancel_check=cancel_check_for(conversation_id, pending_handoff.source_user_message_id),
            start_task_index=pending_handoff.next_task_index,
            pause_on_agent_handoff=True,
            incoming_handoff_from=pending_handoff.handoff_from,
        )
        combined_executions = [
            *[e.model_copy(deep=True) for e in pending_handoff.completed_executions],
            *resumed_executions,
        ]
        effective_executions = [e.model_copy(deep=True) for e in combined_executions]
        pending_agent_handoff = None
        if effective_executions and effective_executions[-1].status == "handoff":
            pending_agent_handoff = response_builder.build_pending_agent_handoff(
                pending_handoff.route,
                message_request,
                effective_executions,
                source_user_message_id=pending_handoff.source_user_message_id,
            )
        final_summary = (
            effective_executions[-1].final_answer if effective_executions else pending_handoff.route.summary
        )
        response = OrchestratorResponse(
            conversation_id=conversation_id,
            route=pending_handoff.route,
            executions=effective_executions,
            final_response_summary=final_summary,
            next_action="continue-agent-handoff" if pending_agent_handoff else "respond-with-agent-summary",
            pending_actions=["continue-agent-handoff"] if pending_agent_handoff else [],
            pending_user_actions=[],
            state_snapshot=(
                SessionStateSnapshot(
                    conversation_id=conversation_id,
                    primary_agent=pending_handoff.route.primary_agent,
                    current_agent=(
                        pending_handoff.route.tasks[pending_agent_handoff.next_task_index].agent
                        if pending_agent_handoff
                        else pending_handoff.route.primary_agent
                    ),
                    session_context=(
                        pending_agent_handoff.request_snapshot.session_context.model_copy(deep=True)
                        if pending_agent_handoff
                        else message_request.session_context.model_copy(deep=True)
                    ),
                    pending_agent_handoff=pending_agent_handoff,
                )
                if pending_agent_handoff
                else None
            ),
            review=None,
            trace=trace,
        )
        next_action, pending_actions = resolve_next_action(response)
        response.next_action = next_action
        response.pending_actions = pending_actions
        response.pending_user_actions = response_builder.build_pending_user_actions(response)
        response.review = review_service.review(pending_handoff.route, combined_executions, final_summary or "")
        response.state_snapshot = response_builder.build_response_state_snapshot(
            conversation_id, message_request, response, trace
        )
        persisted_response = response.model_copy(deep=True)
        conversation_store.store_assistant_continuation(
            conversation_id=conversation_id,
            source_user_message_id=pending_handoff.source_user_message_id,
            assistant_message_id=continue_assistant_message_id(pending_handoff.source_user_message_id),
            message_request=message_request,
            response=persisted_response,
            status=response_message_status(response),
            session_context=(
                response.state_snapshot.session_context
                if response.state_snapshot
                else message_request.session_context
            ),
            trace=trace,
        )
        persisted_response.state_snapshot = response_builder.get_state_snapshot(conversation_id)
    except ActiveRunConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=ErrorInfo(
                code="CHAT_MESSAGE_ALREADY_RUNNING",
                message=f"Conversation '{exc.conversation_id}' is already running message '{exc.message_id}'.",
            ).model_dump(),
        ) from exc
    except RunControlBackendUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=ErrorInfo(code="CHAT_RUN_CONTROL_UNAVAILABLE", message=str(exc)).model_dump(),
        ) from exc
    finally:
        run_control.finish(active_run.conversation_id, active_run.message_id)
    return persisted_response, pending_handoff.source_user_message_id
