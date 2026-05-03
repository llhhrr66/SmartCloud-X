from __future__ import annotations

import json
import re
import tempfile
import time
from pathlib import Path
from threading import RLock

from app.models.orchestration import MessageEventPage, StreamEventRecord
from app.services.runtime_redis import build_redis_client, normalize_namespace

RECOVERY_RETRY_SECONDS = 5.0


class SseEventStore:
    """SSE event store with Redis-list mainline persistence and local fallback."""

    EVENT_ID_PATTERN = re.compile(r"^evt-(\d+)$")

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:sse",
        ttl_seconds: int | None = 86400,
    ) -> None:
        self._lock = RLock()
        self._events: dict[tuple[str, str], list[StreamEventRecord]] = {}
        self._file_path: Path | None = None
        self._redis_url: str | None = None
        self._redis_namespace = normalize_namespace(redis_namespace)
        self._ttl_seconds = max(int(ttl_seconds), 1) if ttl_seconds and int(ttl_seconds) > 0 else None
        self._redis_client = None
        self._backend_error: str | None = None
        self._next_recovery_attempt_at = 0.0
        self.configure_persistence(
            file_path,
            redis_url=redis_url,
            redis_namespace=redis_namespace,
            ttl_seconds=ttl_seconds,
        )

    def configure_persistence(
        self,
        file_path: str | Path | None,
        *,
        redis_url: str | None = None,
        redis_namespace: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._redis_url = redis_url
            if redis_namespace:
                self._redis_namespace = normalize_namespace(redis_namespace)
            if ttl_seconds is not None:
                self._ttl_seconds = max(int(ttl_seconds), 1) if int(ttl_seconds) > 0 else None
            self._redis_client = build_redis_client(redis_url)
            self._backend_error = "Redis connection unavailable." if redis_url and self._redis_client is None else None
            self._next_recovery_attempt_at = 0.0
            self._events = self._load_events(path)
            self._bootstrap_redis_from_local_unlocked()
            self._persist_unlocked()

    def save(
        self,
        conversation_id: str,
        message_id: str,
        events: list[StreamEventRecord],
    ) -> list[StreamEventRecord]:
        self._maybe_restore_backend()
        stored_events = [event.model_copy(deep=True) for event in events]
        if self._save_to_redis(conversation_id, message_id, stored_events):
            with self._lock:
                self._events[(conversation_id, message_id)] = [event.model_copy(deep=True) for event in stored_events]
                self._persist_unlocked()
            return [event.model_copy(deep=True) for event in stored_events]
        with self._lock:
            self._events[(conversation_id, message_id)] = stored_events
            self._persist_unlocked()
        return [event.model_copy(deep=True) for event in stored_events]

    def get_page(
        self,
        conversation_id: str,
        message_id: str,
        *,
        after_event_id: str | None = None,
        limit: int = 100,
    ) -> MessageEventPage | None:
        self._maybe_restore_backend()
        redis_page = self._get_page_from_redis(
            conversation_id,
            message_id,
            after_event_id=after_event_id,
            limit=limit,
        )
        if redis_page is not None:
            return redis_page
        with self._lock:
            stored = self._events.get((conversation_id, message_id))
            if stored is None:
                return None
            events = [event.model_copy(deep=True) for event in stored]
        start_index = self._start_index(events, after_event_id)
        page_items = events[start_index : start_index + limit]
        has_more = start_index + limit < len(events)
        next_event_id = page_items[-1].event_id if has_more and page_items else None
        return MessageEventPage(
            conversation_id=conversation_id,
            message_id=message_id,
            items=page_items,
            next_event_id=next_event_id,
            has_more=has_more,
        )

    def clear(self) -> None:
        self._maybe_restore_backend()
        with self._lock:
            self._events.clear()
            self._persist_unlocked()
        client = self._redis_client
        if client is not None:
            try:
                for key in client.scan_iter(match=f"{self._redis_namespace}:*"):
                    client.delete(key)
            except Exception as exc:
                self._degrade_redis_backend(exc)

    def describe_backend(self) -> dict[str, object]:
        self._maybe_restore_backend()
        if self._redis_client is not None:
            return {
                "backend": "redis-list",
                "redisConfigured": bool(self._redis_url),
                "redisNamespace": self._redis_namespace if self._redis_url else None,
                "ttlSeconds": self._ttl_seconds,
                "fallbackBackend": "json-file" if self._file_path else "memory",
                "fallbackPath": str(self._file_path) if self._file_path else None,
                "fallbackWriteMode": "degraded-only",
            }
        return {
            "backend": "json-file" if self._file_path else "memory",
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._redis_namespace if self._redis_url else None,
            "ttlSeconds": self._ttl_seconds,
            "path": str(self._file_path) if self._file_path else None,
            "degradedFrom": "redis-list" if self._backend_error else None,
            "backendError": self._backend_error,
        }

    def _redis_key(self, conversation_id: str, message_id: str) -> str:
        return f"{self._redis_namespace}:{conversation_id}:{message_id}"

    def _save_to_redis(
        self,
        conversation_id: str,
        message_id: str,
        events: list[StreamEventRecord],
    ) -> bool:
        client = self._redis_client
        if client is None:
            return False
        key = self._redis_key(conversation_id, message_id)
        try:
            client.delete(key)
            if events:
                client.rpush(key, *[json.dumps(event.model_dump(mode="json"), ensure_ascii=False) for event in events])
                if self._ttl_seconds is not None:
                    client.expire(key, self._ttl_seconds)
        except Exception as exc:
            self._degrade_redis_backend(exc)
            return False
        return True

    def _get_page_from_redis(
        self,
        conversation_id: str,
        message_id: str,
        *,
        after_event_id: str | None,
        limit: int,
    ) -> MessageEventPage | None:
        client = self._redis_client
        if client is None:
            return None
        key = self._redis_key(conversation_id, message_id)
        try:
            bounded_page = self._get_bounded_page_from_redis(
                client,
                key,
                conversation_id=conversation_id,
                message_id=message_id,
                after_event_id=after_event_id,
                limit=limit,
            )
            if bounded_page is not None:
                return bounded_page
            payloads = client.lrange(key, 0, -1)
        except Exception as exc:
            self._degrade_redis_backend(exc)
            return None
        if not payloads:
            return None
        try:
            events = [StreamEventRecord.model_validate(json.loads(payload)) for payload in payloads]
        except Exception:
            try:
                client.delete(key)
            except Exception:
                pass
            return None
        start_index = self._start_index(events, after_event_id)
        page_items = events[start_index : start_index + limit]
        has_more = start_index + limit < len(events)
        next_event_id = page_items[-1].event_id if has_more and page_items else None
        return MessageEventPage(
            conversation_id=conversation_id,
            message_id=message_id,
            items=page_items,
            next_event_id=next_event_id,
            has_more=has_more,
        )

    def _load_events_from_redis(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[StreamEventRecord] | None:
        client = self._redis_client
        if client is None:
            return None
        key = self._redis_key(conversation_id, message_id)
        try:
            payloads = client.lrange(key, 0, -1)
        except Exception as exc:
            self._degrade_redis_backend(exc)
            return None
        if not payloads:
            return None
        try:
            return [StreamEventRecord.model_validate(json.loads(payload)) for payload in payloads]
        except Exception:
            try:
                client.delete(key)
            except Exception:
                pass
            return None

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
                self._persist_unlocked(force=True)
                return
            self._redis_client = client
            self._backend_error = None
            self._next_recovery_attempt_at = 0.0
            self._bootstrap_redis_from_local_unlocked()
            self._persist_unlocked()

    def _degrade_redis_backend(self, exc: Exception) -> None:
        with self._lock:
            self._redis_client = None
            self._backend_error = f"{exc.__class__.__name__}: {exc}"
            self._next_recovery_attempt_at = time.monotonic() + RECOVERY_RETRY_SECONDS
            self._persist_unlocked(force=True)

    def _bootstrap_redis_from_local_unlocked(self) -> None:
        if self._redis_client is None or not self._events:
            return
        authoritative: dict[tuple[str, str], list[StreamEventRecord]] = {}
        for (conversation_id, message_id), events in self._events.items():
            local_events = [event.model_copy(deep=True) for event in events]
            remote_events = self._load_events_from_redis(conversation_id, message_id)
            if remote_events is not None:
                if self._local_stream_extends_remote(local_events, remote_events):
                    if not self._save_to_redis(conversation_id, message_id, local_events):
                        return
                    authoritative[(conversation_id, message_id)] = [
                        event.model_copy(deep=True) for event in local_events
                    ]
                    continue
                authoritative[(conversation_id, message_id)] = [
                    event.model_copy(deep=True) for event in remote_events
                ]
                continue
            if not self._save_to_redis(
                conversation_id,
                message_id,
                local_events,
            ):
                return
            authoritative[(conversation_id, message_id)] = [
                event.model_copy(deep=True) for event in local_events
            ]
        self._events = authoritative

    @staticmethod
    def _local_stream_extends_remote(
        local_events: list[StreamEventRecord],
        remote_events: list[StreamEventRecord],
    ) -> bool:
        if len(local_events) <= len(remote_events):
            return False
        for index, remote_event in enumerate(remote_events):
            if local_events[index].model_dump(mode="json") != remote_event.model_dump(mode="json"):
                return False
        return True

    @staticmethod
    def _start_index(events: list[StreamEventRecord], after_event_id: str | None) -> int:
        if not after_event_id:
            return 0
        for index, event in enumerate(events):
            if event.event_id == after_event_id:
                return index + 1
        return 0

    def _persist_unlocked(self, *, force: bool = False) -> None:
        if self._file_path is None:
            return
        if not force and self._redis_client is not None:
            self._remove_fallback_file_unlocked()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "streams": {
                f"{conversation_id}::{message_id}": [event.model_dump(mode="json") for event in events]
                for (conversation_id, message_id), events in self._events.items()
            }
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
        except FileNotFoundError:
            return
        except OSError:
            return

    def _get_bounded_page_from_redis(
        self,
        client,
        key: str,
        *,
        conversation_id: str,
        message_id: str,
        after_event_id: str | None,
        limit: int,
    ) -> MessageEventPage | None:
        lrange = getattr(client, "lrange", None)
        llen = getattr(client, "llen", None)
        if not callable(lrange) or not callable(llen):
            return None
        start_index = self._bounded_start_index(after_event_id)
        if start_index is None:
            return None
        total_count = int(llen(key))
        if total_count <= 0:
            return None
        payloads = lrange(key, start_index, start_index + max(limit, 1) - 1)
        if not payloads:
            return MessageEventPage(
                conversation_id=conversation_id,
                message_id=message_id,
                items=[],
                next_event_id=None,
                has_more=False,
            )
        events = [StreamEventRecord.model_validate(json.loads(payload)) for payload in payloads]
        has_more = start_index + len(events) < total_count
        next_event_id = events[-1].event_id if has_more and events else None
        return MessageEventPage(
            conversation_id=conversation_id,
            message_id=message_id,
            items=events,
            next_event_id=next_event_id,
            has_more=has_more,
        )

    @classmethod
    def _bounded_start_index(cls, after_event_id: str | None) -> int | None:
        if after_event_id is None:
            return 0
        match = cls.EVENT_ID_PATTERN.fullmatch(after_event_id.strip())
        if match is None:
            return None
        return max(int(match.group(1)), 0)

    @staticmethod
    def _load_events(path: Path | None) -> dict[tuple[str, str], list[StreamEventRecord]]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        events: dict[tuple[str, str], list[StreamEventRecord]] = {}
        for composite_key, raw_events in payload.get("streams", {}).items():
            conversation_id, _, message_id = str(composite_key).partition("::")
            if not conversation_id or not message_id or not isinstance(raw_events, list):
                continue
            events[(conversation_id, message_id)] = [
                StreamEventRecord.model_validate(raw_event)
                for raw_event in raw_events
                if isinstance(raw_event, dict)
            ]
        return events
