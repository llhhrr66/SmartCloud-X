from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    SessionContext,
    SessionMessagesPage,
)
from app.services.conversation_types import (
    RECOVERY_RETRY_SECONDS,
    ConversationStoreError,
    _ConversationSnapshotBundle,
)

if TYPE_CHECKING:
    from app.services.conversation_mysql_backend import _MySQLConversationBackend


class _ConversationPersistenceMixin:
    """Mixin providing local persistence, backend recovery, and in-memory mirror operations.

    Expects the host class (ConversationStore) to define:
      _lock, _file_path, _mysql_dsn, _mongo_runtime,
      _backend, _backend_error, _next_backend_recovery_at,
      _conversations, _messages, _contexts, _request_snapshots, _assistant_to_user,
      _cache (ConversationRuntimeCache)
    """

    # ------------------------------------------------------------------
    # Backend recovery
    # ------------------------------------------------------------------

    def _maybe_restore_backend(self) -> _MySQLConversationBackend | None:
        if self._backend is not None or not self._mysql_dsn:
            return self._backend
        now = time.monotonic()
        if now < self._next_backend_recovery_at:
            return None
        with self._lock:
            if self._backend is not None or not self._mysql_dsn:
                return self._backend
            now = time.monotonic()
            if now < self._next_backend_recovery_at:
                return None
            from app.services.conversation_mysql_backend import _MySQLConversationBackend
            backend = _MySQLConversationBackend(self._mysql_dsn, mongo_runtime=self._mongo_runtime)
            try:
                backend.ensure_ready()
            except Exception as exc:
                self._backend_error = f"{exc.__class__.__name__}: {exc}"
                self._next_backend_recovery_at = now + RECOVERY_RETRY_SECONDS
                self._persist_unlocked(force=True)
                return None
            self._backend = backend
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            self._bootstrap_backend_from_local_unlocked()
            self._cache.maybe_restore()
            self._cache.bootstrap_from_local(
                self._conversations,
                self._messages,
                self._contexts,
                self._request_snapshots,
                self._assistant_to_user,
            )
            self._persist_unlocked()
            return self._backend

    def _degrade_backend(self, exc: Exception) -> None:
        with self._lock:
            self._backend = None
            self._backend_error = f"{exc.__class__.__name__}: {exc}"
            self._next_backend_recovery_at = time.monotonic() + RECOVERY_RETRY_SECONDS
            self._persist_unlocked(force=True)

    def _bootstrap_backend_from_local_unlocked(self) -> None:
        backend = self._backend
        if backend is None or not self._conversations:
            return
        authoritative: dict = {
            "conversations": {},
            "messages": {},
            "contexts": {},
            "request_snapshots": {},
            "assistant_to_user": {},
        }
        for conversation_id, record in self._conversations.items():
            local_context = (
                self._contexts.get(conversation_id) or record.initial_context
            ).model_copy(deep=True)
            local_messages = [
                item.model_copy(deep=True) for item in self._messages.get(conversation_id, [])
            ]
            local_snapshots = {
                key: snap.model_copy(deep=True)
                for key, snap in self._request_snapshots.items()
                if key[0] == conversation_id
            }
            local_a2u = {
                key: val
                for key, val in self._assistant_to_user.items()
                if key[0] == conversation_id
            }
            remote = backend.export_snapshot(conversation_id)
            if remote is None or self._prefer_local_snapshot(
                local_record=record,
                local_message_count=len(local_messages),
                remote_record=remote.record,
                remote_message_count=len(remote.messages),
            ):
                backend.import_snapshot(
                    conversations={conversation_id: record.model_copy(deep=True)},
                    messages={conversation_id: local_messages},
                    contexts={conversation_id: local_context.model_copy(deep=True)},
                    request_snapshots={k: v.model_copy(deep=True) for k, v in local_snapshots.items()},
                    assistant_to_user=dict(local_a2u),
                )
                authoritative["conversations"][conversation_id] = record.model_copy(deep=True)
                authoritative["messages"][conversation_id] = local_messages
                authoritative["contexts"][conversation_id] = local_context.model_copy(deep=True)
                authoritative["request_snapshots"].update(local_snapshots)
                authoritative["assistant_to_user"].update(local_a2u)
            else:
                authoritative["conversations"][conversation_id] = remote.record.model_copy(deep=True)
                authoritative["messages"][conversation_id] = [
                    m.model_copy(deep=True) for m in remote.messages
                ]
                authoritative["contexts"][conversation_id] = remote.context.model_copy(deep=True)
                authoritative["request_snapshots"].update(
                    {k: v.model_copy(deep=True) for k, v in remote.request_snapshots.items()}
                )
                authoritative["assistant_to_user"].update(remote.assistant_to_user)
        self._conversations = authoritative["conversations"]
        self._messages = authoritative["messages"]
        self._contexts = authoritative["contexts"]
        self._request_snapshots = authoritative["request_snapshots"]
        self._assistant_to_user = authoritative["assistant_to_user"]

    @staticmethod
    def _prefer_local_snapshot(
        *,
        local_record: ConversationRecord,
        local_message_count: int,
        remote_record: ConversationRecord,
        remote_message_count: int,
    ) -> bool:
        local_ts = _ConversationPersistenceMixin._parse_timestamp(local_record.updated_at)
        remote_ts = _ConversationPersistenceMixin._parse_timestamp(remote_record.updated_at)
        if local_ts is not None and remote_ts is not None and local_ts != remote_ts:
            return local_ts > remote_ts
        if local_ts is not None and remote_ts is None:
            return True
        if remote_ts is not None and local_ts is None:
            return False
        if local_record.total_messages != remote_record.total_messages:
            return local_record.total_messages > remote_record.total_messages
        return local_message_count > remote_message_count

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Local file persistence
    # ------------------------------------------------------------------

    def _persist_unlocked(self, *, force: bool = False) -> None:
        if self._file_path is None:
            return
        if not force and self._backend is not None:
            self._remove_fallback_file_unlocked()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "conversations": {
                cid: rec.model_dump(mode="json")
                for cid, rec in self._conversations.items()
            },
            "messages": {
                cid: [item.model_dump(mode="json") for item in msgs]
                for cid, msgs in self._messages.items()
            },
            "contexts": {
                cid: ctx.model_dump(mode="json")
                for cid, ctx in self._contexts.items()
            },
            "request_snapshots": {
                f"{cid}::{mid}": snap.model_dump(mode="json")
                for (cid, mid), snap in self._request_snapshots.items()
            },
            "assistant_to_user": {
                f"{cid}::{aid}": uid
                for (cid, aid), uid in self._assistant_to_user.items()
            },
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._file_path.parent,
            prefix=f"{self._file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            tmp_path = Path(handle.name)
        tmp_path.replace(self._file_path)

    def _remove_fallback_file_unlocked(self) -> None:
        if self._file_path is None:
            return
        try:
            self._file_path.unlink()
        except (FileNotFoundError, OSError):
            return

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
            str(cid): ConversationRecord.model_validate(raw)
            for cid, raw in payload.get("conversations", {}).items()
        }
        self._messages = {
            str(cid): [
                ChatMessageRecord.model_validate(item)
                for item in raw_msgs
                if isinstance(item, dict)
            ]
            for cid, raw_msgs in payload.get("messages", {}).items()
            if isinstance(raw_msgs, list)
        }
        self._contexts = {
            str(cid): SessionContext.model_validate(raw)
            for cid, raw in payload.get("contexts", {}).items()
        }
        self._request_snapshots = {
            (cid, mid): MessageRequest.model_validate(raw)
            for composite, raw in payload.get("request_snapshots", {}).items()
            for cid, _, mid in [str(composite).partition("::")]
            if cid and mid
        }
        self._assistant_to_user = {
            (cid, aid): str(uid)
            for composite, uid in payload.get("assistant_to_user", {}).items()
            for cid, _, aid in [str(composite).partition("::")]
            if cid and aid
        }

    # ------------------------------------------------------------------
    # In-memory mirrors
    # ------------------------------------------------------------------

    def _mirror_record_unlocked(
        self,
        record: ConversationRecord,
        *,
        context: SessionContext,
    ) -> None:
        cid = record.conversation_id
        self._conversations[cid] = record.model_copy(deep=True)
        self._messages.setdefault(cid, [])
        self._contexts[cid] = context.model_copy(deep=True)
        self._persist_unlocked()

    def _mirror_exchange_unlocked(
        self,
        record: ConversationRecord,
        messages: list[ChatMessageRecord],
        *,
        context: SessionContext,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        cid = record.conversation_id
        self._conversations[cid] = record.model_copy(deep=True)
        self._messages[cid] = [item.model_copy(deep=True) for item in messages]
        self._contexts[cid] = context.model_copy(deep=True)
        self._request_snapshots[(cid, user_message_id)] = message_request.model_copy(deep=True)
        self._assistant_to_user[(cid, assistant_message_id)] = user_message_id
        self._persist_unlocked()

    def _mirror_assistant_continuation_unlocked(
        self,
        record: ConversationRecord,
        messages: list[ChatMessageRecord],
        *,
        context: SessionContext,
        source_user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        cid = record.conversation_id
        self._conversations[cid] = record.model_copy(deep=True)
        self._messages[cid] = [item.model_copy(deep=True) for item in messages]
        self._contexts[cid] = context.model_copy(deep=True)
        self._request_snapshots[(cid, source_user_message_id)] = message_request.model_copy(deep=True)
        self._assistant_to_user[(cid, assistant_message_id)] = source_user_message_id
        self._persist_unlocked()

    # ------------------------------------------------------------------
    # Static utilities shared with exchange operations
    # ------------------------------------------------------------------

    @staticmethod
    def _build_message_page(
        items: list[ChatMessageRecord],
        *,
        cursor: str | None,
        page_size: int,
    ) -> SessionMessagesPage:
        start_index = 0
        if cursor:
            for index, item in enumerate(items):
                if item.message_id == cursor:
                    start_index = index + 1
                    break
        page_items = items[start_index : start_index + page_size]
        has_more = start_index + page_size < len(items)
        return SessionMessagesPage(
            items=[item.model_copy(deep=True) for item in page_items],
            next_cursor=page_items[-1].message_id if has_more and page_items else None,
            has_more=has_more,
        )

    @staticmethod
    def _build_retry_request_from_snapshot(
        snapshot: MessageRequest,
        *,
        override_input: str | None,
    ) -> MessageRequest:
        return snapshot.model_copy(
            deep=True,
            update={"message_id": None, "user_query": override_input or snapshot.user_query, "trace": None},
        )

    @staticmethod
    def _latest_message_id_from_items(
        items: list[ChatMessageRecord],
        *,
        conversation_id: str,
        role: str | None,
    ) -> str:
        for item in reversed(items):
            if role is None or item.role == role:
                return item.message_id
        raise ConversationStoreError(
            status_code=404,
            code="CHAT_MESSAGE_NOT_FOUND",
            message=f"No messages were found in conversation '{conversation_id}'.",
        )
