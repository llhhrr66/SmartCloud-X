from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from business_tools.interfaces import ToolExecutionContext, ToolExecutionResult


@dataclass
class StoredToolExecution:
    fingerprint: str
    result: ToolExecutionResult


class ToolIdempotencyStore:
    """Process-local write-tool idempotency store with optional file persistence."""

    def __init__(self, persistence_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._records: dict[tuple[str, str], StoredToolExecution] = {}
        self._persistence_path: Path | None = None
        self.configure_persistence(persistence_path)

    def configure_persistence(self, persistence_path: str | Path | None) -> None:
        path = Path(persistence_path).expanduser() if persistence_path else None
        with self._lock:
            self._persistence_path = path
            self._records = self._load_records(path) if path else {}

    def get(
        self,
        tool_name: str,
        idempotency_key: str,
        payload: dict,
        context: ToolExecutionContext,
    ) -> tuple[ToolExecutionResult | None, bool]:
        fingerprint = self._fingerprint(tool_name, payload, context)
        with self._lock:
            record = self._records.get((tool_name, idempotency_key))
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
        result: ToolExecutionResult,
    ) -> ToolExecutionResult:
        fingerprint = self._fingerprint(tool_name, payload, context)
        stored = result.model_copy(deep=True)
        with self._lock:
            self._records[(tool_name, idempotency_key)] = StoredToolExecution(
                fingerprint=fingerprint,
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
                f"{tool_name}::{idempotency_key}": {
                    "fingerprint": record.fingerprint,
                    "result": record.result.model_dump(mode="json"),
                }
                for (tool_name, idempotency_key), record in self._records.items()
            }
        }
        tmp_path = self._persistence_path.with_suffix(f"{self._persistence_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._persistence_path)

    @staticmethod
    def _load_records(path: Path | None) -> dict[tuple[str, str], StoredToolExecution]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        records: dict[tuple[str, str], StoredToolExecution] = {}
        for composite_key, raw_record in payload.get("records", {}).items():
            tool_name, _, idempotency_key = composite_key.partition("::")
            if not tool_name or not idempotency_key:
                continue
            records[(tool_name, idempotency_key)] = StoredToolExecution(
                fingerprint=str(raw_record.get("fingerprint", "")),
                result=ToolExecutionResult.model_validate(raw_record.get("result", {})),
            )
        return records

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


def configure_idempotency_store(*, persistence_path: str | Path | None = None) -> ToolIdempotencyStore:
    _store.configure_persistence(persistence_path)
    return _store
