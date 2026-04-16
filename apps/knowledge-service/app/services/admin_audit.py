import json
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.core.config import get_settings
from app.core.metrics import ADMIN_AUDIT_RECORDS_TOTAL
from app.models.admin import AdminAuditRecord


class KnowledgeAdminAuditService:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def record(
        self,
        *,
        operator_id: str,
        resource_type: str,
        resource_id: str,
        action: str,
        reason: str,
        before_json: dict | None,
        after_json: dict | None,
        operator_ip: str | None,
        created_at: str,
    ) -> AdminAuditRecord:
        entry = AdminAuditRecord(
            audit_id=f"audit-{uuid4().hex[:12]}",
            operator_type="admin-console",
            operator_id=operator_id,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            reason=reason,
            before_json=before_json,
            after_json=after_json,
            operator_ip=operator_ip,
            created_at=created_at,
        )
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False))
                handle.write("\n")
        ADMIN_AUDIT_RECORDS_TOTAL.inc()
        return entry

    def list_records(
        self,
        *,
        resource_type: str | None = None,
        action: str | None = None,
        operator_id: str | None = None,
    ) -> list[AdminAuditRecord]:
        if not self.path.exists():
            return []

        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()

        records: list[AdminAuditRecord] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = AdminAuditRecord.model_validate(json.loads(line))
            except (ValueError, json.JSONDecodeError):
                continue
            if resource_type and record.resource_type != resource_type:
                continue
            if action and record.action != action:
                continue
            if operator_id and record.operator_id != operator_id:
                continue
            records.append(record)
        return records


@lru_cache(maxsize=1)
def get_admin_audit_service() -> KnowledgeAdminAuditService:
    return KnowledgeAdminAuditService(get_settings().audit_path)
