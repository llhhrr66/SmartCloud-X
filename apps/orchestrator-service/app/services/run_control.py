from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Event, RLock

from app.services.runtime_redis import build_redis_client, normalize_namespace

RECOVERY_RETRY_SECONDS = 5.0


@dataclass
class ActiveRun:
    conversation_id: str
    message_id: str
    started_at: str
    cancelled: Event = field(default_factory=Event)


class ActiveRunConflictError(Exception):
    def __init__(self, *, conversation_id: str, message_id: str) -> None:
        super().__init__(f"Conversation '{conversation_id}' is already running message '{message_id}'.")
        self.conversation_id = conversation_id
        self.message_id = message_id


class OrchestrationCancelled(Exception):
    def __init__(self, *, conversation_id: str, message_id: str) -> None:
        super().__init__(f"Message '{message_id}' in conversation '{conversation_id}' was cancelled.")
        self.conversation_id = conversation_id
        self.message_id = message_id


class RunControlBackendUnavailableError(RuntimeError):
    pass


class OrchestrationRunControl:
    """Redis-backed run coordination with optional strict fail-closed mode."""

    def __init__(
        self,
        *,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:run-control",
        lease_seconds: int = 300,
        strict_backend: bool = False,
    ) -> None:
        self._lock = RLock()
        self._runs: dict[str, ActiveRun] = {}
        self._redis_url = redis_url
        self._redis_namespace = normalize_namespace(redis_namespace)
        self._lease_seconds = max(int(lease_seconds), 1)
        self._redis_client = build_redis_client(redis_url)
        self._backend_error: str | None = "Redis connection unavailable." if redis_url and self._redis_client is None else None
        self._next_recovery_attempt_at = 0.0
        self._strict_backend = bool(strict_backend and redis_url)

    def start(self, conversation_id: str, message_id: str) -> ActiveRun:
        self._maybe_restore_backend()
        self._require_backend()
        with self._lock:
            existing = self._runs.get(conversation_id)
            if existing is not None:
                raise ActiveRunConflictError(
                    conversation_id=conversation_id,
                    message_id=existing.message_id,
                )
            run = ActiveRun(
                conversation_id=conversation_id,
                message_id=message_id,
                started_at=self._now(),
            )
            self._claim_remote_run(run)
            self._require_backend()
            self._runs[conversation_id] = run
            return run

    def finish(self, conversation_id: str, message_id: str) -> None:
        self._maybe_restore_backend()
        with self._lock:
            existing = self._runs.get(conversation_id)
            if existing is None or existing.message_id != message_id:
                return
            self._runs.pop(conversation_id, None)
            self._release_remote_run(conversation_id, message_id)

    def cancel(self, conversation_id: str, message_id: str) -> bool:
        self._maybe_restore_backend()
        local_match = False
        with self._lock:
            run = self._runs.get(conversation_id)
            if run is not None and run.message_id == message_id:
                run.cancelled.set()
                local_match = True
        remote_match = self._cancel_remote_run(conversation_id, message_id)
        return local_match or remote_match

    def is_running(self, conversation_id: str, message_id: str | None = None) -> bool:
        self._maybe_restore_backend()
        with self._lock:
            local_run = self._runs.get(conversation_id)
            if local_run is not None:
                return message_id is None or local_run.message_id == message_id
        remote_run = self._read_remote_run(conversation_id)
        if remote_run is None:
            return False
        return message_id is None or remote_run.message_id == message_id

    def is_cancelled(self, conversation_id: str, message_id: str) -> bool:
        self._maybe_restore_backend()
        with self._lock:
            local_run = self._runs.get(conversation_id)
            if local_run is not None and local_run.message_id == message_id and local_run.cancelled.is_set():
                return True
        return self._remote_cancelled(conversation_id, message_id)

    def ensure_not_cancelled(self, conversation_id: str, message_id: str) -> None:
        self._maybe_restore_backend()
        self._require_backend()
        if self.is_cancelled(conversation_id, message_id):
            raise OrchestrationCancelled(
                conversation_id=conversation_id,
                message_id=message_id,
            )
        self._refresh_remote_run(conversation_id, message_id)
        self._require_backend()

    def clear(self) -> None:
        self._maybe_restore_backend()
        with self._lock:
            self._runs.clear()
        client = self._redis_client
        if client is None:
            return
        try:
            for key in client.scan_iter(match=f"{self._redis_namespace}:*"):
                client.delete(key)
        except Exception as exc:
            self._degrade_backend(exc)

    def describe_backend(self) -> dict[str, object]:
        self._maybe_restore_backend()
        if self._redis_client is not None:
            return {
                "backend": "redis-lock",
                "redisConfigured": bool(self._redis_url),
                "redisNamespace": self._redis_namespace if self._redis_url else None,
                "leaseSeconds": self._lease_seconds,
                "fallbackBackend": "memory",
                "activeRuns": len(self._runs),
                "strictBackend": self._strict_backend,
            }
        return {
            "backend": "memory",
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._redis_namespace if self._redis_url else None,
            "leaseSeconds": self._lease_seconds,
            "activeRuns": len(self._runs),
            "degradedFrom": "redis-lock" if self._backend_error else None,
            "backendError": self._backend_error,
            "strictBackend": self._strict_backend,
        }

    def _require_backend(self) -> None:
        if self._strict_backend and self._redis_url and self._redis_client is None:
            raise RunControlBackendUnavailableError(self._backend_error or "Redis connection unavailable.")

    def _maybe_restore_backend(self) -> None:
        if self._redis_client is not None or not self._redis_url:
            return
        now = time.monotonic()
        if now < self._next_recovery_attempt_at:
            return
        with self._lock:
            if self._redis_client is not None or not self._redis_url:
                return
            now = time.monotonic()
            if now < self._next_recovery_attempt_at:
                return
            client = build_redis_client(self._redis_url)
            if client is None:
                self._backend_error = "Redis connection unavailable."
                self._next_recovery_attempt_at = now + RECOVERY_RETRY_SECONDS
                return
            self._redis_client = client
            self._backend_error = None
            self._next_recovery_attempt_at = 0.0

    def _claim_remote_run(self, run: ActiveRun) -> None:
        client = self._redis_client
        if client is None:
            return
        key = self._active_key(run.conversation_id)
        payload = self._serialize_run(run)
        try:
            acquired = client.set(key, payload, nx=True, ex=self._lease_seconds)
        except Exception as exc:
            self._degrade_backend(exc)
            return
        if acquired:
            return
        existing = self._read_remote_run(run.conversation_id)
        if existing is None:
            try:
                client.delete(key)
                acquired = client.set(key, payload, nx=True, ex=self._lease_seconds)
            except Exception as exc:
                self._degrade_backend(exc)
                return
            if acquired:
                return
            existing = self._read_remote_run(run.conversation_id)
        raise ActiveRunConflictError(
            conversation_id=run.conversation_id,
            message_id=existing.message_id if existing is not None else run.message_id,
        )

    def _release_remote_run(self, conversation_id: str, message_id: str) -> None:
        client = self._redis_client
        if client is None:
            return
        active_run = self._read_remote_run(conversation_id)
        if active_run is None or active_run.message_id != message_id:
            return
        try:
            client.delete(self._active_key(conversation_id))
            client.delete(self._cancel_key(conversation_id, message_id))
        except Exception as exc:
            self._degrade_backend(exc)

    def _cancel_remote_run(self, conversation_id: str, message_id: str) -> bool:
        client = self._redis_client
        if client is None:
            return False
        active_run = self._read_remote_run(conversation_id)
        if active_run is None or active_run.message_id != message_id:
            return False
        try:
            client.set(
                self._cancel_key(conversation_id, message_id),
                "1",
                ex=self._lease_seconds,
            )
            client.expire(self._active_key(conversation_id), self._lease_seconds)
        except Exception as exc:
            self._degrade_backend(exc)
            return False
        return True

    def _remote_cancelled(self, conversation_id: str, message_id: str) -> bool:
        client = self._redis_client
        if client is None:
            return False
        try:
            payload = client.get(self._cancel_key(conversation_id, message_id))
        except Exception as exc:
            self._degrade_backend(exc)
            return False
        return bool(payload)

    def _refresh_remote_run(self, conversation_id: str, message_id: str) -> None:
        client = self._redis_client
        if client is None:
            return
        active_run = self._read_remote_run(conversation_id)
        if active_run is None:
            with self._lock:
                local_run = self._runs.get(conversation_id)
            if local_run is not None and local_run.message_id == message_id:
                try:
                    client.set(
                        self._active_key(conversation_id),
                        self._serialize_run(local_run),
                        nx=True,
                        ex=self._lease_seconds,
                    )
                    if local_run.cancelled.is_set():
                        client.set(
                            self._cancel_key(conversation_id, message_id),
                            "1",
                            ex=self._lease_seconds,
                        )
                except Exception as exc:
                    self._degrade_backend(exc)
                    return
                active_run = self._read_remote_run(conversation_id)
        if active_run is None or active_run.message_id != message_id:
            return
        try:
            client.expire(self._active_key(conversation_id), self._lease_seconds)
            client.expire(self._cancel_key(conversation_id, message_id), self._lease_seconds)
        except Exception as exc:
            self._degrade_backend(exc)

    def _read_remote_run(self, conversation_id: str) -> ActiveRun | None:
        client = self._redis_client
        if client is None:
            return None
        try:
            payload = client.get(self._active_key(conversation_id))
        except Exception as exc:
            self._degrade_backend(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            data = json.loads(payload)
            return ActiveRun(
                conversation_id=str(data.get("conversation_id") or conversation_id),
                message_id=str(data["message_id"]),
                started_at=str(data.get("started_at") or self._now()),
            )
        except Exception:
            try:
                client.delete(self._active_key(conversation_id))
            except Exception:
                pass
            return None

    def _degrade_backend(self, exc: Exception) -> None:
        self._redis_client = None
        self._backend_error = f"{exc.__class__.__name__}: {exc}"
        self._next_recovery_attempt_at = time.monotonic() + RECOVERY_RETRY_SECONDS

    def _active_key(self, conversation_id: str) -> str:
        return f"{self._redis_namespace}:active:{conversation_id}"

    def _cancel_key(self, conversation_id: str, message_id: str) -> str:
        return f"{self._redis_namespace}:cancel:{conversation_id}:{message_id}"

    @staticmethod
    def _serialize_run(run: ActiveRun) -> str:
        return json.dumps(
            {
                "conversation_id": run.conversation_id,
                "message_id": run.message_id,
                "started_at": run.started_at,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
