from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.models.compact import SessionMemoryRecord
from app.services.runtime_redis import build_redis_client, normalize_namespace

logger = logging.getLogger(__name__)

# Default TTL: 7 days
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600

# Recovery retry interval
_RECOVERY_RETRY_SECONDS = 5.0

# Key template: {namespace}:memory:{conversation_id}
_KEY_TEMPLATE = "{ns}:memory:{conversation_id}"


class SessionMemoryStore:
    """Redis-backed persistence for SessionMemoryRecord.

    Follows the same degradation/recovery pattern as other Redis stores
    in the orchestrator: on Redis failure, falls back to in-memory dict;
    periodically attempts to restore the Redis connection.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:session-memory",
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis_url = redis_url
        self._namespace = normalize_namespace(redis_namespace)
        self._ttl_seconds = ttl_seconds
        self._redis_client = build_redis_client(redis_url)
        self._fallback: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last_recovery_attempt: float = 0.0

    # ---- public API ----

    def get(self, conversation_id: str) -> SessionMemoryRecord | None:
        """Retrieve session memory for a conversation."""
        key = self._make_key(conversation_id)
        client = self._get_client()
        if client is not None:
            try:
                raw = client.get(key)
                if raw:
                    return SessionMemoryRecord.model_validate_json(raw)
                return None
            except Exception as exc:
                logger.error("session-memory Redis GET failed: %s", exc)
                self._mark_degraded()
        # Fallback: in-memory
        with self._lock:
            data = self._fallback.get(conversation_id)
            if data:
                return SessionMemoryRecord.model_validate(data)
        return None

    def put(self, record: SessionMemoryRecord) -> None:
        """Store or update session memory."""
        key = self._make_key(record.conversation_id)
        client = self._get_client()
        payload = record.model_dump(mode="json")
        if client is not None:
            try:
                client.set(key, json.dumps(payload, ensure_ascii=False), ex=self._ttl_seconds)
                # Also keep in fallback for read-during-degradation
                with self._lock:
                    self._fallback[record.conversation_id] = payload
                return
            except Exception as exc:
                logger.error("session-memory Redis SET failed: %s", exc)
                self._mark_degraded()
        # Fallback: in-memory only
        with self._lock:
            self._fallback[record.conversation_id] = payload

    def delete(self, conversation_id: str) -> None:
        """Delete session memory for a conversation."""
        key = self._make_key(conversation_id)
        client = self._get_client()
        if client is not None:
            try:
                client.delete(key)
            except Exception as exc:
                logger.error("session-memory Redis DELETE failed: %s", exc)
                self._mark_degraded()
        with self._lock:
            self._fallback.pop(conversation_id, None)

    # ---- internal ----

    def _make_key(self, conversation_id: str) -> str:
        return _KEY_TEMPLATE.format(ns=self._namespace, conversation_id=conversation_id)

    def _get_client(self):
        """Get Redis client, attempting recovery if needed."""
        if self._redis_client is not None:
            return self._redis_client
        self._maybe_restore_backend()
        return self._redis_client

    def _mark_degraded(self) -> None:
        """Mark Redis as unavailable; will retry later."""
        self._redis_client = None
        self._last_recovery_attempt = 0.0  # force immediate next retry

    def _maybe_restore_backend(self) -> None:
        """Periodically attempt to restore the Redis connection."""
        import time

        now = time.monotonic()
        if now - self._last_recovery_attempt < _RECOVERY_RETRY_SECONDS:
            return
        self._last_recovery_attempt = now
        client = build_redis_client(self._redis_url)
        if client is not None:
            logger.info("session-memory Redis backend restored")
            self._redis_client = client
