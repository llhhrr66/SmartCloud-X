from __future__ import annotations

import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from app.models.tools import ToolCallAuditRecord, ToolCallRequest, ToolCallResponse
from app.core.observability import mark_audit_record_written
from app.services import runtime_mysql

RECOVERY_RETRY_SECONDS = 5.0


class _MySQLAuditStoreBackend:
    TABLE_NAME = "tool_hub_tool_call_audits"
    TAG_TABLE_NAME = "tool_hub_tool_call_audit_tags"

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

    def record(self, request: ToolCallRequest, response: ToolCallResponse) -> ToolCallAuditRecord:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get(request.tool_call_id)
        record = ToolCallAuditRecord(
            tool_call_id=request.tool_call_id,
            trace_id=request.trace_id,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            tool_name=request.tool_name,
            operation=request.operation,
            status=ToolCallAuditStore._status_for(response),
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
            idempotency_key=request.idempotency_key or response.idempotency_key,
            audit_tags=list(response.audit_tags),
            citations=list(response.citations),
            data_preview=ToolCallAuditStore._preview(response.data),
            session_context_patch=ToolCallAuditStore._preview(response.session_context_patch),
            error=response.error,
            user_action_hint=response.user_action_hint,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.TABLE_NAME}` (
                        tool_call_id,
                        tool_name,
                        status,
                        trace_id,
                        conversation_id,
                        message_id,
                        tenant_id,
                        idempotency_key,
                        updated_at,
                        payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.tool_call_id,
                        record.tool_name,
                        record.status,
                        record.trace_id,
                        record.conversation_id,
                        record.message_id,
                        record.tenant_id,
                        record.idempotency_key,
                        record.updated_at,
                        json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
                self._replace_tags(cursor, record)
            connection.commit()
        finally:
            connection.close()
        return record

    def get(self, tool_call_id: str) -> ToolCallAuditRecord | None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"SELECT payload_json FROM `{self.TABLE_NAME}` WHERE tool_call_id = %s",
                    (tool_call_id,),
                )
                row = cursor.fetchone()
        finally:
            connection.close()
        if not row:
            return None
        return ToolCallAuditRecord.model_validate(json.loads(row["payload_json"]))

    def list(
        self,
        *,
        tool_name: str | None,
        status: str | None,
        trace_id: str | None,
        conversation_id: str | None,
        message_id: str | None,
        tenant_id: str | None,
        idempotency_key: str | None,
        audit_tag: str | None,
        limit: int,
    ) -> list[ToolCallAuditRecord]:
        conditions: list[str] = []
        params: list[object] = []
        join_clause = ""
        if audit_tag is not None:
            join_clause = (
                f"INNER JOIN `{self.TAG_TABLE_NAME}` AS audit_tags "
                "ON audit_tags.tool_call_id = audit.tool_call_id AND audit_tags.audit_tag = %s"
            )
            params.append(audit_tag)
        for column, value in (
            ("tool_name", tool_name),
            ("status", status),
            ("trace_id", trace_id),
            ("conversation_id", conversation_id),
            ("message_id", message_id),
            ("tenant_id", tenant_id),
            ("idempotency_key", idempotency_key),
        ):
            if value is not None:
                conditions.append(f"audit.{column} = %s")
                params.append(value)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT audit.payload_json
                    FROM `{self.TABLE_NAME}` AS audit
                    {join_clause}
                    {where_clause}
                    ORDER BY audit.updated_at DESC, audit.tool_call_id DESC
                    LIMIT %s
                    """,
                    (*params, limit),
                )
                rows = cursor.fetchall() or []
        finally:
            connection.close()
        return [
            ToolCallAuditRecord.model_validate(json.loads(row["payload_json"]))
            for row in rows
        ]

    def clear(self) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(f"DELETE FROM `{self.TAG_TABLE_NAME}`")
                cursor.execute(f"DELETE FROM `{self.TABLE_NAME}`")
            connection.commit()
        finally:
            connection.close()

    def import_record(self, record: ToolCallAuditRecord) -> None:
        connection = runtime_mysql.connect(self._mysql_dsn)
        try:
            with connection.cursor() as cursor:
                self._ensure_schema(cursor)
                cursor.execute(
                    f"""
                    REPLACE INTO `{self.TABLE_NAME}` (
                        tool_call_id,
                        tool_name,
                        status,
                        trace_id,
                        conversation_id,
                        message_id,
                        tenant_id,
                        idempotency_key,
                        updated_at,
                        payload_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.tool_call_id,
                        record.tool_name,
                        record.status,
                        record.trace_id,
                        record.conversation_id,
                        record.message_id,
                        record.tenant_id,
                        record.idempotency_key,
                        record.updated_at,
                        json.dumps(record.model_dump(mode="json"), ensure_ascii=False),
                    ),
                )
                self._replace_tags(cursor, record)
            connection.commit()
        finally:
            connection.close()

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "mysql",
            "table": self.TABLE_NAME,
            "auditTagTable": self.TAG_TABLE_NAME,
            "configured": True,
        }

    def _ensure_schema(self, cursor) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.TABLE_NAME}` (
                tool_call_id VARCHAR(128) PRIMARY KEY,
                tool_name VARCHAR(255) NOT NULL,
                status VARCHAR(64) NOT NULL,
                trace_id VARCHAR(128) NULL,
                conversation_id VARCHAR(128) NULL,
                message_id VARCHAR(128) NULL,
                tenant_id VARCHAR(128) NULL,
                idempotency_key VARCHAR(255) NULL,
                updated_at VARCHAR(128) NOT NULL,
                payload_json LONGTEXT NOT NULL
            )
            """
        )
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS `{self.TAG_TABLE_NAME}` (
                tool_call_id VARCHAR(128) NOT NULL,
                audit_tag VARCHAR(128) NOT NULL,
                updated_at VARCHAR(128) NOT NULL,
                PRIMARY KEY (tool_call_id, audit_tag)
            )
            """
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.TABLE_NAME,
            index_name=f"idx_{self.TABLE_NAME}_updated",
            columns=("updated_at", "tool_call_id"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.TABLE_NAME,
            index_name=f"idx_{self.TABLE_NAME}_conversation",
            columns=("conversation_id", "message_id", "updated_at"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.TABLE_NAME,
            index_name=f"idx_{self.TABLE_NAME}_trace",
            columns=("trace_id", "updated_at"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.TABLE_NAME,
            index_name=f"idx_{self.TABLE_NAME}_idempotency",
            columns=("idempotency_key", "updated_at"),
        )
        runtime_mysql.create_index_if_missing(
            cursor,
            table_name=self.TAG_TABLE_NAME,
            index_name=f"idx_{self.TAG_TABLE_NAME}_audit_tag",
            columns=("audit_tag", "updated_at", "tool_call_id"),
        )

    def _replace_tags(self, cursor, record: ToolCallAuditRecord) -> None:
        cursor.execute(
            f"DELETE FROM `{self.TAG_TABLE_NAME}` WHERE tool_call_id = %s",
            (record.tool_call_id,),
        )
        for audit_tag in dict.fromkeys(record.audit_tags):
            cursor.execute(
                f"""
                INSERT INTO `{self.TAG_TABLE_NAME}` (
                    tool_call_id,
                    audit_tag,
                    updated_at
                ) VALUES (%s, %s, %s)
                """,
                (
                    record.tool_call_id,
                    audit_tag,
                    record.updated_at,
                ),
            )


class ToolCallAuditStore:
    """Tool-call audit trail with MySQL-first persistence and local fallback."""

    def __init__(
        self,
        file_path: str | Path | None = None,
        *,
        mysql_dsn: str | None = None,
    ) -> None:
        self._lock = RLock()
        self._records: dict[str, ToolCallAuditRecord] = {}
        self._file_path: Path | None = None
        self._mysql_dsn: str | None = None
        self._backend: _MySQLAuditStoreBackend | None = None
        self._backend_error: str | None = None
        self._next_recovery_attempt_at = 0.0
        self.configure_persistence(file_path, mysql_dsn=mysql_dsn)

    def configure_persistence(
        self,
        file_path: str | Path | None,
        *,
        mysql_dsn: str | None = None,
    ) -> None:
        path = Path(file_path).expanduser() if file_path else None
        with self._lock:
            self._file_path = path
            self._mysql_dsn = mysql_dsn
            self._backend = _MySQLAuditStoreBackend(mysql_dsn) if mysql_dsn else None
            self._backend_error = None
            self._next_recovery_attempt_at = 0.0
            self._records = self._load_records(path)
            if self._backend is not None:
                try:
                    self._backend.ensure_ready()
                    self._bootstrap_backend_from_local_unlocked()
                    self._persist_unlocked()
                except Exception as exc:
                    self._degrade_backend(exc)

    def record(self, request: ToolCallRequest, response: ToolCallResponse) -> ToolCallAuditRecord:
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.record(request, response).model_copy(deep=True)
                with self._lock:
                    self._records[record.tool_call_id] = record.model_copy(deep=True)
                    self._persist_unlocked()
                mark_audit_record_written()
                return record
            except Exception as exc:
                self._degrade_backend(exc)
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
                idempotency_key=request.idempotency_key or response.idempotency_key,
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
            mark_audit_record_written()
            return record

    def get(self, tool_call_id: str) -> ToolCallAuditRecord | None:
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                record = backend.get(tool_call_id)
                if record is not None:
                    with self._lock:
                        self._records[record.tool_call_id] = record.model_copy(deep=True)
                return record.model_copy(deep=True) if record else None
            except Exception as exc:
                self._degrade_backend(exc)
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
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                records = [
                    item.model_copy(deep=True)
                    for item in backend.list(
                        tool_name=tool_name,
                        status=status,
                        trace_id=trace_id,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        tenant_id=tenant_id,
                        idempotency_key=idempotency_key,
                        audit_tag=audit_tag,
                        limit=limit,
                    )
                ]
                if records:
                    with self._lock:
                        for record in records:
                            self._records[record.tool_call_id] = record.model_copy(deep=True)
                return records
            except Exception as exc:
                self._degrade_backend(exc)
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
        backend = self._maybe_restore_backend()
        if backend is not None:
            try:
                backend.clear()
                with self._lock:
                    self._records.clear()
                    self._persist_unlocked()
                return
            except Exception as exc:
                self._degrade_backend(exc)
        with self._lock:
            self._records.clear()
            self._persist_unlocked()

    def describe_backend(self) -> dict[str, object]:
        backend = self._maybe_restore_backend()
        if backend is not None:
            description = backend.describe_backend()
            description["fallbackBackend"] = "json-file" if self._file_path else "memory"
            description["fallbackPath"] = str(self._file_path) if self._file_path else None
            description["fallbackWriteMode"] = "degraded-only"
            return description
        return {
            "backend": "json-file" if self._file_path else "memory",
            "configured": self._file_path is not None,
            "path": str(self._file_path) if self._file_path else None,
            "degradedFrom": "mysql" if self._backend_error else None,
            "backendError": self._backend_error,
        }

    def _maybe_restore_backend(self) -> _MySQLAuditStoreBackend | None:
        if self._backend is not None or not self._mysql_dsn:
            return self._backend
        now = time.monotonic()
        if now < self._next_recovery_attempt_at:
            return None
        with self._lock:
            if self._backend is not None or not self._mysql_dsn:
                return self._backend
            now = time.monotonic()
            if now < self._next_recovery_attempt_at:
                return None
            backend = _MySQLAuditStoreBackend(self._mysql_dsn)
            try:
                backend.ensure_ready()
            except Exception as exc:
                self._backend_error = f"{exc.__class__.__name__}: {exc}"
                self._next_recovery_attempt_at = now + RECOVERY_RETRY_SECONDS
                self._persist_unlocked(force=True)
                return None
            self._backend = backend
            self._backend_error = None
            self._next_recovery_attempt_at = 0.0
            self._bootstrap_backend_from_local_unlocked()
            self._persist_unlocked()
            return self._backend

    def _degrade_backend(self, exc: Exception) -> None:
        with self._lock:
            self._backend = None
            self._backend_error = f"{exc.__class__.__name__}: {exc}"
            self._next_recovery_attempt_at = time.monotonic() + RECOVERY_RETRY_SECONDS
            self._persist_unlocked(force=True)

    def _bootstrap_backend_from_local_unlocked(self) -> None:
        backend = self._backend
        if backend is None or not self._records:
            return
        authoritative: dict[str, ToolCallAuditRecord] = {}
        for tool_call_id, record in self._records.items():
            remote_record = backend.get(tool_call_id)
            if remote_record is None or self._prefer_local_record(record, remote_record):
                backend.import_record(record.model_copy(deep=True))
                authoritative[tool_call_id] = record.model_copy(deep=True)
                continue
            authoritative[tool_call_id] = remote_record.model_copy(deep=True)
        self._records = authoritative

    @staticmethod
    def _prefer_local_record(local: ToolCallAuditRecord, remote: ToolCallAuditRecord) -> bool:
        local_updated_at = ToolCallAuditStore._parse_timestamp(local.updated_at)
        remote_updated_at = ToolCallAuditStore._parse_timestamp(remote.updated_at)
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

    def _persist_unlocked(self, *, force: bool = False) -> None:
        if self._file_path is None:
            return
        if not force and self._backend is not None:
            self._remove_fallback_file_unlocked()
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": {
                tool_call_id: record.model_dump(mode="json")
                for tool_call_id, record in self._records.items()
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
