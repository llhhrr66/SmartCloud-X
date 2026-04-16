import sqlite3
from pathlib import Path

import app.services.runtime_mysql as runtime_mysql_module
from app.models.tools import (
    ToolCallOperator,
    ToolCallRequest,
    ToolCallResponse,
    ToolCallUserContext,
)
from app.services.audit_store import ToolCallAuditStore


class _SQLiteCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def execute(self, sql: str, params=()) -> None:
        translated = sql.replace("`", "").replace("%s", "?")
        self._cursor.execute(translated, params)

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self):
        return [dict(row) for row in self._cursor.fetchall()]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._cursor.close()


class _SQLiteConnection:
    def __init__(self, path: Path) -> None:
        self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row

    def cursor(self) -> _SQLiteCursor:
        return _SQLiteCursor(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


class _FailingPyMySQLModule:
    cursors = type("FakeCursors", (), {"DictCursor": object})

    @staticmethod
    def connect(**kwargs):
        raise RuntimeError("mysql unavailable")


def test_audit_store_reloads_persisted_records(tmp_path: Path) -> None:
    store_path = tmp_path / "tool-call-audits.json"
    store = ToolCallAuditStore(file_path=store_path)
    request = ToolCallRequest(
        trace_id="trace-audit-1",
        conversation_id="conv-audit-1",
        message_id="msg-audit-1",
        tool_call_id="tc-audit-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-1",
        operation="execute",
    )
    response = ToolCallResponse(
        success=True,
        code=0,
        message="ok",
        status="completed",
        summary="账单查询已完成。",
        result={"billing_cycle": "2026-04"},
        data={"billing_cycle": "2026-04"},
        citations=["billing://statement"],
        audit_tags=["finance-order", "execute"],
        session_context_patch={"attributes": {"statement_no": "stmt_2026_04_001"}},
        tool_call_id="tc-audit-1",
        latency_ms=12,
        provider="business-tools",
        idempotency_key="tool-tc-audit-1",
        user_action_hint={
            "action": "clarify-tool-input",
            "message": "请提供账单范围。",
            "missing_fields": ["range"],
        },
    )

    store.record(request, response)

    reloaded = ToolCallAuditStore(file_path=store_path)
    record = reloaded.get("tc-audit-1")

    assert record is not None
    assert record.trace_id == "trace-audit-1"
    assert record.message_id == "msg-audit-1"
    assert record.summary == "账单查询已完成。"
    assert record.citations == ["billing://statement"]
    assert record.session_context_patch["attributes"]["statement_no"] == "stmt_2026_04_001"
    assert record.user_action_hint is not None
    assert record.user_action_hint.action == "clarify-tool-input"
    assert reloaded.list(conversation_id="conv-audit-1")[0].tool_call_id == "tc-audit-1"


def test_audit_store_uses_mysql_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "tool-hub-runtime.db"
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FakePyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: _SQLiteConnection(runtime_db)),
            },
        ),
    )
    fallback_path = tmp_path / "degraded-audit-store.json"
    store = ToolCallAuditStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    request = ToolCallRequest(
        trace_id="trace-audit-mysql-1",
        conversation_id="conv-audit-mysql-1",
        message_id="msg-audit-mysql-1",
        tool_call_id="tc-audit-mysql-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-mysql-1",
        operation="execute",
    )
    response = ToolCallResponse(
        success=True,
        code=0,
        message="ok",
        status="completed",
        summary="账单查询已完成。",
        result={"billing_cycle": "2026-04"},
        data={"billing_cycle": "2026-04"},
        citations=["billing://statement"],
        audit_tags=["finance-order", "execute"],
        session_context_patch={"attributes": {"statement_no": "stmt_2026_04_001"}},
        tool_call_id="tc-audit-mysql-1",
        latency_ms=12,
        provider="business-tools",
        idempotency_key="tool-tc-audit-mysql-1",
    )

    store.record(request, response)
    record = store.get("tc-audit-mysql-1")

    assert record is not None
    assert record.trace_id == "trace-audit-mysql-1"
    assert record.status == "completed"
    assert store.list(conversation_id="conv-audit-mysql-1")[0].tool_call_id == "tc-audit-mysql-1"
    assert not fallback_path.exists()
    description = store.describe_backend()
    assert description["backend"] == "mysql"
    assert description["fallbackPath"] == str(fallback_path)


def test_audit_store_keeps_degraded_json_mirror_after_mysql_read_failure(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "tool-hub-runtime-mirror.db"
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FakePyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: _SQLiteConnection(runtime_db)),
            },
        ),
    )
    fallback_path = tmp_path / "degraded-audit-store-mirror.json"
    store = ToolCallAuditStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    request = ToolCallRequest(
        trace_id="trace-audit-mirror-1",
        conversation_id="conv-audit-mirror-1",
        message_id="msg-audit-mirror-1",
        tool_call_id="tc-audit-mirror-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-mirror-1",
        operation="execute",
    )
    response = ToolCallResponse(
        success=True,
        code=0,
        message="ok",
        status="completed",
        summary="账单查询已镜像。",
        result={"billing_cycle": "2026-04"},
        data={"billing_cycle": "2026-04"},
        citations=[],
        audit_tags=["finance-order", "execute"],
        tool_call_id="tc-audit-mirror-1",
        latency_ms=12,
        provider="business-tools",
    )

    store.record(request, response)
    backend = store._backend
    assert backend is not None
    assert not fallback_path.exists()
    monkeypatch.setattr(backend, "get", lambda tool_call_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))

    record = store.get("tc-audit-mirror-1")

    assert record is not None
    assert record.summary == "账单查询已镜像。"
    assert fallback_path.exists()
    description = store.describe_backend()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "mysql"
    assert description["path"] == str(fallback_path)


def test_audit_store_degrades_at_startup_when_mysql_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runtime_mysql_module, "pymysql", _FailingPyMySQLModule)
    fallback_path = tmp_path / "degraded-audit-store-startup.json"

    store = ToolCallAuditStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )

    description = store.describe_backend()

    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "mysql"
    assert description["path"] == str(fallback_path)


def test_audit_store_recovers_mysql_after_startup_degradation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(runtime_mysql_module, "pymysql", _FailingPyMySQLModule)
    fallback_path = tmp_path / "recovering-audit-store-startup.json"
    store = ToolCallAuditStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    request = ToolCallRequest(
        trace_id="trace-audit-recover-1",
        conversation_id="conv-audit-recover-1",
        message_id="msg-audit-recover-1",
        tool_call_id="tc-audit-recover-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-recover-1",
        operation="execute",
    )
    response = ToolCallResponse(
        success=True,
        code=0,
        message="ok",
        status="completed",
        summary="账单查询已恢复到 MySQL。",
        result={"billing_cycle": "2026-04"},
        data={"billing_cycle": "2026-04"},
        citations=["billing://statement"],
        audit_tags=["finance-order", "execute"],
        tool_call_id="tc-audit-recover-1",
        latency_ms=12,
        provider="business-tools",
        idempotency_key="tool-tc-audit-recover-1",
    )

    store.record(request, response)
    assert fallback_path.exists()

    runtime_db = tmp_path / "tool-hub-runtime-recover.db"
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FakePyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: _SQLiteConnection(runtime_db)),
            },
        ),
    )
    store._next_recovery_attempt_at = 0.0

    record = store.get("tc-audit-recover-1")

    assert record is not None
    assert record.summary == "账单查询已恢复到 MySQL。"
    assert store.describe_backend()["backend"] == "mysql"
    assert not fallback_path.exists()
    assert store.list(conversation_id="conv-audit-recover-1")[0].tool_call_id == "tc-audit-recover-1"


def test_audit_store_mysql_filters_audit_tags_without_loading_all_records(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "tool-hub-runtime-filter.db"
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FakePyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: _SQLiteConnection(runtime_db)),
            },
        ),
    )
    store = ToolCallAuditStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    request = ToolCallRequest(
        trace_id="trace-audit-filter-1",
        conversation_id="conv-audit-filter-1",
        message_id="msg-audit-filter-1",
        tool_call_id="tc-audit-filter-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-filter-1",
        operation="execute",
    )

    store.record(
        request,
        ToolCallResponse(
            success=True,
            code=0,
            message="ok",
            status="completed",
            summary="首次查询完成。",
            result={"billing_cycle": "2026-04"},
            data={"billing_cycle": "2026-04"},
            citations=[],
            audit_tags=["finance-order", "execute"],
            tool_call_id="tc-audit-filter-1",
            latency_ms=12,
            provider="business-tools",
        ),
    )
    store.record(
        request.model_copy(update={"tool_call_id": "tc-audit-filter-2"}),
        ToolCallResponse(
            success=True,
            code=0,
            message="ok",
            status="completed",
            summary="命中缓存。",
            result={"billing_cycle": "2026-04"},
            data={"billing_cycle": "2026-04"},
            citations=[],
            audit_tags=["finance-order", "execute", "cache-hit"],
            tool_call_id="tc-audit-filter-2",
            latency_ms=3,
            provider="business-tools",
        ),
    )

    filtered = store.list(audit_tag="cache-hit", limit=10)

    assert [item.tool_call_id for item in filtered] == ["tc-audit-filter-2"]


def test_audit_store_warms_degraded_mirror_from_mysql_reads(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "tool-hub-runtime-read-mirror.db"
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FakePyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: _SQLiteConnection(runtime_db)),
            },
        ),
    )
    request = ToolCallRequest(
        trace_id="trace-audit-read-mirror-1",
        conversation_id="conv-audit-read-mirror-1",
        message_id="msg-audit-read-mirror-1",
        tool_call_id="tc-audit-read-mirror-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-read-mirror-1",
        operation="execute",
    )
    response = ToolCallResponse(
        success=True,
        code=0,
        message="ok",
        status="completed",
        summary="跨实例读取后仍可降级。",
        result={"billing_cycle": "2026-04"},
        data={"billing_cycle": "2026-04"},
        citations=["billing://statement"],
        audit_tags=["finance-order", "execute"],
        tool_call_id="tc-audit-read-mirror-1",
        latency_ms=12,
        provider="business-tools",
        idempotency_key="tool-tc-audit-read-mirror-1",
    )
    primary = ToolCallAuditStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    primary.record(request, response)

    fallback_path = tmp_path / "degraded-audit-store-read-mirror.json"
    replica = ToolCallAuditStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )

    record = replica.get("tc-audit-read-mirror-1")

    assert record is not None
    assert record.summary == "跨实例读取后仍可降级。"
    assert not fallback_path.exists()

    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(backend, "get", lambda tool_call_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))

    record = replica.get("tc-audit-read-mirror-1")

    description = replica.describe_backend()
    assert record is not None
    assert record.summary == "跨实例读取后仍可降级。"
    assert fallback_path.exists()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "mysql"
    assert description["path"] == str(fallback_path)


def test_audit_store_keeps_mysql_authority_over_stale_degraded_json_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_db = tmp_path / "tool-hub-runtime-authority.db"
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FakePyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: _SQLiteConnection(runtime_db)),
            },
        ),
    )
    fallback_path = tmp_path / "stale-audit-store.json"
    local_store = ToolCallAuditStore(file_path=fallback_path)
    request = ToolCallRequest(
        trace_id="trace-audit-authority-1",
        conversation_id="conv-audit-authority-1",
        message_id="msg-audit-authority-1",
        tool_call_id="tc-audit-authority-1",
        tool_name="billing.query_statement",
        operator=ToolCallOperator(type="agent", id="Finance_Order_Agent"),
        user_context=ToolCallUserContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            tenant_id="tenant-a",
        ),
        payload={"range": "this_month"},
        idempotency_key="tool-tc-audit-authority-1",
        operation="execute",
    )
    local_store.record(
        request,
        ToolCallResponse(
            success=True,
            code=0,
            message="ok",
            status="completed",
            summary="本地旧审计记录。",
            result={"billing_cycle": "2026-03"},
            data={"billing_cycle": "2026-03"},
            citations=[],
            audit_tags=["finance-order", "execute"],
            tool_call_id="tc-audit-authority-1",
            latency_ms=12,
            provider="business-tools",
        ),
    )

    primary = ToolCallAuditStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    primary.record(
        request,
        ToolCallResponse(
            success=True,
            code=0,
            message="ok",
            status="completed",
            summary="数据库新审计记录。",
            result={"billing_cycle": "2026-04"},
            data={"billing_cycle": "2026-04"},
            citations=[],
            audit_tags=["finance-order", "execute"],
            tool_call_id="tc-audit-authority-1",
            latency_ms=3,
            provider="business-tools",
        ),
    )

    replica = ToolCallAuditStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(backend, "get", lambda tool_call_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))

    record = replica.get("tc-audit-authority-1")

    assert record is not None
    assert record.summary == "数据库新审计记录。"
    assert record.data_preview["billing_cycle"] == "2026-04"
