from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from business_tools.interfaces import ToolExecutionContext, ToolExecutionResult
from business_tools.runtime_backend import build_redis_client, clear_namespace, normalize_namespace

RECOVERY_RETRY_SECONDS = 5.0


@dataclass
class StoredToolQueryResult:
    fingerprint: str
    expires_at: float
    result: ToolExecutionResult


class ToolQueryCacheStore:
    """Query-result cache with Redis-first runtime persistence and local fallback."""

    def __init__(
        self,
        persistence_path: str | Path | None = None,
        *,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:business-tools:query-cache",
    ) -> None:
        self._lock = RLock()
        self._records: dict[tuple[str, str], StoredToolQueryResult] = {}
        self._enabled = True
        self._ttl_cap_seconds = 300
        self._persistence_path: Path | None = None
        self._redis_url: str | None = None
        self._redis_namespace = normalize_namespace(redis_namespace)
        self._redis_client = None
        self._backend_error: str | None = None
        self._next_recovery_attempt_at = 0.0
        self.configure_persistence(
            persistence_path,
            redis_url=redis_url,
            redis_namespace=redis_namespace,
        )

    def configure(self, *, enabled: bool, ttl_cap_seconds: int | None = None) -> None:
        with self._lock:
            self._enabled = enabled
            if ttl_cap_seconds is not None:
                self._ttl_cap_seconds = ttl_cap_seconds
            if not enabled:
                self._records.clear()
            self._persist_unlocked()
        if not enabled:
            client = self._redis_client
            if client is not None:
                try:
                    clear_namespace(client, self._redis_namespace)
                except Exception as exc:
                    self._degrade_backend(exc)

    def configure_persistence(
        self,
        persistence_path: str | Path | None,
        *,
        redis_url: str | None = None,
        redis_namespace: str | None = None,
    ) -> None:
        path = Path(persistence_path).expanduser() if persistence_path else None
        with self._lock:
            self._persistence_path = path
            self._redis_url = redis_url
            if redis_namespace:
                self._redis_namespace = normalize_namespace(redis_namespace)
            self._redis_client = build_redis_client(redis_url)
            self._backend_error = "Redis connection unavailable." if redis_url and self._redis_client is None else None
            self._next_recovery_attempt_at = 0.0
            self._records = self._load_records(path)
            self._bootstrap_redis_from_local_unlocked()
            self._persist_unlocked()

    def get(
        self,
        tool_name: str,
        operation: str,
        payload: dict,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult | None:
        if not self._enabled:
            return None
        self._maybe_restore_backend()
        fingerprint = self._fingerprint(tool_name, operation, payload, context)
        redis_entry = self._get_from_redis(tool_name, fingerprint)
        if redis_entry is not None:
            redis_result, ttl_seconds = redis_entry
            if ttl_seconds is not None:
                with self._lock:
                    self._records[(tool_name, fingerprint)] = StoredToolQueryResult(
                        fingerprint=fingerprint,
                        expires_at=time.time() + ttl_seconds,
                        result=redis_result.model_copy(deep=True),
                    )
            if "cache-hit" not in redis_result.audit_tags:
                redis_result.audit_tags.append("cache-hit")
            return redis_result
        now = time.time()
        with self._lock:
            record = self._records.get((tool_name, fingerprint))
            if record is None:
                return None
            if record.expires_at <= now:
                self._records.pop((tool_name, fingerprint), None)
                self._persist_unlocked()
                return None
            replay = record.result.model_copy(deep=True)
        if "cache-hit" not in replay.audit_tags:
            replay.audit_tags.append("cache-hit")
        return replay

    def save(
        self,
        tool_name: str,
        operation: str,
        payload: dict,
        context: ToolExecutionContext,
        ttl_seconds: int | None,
        result: ToolExecutionResult,
    ) -> ToolExecutionResult:
        if not self._enabled or ttl_seconds is None or ttl_seconds <= 0 or not result.success:
            return result
        self._maybe_restore_backend()
        effective_ttl = ttl_seconds
        if self._ttl_cap_seconds > 0:
            effective_ttl = min(ttl_seconds, self._ttl_cap_seconds)
        fingerprint = self._fingerprint(tool_name, operation, payload, context)
        stored = result.model_copy(deep=True)
        if self._save_to_redis(tool_name, fingerprint, effective_ttl, stored):
            with self._lock:
                self._records[(tool_name, fingerprint)] = StoredToolQueryResult(
                    fingerprint=fingerprint,
                    expires_at=time.time() + effective_ttl,
                    result=stored.model_copy(deep=True),
                )
                self._persist_unlocked()
            return result
        with self._lock:
            self._records[(tool_name, fingerprint)] = StoredToolQueryResult(
                fingerprint=fingerprint,
                expires_at=time.time() + effective_ttl,
                result=stored,
            )
            self._persist_unlocked()
        return result

    def clear(self) -> None:
        self._maybe_restore_backend()
        with self._lock:
            self._records.clear()
            self._persist_unlocked()
        client = self._redis_client
        if client is not None:
            try:
                clear_namespace(client, self._redis_namespace)
            except Exception as exc:
                self._degrade_backend(exc)

    def describe_backend(self) -> dict[str, object]:
        self._maybe_restore_backend()
        return {
            "backend": "redis-ttl" if self._redis_client is not None else ("json-file" if self._persistence_path else "memory-ttl"),
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._redis_namespace if self._redis_url else None,
            "enabled": self._enabled,
            "fallbackPath": str(self._persistence_path) if self._persistence_path else None,
            "fallbackWriteMode": "degraded-only" if self._redis_client is not None and self._redis_url else "active",
            "degradedFrom": "redis-ttl" if self._backend_error else None,
            "backendError": self._backend_error,
        }

    def _key(self, tool_name: str, fingerprint: str) -> str:
        return f"{self._redis_namespace}:{tool_name}:{fingerprint}"

    def _get_from_redis(
        self,
        tool_name: str,
        fingerprint: str,
    ) -> tuple[ToolExecutionResult, int | None] | None:
        client = self._redis_client
        if client is None or not self._enabled:
            return None
        key = self._key(tool_name, fingerprint)
        try:
            payload = client.get(key)
        except Exception as exc:
            self._degrade_backend(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            result = ToolExecutionResult.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(key)
            except Exception:
                pass
            return None
        ttl_seconds = self._ttl_from_redis(client, key)
        return result, ttl_seconds

    def _ttl_from_redis(self, client, key: str) -> int | None:
        ttl_reader = getattr(client, "ttl", None)
        if not callable(ttl_reader):
            return None
        try:
            ttl = ttl_reader(key)
        except Exception:
            return None
        if isinstance(ttl, bool):
            return None
        if not isinstance(ttl, (int, float)):
            return None
        parsed_ttl = int(ttl)
        if parsed_ttl <= 0:
            return None
        return parsed_ttl

    def _save_to_redis(
        self,
        tool_name: str,
        fingerprint: str,
        ttl_seconds: int,
        result: ToolExecutionResult,
    ) -> bool:
        client = self._redis_client
        if client is None or not self._enabled:
            return False
        try:
            client.setex(
                self._key(tool_name, fingerprint),
                max(ttl_seconds, 1),
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_backend(exc)
            return False
        return True

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

    def _degrade_backend(self, exc: Exception) -> None:
        with self._lock:
            self._redis_client = None
            self._backend_error = f"{exc.__class__.__name__}: {exc}"
            self._next_recovery_attempt_at = time.monotonic() + RECOVERY_RETRY_SECONDS
            self._persist_unlocked(force=True)

    def _bootstrap_redis_from_local_unlocked(self) -> None:
        if self._redis_client is None or not self._records or not self._enabled:
            return
        now = time.time()
        authoritative: dict[tuple[str, str], StoredToolQueryResult] = {}
        for (tool_name, fingerprint), record in self._records.items():
            remote_entry = self._get_from_redis(tool_name, fingerprint)
            if remote_entry is not None:
                remote_result, ttl_seconds = remote_entry
                authoritative[(tool_name, fingerprint)] = StoredToolQueryResult(
                    fingerprint=fingerprint,
                    expires_at=(time.time() + ttl_seconds) if ttl_seconds is not None else record.expires_at,
                    result=remote_result.model_copy(deep=True),
                )
                continue
            ttl_seconds = max(int(record.expires_at - now), 1)
            if not self._save_to_redis(
                tool_name,
                fingerprint,
                ttl_seconds,
                record.result.model_copy(deep=True),
            ):
                return
            authoritative[(tool_name, fingerprint)] = StoredToolQueryResult(
                fingerprint=fingerprint,
                expires_at=record.expires_at,
                result=record.result.model_copy(deep=True),
            )
        self._records = authoritative

    def _persist_unlocked(self, *, force: bool = False) -> None:
        if self._persistence_path is None:
            return
        if not force and self._redis_client is not None:
            self._remove_fallback_file_unlocked()
            return
        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": {
                f"{tool_name}::{fingerprint}": {
                    "fingerprint": record.fingerprint,
                    "expires_at": record.expires_at,
                    "result": record.result.model_dump(mode="json"),
                }
                for (tool_name, fingerprint), record in self._records.items()
            }
        }
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._persistence_path.parent,
            prefix=f"{self._persistence_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            tmp_path = Path(handle.name)
        tmp_path.replace(self._persistence_path)

    def _remove_fallback_file_unlocked(self) -> None:
        if self._persistence_path is None:
            return
        try:
            self._persistence_path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    @staticmethod
    def _load_records(path: Path | None) -> dict[tuple[str, str], StoredToolQueryResult]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        records: dict[tuple[str, str], StoredToolQueryResult] = {}
        now = time.time()
        for composite_key, raw_record in payload.get("records", {}).items():
            tool_name, _, fingerprint = composite_key.partition("::")
            expires_at = float(raw_record.get("expires_at", 0))
            if not tool_name or not fingerprint or expires_at <= now:
                continue
            records[(tool_name, fingerprint)] = StoredToolQueryResult(
                fingerprint=str(raw_record.get("fingerprint", fingerprint)),
                expires_at=expires_at,
                result=ToolExecutionResult.model_validate(raw_record.get("result", {})),
            )
        return records

    @staticmethod
    def _fingerprint(
        tool_name: str,
        operation: str,
        payload: dict,
        context: ToolExecutionContext,
    ) -> str:
        return json.dumps(
            {
                "tool_name": tool_name,
                "operation": operation,
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "account_id": context.account_id,
                "locale": context.locale,
                "payload": payload,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )


_store = ToolQueryCacheStore()


def configure_query_cache(
    *,
    enabled: bool,
    ttl_cap_seconds: int | None = None,
    persistence_path: str | Path | None = None,
    redis_url: str | None = None,
    redis_namespace: str = "smartcloud:business-tools:query-cache",
) -> None:
    _store.configure_persistence(
        persistence_path,
        redis_url=redis_url,
        redis_namespace=redis_namespace,
    )
    _store.configure(enabled=enabled, ttl_cap_seconds=ttl_cap_seconds)


def get_query_cache_store() -> ToolQueryCacheStore:
    return _store
