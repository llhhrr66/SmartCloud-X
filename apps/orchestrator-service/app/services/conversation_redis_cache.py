from __future__ import annotations

import json
import time
from threading import RLock

from app.models.orchestration import (
    ChatMessageRecord,
    ConversationRecord,
    MessageRequest,
    SessionContext,
)
from app.services.runtime_redis import build_redis_client, normalize_namespace
from app.services.conversation_types import RECOVERY_RETRY_SECONDS


class ConversationRuntimeCache:
    """Redis-backed runtime cache for conversation data (Cache-Aside pattern).

    Falls back silently when Redis is unavailable; the store degrades to in-memory only.
    """

    def __init__(
        self,
        redis_url: str | None,
        namespace: str,
        lock: RLock,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = normalize_namespace(namespace)
        self._lock = lock
        self._client = build_redis_client(redis_url) if redis_url else None
        self._error: str | None = (
            "Redis connection unavailable." if redis_url and self._client is None else None
        )
        self._next_recovery_at = 0.0

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @property
    def error(self) -> str | None:
        return self._error

    # ------------------------------------------------------------------
    # Cache key builders
    # ------------------------------------------------------------------

    def _record_key(self, conversation_id: str) -> str:
        return f"{self._namespace}:conversation:{conversation_id}"

    def _context_key(self, conversation_id: str) -> str:
        return f"{self._namespace}:context:{conversation_id}"

    def _messages_key(self, conversation_id: str) -> str:
        return f"{self._namespace}:messages:{conversation_id}"

    def _request_snapshot_key(self, conversation_id: str, user_message_id: str) -> str:
        return f"{self._namespace}:request:{conversation_id}:{user_message_id}"

    def _assistant_mapping_key(self, conversation_id: str, assistant_message_id: str) -> str:
        return f"{self._namespace}:assistant:{conversation_id}:{assistant_message_id}"

    # ------------------------------------------------------------------
    # Readers
    # ------------------------------------------------------------------

    def get_record(self, conversation_id: str) -> ConversationRecord | None:
        if not self.enabled:
            return None
        client = self._client
        try:
            payload = client.get(self._record_key(conversation_id))
        except Exception as exc:
            self.degrade(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return ConversationRecord.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._record_key(conversation_id))
            except Exception:
                pass
            return None

    def get_context(self, conversation_id: str) -> SessionContext | None:
        if not self.enabled:
            return None
        client = self._client
        try:
            payload = client.get(self._context_key(conversation_id))
        except Exception as exc:
            self.degrade(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return SessionContext.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._context_key(conversation_id))
            except Exception:
                pass
            return None

    def get_messages(self, conversation_id: str) -> list[ChatMessageRecord] | None:
        if not self.enabled:
            return None
        client = self._client
        try:
            payload = client.get(self._messages_key(conversation_id))
        except Exception as exc:
            self.degrade(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            raw_items = json.loads(payload)
            if not isinstance(raw_items, list):
                raise ValueError("messages cache payload must be a list")
            return [
                ChatMessageRecord.model_validate(item)
                for item in raw_items
                if isinstance(item, dict)
            ]
        except Exception:
            try:
                client.delete(self._messages_key(conversation_id))
            except Exception:
                pass
            return None

    def get_request_snapshot(
        self,
        conversation_id: str,
        user_message_id: str,
    ) -> MessageRequest | None:
        if not self.enabled:
            return None
        client = self._client
        try:
            payload = client.get(self._request_snapshot_key(conversation_id, user_message_id))
        except Exception as exc:
            self.degrade(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return MessageRequest.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._request_snapshot_key(conversation_id, user_message_id))
            except Exception:
                pass
            return None

    def get_assistant_mapping(
        self,
        conversation_id: str,
        assistant_message_id: str,
    ) -> str | None:
        if not self.enabled:
            return None
        client = self._client
        try:
            payload = client.get(self._assistant_mapping_key(conversation_id, assistant_message_id))
        except Exception as exc:
            self.degrade(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        return payload

    # ------------------------------------------------------------------
    # Writers
    # ------------------------------------------------------------------

    def save_record(self, record: ConversationRecord, *, context: SessionContext) -> None:
        if not self.enabled:
            return
        client = self._client
        try:
            client.set(
                self._record_key(record.conversation_id),
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
            )
            client.set(
                self._context_key(record.conversation_id),
                json.dumps(context.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self.degrade(exc)

    def save_context(self, conversation_id: str, context: SessionContext) -> None:
        if not self.enabled:
            return
        client = self._client
        try:
            client.set(
                self._context_key(conversation_id),
                json.dumps(context.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self.degrade(exc)

    def save_messages(
        self,
        conversation_id: str,
        messages: list[ChatMessageRecord],
    ) -> None:
        if not self.enabled:
            return
        client = self._client
        try:
            client.set(
                self._messages_key(conversation_id),
                json.dumps([item.model_dump(mode="json") for item in messages], ensure_ascii=False),
            )
        except Exception as exc:
            self.degrade(exc)

    def save_request_snapshot(
        self,
        conversation_id: str,
        user_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        if not self.enabled:
            return
        client = self._client
        try:
            client.set(
                self._request_snapshot_key(conversation_id, user_message_id),
                json.dumps(message_request.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self.degrade(exc)

    def save_assistant_mapping(
        self,
        conversation_id: str,
        assistant_message_id: str,
        user_message_id: str,
    ) -> None:
        if not self.enabled:
            return
        client = self._client
        try:
            client.set(
                self._assistant_mapping_key(conversation_id, assistant_message_id),
                user_message_id,
            )
        except Exception as exc:
            self.degrade(exc)

    def save_exchange(
        self,
        record: ConversationRecord,
        messages: list[ChatMessageRecord],
        *,
        context: SessionContext,
        user_message_id: str,
        assistant_message_id: str,
        message_request: MessageRequest,
    ) -> None:
        self.save_record(record, context=context)
        self.save_messages(record.conversation_id, messages)
        self.save_request_snapshot(record.conversation_id, user_message_id, message_request)
        self.save_assistant_mapping(record.conversation_id, assistant_message_id, user_message_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bootstrap_from_local(
        self,
        conversations: dict[str, ConversationRecord],
        messages: dict[str, list[ChatMessageRecord]],
        contexts: dict[str, SessionContext],
        request_snapshots: dict[tuple[str, str], MessageRequest],
        assistant_to_user: dict[tuple[str, str], str],
    ) -> None:
        if not self.enabled or not conversations:
            return
        for conversation_id, record in conversations.items():
            context = contexts.get(conversation_id) or record.initial_context
            self.save_record(record.model_copy(deep=True), context=context.model_copy(deep=True))
            self.save_messages(
                conversation_id,
                [item.model_copy(deep=True) for item in messages.get(conversation_id, [])],
            )
        for (conversation_id, user_message_id), snapshot in request_snapshots.items():
            self.save_request_snapshot(
                conversation_id,
                user_message_id,
                snapshot.model_copy(deep=True),
            )
        for (conversation_id, asst_msg_id), user_message_id in assistant_to_user.items():
            self.save_assistant_mapping(conversation_id, asst_msg_id, user_message_id)

    def clear(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            for key in client.scan_iter(match=f"{self._namespace}:*"):
                client.delete(key)
        except Exception as exc:
            self.degrade(exc)

    def describe(self) -> dict[str, object]:
        return {
            "backend": "redis-json" if self.enabled else "memory",
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._namespace if self._redis_url else None,
            "degradedFrom": "redis-json" if self._error else None,
            "backendError": self._error,
        }

    def maybe_restore(self) -> None:
        if self._client is not None or not self._redis_url:
            return
        now = time.monotonic()
        if now < self._next_recovery_at:
            return
        with self._lock:
            if self._client is not None or not self._redis_url:
                return
            now = time.monotonic()
            if now < self._next_recovery_at:
                return
            client = build_redis_client(self._redis_url)
            if client is None:
                self._error = "Redis connection unavailable."
                self._next_recovery_at = now + RECOVERY_RETRY_SECONDS
                return
            self._client = client
            self._error = None
            self._next_recovery_at = 0.0

    def degrade(self, exc: Exception) -> None:
        with self._lock:
            self._client = None
            self._error = f"{exc.__class__.__name__}: {exc}"
            self._next_recovery_at = time.monotonic() + RECOVERY_RETRY_SECONDS
