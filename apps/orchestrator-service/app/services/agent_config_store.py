from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.models.orchestration import AgentConfigOverride, AgentName
from app.services import runtime_mysql
from app.services.runtime_redis import build_redis_client, normalize_namespace

RECOVERY_RETRY_SECONDS = 5.0


class _MySQLAgentConfigBackend:
    TABLE_NAME = "orchestrator_agent_configs"

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

    def clear(self) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"DELETE FROM `{self.TABLE_NAME}`")
            connection.commit()
        finally:
            connection.close()

    def list(self) -> list[AgentConfigOverride]:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"SELECT payload_json FROM `{self.TABLE_NAME}` ORDER BY agent_name ASC")
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        return [AgentConfigOverride.model_validate(json.loads(row["payload_json"])) for row in rows]

    def get(self, agent_name: AgentName) -> AgentConfigOverride | None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"SELECT payload_json FROM `{self.TABLE_NAME}` WHERE agent_name = %s",
                    (agent_name,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return AgentConfigOverride.model_validate(json.loads(row["payload_json"]))

    def upsert(
        self,
        *,
        agent_name: AgentName,
        agent_code: str,
        values: dict[str, Any],
    ) -> AgentConfigOverride:
        current = self.get(agent_name)
        payload = current.model_dump() if current is not None else {
            "agent_name": agent_name,
            "agent_code": agent_code,
        }
        payload.update(values)
        payload["agent_name"] = agent_name
        payload["agent_code"] = agent_code
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        override = AgentConfigOverride.model_validate(payload)

        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.TABLE_NAME}` (
                        agent_name,
                        agent_code,
                        updated_at,
                        payload_json
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        override.agent_name,
                        override.agent_code,
                        override.updated_at or "",
                        json.dumps(override.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
            connection.commit()
        finally:
            connection.close()
        return override

    def describe_backend(self) -> dict[str, object]:
        return {"backend": "mysql", "table": self.TABLE_NAME, "configured": True}

    def import_override(self, override: AgentConfigOverride) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.TABLE_NAME}` (
                        agent_name,
                        agent_code,
                        updated_at,
                        payload_json
                    ) VALUES (%s, %s, %s, %s)
                    """,
                    (
                        override.agent_name,
                        override.agent_code,
                        override.updated_at or "",
                        json.dumps(override.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
            connection.commit()
        finally:
            connection.close()

    def _ensure_schema(self, cursor) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.TABLE_NAME}` (
                agent_name VARCHAR(128) PRIMARY KEY,
                agent_code VARCHAR(128) NOT NULL,
                updated_at VARCHAR(128) NOT NULL,
                payload_json LONGTEXT NOT NULL
            )
            """
        )


class AgentConfigStore:
    """Agent override store with MySQL authority and Redis runtime caching."""

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        mysql_dsn: str | None = None,
        redis_url: str | None = None,
        redis_namespace: str = "smartcloud:orchestrator:agent-config",
    ) -> None:
        self._lock = RLock()
        self._overrides: dict[str, AgentConfigOverride] = {}
        self._file_path: Path | None = None
        self._mysql_dsn: str | None = None
        self._backend: _MySQLAgentConfigBackend | None = None
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
            self._backend = _MySQLAgentConfigBackend(mysql_dsn) if mysql_dsn else None
            self._backend_error = None
            self._next_backend_recovery_at = 0.0
            self._redis_url = redis_url
            if redis_namespace:
                self._redis_namespace = normalize_namespace(redis_namespace)
            self._redis_client = build_redis_client(redis_url)
            self._cache_error = "Redis connection unavailable." if redis_url and self._redis_client is None else None
            self._next_cache_recovery_at = 0.0
            self._overrides = self._load_overrides(path)
            if self._backend is not None:
                try:
                    self._backend.ensure_ready()
                    self._bootstrap_backend_from_local_unlocked()
                except Exception as exc:
                    self._degrade_backend(exc)
            self._bootstrap_runtime_cache_from_local_unlocked()
            self._persist_unlocked()

    def clear(self) -> None:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                backend.clear()
                self._clear_runtime_cache()
                with self._lock:
                    self._overrides.clear()
                    self._persist_unlocked()
                return
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            self._overrides.clear()
            self._persist_unlocked()
        self._clear_runtime_cache()

    def list(self) -> list[AgentConfigOverride]:
        self._maybe_restore_runtime_cache()
        self._maybe_restore_backend()
        cached = self._list_from_runtime_cache()
        if cached is not None:
            with self._lock:
                self._overrides = {
                    override.agent_name: override.model_copy(deep=True)
                    for override in cached
                }
            return [override.model_copy(deep=True) for override in cached]
        backend = self._backend
        if backend is not None:
            try:
                overrides = [override.model_copy(deep=True) for override in backend.list()]
                self._replace_runtime_cache(overrides)
                with self._lock:
                    self._overrides = {
                        override.agent_name: override.model_copy(deep=True)
                        for override in overrides
                    }
                return overrides
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            return [
                override.model_copy(deep=True)
                for _, override in sorted(self._overrides.items(), key=lambda item: item[0])
            ]

    def get(self, agent_name: AgentName) -> AgentConfigOverride | None:
        self._maybe_restore_runtime_cache()
        self._maybe_restore_backend()
        cached = self._get_from_runtime_cache(agent_name)
        if cached is not None:
            with self._lock:
                self._overrides[agent_name] = cached.model_copy(deep=True)
            return cached.model_copy(deep=True)
        backend = self._backend
        if backend is not None:
            try:
                override = backend.get(agent_name)
                if override is None:
                    return None
                self._save_to_runtime_cache(override)
                with self._lock:
                    self._overrides[agent_name] = override.model_copy(deep=True)
                return override.model_copy(deep=True)
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            override = self._overrides.get(agent_name)
            return override.model_copy(deep=True) if override else None

    def upsert(
        self,
        *,
        agent_name: AgentName,
        agent_code: str,
        values: dict[str, Any],
    ) -> AgentConfigOverride:
        self._maybe_restore_runtime_cache()
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                override = backend.upsert(agent_name=agent_name, agent_code=agent_code, values=values).model_copy(
                    deep=True
                )
                self._save_to_runtime_cache(override)
                with self._lock:
                    self._overrides[agent_name] = override.model_copy(deep=True)
                    self._persist_unlocked()
                return override
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            current = self._overrides.get(agent_name)
            payload = current.model_dump() if current is not None else {
                "agent_name": agent_name,
                "agent_code": agent_code,
            }
            payload.update(values)
            payload["agent_name"] = agent_name
            payload["agent_code"] = agent_code
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            override = AgentConfigOverride.model_validate(payload)
            self._overrides[agent_name] = override
            self._persist_unlocked()
            return override.model_copy(deep=True)

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

    def _maybe_restore_backend(self) -> _MySQLAgentConfigBackend | None:
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
            backend = _MySQLAgentConfigBackend(self._mysql_dsn)
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
        if backend is None or not self._overrides:
            return
        authoritative: dict[str, AgentConfigOverride] = {}
        for agent_name, override in self._overrides.items():
            remote_override = backend.get(override.agent_name)
            if remote_override is None or self._prefer_local_override(override, remote_override):
                backend.import_override(override.model_copy(deep=True))
                authoritative[agent_name] = override.model_copy(deep=True)
                continue
            authoritative[agent_name] = remote_override.model_copy(deep=True)
        self._overrides = authoritative

    @staticmethod
    def _prefer_local_override(local: AgentConfigOverride, remote: AgentConfigOverride) -> bool:
        local_updated_at = AgentConfigStore._parse_timestamp(local.updated_at)
        remote_updated_at = AgentConfigStore._parse_timestamp(remote.updated_at)
        if local_updated_at is None:
            return False
        if remote_updated_at is None:
            return True
        return local_updated_at > remote_updated_at

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _item_cache_key(self, agent_name: str) -> str:
        return f"{self._redis_namespace}:item:{agent_name}"

    def _index_cache_key(self) -> str:
        return f"{self._redis_namespace}:index"

    def _get_from_runtime_cache(self, agent_name: str) -> AgentConfigOverride | None:
        client = self._redis_client
        if client is None:
            return None
        try:
            payload = client.get(self._item_cache_key(agent_name))
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(payload, str) or not payload.strip():
            return None
        try:
            return AgentConfigOverride.model_validate(json.loads(payload))
        except Exception:
            try:
                client.delete(self._item_cache_key(agent_name))
            except Exception:
                pass
            return None

    def _list_from_runtime_cache(self) -> list[AgentConfigOverride] | None:
        client = self._redis_client
        if client is None:
            return None
        try:
            raw_index = client.get(self._index_cache_key())
        except Exception as exc:
            self._degrade_runtime_cache(exc)
            return None
        if not isinstance(raw_index, str) or not raw_index.strip():
            return None
        try:
            agent_names = [str(item) for item in json.loads(raw_index)]
        except Exception:
            try:
                client.delete(self._index_cache_key())
            except Exception:
                pass
            return None
        overrides: list[AgentConfigOverride] = []
        for agent_name in agent_names:
            override = self._get_from_runtime_cache(agent_name)
            if override is None:
                return None
            overrides.append(override)
        return [override.model_copy(deep=True) for override in overrides]

    def _save_to_runtime_cache(self, override: AgentConfigOverride) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            client.set(
                self._item_cache_key(override.agent_name),
                json.dumps(override.model_dump(mode="json"), ensure_ascii=False),
            )
            raw_index = client.get(self._index_cache_key())
            try:
                agent_names = [str(item) for item in json.loads(raw_index)] if isinstance(raw_index, str) else []
            except Exception:
                agent_names = []
            if override.agent_name not in agent_names:
                agent_names.append(override.agent_name)
            client.set(
                self._index_cache_key(),
                json.dumps(sorted(dict.fromkeys(agent_names)), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _replace_runtime_cache(self, overrides: list[AgentConfigOverride]) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            if not overrides:
                self._clear_runtime_cache()
                return
            for override in overrides:
                client.set(
                    self._item_cache_key(override.agent_name),
                    json.dumps(override.model_dump(mode="json"), ensure_ascii=False),
                )
            client.set(
                self._index_cache_key(),
                json.dumps(sorted(override.agent_name for override in overrides), ensure_ascii=False),
            )
        except Exception as exc:
            self._degrade_runtime_cache(exc)

    def _bootstrap_runtime_cache_from_local_unlocked(self) -> None:
        if self._redis_client is None or not self._overrides:
            return
        self._replace_runtime_cache(
            [override.model_copy(deep=True) for override in self._overrides.values()]
        )

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
            "overrides": {
                agent_name: override.model_dump(mode="json")
                for agent_name, override in self._overrides.items()
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
    def _load_overrides(path: Path | None) -> dict[str, AgentConfigOverride]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(agent_name): AgentConfigOverride.model_validate(raw_override)
            for agent_name, raw_override in payload.get("overrides", {}).items()
        }
