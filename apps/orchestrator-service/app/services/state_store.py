from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.models.orchestration import SessionStateSnapshot
from app.services import runtime_mysql
from app.services.runtime_redis import build_redis_client, normalize_namespace

RECOVERY_RETRY_SECONDS = 5.0


class _MySQLStateStoreBackend:
    TABLE_NAME = "orchestrator_session_state"

    def __init__(self, mysql_dsn: str) -> None:
        self._mysql_dsn = mysql_dsn

    def ensure_ready(self) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
            connection.commit()
        finally:
            connection.close()

    def save(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"SELECT version FROM `{self.TABLE_NAME}` WHERE conversation_id = %s",
                    (snapshot.conversation_id,),
                )
                row = cursor.fetchone()
                version = int((row or {}).get("version", 0)) + 1
                persisted = snapshot.model_copy(deep=True, update={"version": version})
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.TABLE_NAME}` (
                        conversation_id,
                        version,
                        updated_at,
                        payload_json
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        persisted.conversation_id,
                        persisted.version,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(persisted.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
            connection.commit()
        finally:
            connection.close()
        return persisted

    def get(self, conversation_id: str) -> SessionStateSnapshot | None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"SELECT payload_json FROM `{self.TABLE_NAME}` WHERE conversation_id = %s",
                    (conversation_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return SessionStateSnapshot.model_validate(json.loads(row["payload_json"]))

    def clear(self) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"DELETE FROM `{self.TABLE_NAME}`")
            connection.commit()
        finally:
            connection.close()

    def import_snapshot(self, snapshot: SessionStateSnapshot) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.TABLE_NAME}` (
                        conversation_id,
                        version,
                        updated_at,
                        payload_json
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        snapshot.conversation_id,
                        snapshot.version,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "mysql",
            "table": self.TABLE_NAME,
            "configured": True,
        }

    def _ensure_schema(self, cursor) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.TABLE_NAME}` (
                conversation_id VARCHAR(128) PRIMARY KEY,
                version INT NOT NULL,
                updated_at VARCHAR(128) NOT NULL,
                payload_json LONGTEXT NOT NULL
            )
            """
        )


class OrchestrationStateStore:
    """Checkpoint/state store with MySQL authority and Redis runtime caching."""

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        mysql_dsn: str | None = None,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:state",
    ) -> None:
        self._lock = RLock()
        self._snapshots: dict[str, SessionStateSnapshot] = {}
        self._file_path: Path | None = None
        self._mysql_dsn: str | None = None
        self._backend: _MySQLStateStoreBackend | None = None
        self._backend_error: str | None = None
        self._next_backend_recovery_at = 0.0
        self._redis_url: str | None = None
        self._redis_namespace = normalize_namespace(redis_namespace)
        self._redis_client = None
        self._cache_error: str | None = None
        self._next_cache_recovery_at = 0.0
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
            self._backend = _MySQLStateStoreBackend(mysql_dsn) if mysql_dsn else None
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            self._redis_url = redis_url
            if redis_namespace:
                self._redis_namespace = normalize_namespace(redis_namespace)
            self._redis_client = build_redis_client(redis_url)
            self._cache_error = "Redis connection unavailable." if redis_url and self._redis_client is None else None
            self._next_cache_recovery_at = 0.0
            self._snapshots = self._load_snapshots(path)
            if self._backend is not None:
                try:
                    self._backend.ensure_ready()
                    self._bootstrap_backend_from_local_unlocked()
                except Exception as exc:
                    self._degrade_backend(exc)
            self._bootstrap_runtime_cache_from_local_unlocked()
            self._persist_unlocked()

    def save(self, snapshot: SessionStateSnapshot) -> SessionStateSnapshot:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                persisted = backend.save(snapshot).model_copy(deep=True)
                self._save_to_runtime_cache(persisted)
                with self._lock:
                    self._snapshots[persisted.conversation_id] = persisted.model_copy(deep=True)
                    self._persist_unlocked()
                return persisted
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            current = self._snapshots.get(snapshot.conversation_id)
            version = 1 if current is None else current.version + 1
            persisted = snapshot.model_copy(deep=True, update={"version": version})
            self._snapshots[snapshot.conversation_id] = persisted
            self._persist_unlocked()
        return persisted.model_copy(deep=True)

    def get(self, conversation_id: str) -> SessionStateSnapshot | None:
        self._maybe_restore_runtime_cache()
        self._maybe_restore_backend()
        cached = self._get_from_runtime_cache(conversation_id)
        if cached is not None:
            with self._lock:
                self._snapshots[conversation_id] = cached.model_copy(deep=True)
            return cached.model_copy(deep=True)
        backend = self._backend
        if backend is not None:
            try:
                snapshot = backend.get(conversation_id)
                if snapshot is None:
                    return None
                self._save_to_runtime_cache(snapshot)
                with self._lock:
                    self._snapshots[conversation_id] = snapshot.model_copy(deep=True)
                return snapshot.model_copy(deep=True)
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            snapshot = self._snapshots.get(conversation_id)
            return snapshot.model_copy(deep=True) if snapshot else None

    def clear(self) -> None:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                backend.clear()
                self._clear_runtime_cache()
                with self._lock:
                    self._snapshots.clear()
                    self._persist_unlocked()
                return
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            self._snapshots.clear()
            self._persist_unlocked()
        self._clear_runtime_cache()

    def describe_backend(self) -> dict[str, object]:
        self._maybe_restore_runtime_cache()
        self._maybe_restore_backend()
        runtime_cache = self._describe_runtime_cache()
        backend = self._backend
        if backend is not None:
            description = backend.describe_backend()
            description["fallbackBackend"] = "json-file" if self._file_path else "memory"
            description["fallbackPath"] = str(self._file_path) if self._file_path else None
            description["fallbackWriteMode"] = "degraded-only"
            description["runtimeCache"] = runtime_cache
            return description
        description = {
            "backend": "json-file" if self._file_path else "memory",
            "configured": self._file_path is not None,
            "path": str(self._file_path) if self._file_path else None,
            "degradedFrom": "mysql" if self._backend_error else None,
            "backendError": self._backend_error,
        }
        description["runtimeCache"] = runtime_cache
        return description

    def _maybe_restore_backend(self) -> _MySQLStateStoreBackend | None:
        if self._backend is not None or not self._mysql_dsn:
            return self._backend
        now = time.monotonic()
        if now < self._next_backend_recovery_at:
            return None
        with self._lock:
            if self._backend is not None or not self._mysql_dsn:
                return self._backend
            now = time.monotonic()
            if now < self._next_backend_recovery_at:
                return None
            backend = _MySQLStateStoreBackend(self._mysql_dsn)
            try:
                backend.ensure_ready()
            except Exception as exc:
                self._backend_error = f"{exc.__class__.__name__}: {exc}"
                self._next_backend_recovery_at = now + RECOVERY_RETRY_SECONDS
                self._persist_unlocked(force=True)
                return None
            self._backend = backend
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            self._bootstrap_backend_from_local_unlocked()
            self._persist_unlocked()
            return self._backend

    def _degrade_backend(self, exc: Exception) -> None:
        with self._lock:
            self._backend = None
            self._backend_error = f"{exc.__class__.__name__}: {exc}"
            self._next_backend_recovery_at = time.monotonic() + RECOVERY_RETRY_SECONDS
            self._persist_unlocked(force=True)

    def _bootstrap_backend_from_local_unlocked(self) -> None:
        backend = self._backend
        if backend is None or not self._snapshots:
            return
        authoritative: dict[str, SessionStateSnapshot] = {}
        for conversation_id, snapshot in self._snapshots.items():
            remote_snapshot = backend.get(conversation_id)
            if remote_snapshot is None or snapshot.version > remote_snapshot.version:
                backend.import_snapshot(snapshot.model_copy(deep=True))
                authoritative[conversation_id] = snapshot.model_copy(deep=True)
                continue
            authoritative[conversation_id] = remote_snapshot.model_copy(deep=True)
        self._snapshots = authoritative

    def _cache_key(self, conversation_id: str) -> str:
        return f"{self._redis_namespace}:snapshot:{conversation_id}"

    def _get_from_runtime_cache(self, conversation_id: str) -> SessionStateSnapshot | None:
        client = self._redis_client
        if client is None:
            return None
        try:
            payload = client.get(self._cache_key(conversation_id))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return SessionStateSnapshot.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._cache_key(conversation_id))
            except Exception:
                pass
            return None

    def _save_to_runtime_cache(self, snapshot: SessionStateSnapshot) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            client.set(
                self._cache_key(snapshot.conversation_id),
                json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _bootstrap_runtime_cache_from_local_unlocked(self) -> None:
        if self._redis_client is None or not self._snapshots:
            return
        for snapshot in self._snapshots.values():
            self._save_to_runtime_cache(snapshot.model_copy(deep=True))

    def _clear_runtime_cache(self) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            for key in client.scan_iter(match=f"{self._redis_namespace}:*"):
                client.delete(key)
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _describe_runtime_cache(self) -> dict[str, object]:
        return {
            "backend": "redis-json" if self._redis_client is not None else "memory",
            "redisConfigured": bool(self._redis_url),
            "redisNamespace": self._redis_namespace if self._redis_url else None,
            "degradedFrom": "redis-json" if self._cache_error else None,
            "backendError": self._cache_error,
        }

    def _maybe_restore_runtime_cache(self) -> None:
        if self._redis_client is not None or not self._redis_url:
            return
        now = time.monotonic()
        if now < self._next_cache_recovery_at:
            return
        with self._lock:
            if self._redis_client is not None or not self._redis_url:
                return
            now = time.monotonic()
            if now < self._next_cache_recovery_at:
                return
            client = build_redis_client(self._redis_url)
            if client is None:
                self._cache_error = "Redis connection unavailable."
                self._next_cache_recovery_at = now + RECOVERY_RETRY_SECONDS
                return
            self._redis_client = client
            self._cache_error = None
            self._next_cache_recovery_at = 0.0
            self._bootstrap_runtime_cache_from_local_unlocked()

    def _degrade_runtime_cache(self, exc: Exception) -> None:
        with self._lock:
            self._redis_client = None
            self._cache_error = f"{exc.__class__.__name__}: {exc}"
            self._next_cache_recovery_at = time.monotonic() + RECOVERY_RETRY_SECONDS

    def _persist_unlocked(self, *, force: bool = False) -> None:
        if self._file_path is None:
            return
        if not force and self._backend is not None:
            self._remove_fallback_file_unlocked()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "snapshots": {
                conversation_id: snapshot.model_dump(mode="json")
                for conversation_id, snapshot in self._snapshots.items()
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

    @staticmethod
    def _load_snapshots(path: Path | None) -> dict[str, SessionStateSnapshot]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(conversation_id): SessionStateSnapshot.model_validate(raw_snapshot)
            for conversation_id, raw_snapshot in payload.get("snapshots", {}).items()
        }
