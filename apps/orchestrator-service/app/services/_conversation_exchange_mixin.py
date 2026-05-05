from __future__ import annotations

from app.models.common import TraceContext
from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    OrchestratorResponse,
    SessionContext,
    SessionMessagesPage,
)
from app.services.conversation_context_merge import ConversationContextMerger
from app.services.conversation_types import ConversationStoreError
from app.services.mongo_runtime import ConversationMongoRuntimeError


class _ConversationExchangeMixin:
    """Mixin for ConversationStore: exchange/message storage with backend routing.

    Expects the host class to define:
      _lock, _conversations, _messages, _contexts, _request_snapshots,
      _assistant_to_user, _max_recent_messages, _cache (ConversationRuntimeCache),
      get_context(), require(), _maybe_restore_backend(), _degrade_backend(),
      _document_store_error(), _mirror_exchange_unlocked(),
      _mirror_assistant_continuation_unlocked(), _persist_unlocked(),
      _build_message_page(), _build_retry_request_from_snapshot(),
      _latest_message_id_from_items(), _now() (or ConversationContextMerger.now()),
      derive_title() (or ConversationContextMerger.derive_title())
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
        self._cache.maybe_restore()
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else ConversationContextMerger.derive_next_session_context(
                self.get_context(conversation_id),
                message_request,
                response,
                max_recent_messages=self._max_recent_messages,
                compaction_summary=response.compaction_summary,
            )
        )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record, messages = backend.store_exchange(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                    response=response,
                    status=status,
                    session_context=effective_context,
                    trace=trace,
                )
                self._cache.save_exchange(
                    record, messages,
                    context=effective_context,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                )
                with self._lock:
                    self._mirror_exchange_unlocked(
                        record, messages,
                        context=effective_context,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        message_request=message_request,
                    )
                return record.model_copy(deep=True), [item.model_copy(deep=True) for item in messages]
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            if record.status == "archived":
                raise ConversationStoreError(
                    status_code=409,
                    code="CHAT_CONVERSATION_ARCHIVED",
                    message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
                )
            messages = list(self._messages.get(conversation_id, []))
            messages = [
                item for item in messages
                if item.message_id not in {user_message_id, assistant_message_id}
            ]
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
                agent_name=response.route.primary_agent,
                content=response.final_response_summary or response.route.summary,
                citations=list(dict.fromkeys(
                    c for ex in response.executions for c in ex.citations
                )),
                tool_calls=[tc for ex in response.executions for tc in ex.tool_calls],
                finish_reason=response.next_action,
                trace=trace,
            )
            messages.extend([user_message, assistant_message])
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
            self._messages[conversation_id] = messages
            self._contexts[conversation_id] = effective_context.model_copy(deep=True)
            self._request_snapshots[(conversation_id, user_message_id)] = message_request.model_copy(deep=True)
            self._assistant_to_user[(conversation_id, assistant_message_id)] = user_message_id
            self._persist_unlocked()
            return record.model_copy(deep=True), [user_message, assistant_message]

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
        self._cache.maybe_restore()
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else ConversationContextMerger.derive_next_session_context(
                self.get_context(conversation_id),
                message_request,
                response,
                max_recent_messages=self._max_recent_messages,
                compaction_summary=response.compaction_summary,
            )
        )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record, messages = backend.store_assistant_continuation(
                    conversation_id=conversation_id,
                    source_user_message_id=source_user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                    response=response,
                    status=status,
                    session_context=effective_context,
                    trace=trace,
                )
                self._cache.save_record(record, context=effective_context)
                self._cache.save_messages(record.conversation_id, messages)
                self._cache.save_request_snapshot(
                    record.conversation_id, source_user_message_id, message_request
                )
                self._cache.save_assistant_mapping(
                    record.conversation_id, assistant_message_id, source_user_message_id
                )
                with self._lock:
                    self._mirror_assistant_continuation_unlocked(
                        record, messages,
                        context=effective_context,
                        source_user_message_id=source_user_message_id,
                        assistant_message_id=assistant_message_id,
                        message_request=message_request,
                    )
                return record.model_copy(deep=True), [item.model_copy(deep=True) for item in messages]
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            if record.status == "archived":
                raise ConversationStoreError(
                    status_code=409,
                    code="CHAT_CONVERSATION_ARCHIVED",
                    message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
                )
            messages = [item.model_copy(deep=True) for item in self._messages.get(conversation_id, [])]
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
                citations=list(dict.fromkeys(
                    c for ex in response.executions for c in ex.citations
                )),
                tool_calls=[tc for ex in response.executions for tc in ex.tool_calls],
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
            self._messages[conversation_id] = messages
            self._contexts[conversation_id] = effective_context.model_copy(deep=True)
            self._request_snapshots[(conversation_id, source_user_message_id)] = message_request.model_copy(deep=True)
            self._assistant_to_user[(conversation_id, assistant_message_id)] = source_user_message_id
            self._persist_unlocked()
            return record.model_copy(deep=True), [item.model_copy(deep=True) for item in messages]

    def store_cancelled_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
        reason: str = "生成已取消。",
        session_context: SessionContext | None = None,
        trace: TraceContext | None = None,
    ) -> tuple[ConversationRecord, list[ChatMessageRecord]]:
        self._cache.maybe_restore()
        effective_context = (
            session_context.model_copy(deep=True)
            if session_context is not None
            else self.get_context(conversation_id) or SessionContext()
        )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record, messages = backend.store_cancelled_exchange(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                    reason=reason,
                    session_context=effective_context,
                    trace=trace,
                )
                self._cache.save_exchange(
                    record, messages,
                    context=effective_context,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    message_request=message_request,
                )
                with self._lock:
                    self._mirror_exchange_unlocked(
                        record, messages,
                        context=effective_context,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                        message_request=message_request,
                    )
                return record.model_copy(deep=True), [item.model_copy(deep=True) for item in messages]
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            messages = list(self._messages.get(conversation_id, []))
            messages = [
                item for item in messages
                if item.message_id not in {user_message_id, assistant_message_id}
            ]
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
                status="cancelled",
                created_at=now,
                updated_at=now,
                parent_message_id=user_message_id,
                content=reason,
                finish_reason="cancelled",
                trace=trace,
            )
            messages.extend([user_message, assistant_message])
            record.status = "active"
            record.summary = reason
            record.pending_actions = []
            record.last_message_at = assistant_message.updated_at
            record.updated_at = assistant_message.updated_at
            record.total_messages = len(messages)
            if not record.title:
                record.title = ConversationContextMerger.derive_title(message_request.user_query)
            self._messages[conversation_id] = messages
            self._contexts[conversation_id] = effective_context.model_copy(deep=True)
            self._request_snapshots[(conversation_id, user_message_id)] = message_request.model_copy(deep=True)
            self._assistant_to_user[(conversation_id, assistant_message_id)] = user_message_id
            self._persist_unlocked()
            return record.model_copy(deep=True), [user_message, assistant_message]

    def list_messages(
        self,
        conversation_id: str,
        *,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> SessionMessagesPage:
        self._cache.maybe_restore()
        cached_messages = self._cache.get_messages(conversation_id)
        if cached_messages:
            with self._lock:
                self._messages[conversation_id] = [item.model_copy(deep=True) for item in cached_messages]
            return self._build_message_page(cached_messages, cursor=cursor, page_size=page_size)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                items = backend.fetch_messages(conversation_id)
                if items:
                    self._cache.save_messages(conversation_id, items)
                    with self._lock:
                        self._messages[conversation_id] = [item.model_copy(deep=True) for item in items]
                    return self._build_message_page(items, cursor=cursor, page_size=page_size)
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            items = list(self._messages.get(conversation_id, []))
        if items:
            return self._build_message_page(items, cursor=cursor, page_size=page_size)
        self.require(conversation_id)
        return self._build_message_page([], cursor=cursor, page_size=page_size)

    def latest_message_id(
        self,
        conversation_id: str,
        *,
        role: str | None = None,
    ) -> str:
        self._cache.maybe_restore()
        self.require(conversation_id)
        cached_messages = self._cache.get_messages(conversation_id)
        if cached_messages is not None:
            with self._lock:
                self._messages[conversation_id] = [item.model_copy(deep=True) for item in cached_messages]
            return self._latest_message_id_from_items(
                cached_messages, conversation_id=conversation_id, role=role
            )
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                items = backend.fetch_messages(conversation_id)
                self._cache.save_messages(conversation_id, items)
                with self._lock:
                    self._messages[conversation_id] = [item.model_copy(deep=True) for item in items]
                return self._latest_message_id_from_items(items, conversation_id=conversation_id, role=role)
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        self.require(conversation_id)
        with self._lock:
            items = list(self._messages.get(conversation_id, []))
        return self._latest_message_id_from_items(items, conversation_id=conversation_id, role=role)

    def resolve_request_message_id(
        self,
        conversation_id: str,
        message_id: str,
    ) -> str:
        self._cache.maybe_restore()
        self.require(conversation_id)
        cached_mapping = self._cache.get_assistant_mapping(conversation_id, message_id)
        if cached_mapping is not None:
            with self._lock:
                self._assistant_to_user[(conversation_id, message_id)] = cached_mapping
            return cached_mapping
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                resolved = backend.resolve_request_message_id(conversation_id, message_id)
                if resolved != message_id:
                    self._cache.save_assistant_mapping(conversation_id, message_id, resolved)
                    with self._lock:
                        self._assistant_to_user[(conversation_id, message_id)] = resolved
                return resolved
            except Exception as exc:
                self._degrade_backend(exc)
        self.require(conversation_id)
        with self._lock:
            if (conversation_id, message_id) in self._assistant_to_user:
                return self._assistant_to_user[(conversation_id, message_id)]
        return message_id

    def build_retry_request(
        self,
        conversation_id: str,
        *,
        message_id: str,
        override_input: str | None = None,
    ) -> MessageRequest:
        self._cache.maybe_restore()
        user_message_id = self.resolve_request_message_id(conversation_id, message_id)
        cached_snapshot = self._cache.get_request_snapshot(conversation_id, user_message_id)
        if cached_snapshot is not None:
            return self._build_retry_request_from_snapshot(cached_snapshot, override_input=override_input)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                snapshot = backend.get_request_snapshot(conversation_id, message_id=user_message_id)
                if snapshot is None:
                    raise ConversationStoreError(
                        status_code=404,
                        code="CHAT_MESSAGE_NOT_FOUND",
                        message=f"Message '{message_id}' was not found in conversation '{conversation_id}'.",
                    )
                self._cache.save_request_snapshot(conversation_id, user_message_id, snapshot)
                if user_message_id != message_id:
                    self._cache.save_assistant_mapping(conversation_id, message_id, user_message_id)
                with self._lock:
                    self._request_snapshots[(conversation_id, user_message_id)] = snapshot.model_copy(deep=True)
                    if user_message_id != message_id:
                        self._assistant_to_user[(conversation_id, message_id)] = user_message_id
                return self._build_retry_request_from_snapshot(snapshot, override_input=override_input)
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            snapshot = self._request_snapshots.get((conversation_id, user_message_id))
        if snapshot is None:
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_MESSAGE_NOT_FOUND",
                message=f"Message '{message_id}' was not found in conversation '{conversation_id}'.",
            )
        return self._build_retry_request_from_snapshot(snapshot, override_input=override_input)
