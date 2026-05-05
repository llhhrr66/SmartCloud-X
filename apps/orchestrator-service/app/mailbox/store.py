from __future__ import annotations

import json
import time
from threading import RLock

from app.services.runtime_redis import build_redis_client, normalize_namespace

from .mailbox import AgentMessage

RECOVERY_RETRY_SECONDS = 5.0
DEFAULT_TTL_SECONDS = 86400  # 24h


class MemoryMailbox:
    """In-memory fallback store when Redis is unavailable."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._boxes: dict[str, list[dict]] = {}

    def write(self, agent_id: str, message: AgentMessage) -> None:
        with self._lock:
            if agent_id not in self._boxes:
                self._boxes[agent_id] = []
            self._boxes[agent_id].append(message.model_dump(mode="json"))

    def read(self, agent_id: str) -> list[AgentMessage]:
        with self._lock:
            raw = self._boxes.get(agent_id, [])
            return [AgentMessage.model_validate(m) for m in raw]

    def broadcast(self, message: AgentMessage) -> list[str]:
        with self._lock:
            rids = list(self._boxes.keys())
            for aid in rids:
                self.write(aid, message)
            return rids

    def count(self, agent_id: str) -> int:
        with self._lock:
            return len(self._boxes.get(agent_id, []))

    def clear(self) -> None:
        with self._lock:
            self._boxes.clear()


class RedisMailbox:
    """Redis-backed persistent Mailbox store.

    Keys:
        mailbox:{agent_id}       -> Redis List (RPUSH / LRANGE)
        mailbox:_broadcast_set   -> Redis Set (all agent IDs with mailboxes)
    """

    def __init__(
        self,
        redis_url: str,
        *,
        redis_namespace: str = "smartcloud:mailbox",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._redis_url = redis_url
        self._redis_namespace = normalize_namespace(redis_namespace)
        self._ttl_seconds = max(int(ttl_seconds), 1) if ttl_seconds else None
        self._redis_client = build_redis_client(redis_url)
        self._backend_error: str | None = (
            "Redis connection unavailable."
            if redis_url and self._redis_client is None
            else None
        )
        self._next_recovery_attempt_at = 0.0

    @property
    def available(self) -> bool:
        return self._redis_client is not None

    def _key(self, agent_id: str) -> str:
        return f"{self._redis_namespace}:mailbox:{agent_id}"

    def _broadcast_set_key(self) -> str:
        return f"{self._redis_namespace}:_broadcast_set"

    def write(self, agent_id: str, message: AgentMessage) -> None:
        self._maybe_restore_backend()
        client = self._redis_client
        if client is None:
            return
        payload = json.dumps(message.model_dump(mode="json"), ensure_ascii=False)
        try:
            client.rpush(self._key(agent_id), payload)
            if self._ttl_seconds is not None:
                client.expire(self._key(agent_id), self._ttl_seconds)
            client.sadd(self._broadcast_set_key(), agent_id)
            if self._ttl_seconds is not None:
                client.expire(self._broadcast_set_key(), self._ttl_seconds)
        except Exception as exc:
            self._degrade_backend(exc)

    def read(self, agent_id: str) -> list[AgentMessage]:
        self._maybe_restore_backend()
        client = self._redis_client
        if client is None:
            return []
        try:
            payloads = client.lrange(self._key(agent_id), 0, -1)
        except Exception as exc:
            self._degrade_backend(exc)
            return []
        if not payloads:
            return []
        msgs: list[AgentMessage] = []
        for p in payloads:
            try:
                msgs.append(AgentMessage.model_validate(json.loads(p)))
            except Exception:
                continue
        return msgs

    def broadcast(self, message: AgentMessage) -> list[str]:
        self._maybe_restore_backend()
        client = self._redis_client
        if client is None:
            return []
        try:
            agent_ids = list(client.smembers(self._broadcast_set_key()))
        except Exception as exc:
            self._degrade_backend(exc)
            return []
        for aid in agent_ids:
            self.write(aid, message)
        return agent_ids

    def count(self, agent_id: str) -> int:
        self._maybe_restore_backend()
        client = self._redis_client
        if client is None:
            return 0
        try:
            return client.llen(self._key(agent_id))
        except Exception as exc:
            self._degrade_backend(exc)
            return 0

    def clear(self) -> None:
        self._maybe_restore_backend()
        client = self._redis_client
        if client is None:
            return
        try:
            for key in client.scan_iter(
                match=f"{self._redis_namespace}:mailbox:*"
            ):
                client.delete(key)
            client.delete(self._broadcast_set_key())
        except Exception as exc:
            self._degrade_backend(exc)

    def _maybe_restore_backend(self) -> None:
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

    def _degrade_backend(self, exc: Exception) -> None:
        self._redis_client = None
        self._backend_error = f"{exc.__class__.__name__}: {exc}"
        self._next_recovery_attempt_at = time.monotonic() + RECOVERY_RETRY_SECONDS


def build_mailbox_store(
    redis_url: str | None = None,
    *,
    redis_namespace: str = "smartcloud:mailbox",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
):
    """Factory: returns RedisMailbox if Redis available, else MemoryMailbox."""
    if redis_url:
        box = RedisMailbox(
            redis_url, redis_namespace=redis_namespace, ttl_seconds=ttl_seconds
        )
        if box.available:
            return box
    return MemoryMailbox()