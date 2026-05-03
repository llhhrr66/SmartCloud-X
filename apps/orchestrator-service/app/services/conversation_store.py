from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from app.core.config import get_settings
from app.models.orchestration import (
    ConversationRecord,
    SceneName,
    SessionContext,
    SessionCreateRequest,
)
from app.services._conversation_exchange_mixin import _ConversationExchangeMixin
from app.services._conversation_persistence_mixin import _ConversationPersistenceMixin
from app.services.conversation_context_merge import ConversationContextMerger
from app.services.conversation_mysql_backend import _MySQLConversationBackend
from app.services.conversation_redis_cache import ConversationRuntimeCache
from app.services.conversation_types import (
    RECOVERY_RETRY_SECONDS,  # noqa: F401 — re-exported for back-compat
    ConversationStoreError,
    _ConversationSnapshotBundle,  # noqa: F401
)
from app.services.mongo_runtime import ConversationMongoRuntimeError, DisabledConversationMongoRuntime
from app.services.runtime_redis import normalize_namespace


class ConversationStore(_ConversationExchangeMixin, _ConversationPersistenceMixin):
    """Session/message store with MySQL authority, Redis runtime cache, and JSON fallback.

    Architecture (Cache-Aside + Repository pattern):
      - _MySQLConversationBackend  — authority storage (MySQL)
      - ConversationRuntimeCache   — read-through Redis cache
      - In-memory dicts            — local mirror for degraded/test operation
      - JSON file                  — local durability when MySQL is unavailable
    """

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        mysql_dsn: str | None = None,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:conversation",
        mongo_runtime: DisabledConversationMongoRuntime | object | None = None,
    ) -> None:
        settings = get_settings()
        self._lock = RLock()
        self._conversations: dict[str, ConversationRecord] = {}
        self._messages: dict[str, list] = {}
        self._contexts: dict[str, SessionContext] = {}
        self._request_snapshots: dict[tuple[str, str], Any] = {}
        self._assistant_to_user: dict[tuple[str, str], str] = {}
        self._max_recent_messages = max(settings.max_history_turns, 20)
        self._file_path: Path | None = None
        self._mysql_dsn: str | None = None
        self._backend: _MySQLConversationBackend | None = None
        self._backend_error: str | None = None
        self._next_backend_recovery_at = 0.0
        self._mongo_runtime = mongo_runtime or DisabledConversationMongoRuntime()
        self._cache = ConversationRuntimeCache(None, redis_namespace, self._lock)
        self.configure_persistence(
            file_path,
            mysql_dsn=mysql_dsn,
            redis_url=redis_url,
            redis_namespace=redis_namespace,
        )

    def configure_persistence(
        self,
        file_path: str | Path | None,
        *,
        mysql_dsn: str | None = None,
        redis_url: str | None = None,
        redis_namespace: str | None = None,
    ) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._mysql_dsn = mysql_dsn
            self._backend = (
                _MySQLConversationBackend(mysql_dsn, mongo_runtime=self._mongo_runtime)
                if mysql_dsn else None
            )
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            ns = normalize_namespace(redis_namespace) if redis_namespace else self._cache._namespace
            self._cache = ConversationRuntimeCache(
                redis_url if self._backend is not None else None,
                ns,
                self._lock,
            )
            self._load_unlocked(path)
            if self._backend is not None:
                try:
                    self._backend.ensure_ready()
                    self._bootstrap_backend_from_local_unlocked()
                    self._cache.bootstrap_from_local(
                        self._conversations,
                        self._messages,
                        self._contexts,
                        self._request_snapshots,
                        self._assistant_to_user,
                    )
                    self._persist_unlocked()
                except Exception as exc:
                    self._degrade_backend(exc)

    def configure_mongo_runtime(self, runtime: Any) -> None:
        with self._lock:
            self._mongo_runtime = runtime or DisabledConversationMongoRuntime()
            if self._backend is not None:
                self._backend._mongo_runtime = self._mongo_runtime

    @staticmethod
    def _document_store_error(exc: ConversationMongoRuntimeError) -> ConversationStoreError:
        return ConversationStoreError(
            status_code=503,
            code="CHAT_DOCUMENT_STORE_UNAVAILABLE",
            message=str(exc),
        )

    def clear(self) -> None:
        self._cache.maybe_restore()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                backend.clear()
                self._cache.clear()
                with self._lock:
                    self._conversations.clear()
                    self._messages.clear()
                    self._contexts.clear()
                    self._request_snapshots.clear()
                    self._assistant_to_user.clear()
                    self._persist_unlocked()
                return
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            self._conversations.clear()
            self._messages.clear()
            self._contexts.clear()
            self._request_snapshots.clear()
            self._assistant_to_user.clear()
            self._persist_unlocked()
        self._cache.clear()

    @property
    def max_recent_messages(self) -> int:
        return self._max_recent_messages

    def create(self, request: SessionCreateRequest) -> ConversationRecord:
        self._cache.maybe_restore()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.create(request).model_copy(deep=True)
                self._cache.save_record(record, context=request.initial_context)
                with self._lock:
                    self._mirror_record_unlocked(record, context=request.initial_context.model_copy(deep=True))
                return record
            except Exception as exc:
                self._degrade_backend(exc)
        conversation_id = ConversationContextMerger.new_conversation_id()
        now = ConversationContextMerger.now()
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
        self._cache.maybe_restore()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.ensure(
                    conversation_id, scene=scene, title=title, initial_context=initial_context
                ).model_copy(deep=True)
                context = backend.get_context(conversation_id) or initial_context or record.initial_context
                self._cache.save_record(record, context=context)
                with self._lock:
                    self._mirror_record_unlocked(record, context=context.model_copy(deep=True))
                return record
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None:
                now = ConversationContextMerger.now()
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
        self._cache.maybe_restore()
        cached = self._cache.get_record(conversation_id)
        if cached is not None:
            with self._lock:
                self._conversations[conversation_id] = cached.model_copy(deep=True)
            return cached.model_copy(deep=True)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.get(conversation_id)
                if record is not None:
                    context = (
                        backend.get_context(conversation_id)
                        or self._contexts.get(conversation_id)
                        or record.initial_context
                    )
                    self._cache.save_record(record, context=context)
                    with self._lock:
                        self._conversations[conversation_id] = record.model_copy(deep=True)
                        self._contexts[conversation_id] = context.model_copy(deep=True)
                return record.model_copy(deep=True) if record else None
            except Exception as exc:
                self._degrade_backend(exc)
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
        self._cache.maybe_restore()
        cached = self._cache.get_context(conversation_id)
        if cached is not None:
            with self._lock:
                self._contexts[conversation_id] = cached.model_copy(deep=True)
            return cached.model_copy(deep=True)
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                context = backend.get_context(conversation_id)
                if context is not None:
                    self._cache.save_context(conversation_id, context)
                    with self._lock:
                        self._contexts[conversation_id] = context.model_copy(deep=True)
                return context.model_copy(deep=True) if context else None
            except Exception as exc:
                self._degrade_backend(exc)
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
        return ConversationContextMerger.merge_session_context(
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
        self._cache.maybe_restore()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                items, total = backend.list(
                    page=page, page_size=page_size, scene=scene, status=status, keyword=keyword
                )
                return [item.model_copy(deep=True) for item in items], total
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            records = list(self._conversations.values())
        normalized_keyword = keyword.strip().lower() if keyword else None
        filtered = [
            r for r in records
            if r.status != "deleted"
            and (scene is None or r.scene == scene)
            and (status is None or r.status == status)
            and (
                normalized_keyword is None
                or normalized_keyword in r.conversation_id.lower()
                or normalized_keyword in (r.title or "").lower()
                or normalized_keyword in (r.summary or "").lower()
            )
        ]
        filtered.sort(key=lambda r: r.updated_at, reverse=True)
        total = len(filtered)
        start = max((page - 1) * page_size, 0)
        return [r.model_copy(deep=True) for r in filtered[start : start + page_size]], total

    def update_title(self, conversation_id: str, title: str) -> ConversationRecord:
        self._cache.maybe_restore()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.update_title(conversation_id, title).model_copy(deep=True)
                context = (
                    backend.get_context(conversation_id)
                    or self._contexts.get(conversation_id)
                    or record.initial_context
                )
                self._cache.save_record(record, context=context)
                with self._lock:
                    self._mirror_record_unlocked(record, context=context)
                return record
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or record.status == "deleted":
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            record.title = title
            record.updated_at = ConversationContextMerger.now()
            self._persist_unlocked()
            return record.model_copy(deep=True)

    def archive(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "archived")

    def delete(self, conversation_id: str) -> ConversationRecord:
        return self._set_status(conversation_id, "deleted")

    def soft_delete(self, conversation_id: str) -> ConversationRecord:
        return self.delete(conversation_id)

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
        self.ensure(conversation_id, scene=scene, title=title, initial_context=initial_context)
        return self._set_status(conversation_id, "running")

    def _set_status(self, conversation_id: str, status: str) -> ConversationRecord:
        self._cache.maybe_restore()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.set_status(conversation_id, status).model_copy(deep=True)
                context = (
                    backend.get_context(conversation_id)
                    or self._contexts.get(conversation_id)
                    or record.initial_context
                )
                self._cache.save_record(record, context=context)
                with self._lock:
                    self._mirror_record_unlocked(record, context=context)
                return record
            except ConversationStoreError:
                raise
            except ConversationMongoRuntimeError as exc:
                raise self._document_store_error(exc) from exc
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            record = self._conversations.get(conversation_id)
            if record is None or record.status == "deleted":
                raise ConversationStoreError(
                    status_code=404,
                    code="CHAT_CONVERSATION_NOT_FOUND",
                    message=f"Conversation '{conversation_id}' was not found.",
                )
            record.status = status  # type: ignore[assignment]
            record.updated_at = ConversationContextMerger.now()
            self._persist_unlocked()
            return record.model_copy(deep=True)

    def describe_backend(self) -> dict[str, object]:
        self._cache.maybe_restore()
        self._maybe_restore_backend()
        runtime_cache = self._cache.describe()
        backend = self._backend
        if backend is not None:
            description = backend.describe_backend()
            description["fallbackBackend"] = "json-file" if self._file_path else "memory"
            description["fallbackPath"] = str(self._file_path) if self._file_path else None
            description["fallbackWriteMode"] = "degraded-only"
            description.setdefault("documentStore", self._mongo_runtime.describe_backend())
            description["runtimeCache"] = runtime_cache
            return description
        return {
            "backend": "json-file" if self._file_path else "memory",
            "configured": self._file_path is not None,
            "path": str(self._file_path) if self._file_path else None,
            "degradedFrom": "mysql" if self._backend_error else None,
            "backendError": self._backend_error,
            "documentStore": self._mongo_runtime.describe_backend(),
            "runtimeCache": runtime_cache,
        }

    # ------------------------------------------------------------------
    # Backward-compatible static aliases (used by orchestration routes)
    # ------------------------------------------------------------------

    merge_session_context = staticmethod(ConversationContextMerger.merge_session_context)
    derive_next_session_context = staticmethod(ConversationContextMerger.derive_next_session_context)
    _apply_session_context_patch = staticmethod(ConversationContextMerger._apply_session_context_patch)
    derive_title = staticmethod(ConversationContextMerger.derive_title)
    new_conversation_id = staticmethod(ConversationContextMerger.new_conversation_id)
    new_message_id = staticmethod(ConversationContextMerger.new_message_id)
    assistant_message_id = staticmethod(ConversationContextMerger.assistant_message_id)

    @staticmethod
    def _now() -> str:
        return ConversationContextMerger.now()

    # ------------------------------------------------------------------
    # Cache key proxies (backward-compat for tests)
    # ------------------------------------------------------------------

    @property
    def _next_cache_recovery_at(self) -> float:
        return self._cache._next_recovery_at

    @_next_cache_recovery_at.setter
    def _next_cache_recovery_at(self, value: float) -> None:
        self._cache._next_recovery_at = value

    def _record_cache_key(self, conversation_id: str) -> str:
        return self._cache._record_key(conversation_id)

    def _context_cache_key(self, conversation_id: str) -> str:
        return self._cache._context_key(conversation_id)

    def _messages_cache_key(self, conversation_id: str) -> str:
        return self._cache._messages_key(conversation_id)

    def _request_snapshot_cache_key(self, conversation_id: str, user_message_id: str) -> str:
        return self._cache._request_snapshot_key(conversation_id, user_message_id)

    def _assistant_mapping_cache_key(self, conversation_id: str, assistant_message_id: str) -> str:
        return self._cache._assistant_mapping_key(conversation_id, assistant_message_id)
