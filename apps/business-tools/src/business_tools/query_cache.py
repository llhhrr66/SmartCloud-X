from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from business_tools.interfaces import ToolExecutionContext, ToolExecutionResult


@dataclass
class StoredToolQueryResult:
    fingerprint: str
    expires_at: float
    result: ToolExecutionResult


class ToolQueryCacheStore:
    """Process-local query-result cache with optional file persistence."""

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._records: dict[tuple[str, str], StoredToolQueryResult] = {}
        self._enabled = True
        self._ttl_cap_seconds = 300
        self._persistence_path: Path | None = None
        self.configure_persistence(persistence_path)

    def configure(self, *, enabled: bool, ttl_cap_seconds: int | None = None) -> None:
        with self._lock:
            self._enabled = enabled
            if ttl_cap_seconds is not None:
                self._ttl_cap_seconds = ttl_cap_seconds
            if not enabled:
                self._records.clear()
            self._persist_unlocked()

    def configure_persistence(self, persistence_path: str | Path | None) -> None:
        path = Path(persistence_path).expanduser() if persistence_path else None
        with self._lock:
            self._persistence_path = path
            self._records = self._load_records(path)

    def get(
        self,
        tool_name: str,
        operation: str,
        payload: dict,
        context: ToolExecutionContext,
    ) -> ToolExecutionResult | None:
        if not self._enabled:
            return None
        fingerprint = self._fingerprint(tool_name, operation, payload, context)
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
        effective_ttl = ttl_seconds
        if self._ttl_cap_seconds > 0:
            effective_ttl = min(ttl_seconds, self._ttl_cap_seconds)
        fingerprint = self._fingerprint(tool_name, operation, payload, context)
        stored = result.model_copy(deep=True)
        with self._lock:
            self._records[(tool_name, fingerprint)] = StoredToolQueryResult(
                fingerprint=fingerprint,
                expires_at=time.time() + effective_ttl,
                result=stored,
            )
            self._persist_unlocked()
        return result

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        if self._persistence_path is None:
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
        tmp_path = self._persistence_path.with_suffix(f"{self._persistence_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._persistence_path)

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
) -> None:
    _store.configure_persistence(persistence_path)
    _store.configure(enabled=enabled, ttl_cap_seconds=ttl_cap_seconds)


def get_query_cache_store() -> ToolQueryCacheStore:
    return _store
