from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.core.config import get_settings
from app.models.common import TraceContext
from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    OrchestratorResponse,
    SceneName,
    SessionContext,
    SessionCreateRequest,
    SessionMessagesPage,
)


class ConversationStoreError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class ConversationStore:
    """Process-local session/message store with optional file persistence."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        settings = get_settings()
        self._lock = RLock()
        self._conversations: dict[str, ConversationRecord] = {}
        self._messages: dict[str, list[ChatMessageRecord]] = {}
        self._contexts: dict[str, SessionContext] = {}
        self._request_snapshots: dict[tuple[str, str], MessageRequest] = {}
        self._assistant_to_user: dict[tuple[str, str], str] = {}
        self._max_recent_messages = max(settings.max_history_turns, 20)
        self._file_path: Path | None = None
        self.configure_persistence(file_path)

    def configure_persistence(self, file_path: str | Path | None) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._load_unlocked(path)

    def clear(self) -> None:
        with self._lock:
            self._conversations.clear()
            self._messages.clear()
            self._contexts.clear()
            self._request_snapshots.clear()
            self._assistant_to_user.clear()
            self._persist_unlocked()

    @property
    def max_recent_messages(self) -> int:
        return self._max_recent_messages

    def create(self, request: SessionCreateRequest) -> ConversationRecord:
        conversation_id = self.new_conversation_id()
        now = self._now()
        record = ConversationRecord(
            conversation_id=conversation_id,
            scene=request.scene,
            status="active",
            title=request.title,
            created_at=now,
            updated_at=now,
            initial_context=request.initial_context,
            pending_actions=[],
            total_messages=0,
        )
        with self._lock:
            self._conversations[conversation_id] = record
            self._messages[conversation_id] = []
            self._contexts[conversation_id] = request.initial_context.model_copy(deep=True)
            self._persist_unlocked()
        return record.model_copy(deep=True)

    def ensure(
        self,
        conversation_id: str,
        *,
        scene: SceneName,
        title: str | None = None,
        initial_context: SessionContext | None = None,
    ) -> ConversationRecord:
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                now = self._now()
                record = ConversationRecord(
                    conversation_id=conversation_id,
                    scene=scene,
                    status="active",
                    title=title,
                    created_at=now,
                    updated_at=now,
                    initial_context=initial_context or SessionContext(),
                    pending_actions=[],
                    total_messages=0,
                )
                self._conversations[conversation_id] = record
                self._messages[conversation_id] = []
                self._contexts[conversation_id] = (initial_context or SessionContext()).model_copy(deep=True)
                self._persist_unlocked()
            elif record.status == "archived":
                raise ConversationStoreError(
                    status_code=409,
                    code="CHAT_CONVERSATION_ARCHIVED",
                    message=f"Conversation '{conversation_id}' is archived and cannot accept new messages.",
                )
            elif record.status == "deleted":
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            return record.model_copy(deep=True)

    def get(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock:
            record = self._conversations.get(conversation_id)
            return record.model_copy(deep=True) if record else None

    def require(self, conversation_id: str) -> ConversationRecord:
        record = self.get(conversation_id)
        if record is None or record.status == "deleted":
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_CONVERSATION_NOT_FOUND",
                message=f"Conversation '{conversation_id}' was not found.",
            )
        return record

    def get_context(self, conversation_id: str) -> SessionContext | None:
        with self._lock:
            context = self._contexts.get(conversation_id)
            return context.model_copy(deep=True) if context else None

    def compose_context(
        self,
        conversation_id: str,
        incoming: SessionContext | None = None,
    ) -> SessionContext:
        base = self.get_context(conversation_id) or SessionContext()
        if incoming is not None and base.model_dump() == incoming.model_dump():
            return incoming.model_copy(deep=True)
        return self.merge_session_context(
            base,
            incoming,
            persist_confirmed_tool_names=True,
            max_recent_messages=self._max_recent_messages,
        )

    def list(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        scene: SceneName | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[ConversationRecord], int]:
        with self._lock:
            records = list(self._conversations.values())
        normalized_keyword = keyword.strip().lower() if keyword else None
        filtered = [
            record
            for record in records
            if record.status != "deleted"
            and (scene is None or record.scene == scene)
            and (status is None or record.status == status)
            and (
                normalized_keyword is None
                or normalized_keyword in record.conversation_id.lower()
                or normalized_keyword in (record.title or "").lower()
                or normalized_keyword in (record.summary or "").lower()
            )
        ]
        filtered.sort(key=lambda item: item.updated_at, reverse=True)
        total = len(filtered)
        start = max((page - 1) * page_size, 0)
        end = start + page_size
        return [item.model_copy(deep=True) for item in filtered[start:end]], total

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord:
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or record.status == "deleted":
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            record.title = title
            record.updated_at = self._now()
            self._persist_unlocked()
            return record.model_copy(deep=True)

    def archive(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "archived")

    def delete(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "deleted")

    def activate(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "active")

    def restore(self, conversation_id: str) -> ConversationRecord:
        record = self.require(conversation_id)
        if record.status != "archived":
            raise ConversationStoreError(
                status_code=409,
                code="CHAT_CONVERSATION_RESTORE_INVALID",
                message=f"Conversation '{conversation_id}' is not archived.",
            )
        return self._set_status(conversation_id, "active")

    def mark_running(
        self,
        conversation_id: str,
        *,
        scene: SceneName,
        title: str | None = None,
        initial_context: SessionContext | None = None,
    ) -> ConversationRecord:
        self.ensure(
            conversation_id,
            scene=scene,
            title=title,
            initial_context=initial_context,
        )
        return self._set_status(conversation_id, "running")

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
                item
                for item in messages
                if item.message_id not in {user_message_id, assistant_message_id}
            ]
            now = self._now()
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
                citations=list(
                    dict.fromkeys(
                        citation
                        for execution in response.executions
                        for citation in execution.citations
                    )
                ),
                tool_calls=[tool_call for execution in response.executions for tool_call in execution.tool_calls],
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
                record.title = self.derive_title(message_request.user_query)
            self._messages[conversation_id] = messages
            if session_context is not None:
                self._contexts[conversation_id] = session_context.model_copy(deep=True)
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
        self.require(conversation_id)
        with self._lock:
            items = list(self._messages.get(conversation_id, []))
        start_index = 0
        if cursor:
            for index, item in enumerate(items):
                if item.message_id == cursor:
                    start_index = index + 1
                    break
        page_items = items[start_index : start_index + page_size]
        has_more = start_index + page_size < len(items)
        next_cursor = page_items[-1].message_id if has_more and page_items else None
        return SessionMessagesPage(
            items=[item.model_copy(deep=True) for item in page_items],
            next_cursor=next_cursor,
            has_more=has_more,
        )

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
                item
                for item in messages
                if item.message_id not in {user_message_id, assistant_message_id}
            ]
            now = self._now()
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
                record.title = self.derive_title(message_request.user_query)
            self._messages[conversation_id] = messages
            if session_context is not None:
                self._contexts[conversation_id] = session_context.model_copy(deep=True)
            self._request_snapshots[(conversation_id, user_message_id)] = message_request.model_copy(deep=True)
            self._assistant_to_user[(conversation_id, assistant_message_id)] = user_message_id
            self._persist_unlocked()
            return record.model_copy(deep=True), [user_message, assistant_message]

    def build_retry_request(
        self,
        conversation_id: str,
        *,
        message_id: str,
        override_input: str | None = None,
    ) -> MessageRequest:
        user_message_id = message_id
        with self._lock:
            if (conversation_id, message_id) in self._assistant_to_user:
                user_message_id = self._assistant_to_user[(conversation_id, message_id)]
            snapshot = self._request_snapshots.get((conversation_id, user_message_id))
        if snapshot is None:
            raise ConversationStoreError(
                status_code=404,
                code="CHAT_MESSAGE_NOT_FOUND",
                message=f"Message '{message_id}' was not found in conversation '{conversation_id}'.",
            )
        return snapshot.model_copy(
            deep=True,
            update={
                "message_id": None,
                "user_query": override_input or snapshot.user_query,
                "trace": None,
            },
        )

    def latest_message_id(
        self,
        conversation_id: str,
        *,
        role: str | None = None,
    ) -> str:
        self.require(conversation_id)
        with self._lock:
            items = list(self._messages.get(conversation_id, []))
        for item in reversed(items):
            if role is None or item.role == role:
                return item.message_id
        raise ConversationStoreError(
            status_code=404,
            code="CHAT_MESSAGE_NOT_FOUND",
                message=f"No messages were found in conversation '{conversation_id}'.",
            )

    def resolve_request_message_id(
        self,
        conversation_id: str,
        message_id: str,
    ) -> str:
        self.require(conversation_id)
        with self._lock:
            if (conversation_id, message_id) in self._assistant_to_user:
                return self._assistant_to_user[(conversation_id, message_id)]
        return message_id

    @classmethod
    def merge_session_context(
        cls,
        base: SessionContext | None,
        override: SessionContext | None,
        *,
        persist_confirmed_tool_names: bool,
        max_recent_messages: int,
    ) -> SessionContext:
        base_context = base.model_copy(deep=True) if base else SessionContext()
        if override is None:
            if not persist_confirmed_tool_names:
                base_context.confirmed_tool_names = []
            return base_context

        merged = base_context.model_copy(deep=True)
        if override.history_summary:
            merged.history_summary = override.history_summary
        merged.recent_messages = cls._merge_recent_messages(
            merged.recent_messages,
            override.recent_messages,
            max_recent_messages=max_recent_messages,
        )
        merged.active_products = cls._dedupe_strings(
            [*merged.active_products, *override.active_products]
        )
        if override.open_ticket_id:
            merged.open_ticket_id = override.open_ticket_id
        merged.attributes = cls._merge_attributes(merged.attributes, override.attributes)
        if persist_confirmed_tool_names:
            merged.confirmed_tool_names = cls._dedupe_strings(
                [*merged.confirmed_tool_names, *override.confirmed_tool_names]
            )
        else:
            merged.confirmed_tool_names = []
        return merged

    @classmethod
    def derive_next_session_context(
        cls,
        base_context: SessionContext | None,
        message_request: MessageRequest,
        response: OrchestratorResponse,
        *,
        max_recent_messages: int,
    ) -> SessionContext:
        merged = cls.merge_session_context(
            base_context,
            message_request.session_context,
            persist_confirmed_tool_names=False,
            max_recent_messages=max_recent_messages,
        )
        assistant_summary = response.final_response_summary or response.route.summary
        merged.history_summary = cls._merge_history_summary(
            merged.history_summary,
            message_request.user_query,
            assistant_summary,
        )
        merged.recent_messages = cls._merge_recent_messages(
            merged.recent_messages,
            [
                {"role": "user", "content": cls._compact_text(message_request.user_query)},
                {
                    "role": "assistant",
                    "content": cls._compact_text(assistant_summary),
                    "agent": response.route.primary_agent,
                    "status": response.next_action,
                },
            ],
            max_recent_messages=max_recent_messages,
        )
        for execution in response.executions:
            for tool_call in execution.tool_calls:
                if tool_call.success:
                    cls._apply_session_context_patch(merged, tool_call.session_context_patch)
        merged.confirmed_tool_names = []
        return merged

    @classmethod
    def _apply_session_context_patch(cls, context: SessionContext, patch: dict[str, object]) -> None:
        if not patch:
            return
        history_summary = patch.get("history_summary")
        if isinstance(history_summary, str) and history_summary.strip():
            context.history_summary = history_summary.strip()
        context.recent_messages = cls._merge_recent_messages(
            context.recent_messages,
            patch.get("recent_messages") if isinstance(patch.get("recent_messages"), list) else [],
            max_recent_messages=20,
        )
        context.active_products = cls._dedupe_strings(
            [
                *context.active_products,
                *(
                    patch.get("active_products")
                    if isinstance(patch.get("active_products"), list)
                    else []
                ),
            ]
        )
        open_ticket_id = patch.get("open_ticket_id")
        if isinstance(open_ticket_id, str) and open_ticket_id.strip():
            context.open_ticket_id = open_ticket_id
        if isinstance(patch.get("attributes"), dict):
            context.attributes = cls._merge_attributes(
                context.attributes,
                patch["attributes"],  # type: ignore[arg-type]
            )

    @staticmethod
    def _merge_recent_messages(
        current: list[dict[str, object]],
        new_items: list[dict[str, object]],
        *,
        max_recent_messages: int,
    ) -> list[dict[str, object]]:
        merged = [dict(item) for item in current]
        merged.extend(dict(item) for item in new_items if isinstance(item, dict))
        if len(merged) <= max_recent_messages:
            return merged
        return merged[-max_recent_messages:]

    @staticmethod
    def _merge_attributes(base: dict[str, object], update: dict[str, object]) -> dict[str, object]:
        merged = dict(base)
        for key, value in update.items():
            existing_value = merged.get(key)
            if isinstance(value, dict) and isinstance(existing_value, dict):
                merged[key] = {**existing_value, **value}
            else:
                merged[key] = value
        return merged

    @staticmethod
    def _merge_history_summary(
        existing: str | None,
        user_query: str,
        assistant_summary: str,
    ) -> str:
        parts = [part.strip() for part in (existing or "").split(" | ") if part.strip()]
        parts.extend(
            [
                f"用户：{ConversationStore._compact_text(user_query, limit=72)}",
                f"助手：{ConversationStore._compact_text(assistant_summary, limit=96)}",
            ]
        )
        return " | ".join(parts[-6:])[:480]

    @staticmethod
    def _dedupe_strings(values: list[object]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    @staticmethod
    def _compact_text(value: object, *, limit: int = 80) -> str:
        text = " ".join(str(value or "").split())
        return text[:limit] if len(text) > limit else text

    @staticmethod
    def derive_title(user_query: str, *, max_length: int = 48) -> str:
        title = " ".join(user_query.strip().split())
        return title[:max_length] if len(title) > max_length else title

    @staticmethod
    def new_conversation_id() -> str:
        return f"conv_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def new_message_id() -> str:
        return f"msg_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def assistant_message_id(user_message_id: str) -> str:
        return f"asst_{user_message_id}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _set_status(self, conversation_id: str, status: str) -> ConversationRecord:
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or (record.status == "deleted" and status != "deleted"):
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            record.status = status  # type: ignore[assignment]
            record.updated_at = self._now()
            self._persist_unlocked()
            return record.model_copy(deep=True)

    def _persist_unlocked(self) -> None:
        if self._file_path is None:
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "conversations": {
                conversation_id: record.model_dump(mode="json")
                for conversation_id, record in self._conversations.items()
            },
            "messages": {
                conversation_id: [item.model_dump(mode="json") for item in messages]
                for conversation_id, messages in self._messages.items()
            },
            "contexts": {
                conversation_id: context.model_dump(mode="json")
                for conversation_id, context in self._contexts.items()
            },
            "request_snapshots": {
                f"{conversation_id}::{message_id}": snapshot.model_dump(mode="json")
                for (conversation_id, message_id), snapshot in self._request_snapshots.items()
            },
            "assistant_to_user": {
                f"{conversation_id}::{assistant_message_id}": user_message_id
                for (conversation_id, assistant_message_id), user_message_id in self._assistant_to_user.items()
            },
        }
        tmp_path = self._file_path.with_suffix(f"{self._file_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._file_path)

    def _load_unlocked(self, file_path: Path | None) -> None:
        self._conversations.clear()
        self._messages.clear()
        self._contexts.clear()
        self._request_snapshots.clear()
        self._assistant_to_user.clear()
        if file_path is None or not file_path.exists():
            return
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        self._conversations = {
            str(conversation_id): ConversationRecord.model_validate(raw_record)
            for conversation_id, raw_record in payload.get("conversations", {}).items()
        }
        self._messages = {
            str(conversation_id): [
                ChatMessageRecord.model_validate(item)
                for item in raw_messages
                if isinstance(item, dict)
            ]
            for conversation_id, raw_messages in payload.get("messages", {}).items()
            if isinstance(raw_messages, list)
        }
        self._contexts = {
            str(conversation_id): SessionContext.model_validate(raw_context)
            for conversation_id, raw_context in payload.get("contexts", {}).items()
        }
        self._request_snapshots = {
            (conversation_id, message_id): MessageRequest.model_validate(raw_snapshot)
            for composite_key, raw_snapshot in payload.get("request_snapshots", {}).items()
            for conversation_id, _, message_id in [str(composite_key).partition("::")]
            if conversation_id and message_id
        }
        self._assistant_to_user = {
            (conversation_id, assistant_message_id): str(user_message_id)
            for composite_key, user_message_id in payload.get("assistant_to_user", {}).items()
            for conversation_id, _, assistant_message_id in [str(composite_key).partition("::")]
            if conversation_id and assistant_message_id
        }
