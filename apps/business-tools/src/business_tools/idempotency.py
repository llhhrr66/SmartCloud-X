from __future__ import annotations

import hashlib
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
class StoredToolExecution:
    fingerprint: str
    result: ToolExecutionResult
    expires_at: float | None = None


class ToolIdempotencyStore:
    """Write-tool idempotency store with Redis-first runtime persistence and local fallback."""

    def __init__(
        self,
        persistence_path: str | Path | None = None,
        *,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:business-tools:idempotency",
    ) -> None:
        self._lock = RLock()
        self._records: dict[tuple[str, str, str], StoredToolExecution] = {}
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
            self._records = self._load_records(path) if path else {}
            self._bootstrap_redis_from_local_unlocked()
            self._persist_unlocked()

    def get(
        self,
        tool_name: str,
        idempotency_key: str,
        payload: dict,
        context: ToolExecutionContext,
    ) -> tuple[ToolExecutionResult | None, bool]:
        self._maybe_restore_backend()
        fingerprint = self._fingerprint(tool_name, payload, context)
        scope_token = self._scope_token(context)
        redis_record = self._get_from_redis(tool_name, idempotency_key, scope_token=scope_token)
        if redis_record is not None:
            with self._lock:
                self._records[(tool_name, scope_token, idempotency_key)] = StoredToolExecution(
                    fingerprint=redis_record.fingerprint,
                    result=redis_record.result.model_copy(deep=True),
                    expires_at=redis_record.expires_at,
                )
            if redis_record.fingerprint != fingerprint:
                return None, True
            replay = redis_record.result.model_copy(deep=True)
            if "idempotent-replay" not in replay.audit_tags:
                replay.audit_tags.append("idempotent-replay")
            return replay, False
        with self._lock:
            record = self._records.get((tool_name, scope_token, idempotency_key))
            if record is not None and record.expires_at is not None and record.expires_at <= time.time():
                self._records.pop((tool_name, scope_token, idempotency_key), None)
                self._persist_unlocked()
                record = None
        if record is None:
            return None, False
        if record.fingerprint != fingerprint:
            return None, True
        replay = record.result.model_copy(deep=True)
        if "idempotent-replay" not in replay.audit_tags:
            replay.audit_tags.append("idempotent-replay")
        return replay, False

    def save(
        self,
        tool_name: str,
        idempotency_key: str,
        payload: dict,
        context: ToolExecutionContext,
        ttl_seconds: int | None,
        result: ToolExecutionResult,
    ) -> ToolExecutionResult:
        self._maybe_restore_backend()
        fingerprint = self._fingerprint(tool_name, payload, context)
        scope_token = self._scope_token(context)
        stored = result.model_copy(deep=True)
        expires_at = time.time() + ttl_seconds if ttl_seconds and ttl_seconds > 0 else None
        if self._save_to_redis(
            tool_name,
            idempotency_key,
            StoredToolExecution(
                fingerprint=fingerprint,
                result=stored,
                expires_at=expires_at,
            ),
            scope_token=scope_token,
            ttl_seconds=ttl_seconds,
        ):
            with self._lock:
                self._records[(tool_name, scope_token, idempotency_key)] = StoredToolExecution(
                    fingerprint=fingerprint,
                    result=stored.model_copy(deep=True),
                    expires_at=expires_at,
                )
                self._persist_unlocked()
            return result
        with self._lock:
            self._records[(tool_name, scope_token, idempotency_key)] = StoredToolExecution(
                fingerprint=fingerprint,
                result=stored,
                expires_at=expires_at,
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
            "backend": "redis" if self._redis_client is not None else ("json-file" if self._persistence_path else "memory"),
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._redis_namespace if self._redis_url else None,
            "fallbackPath": str(self._persistence_path) if self._persistence_path else None,
            "fallbackWriteMode": "degraded-only" if self._redis_client is not None and self._redis_url else "active",
            "degradedFrom": "redis" if self._backend_error else None,
            "backendError": self._backend_error,
        }

    def _key(
        self,
        tool_name: str,
        idempotency_key: str,
        *,
        scope_token: str = "legacy",
        legacy: bool = False,
    ) -> str:
        if legacy:
            scope_fragment = scope_token
        else:
            scope_fragment = hashlib.sha256(scope_token.encode("utf-8")).hexdigest()
        return f"{self._redis_namespace}:{tool_name}:{scope_fragment}:{idempotency_key}"

    def _get_from_redis(
        self,
        tool_name: str,
        idempotency_key: str,
        *,
        scope_token: str = "legacy",
    ) -> StoredToolExecution | None:
        client = self._redis_client
        if client is None:
            return None
        for legacy in (False, True):
            key = self._key(tool_name, idempotency_key, scope_token=scope_token, legacy=legacy)
            try:
                payload = client.get(key)
            except Exception as exc:
                self._degrade_backend(exc)
                return None
            if not isinstance(payload, str) or not payload.strip():
                continue
            try:
                parsed = json.loads(payload)
                expires_at = parsed.get("expires_at")
                parsed_expires_at = float(expires_at) if expires_at not in {None, ""} else None
                return StoredToolExecution(
                    fingerprint=str(parsed.get("fingerprint", "")),
                    result=ToolExecutionResult.model_validate(parsed.get("result") or {}),
                    expires_at=parsed_expires_at,
                )
            except Exception:
                try:
                    client.delete(key)
                except Exception:
                    pass
                return None
        return None

    def _save_to_redis(
        self,
        tool_name: str,
        idempotency_key: str,
        record: StoredToolExecution,
        *,
        scope_token: str = "legacy",
        ttl_seconds: int | None,
    ) -> bool:
        client = self._redis_client
        if client is None:
            return False
        payload = json.dumps(
            {
                "fingerprint": record.fingerprint,
                "result": record.result.model_dump(mode="json"),
                "expires_at": record.expires_at,
            },
            ensure_ascii=False,
        )
        try:
            if ttl_seconds is not None and ttl_seconds > 0:
                client.setex(self._key(tool_name, idempotency_key, scope_token=scope_token), max(int(ttl_seconds), 1), payload)
            else:
                client.set(self._key(tool_name, idempotency_key, scope_token=scope_token), payload)
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
        if self._redis_client is None or not self._records:
            return
        now = time.time()
        authoritative: dict[tuple[str, str, str], StoredToolExecution] = {}
        for (tool_name, scope_token, idempotency_key), record in self._records.items():
            remote_record = self._get_from_redis(tool_name, idempotency_key, scope_token=scope_token)
            if remote_record is not None:
                authoritative[(tool_name, scope_token, idempotency_key)] = StoredToolExecution(
                    fingerprint=remote_record.fingerprint,
                    result=remote_record.result.model_copy(deep=True),
                    expires_at=remote_record.expires_at,
                )
                continue
            ttl_seconds: int | None = None
            if record.expires_at is not None:
                ttl_seconds = max(int(record.expires_at - now), 1)
            if not self._save_to_redis(
                tool_name,
                idempotency_key,
                StoredToolExecution(
                    fingerprint=record.fingerprint,
                    result=record.result.model_copy(deep=True),
                    expires_at=record.expires_at,
                ),
                scope_token=scope_token,
                ttl_seconds=ttl_seconds,
            ):
                return
            authoritative[(tool_name, scope_token, idempotency_key)] = StoredToolExecution(
                fingerprint=record.fingerprint,
                result=record.result.model_copy(deep=True),
                expires_at=record.expires_at,
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
                f"{tool_name}::{scope_token}::{idempotency_key}": {
                    "fingerprint": record.fingerprint,
                    "result": record.result.model_dump(mode="json"),
                    "expires_at": record.expires_at,
                }
                for (tool_name, scope_token, idempotency_key), record in self._records.items()
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
    def _load_records(path: Path | None) -> dict[tuple[str, str, str], StoredToolExecution]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        records: dict[tuple[str, str, str], StoredToolExecution] = {}
        now = time.time()
        for composite_key, raw_record in payload.get("records", {}).items():
            parts = composite_key.split("::", 2)
            if len(parts) == 3:
                tool_name, scope_token, idempotency_key = parts
            elif len(parts) == 2:
                tool_name, idempotency_key = parts
                scope_token = "legacy"
            else:
                continue
            if not tool_name or not scope_token or not idempotency_key:
                continue
            expires_at = raw_record.get("expires_at")
            parsed_expires_at = float(expires_at) if expires_at not in {None, ""} else None
            if parsed_expires_at is not None and parsed_expires_at <= now:
                continue
            records[(tool_name, scope_token, idempotency_key)] = StoredToolExecution(
                fingerprint=str(raw_record.get("fingerprint", "")),
                result=ToolExecutionResult.model_validate(raw_record.get("result", {})),
                expires_at=parsed_expires_at,
            )
        return records

    @staticmethod
    def _scope_token(context: ToolExecutionContext) -> str:
        return json.dumps(
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "account_id": context.account_id,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _fingerprint(tool_name: str, payload: dict, context: ToolExecutionContext) -> str:
        return json.dumps(
            {
                "tool_name": tool_name,
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "account_id": context.account_id,
                "payload": payload,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )


_store = ToolIdempotencyStore()


def get_idempotency_store() -> ToolIdempotencyStore:
    return _store


def configure_idempotency_store(
    *,
    persistence_path: str | Path | None = None,
    redis_url: str | None = None,
    redis_namespace: str = "smartcloud:business-tools:idempotency",
) -> ToolIdempotencyStore:
    _store.configure_persistence(
        persistence_path,
        redis_url=redis_url,
        redis_namespace=redis_namespace,
    )
    return _store
