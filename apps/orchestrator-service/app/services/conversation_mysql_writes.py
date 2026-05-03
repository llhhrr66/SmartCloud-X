from __future__ import annotations

import json
from uuid import uuid4

from app.models.common import TraceContext
from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    OrchestratorResponse,
    SessionContext,
)
from app.services import runtime_mysql
from app.services.conversation_context_merge import ConversationContextMerger
from app.services.conversation_types import ConversationStoreError


class _MySQLWriteMixin:
    """Mixin providing exchange/write SQL operations for _MySQLConversationBackend.

    Requires that the inheriting class defines:
      - self._mysql_dsn: str
      - self._mongo_runtime: Any
      - self.CONVERSATION_TABLE / MESSAGE_TABLE / SNAPSHOT_TABLE / ASSISTANT_SNAPSHOT_TABLE: str
      - self._ensure_schema(cursor) -> None
      - self._require_record(conversation_id) -> ConversationRecord
      - self.get_context(conversation_id) -> SessionContext | None
      - self.fetch_messages(conversation_id) -> list[ChatMessageRecord]
      - self._write_conversation(cursor, record, *, context) -> None
      - self._write_assistant_request_snapshot(cursor, ...) -> None
    """

    def store_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        status: str,
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        return self._store_messages(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            status=status,
            session_context=session_context,
            trace=trace,
            assistant_content=response.final_response_summary or response.route.summary,
            response=response,
            finish_reason=response.next_action,
        )

    def store_assistant_continuation(
        self,
        *,
        conversation_id: str,
        source_user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        status: str,
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        record = self._require_record(conversation_id)
        if record.status == "archived":
            raise ConversationStoreError(
                status_code=409,
                code="CHAT_CONVERSATION_ARCHIVED",
                message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
            )
        messages = self.fetch_messages(conversation_id)
        now = ConversationContextMerger.now()
        parent_message_id = messages[-1].message_id if messages else source_user_message_id
        assistant_message = ChatMessageRecord(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role="assistant",
            message_type="assistant_response",
            status=status,
            created_at=now,
            updated_at=now,
            parent_message_id=parent_message_id,
            agent_name=response.route.primary_agent,
            content=response.final_response_summary or response.route.summary,
            citations=list(
                dict.fromkeys(
                    citation
                    for execution in response.executions
                    for citation in execution.citations
                )
            ),
            tool_calls=[
                tool_call for execution in response.executions for tool_call in execution.tool_calls
            ],
            finish_reason=response.next_action,
            trace=trace,
        )
        messages.append(assistant_message)
        record.status = "active"
        record.current_agent = (
            response.state_snapshot.current_agent
            if response.state_snapshot and response.state_snapshot.current_agent
            else response.route.primary_agent
        )
        record.summary = response.final_response_summary or response.route.summary
        record.pending_actions = list(response.pending_actions)
        record.last_message_at = assistant_message.updated_at
        record.updated_at = assistant_message.updated_at
        record.total_messages = len(messages)
        if not record.title:
            record.title = ConversationContextMerger.derive_title(message_request.user_query)
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else self.get_context(conversation_id) or SessionContext()
        )
        cleanup_state = None
        persist_fn = getattr(self._mongo_runtime, "persist_assistant_message", None)
        if callable(persist_fn):
            try:
                cleanup_state = persist_fn(
                    record=record,
                    source_user_message_id=source_user_message_id,
                    assistant_message=assistant_message,
                    message_request=message_request,
                    response=response,
                    session_context=effective_context,
                    trace=trace,
                )
                self._record_saga_event(
                    conversation_id=conversation_id,
                    user_message_id=source_user_message_id,
                    assistant_message_id=assistant_message_id,
                    saga_name="conversation_persistence",
                    step="mongo_assistant_continuation",
                    status="succeeded",
                )
            except Exception as exc:
                self._record_saga_event(
                    conversation_id=conversation_id,
                    user_message_id=source_user_message_id,
                    assistant_message_id=assistant_message_id,
                    saga_name="conversation_persistence",
                    step="mongo_assistant_continuation",
                    status="failed",
                    error=exc,
                )
                raise
        connection = None
        try:
            connection = runtime_mysql.connect(self._mysql_dsn)
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    DELETE FROM `{self.MESSAGE_TABLE}`
                    WHERE conversation_id = %s AND message_id = %s
                    """,
                    (conversation_id, assistant_message_id),
                )
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.MESSAGE_TABLE}` (
                        conversation_id, message_id, role, created_at, sequence_no, payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        conversation_id,
                        assistant_message.message_id,
                        assistant_message.role,
                        assistant_message.created_at,
                        len(messages),
                        json.dumps(assistant_message.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
                self._write_assistant_request_snapshot(
                    cursor,
                    conversation_id=conversation_id,
                    user_message_id=source_user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                )
                self._write_conversation(cursor, record, context=effective_context)
                self._write_saga_event(
                    cursor,
                    conversation_id=conversation_id,
                    user_message_id=source_user_message_id,
                    assistant_message_id=assistant_message_id,
                    saga_name="conversation_persistence",
                    step="mysql_assistant_continuation",
                    status="succeeded",
                )
            connection.commit()
        except Exception as exc:
            self._record_saga_event(
                conversation_id=conversation_id,
                user_message_id=source_user_message_id,
                assistant_message_id=assistant_message_id,
                saga_name="conversation_persistence",
                step="mysql_assistant_continuation",
                status="failed",
                error=exc,
            )
            if cleanup_state is not None:
                try:
                    self._mongo_runtime.delete_assistant_continuation(
                        conversation_id=conversation_id,
                        assistant_message_id=assistant_message_id,
                        cleanup_state=cleanup_state,
                    )
                    self._record_saga_event(
                        conversation_id=conversation_id,
                        user_message_id=source_user_message_id,
                        assistant_message_id=assistant_message_id,
                        saga_name="conversation_persistence",
                        step="mongo_assistant_continuation_cleanup",
                        status="compensated",
                    )
                except Exception as cleanup_exc:
                    self._record_saga_event(
                        conversation_id=conversation_id,
                        user_message_id=source_user_message_id,
                        assistant_message_id=assistant_message_id,
                        saga_name="conversation_persistence",
                        step="mongo_assistant_continuation_cleanup",
                        status="compensation_failed",
                        error=cleanup_exc,
                    )
                    raise RuntimeError(
                        f"{exc}; mongo continuation cleanup failed: {cleanup_exc}"
                    ) from cleanup_exc
            raise
        finally:
            if connection is not None:
                connection.close()
        return record, messages

    def store_cancelled_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        reason: str,
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        return self._store_messages(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            message_request=message_request,
            status="cancelled",
            session_context=session_context,
            trace=trace,
            assistant_content=reason,
            response=None,
            finish_reason="cancelled",
        )

    def _store_messages(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        status: str,
        session_context: SessionContext | None,
        trace: TraceContext | None,
        assistant_content: str,
        response: OrchestratorResponse | None,
        finish_reason: str,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        record = self._require_record(conversation_id)
        if record.status == "archived":
            raise ConversationStoreError(
                status_code=409,
                code="CHAT_CONVERSATION_ARCHIVED",
                message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
            )
        messages = self.fetch_messages(conversation_id)
        messages = [
            item
            for item in messages
            if item.message_id not in {user_message_id, assistant_message_id}
        ]
        sequence_base = len(messages)
        now = ConversationContextMerger.now()
        previous_message_id = messages[-1].message_id if messages else None
        user_message = ChatMessageRecord(
            message_id=user_message_id,
            conversation_id=conversation_id,
            role="user",
            message_type="user_input",
            status="completed",
            created_at=now,
            updated_at=now,
            parent_message_id=previous_message_id,
            content=message_request.user_query,
            trace=trace,
        )
        assistant_message = ChatMessageRecord(
            message_id=assistant_message_id,
            conversation_id=conversation_id,
            role="assistant",
            message_type="assistant_response",
            status=status,
            created_at=now,
            updated_at=now,
            parent_message_id=user_message_id,
            agent_name=response.route.primary_agent if response else None,
            content=assistant_content,
            citations=list(
                dict.fromkeys(
                    citation
                    for execution in (response.executions if response else [])
                    for citation in execution.citations
                )
            ),
            tool_calls=[
                tool_call
                for execution in (response.executions if response else [])
                for tool_call in execution.tool_calls
            ],
            finish_reason=finish_reason,
            trace=trace,
        )
        messages.extend([user_message, assistant_message])
        record.status = "active"
        record.current_agent = (
            response.state_snapshot.current_agent
            if response and response.state_snapshot and response.state_snapshot.current_agent
            else (response.route.primary_agent if response else None)
        )
        record.summary = assistant_content
        record.pending_actions = list(response.pending_actions) if response else []
        record.last_message_at = assistant_message.updated_at
        record.updated_at = assistant_message.updated_at
        record.total_messages = len(messages)
        if not record.title:
            record.title = ConversationContextMerger.derive_title(message_request.user_query)
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else self.get_context(conversation_id) or SessionContext()
        )
        sequence_numbers = {
            user_message_id: sequence_base + 1,
            assistant_message_id: sequence_base + 2,
        }
        cleanup_state = None
        if getattr(self._mongo_runtime, "enabled", False):
            try:
                cleanup_state = self._mongo_runtime.persist_exchange(
                    record=record,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    sequence_numbers=sequence_numbers,
                    message_request=message_request,
                    response=response,
                    session_context=effective_context,
                    trace=trace,
                )
                self._record_saga_event(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    saga_name="conversation_persistence",
                    step="mongo_exchange",
                    status="succeeded",
                )
            except Exception as exc:
                self._record_saga_event(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    saga_name="conversation_persistence",
                    step="mongo_exchange",
                    status="failed",
                    error=exc,
                )
                raise
        connection = None
        try:
            connection = runtime_mysql.connect(self._mysql_dsn)
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    DELETE FROM `{self.MESSAGE_TABLE}`
                    WHERE conversation_id = %s AND (message_id = %s OR message_id = %s)
                    """,
                    (conversation_id, user_message_id, assistant_message_id),
                )
                for message in (user_message, assistant_message):
                    sequence_no = sequence_numbers[message.message_id]
                    cursor.execute(
                        f"""
                        REPLACE INTO `{self.MESSAGE_TABLE}` (
                            conversation_id, message_id, role, created_at, sequence_no, payload_json
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            message.message_id,
                            message.role,
                            message.created_at,
                            sequence_no,
                            json.dumps(message.model_dump(mode="json"), ensure_ascii=False),
                        ),
                    )
                self._write_assistant_request_snapshot(
                    cursor,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                )
                self._write_conversation(cursor, record, context=effective_context)
                self._write_saga_event(
                    cursor,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    saga_name="conversation_persistence",
                    step="mysql_exchange",
                    status="succeeded",
                )
            connection.commit()
        except Exception as exc:
            self._record_saga_event(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                saga_name="conversation_persistence",
                step="mysql_exchange",
                status="failed",
                error=exc,
            )
            if cleanup_state is not None:
                try:
                    self._mongo_runtime.delete_exchange(
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        cleanup_state=cleanup_state,
                    )
                    self._record_saga_event(
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        saga_name="conversation_persistence",
                        step="mongo_exchange_cleanup",
                        status="compensated",
                    )
                except Exception as cleanup_exc:
                    self._record_saga_event(
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        saga_name="conversation_persistence",
                        step="mongo_exchange_cleanup",
                        status="compensation_failed",
                        error=cleanup_exc,
                    )
                    raise RuntimeError(
                        f"{exc}; mongo exchange cleanup failed: {cleanup_exc}"
                    ) from cleanup_exc
            raise
        finally:
            if connection is not None:
                connection.close()
        return record, messages

    def _record_saga_event(
        self,
        *,
        conversation_id: str,
        user_message_id: str | None,
        assistant_message_id: str | None,
        saga_name: str,
        step: str,
        status: str,
        error: Exception | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        try:
            connection = runtime_mysql.connect(self._mysql_dsn)
            try:
                with connection.cursor() as cursor:
                    self._ensure_schema(cursor)
                    self._write_saga_event(
                        cursor,
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        saga_name=saga_name,
                        step=step,
                        status=status,
                        error=error,
                        payload=payload,
                    )
                connection.commit()
            finally:
                connection.close()
        except Exception:
            return

    def _write_saga_event(
        self,
        cursor,
        *,
        conversation_id: str,
        user_message_id: str | None,
        assistant_message_id: str | None,
        saga_name: str,
        step: str,
        status: str,
        error: Exception | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        from app.core.metrics import (
            SAGA_COMPENSATIONS_TOTAL,
            SAGA_FAILURES_TOTAL,
            SAGA_STEPS_TOTAL,
        )

        SAGA_STEPS_TOTAL.labels(saga_name=saga_name, step=step, status=status).inc()
        if status == "failed" and error:
            SAGA_FAILURES_TOTAL.labels(
                saga_name=saga_name, step=step, error_type=error.__class__.__name__
            ).inc()
        elif status in ("compensated", "compensation_failed"):
            SAGA_COMPENSATIONS_TOTAL.labels(
                saga_name=saga_name, step=step, result=status
            ).inc()
        cursor.execute(
            f"""
            INSERT INTO `{self.SAGA_EVENT_TABLE}` (
                event_id, conversation_id, user_message_id, assistant_message_id,
                saga_name, step, status, error_type, error_message, created_at, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"saga_{uuid4().hex}",
                conversation_id,
                user_message_id,
                assistant_message_id,
                saga_name,
                step,
                status,
                error.__class__.__name__ if error else None,
                str(error)[:1000] if error else None,
                ConversationContextMerger.now(),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )

    def _write_conversation(
        self, cursor, record: ConversationRecord, *, context: SessionContext
    ) -> None:
        cursor.execute(
            f"""
            REPLACE INTO `{self.CONVERSATION_TABLE}` (
                conversation_id, scene, status, title, current_agent, summary,
                created_at, updated_at, last_message_at, total_messages,
                initial_context_json, context_json, pending_actions_json, payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record.conversation_id,
                record.scene,
                record.status,
                record.title,
                record.current_agent,
                record.summary,
                record.created_at,
                record.updated_at,
                record.last_message_at,
                record.total_messages,
                json.dumps(record.initial_context.model_dump(mode="json"), ensure_ascii=False),
                json.dumps(context.model_dump(mode="json"), ensure_ascii=False),
                json.dumps(record.pending_actions, ensure_ascii=False),
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
            ),
        )

    def _write_assistant_request_snapshot(
        self,
        cursor,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        request_json = json.dumps(message_request.model_dump(mode="json"), ensure_ascii=False)
        cursor.execute(
            f"""
            REPLACE INTO `{self.SNAPSHOT_TABLE}` (
                conversation_id, user_message_id, assistant_message_id, request_json
            ) VALUES (%s, %s, %s, %s)
            """,
            (conversation_id, user_message_id, assistant_message_id, request_json),
        )
        cursor.execute(
            f"""
            REPLACE INTO `{self.ASSISTANT_SNAPSHOT_TABLE}` (
                conversation_id, assistant_message_id, user_message_id, request_json
            ) VALUES (%s, %s, %s, %s)
            """,
            (conversation_id, assistant_message_id, user_message_id, request_json),
        )
