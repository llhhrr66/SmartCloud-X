from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, RLock


@dataclass
class ActiveRun:
    conversation_id: str
    message_id: str
    started_at: str
    cancelled: Event


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


class OrchestrationRunControl:
    """Process-local running-message registry with cooperative cancellation."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._runs: dict[str, ActiveRun] = {}

    def start(self, conversation_id: str, message_id: str) -> ActiveRun:
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
                cancelled=Event(),
            )
            self._runs[conversation_id] = run
            return run

    def finish(self, conversation_id: str, message_id: str) -> None:
        with self._lock:
            existing = self._runs.get(conversation_id)
            if existing is None or existing.message_id != message_id:
                return
            self._runs.pop(conversation_id, None)

    def cancel(self, conversation_id: str, message_id: str) -> bool:
        with self._lock:
            run = self._runs.get(conversation_id)
            if run is None or run.message_id != message_id:
                return False
            run.cancelled.set()
            return True

    def is_running(self, conversation_id: str, message_id: str | None = None) -> bool:
        with self._lock:
            run = self._runs.get(conversation_id)
            if run is None:
                return False
            return message_id is None or run.message_id == message_id

    def is_cancelled(self, conversation_id: str, message_id: str) -> bool:
        with self._lock:
            run = self._runs.get(conversation_id)
            if run is None or run.message_id != message_id:
                return False
            return run.cancelled.is_set()

    def ensure_not_cancelled(self, conversation_id: str, message_id: str) -> None:
        if self.is_cancelled(conversation_id, message_id):
            raise OrchestrationCancelled(
                conversation_id=conversation_id,
                message_id=message_id,
            )

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
