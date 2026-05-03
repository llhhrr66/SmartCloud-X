from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Condition, RLock
import re

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|[A-Za-z0-9][A-Za-z0-9._:-]{7,127})$")


@dataclass(slots=True)
class ReservationResult:
    state: str
    response: object | None = None
    expires_at: datetime | None = None


class IdempotencyConflictError(RuntimeError):
    pass


class IdempotencyKeyValidationError(ValueError):
    pass


class IdempotencyCoordinator:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._inflight: dict[str, datetime] = {}
        self._completed: dict[str, tuple[object, datetime]] = {}

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def validate_key(self, key: str | None) -> str | None:
        if key in {None, ""}:
            return None
        normalized = str(key).strip()
        if not _IDEMPOTENCY_KEY_PATTERN.fullmatch(normalized):
            raise IdempotencyKeyValidationError(
                "Idempotency-Key must be a UUID or a stable token matching [A-Za-z0-9._:-]{8,128}."
            )
        return normalized

    def reserve(self, key: str | None) -> ReservationResult:
        normalized = self.validate_key(key)
        if normalized is None:
            return ReservationResult(state="disabled")
        now = datetime.now(UTC)
        with self._condition:
            self._prune(now)
            cached = self._completed.get(normalized)
            if cached is not None:
                response, expires_at = cached
                return ReservationResult(state="replay", response=response, expires_at=expires_at)
            if normalized in self._inflight:
                raise IdempotencyConflictError(f"Idempotency key '{normalized}' is already in flight.")
            expires_at = now + timedelta(seconds=self._ttl_seconds)
            self._inflight[normalized] = expires_at
            return ReservationResult(state="reserved", expires_at=expires_at)

    def store(self, key: str | None, response: object) -> datetime | None:
        normalized = self.validate_key(key)
        if normalized is None:
            return None
        with self._condition:
            expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
            self._completed[normalized] = (response, expires_at)
            self._inflight.pop(normalized, None)
            self._condition.notify_all()
            return expires_at

    def release(self, key: str | None) -> None:
        normalized = self.validate_key(key)
        if normalized is None:
            return
        with self._condition:
            self._inflight.pop(normalized, None)
            self._condition.notify_all()

    def stats(self) -> dict[str, int]:
        with self._condition:
            self._prune(datetime.now(UTC))
            return {"in_flight": len(self._inflight), "stored": len(self._completed)}

    def clear(self) -> None:
        with self._condition:
            self._inflight.clear()
            self._completed.clear()
            self._condition.notify_all()

    def _prune(self, now: datetime) -> None:
        expired_completed = [key for key, (_, expires_at) in self._completed.items() if expires_at <= now]
        for key in expired_completed:
            self._completed.pop(key, None)
        expired_inflight = [key for key, expires_at in self._inflight.items() if expires_at <= now]
        for key in expired_inflight:
            self._inflight.pop(key, None)


coordinator = IdempotencyCoordinator()
