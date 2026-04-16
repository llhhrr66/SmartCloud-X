from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.models.tools import ToolCallAuditRecord, ToolCallRequest, ToolCallResponse


class ToolCallAuditStore:
    """Process-local audit trail for tool-hub executions with optional file persistence."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        self._lock = RLock()
        self._records: dict[str, ToolCallAuditRecord] = {}
        self._file_path: Path | None = None
        self.configure_persistence(file_path)

    def configure_persistence(self, file_path: str | Path | None) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._records = self._load_records(path)

    def record(self, request: ToolCallRequest, response: ToolCallResponse) -> ToolCallAuditRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            existing = self._records.get(request.tool_call_id)
            record = ToolCallAuditRecord(
                tool_call_id=request.tool_call_id,
                trace_id=request.trace_id,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                tool_name=request.tool_name,
                operation=request.operation,
                status=self._status_for(response),
                success=response.success,
                code=response.code,
                message=response.message,
                summary=response.summary or response.message,
                provider=response.provider,
                retryable=bool(response.error.retryable) if response.error else False,
                latency_ms=response.latency_ms,
                attempts=response.attempts,
                tenant_id=request.user_context.tenant_id,
                operator=request.operator,
                user_context=request.user_context,
                idempotency_key=response.idempotency_key or request.idempotency_key,
                audit_tags=list(response.audit_tags),
                citations=list(response.citations),
                data_preview=self._preview(response.data),
                session_context_patch=self._preview(response.session_context_patch),
                error=response.error,
                user_action_hint=response.user_action_hint,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._records[request.tool_call_id] = record
            self._persist_unlocked()
            return record

    def get(self, tool_call_id: str) -> ToolCallAuditRecord | None:
        with self._lock:
            record = self._records.get(tool_call_id)
            return record.model_copy(deep=True) if record else None

    def list(
        self,
        *,
        tool_name: str | None = None,
        status: str | None = None,
        trace_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        tenant_id: str | None = None,
        idempotency_key: str | None = None,
        audit_tag: str | None = None,
        limit: int = 50,
    ) -> list[ToolCallAuditRecord]:
        with self._lock:
            records = list(self._records.values())
        filtered = [
            record
            for record in records
            if (tool_name is None or record.tool_name == tool_name)
            and (status is None or record.status == status)
            and (trace_id is None or record.trace_id == trace_id)
            and (conversation_id is None or record.conversation_id == conversation_id)
            and (message_id is None or record.message_id == message_id)
            and (tenant_id is None or record.tenant_id == tenant_id)
            and (idempotency_key is None or record.idempotency_key == idempotency_key)
            and (audit_tag is None or audit_tag in record.audit_tags)
        ]
        filtered.sort(key=lambda item: item.updated_at, reverse=True)
        return filtered[:limit]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._persist_unlocked()

    def _persist_unlocked(self) -> None:
        if self._file_path is None:
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": {
                tool_call_id: record.model_dump(mode="json")
                for tool_call_id, record in self._records.items()
            }
        }
        tmp_path = self._file_path.with_suffix(f"{self._file_path.suffix}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(self._file_path)

    @staticmethod
    def _load_records(path: Path | None) -> dict[str, ToolCallAuditRecord]:
        if path is None or not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {
            str(tool_call_id): ToolCallAuditRecord.model_validate(raw_record)
            for tool_call_id, raw_record in payload.get("records", {}).items()
        }

    @staticmethod
    def _status_for(response: ToolCallResponse) -> str:
        if response.status:
            return response.status
        if response.success:
            return "success"
        return {
            4001001: "invalid-payload",
            4030001: "auth-required",
            4040001: "missing-tool",
            4090001: "idempotency-conflict",
            4090002: "confirmation-required",
            5003002: "timeout",
        }.get(response.code, "failed")

    @staticmethod
    def _preview(payload: dict) -> dict:
        if len(payload) <= 6:
            return dict(payload)
        keys = list(payload)[:6]
        return {key: payload[key] for key in keys}
