from __future__ import annotations

from app.models.common import TraceContext
from app.models.orchestration import (
    AgentRouteRecord,
    ChatCompletionResponse,
    ExecutionEvent,
    InternalChatResponse,
    MessageRequest,
    OrchestratorResponse,
    PendingAgentHandoff,
    PendingUserAction,
    SagaCompensationStep,
    SessionStateSnapshot,
    ToolContextItem,
)
from app.services.conversation_store import ConversationStore
from app.services.sse_event_store import SseEventStore
from app.services.state_store import OrchestrationStateStore
from app.services.streaming import build_sse_event_records

from .orchestration_utils import aggregate_citations


class OrchestrationResponseBuilder:
    """Builds orchestration responses, state snapshots, and execution events.

    Encapsulates the response-shaping logic that previously lived in `orchestration.py`
    as scattered `_build_*` helpers. Depends on the state, conversation, and SSE stores
    to read prior state and persist newly-built artifacts.
    """

    def __init__(
        self,
        *,
        state_store: OrchestrationStateStore,
        conversation_store: ConversationStore,
        sse_event_store: SseEventStore,
    ) -> None:
        self._state_store = state_store
        self._conversation_store = conversation_store
        self._sse_event_store = sse_event_store

    # ------------------------------------------------------------------
    # State snapshot accessors
    # ------------------------------------------------------------------

    def get_state_snapshot(self, conversation_id: str) -> SessionStateSnapshot | None:
        return self._state_store.get(conversation_id)

    def persist_state_snapshot(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        return self._state_store.save(snapshot)

    # ------------------------------------------------------------------
    # Agent routes / events / pending actions
    # ------------------------------------------------------------------

    @staticmethod
    def agent_route_records(
        response: OrchestratorResponse,
        pending_agent_handoff: PendingAgentHandoff | None = None,
    ) -> list[AgentRouteRecord]:
        handoff_by_next_agent = {
            execution.next_agent: execution
            for execution in response.executions
            if execution.status == "handoff" and execution.next_agent
        }
        records: list[AgentRouteRecord] = []
        executed_agents = {execution.agent for execution in response.executions}
        pending_next_agent = None
        if (
            pending_agent_handoff is not None
            and pending_agent_handoff.next_task_index < len(pending_agent_handoff.route.tasks)
        ):
            pending_next_agent = pending_agent_handoff.route.tasks[pending_agent_handoff.next_task_index].agent
        for index, task in enumerate(response.route.tasks, start=1):
            execution = next((item for item in response.executions if item.agent == task.agent), None)
            status = "planned"
            action_required = None
            handoff_received_from = None
            handoff_to = None
            handoff_reason = None
            tool_call_ids: list[str] = []
            tool_statuses: list[str] = []
            context_highlights = dict(task.model_dump(mode="json"))
            if execution is not None:
                status = execution.status
                action_required = execution.action_required
                handoff_received_from = execution.handoff_received_from
                handoff_to = execution.next_agent
                handoff_reason = execution.handoff_reason
                tool_call_ids = [tool_call.tool_call_id for tool_call in execution.tool_calls]
                tool_statuses = [tool_call.status for tool_call in execution.tool_calls]
                context_highlights = dict(execution.handoff_payload)
            elif any(item.status == "need_user_input" for item in response.executions):
                status = "blocked"
            elif task.agent in handoff_by_next_agent:
                received = handoff_by_next_agent[task.agent]
                handoff_received_from = received.agent
                handoff_reason = received.handoff_reason
                if task.agent in executed_agents and task.agent != pending_next_agent:
                    status = "success"
            records.append(
                AgentRouteRecord(
                    step_id=task.handoff_step_id or f"route-step-{index}",
                    order=index,
                    agent=task.agent,
                    objective=task.reason,
                    status=status,
                    handoff_received_from=handoff_received_from,
                    handoff_to=handoff_to,
                    handoff_reason=handoff_reason,
                    action_required=action_required,
                    tool_names=list(task.suggested_tools),
                    tool_call_ids=tool_call_ids,
                    tool_statuses=tool_statuses,
                    depends_on=list(task.depends_on_tool_call_ids),
                    depends_on_tool_call_ids=list(task.depends_on_tool_call_ids),
                    session_context_inputs=list(task.session_context_inputs),
                    session_context_outputs=list(task.session_context_outputs),
                    context_highlights=context_highlights,
                )
            )
        return records

    @staticmethod
    def build_execution_events(response: OrchestratorResponse) -> list[ExecutionEvent]:
        events: list[ExecutionEvent] = [
            ExecutionEvent(
                sequence=1,
                event="route_selected",
                agent=response.route.primary_agent,
                message="Route selected for orchestration.",
                data={
                    "primary_agent": response.route.primary_agent,
                    "requires_retrieval": response.route.requires_retrieval,
                    "requires_tools": response.route.requires_tools,
                    "tool_plan": response.route.tool_plan,
                    "handoff_plan": response.route.handoff_plan,
                },
            )
        ]
        for execution in response.executions:
            events.append(
                ExecutionEvent(
                    sequence=len(events) + 1,
                    event="agent_result",
                    agent=execution.agent,
                    message=execution.reasoning_summary,
                    data={
                        "status": execution.status,
                        "next_agent": execution.next_agent,
                        "action_required": execution.action_required,
                        "risk_flags": execution.risk_flags,
                    },
                )
            )
        if response.review is not None:
            events.append(
                ExecutionEvent(
                    sequence=len(events) + 1,
                    event="review_result",
                    message=response.review.summary,
                    data=response.review.model_dump(mode="json"),
                )
            )
        return events

    @staticmethod
    def build_pending_agent_handoff(
        route,
        message_request: MessageRequest,
        executions: list,
        *,
        source_user_message_id: str,
    ) -> PendingAgentHandoff | None:
        if not executions:
            return None
        last_execution = executions[-1]
        next_task_index = len(executions)
        if (
            last_execution.status != "handoff"
            or last_execution.next_agent is None
            or next_task_index >= len(route.tasks)
        ):
            return None
        request_snapshot = message_request.model_copy(deep=True)
        for execution in executions:
            for tool_call in execution.tool_calls:
                if tool_call.success and tool_call.session_context_patch:
                    ConversationStore._apply_session_context_patch(
                        request_snapshot.session_context,
                        tool_call.session_context_patch,
                    )
        return PendingAgentHandoff(
            route=route.model_copy(deep=True),
            request_snapshot=request_snapshot,
            source_user_message_id=source_user_message_id,
            next_task_index=next_task_index,
            completed_executions=[execution.model_copy(deep=True) for execution in executions],
            handoff_from=last_execution.agent,
        )

    @staticmethod
    def build_pending_user_actions(response: OrchestratorResponse) -> list[PendingUserAction]:
        pending_actions: list[PendingUserAction] = []
        for execution in response.executions:
            for tool_call in execution.tool_calls:
                hint = tool_call.user_action_hint
                if hint is None:
                    continue
                pending_actions.append(
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
                        session_context_bindings=dict(hint.session_context_bindings),
                        user_profile_bindings=dict(hint.user_profile_bindings),
                        confirm_tool_names=list(hint.confirm_tool_names),
                    )
                )
        return pending_actions

    # ------------------------------------------------------------------
    # State snapshot construction
    # ------------------------------------------------------------------

    def build_response_state_snapshot(
        self,
        conversation_id: str,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        trace: TraceContext | None,
    ) -> SessionStateSnapshot:
        existing = self.get_state_snapshot(conversation_id)
        if response.state_snapshot is not None and response.state_snapshot.pending_agent_handoff is not None:
            session_context = response.state_snapshot.pending_agent_handoff.request_snapshot.session_context.model_copy(
                deep=True
            )
        else:
            session_context = ConversationStore.derive_next_session_context(
                existing.session_context if existing is not None else self._conversation_store.get_context(conversation_id),
                message_request,
                response,
                max_recent_messages=20,
            )
        if (
            message_request.user_profile.account_id is not None
            and any(
                execution.status not in {"failed", "need_user_input"}
                for execution in response.executions
            )
        ):
            session_context.attributes["auth_profile"] = message_request.user_profile.model_dump()
        existing_compensation_stack: list[SagaCompensationStep] = (
            list(existing.compensation_stack) if existing is not None else []
        )
        existing_step_ids = {step.step_id for step in existing_compensation_stack}
        new_compensation_steps: list[SagaCompensationStep] = []
        for execution in response.executions:
            for tool_call in execution.tool_calls:
                if tool_call.compensation is None:
                    continue
                if tool_call.success is not True:
                    continue
                if tool_call.tool_call_id in existing_step_ids:
                    continue
                new_compensation_steps.append(
                    SagaCompensationStep(
                        saga_id=conversation_id,
                        step_id=tool_call.tool_call_id,
                        tool_name=tool_call.tool_name,
                        compensation=tool_call.compensation.model_copy(deep=True),
                    )
                )
        compensation_stack = [*existing_compensation_stack, *new_compensation_steps]
        existing_tool_context: list[ToolContextItem] = (
            list(existing.tool_context) if existing is not None else []
        )
        new_tool_context_items: list[ToolContextItem] = [
            ToolContextItem(
                tool_name=tool_call.tool_name,
                tool_call_id=tool_call.tool_call_id,
                status=tool_call.status or ("completed" if tool_call.success else "failed"),
                summary=tool_call.summary,
                provider=tool_call.provider,
                data=dict(tool_call.payload) if tool_call.payload else {},
                patch_keys=list(tool_call.session_context_patch.keys()) if tool_call.session_context_patch else [],
            )
            for execution in response.executions
            for tool_call in execution.tool_calls
        ]
        tool_context = [*existing_tool_context, *new_tool_context_items]
        any_tool_calls = any(execution.tool_calls for execution in response.executions)
        updated_checkpoints: list = []
        for cp in response.route.checkpoints:
            if cp.status in {"skipped"}:
                updated_checkpoints.append(cp)
            elif cp.name == "review-answer" and response.review is not None:
                updated_checkpoints.append(cp.model_copy(update={"status": "completed"}))
            elif cp.name == "invoke-tools" and any_tool_calls:
                updated_checkpoints.append(cp.model_copy(update={"status": "completed"}))
            elif cp.name == "retrieve-context" and message_request.retrieval_required:
                updated_checkpoints.append(cp.model_copy(update={"status": "completed"}))
            else:
                updated_checkpoints.append(cp)
        snapshot = SessionStateSnapshot(
            conversation_id=conversation_id,
            primary_agent=response.route.primary_agent,
            current_agent=(
                response.state_snapshot.pending_agent_handoff.route.tasks[
                    response.state_snapshot.pending_agent_handoff.next_task_index
                ].agent
                if response.state_snapshot is not None
                and response.state_snapshot.pending_agent_handoff is not None
                and response.state_snapshot.pending_agent_handoff.next_task_index
                < len(response.state_snapshot.pending_agent_handoff.route.tasks)
                else (
                    response.executions[-1].next_agent
                    if response.executions and response.executions[-1].next_agent
                    else response.route.primary_agent
                )
            ),
            version=existing.version if existing is not None else 1,
            session_context=session_context,
            agent_routes=self.agent_route_records(
                response,
                response.state_snapshot.pending_agent_handoff if response.state_snapshot else None,
            ),
            checkpoints=updated_checkpoints,
            tool_results=[tool_call for execution in response.executions for tool_call in execution.tool_calls],
            tool_context=tool_context,
            compensation_stack=compensation_stack,
            events=self.build_execution_events(response),
            pending_actions=list(response.pending_actions),
            pending_user_actions=list(response.pending_user_actions),
            pending_agent_handoff=(
                response.state_snapshot.pending_agent_handoff
                if response.state_snapshot is not None
                else None
            ),
            final_response_summary=response.final_response_summary,
            review=response.review,
            trace=trace,
        )
        snapshot.events.append(
            ExecutionEvent(
                sequence=len(snapshot.events) + 1,
                event="state_persisted",
                message="当前响应状态已持久化。",
                data={"conversation_id": conversation_id},
            )
        )
        return self.persist_state_snapshot(snapshot)

    def build_cancelled_state_snapshot(
        self,
        conversation_id: str,
        message_request: MessageRequest,
        trace: TraceContext | None,
        *,
        summary: str,
    ) -> SessionStateSnapshot:
        existing = self.get_state_snapshot(conversation_id)
        session_context = self._conversation_store.get_context(conversation_id) or message_request.session_context
        snapshot = SessionStateSnapshot(
            conversation_id=conversation_id,
            primary_agent=existing.primary_agent if existing is not None else "finance_order_agent",
            current_agent=existing.current_agent if existing is not None else None,
            version=existing.version if existing is not None else 1,
            session_context=session_context.model_copy(deep=True),
            agent_routes=list(existing.agent_routes) if existing is not None else [],
            checkpoints=list(existing.checkpoints) if existing is not None else [],
            tool_results=list(existing.tool_results) if existing is not None else [],
            tool_context=list(existing.tool_context) if existing is not None else [],
            compensation_stack=list(existing.compensation_stack) if existing is not None else [],
            events=list(existing.events) if existing is not None else [],
            pending_actions=[],
            pending_user_actions=[],
            pending_agent_handoff=None,
            final_response_summary=summary,
            review=existing.review if existing is not None else None,
            trace=trace,
        )
        return self.persist_state_snapshot(snapshot)

    # ------------------------------------------------------------------
    # Stream events / API responses
    # ------------------------------------------------------------------

    def persist_stream_events(
        self,
        *,
        conversation_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        trace: TraceContext | None,
    ):
        events = build_sse_event_records(
            conversation_id=conversation_id,
            message_id=assistant_message_id,
            user_query=message_request.user_query,
            response=response,
            trace=trace,
        )
        self._sse_event_store.save(conversation_id, assistant_message_id, events)
        return events

    @staticmethod
    def build_internal_chat_response(
        *,
        conversation_id: str,
        message_id: str,
        response: OrchestratorResponse,
    ) -> InternalChatResponse:
        executions = list(response.executions)
        first_agent = response.route.primary_agent
        final_answer = response.final_response_summary or (executions[-1].final_answer if executions else None)
        citations = aggregate_citations(response)
        tool_calls = [tool_call for execution in executions for tool_call in execution.tool_calls]
        return InternalChatResponse(
            conversation_id=conversation_id,
            message_id=message_id,
            status=("failed" if response.next_action == "retry-or-escalate" else "success"),
            agent_name=first_agent,
            route=response.route,
            executions=executions,
            final_answer=final_answer,
            citations=citations,
            tool_calls=tool_calls,
            next_agent=executions[-1].next_agent if executions else None,
            pending_actions=list(response.pending_actions),
            pending_user_actions=list(response.pending_user_actions),
            state_snapshot=response.state_snapshot,
            review=response.review,
            trace=response.trace,
            next_action=response.next_action,
            final_response_summary=response.final_response_summary,
        )

    @staticmethod
    def build_chat_completion_response(
        *,
        conversation_id: str,
        user_message_id: str,
        response: OrchestratorResponse,
    ) -> ChatCompletionResponse:
        answer = response.final_response_summary or (
            response.executions[-1].final_answer if response.executions else response.route.summary
        )
        citations = aggregate_citations(response)
        tool_calls = [tool_call for execution in response.executions for tool_call in execution.tool_calls]
        finish_reason = "retry" if response.next_action == "retry-or-escalate" else None
        return ChatCompletionResponse(
            conversation_id=conversation_id,
            message_id=user_message_id,
            status=("failed" if response.next_action == "retry-or-escalate" else "success"),
            answer=answer or "",
            citations=citations,
            tool_calls=tool_calls,
            pending_actions=list(response.pending_actions),
            pending_user_actions=list(response.pending_user_actions),
            finish_reason=finish_reason,
            response=response.model_dump(mode="json", by_alias=True),
            review=response.review,
            next_action=response.next_action,
            final_response_summary=response.final_response_summary,
            executions=list(response.executions),
            state_snapshot=response.state_snapshot,
            route=response.route,
        )
