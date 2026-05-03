import sqlite3
from pathlib import Path

import app.services.runtime_mysql as runtime_mysql_module
import pytest
from app.models.common import TraceContext
from app.models.orchestration import (
    ConversationRecord,
    IntentSummary,
    MessageRequest,
    OrchestratorResponse,
    RouteDecision,
    SessionCreateRequest,
    SessionContext,
)
from app.services.conversation_store import ConversationStore
from app.services.mongo_runtime import DisabledConversationMongoRuntime
from prometheus_client import CollectorRegistry

from tests.test_persistence import (
    FailingConversationMongoRuntime,
    RollbackRecordingMongoRuntime,
    _SQLiteConnection,
)


def _route_decision() -> RouteDecision:
    return RouteDecision(
        primary_agent="finance_order_agent",
        intent=IntentSummary(
            domain="finance_order",
            matched_domains=["finance_order_agent"],
            urgency="low",
            scene="billing",
        ),
        summary="finance_order_agent handled test query.",
    )


def _make_response(conversation_id: str, req_id: str, summary: str) -> OrchestratorResponse:
    return OrchestratorResponse(
        conversation_id=conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary=summary,
        pending_actions=[],
        trace=TraceContext(requestId=req_id, conversationId=conversation_id, traceId=req_id),
    )


def test_saga_events_recorded_on_successful_exchange(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "saga-success.db"
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
    store = ConversationStore(
        file_path=tmp_path / "saga-success.json",
        mysql_dsn="mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
        mongo_runtime=DisabledConversationMongoRuntime(),
    )
    conv = store.create(SessionCreateRequest(scene="billing", title="saga test"))
    request = MessageRequest(user_query="测试消息", scene="billing")
    response = _make_response(conv.conversation_id, "req-saga-1", "回复内容")
    store.store_exchange(
        conversation_id=conv.conversation_id,
        user_message_id="msg-saga-1",
        assistant_message_id="asst-saga-1",
        message_request=request,
        response=response,
        status="completed",
    )
    assert store._backend is not None
    events = store._backend.list_saga_events(conversation_id=conv.conversation_id)
    assert len(events) >= 1
    assert any(e["step"] == "mysql_exchange" and e["status"] == "succeeded" for e in events)


def test_saga_compensation_on_mysql_failure(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "saga-compensation.db"
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
    mongo_runtime = RollbackRecordingMongoRuntime()
    store = ConversationStore(
        file_path=tmp_path / "saga-compensation.json",
        mysql_dsn="mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
        mongo_runtime=mongo_runtime,
    )
    conv = store.create(SessionCreateRequest(scene="billing", title="saga compensation"))
    request = MessageRequest(user_query="测试补偿", scene="billing")
    response = _make_response(conv.conversation_id, "req-comp-1", "第一次回复")
    store.store_exchange(
        conversation_id=conv.conversation_id,
        user_message_id="msg-comp-1",
        assistant_message_id="asst-comp-1",
        message_request=request,
        response=response,
        status="completed",
    )

    connection_attempts = {"count": 0}

    def _connect_then_fail(**kwargs):
        connection_attempts["count"] += 1
        if connection_attempts["count"] == 1:
            return _SQLiteConnection(runtime_db)
        raise RuntimeError("mysql unavailable")

    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FailingPyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(_connect_then_fail),
            },
        ),
    )
    response2 = _make_response(conv.conversation_id, "req-comp-2", "第二次回复")
    with pytest.raises(RuntimeError, match="mysql unavailable"):
        assert store._backend is not None
        store._backend.store_assistant_continuation(
            conversation_id=conv.conversation_id,
            source_user_message_id="msg-comp-1",
            assistant_message_id="asst-comp-2",
            message_request=request,
            response=response2,
            status="completed",
            session_context=SessionContext(attributes={"stage": "compensation-test"}),
        )
    assert len(mongo_runtime.continuation_delete_calls) == 1


def test_saga_metrics_incremented(tmp_path: Path, monkeypatch) -> None:
    from app.core.metrics import SAGA_STEPS_TOTAL, SAGA_COMPENSATIONS_TOTAL

    registry = CollectorRegistry()
    runtime_db = tmp_path / "saga-metrics.db"
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
    store = ConversationStore(
        file_path=tmp_path / "saga-metrics.json",
        mysql_dsn="mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
        mongo_runtime=DisabledConversationMongoRuntime(),
    )
    conv = store.create(SessionCreateRequest(scene="billing", title="saga metrics"))
    request = MessageRequest(user_query="测试指标", scene="billing")
    response = _make_response(conv.conversation_id, "req-metrics-1", "回复")

    before_steps = SAGA_STEPS_TOTAL.labels(
        saga_name="conversation_persistence", step="mysql_exchange", status="succeeded"
    )._value.get()

    store.store_exchange(
        conversation_id=conv.conversation_id,
        user_message_id="msg-metrics-1",
        assistant_message_id="asst-metrics-1",
        message_request=request,
        response=response,
        status="completed",
    )

    after_steps = SAGA_STEPS_TOTAL.labels(
        saga_name="conversation_persistence", step="mysql_exchange", status="succeeded"
    )._value.get()
    assert after_steps > before_steps


def test_admin_saga_events_endpoint(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    runtime_db = tmp_path / "saga-admin.db"
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

    from app.services.conversation_store import ConversationStore as CS

    _store = CS(
        file_path=tmp_path / "saga-admin.json",
        mysql_dsn="mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
        mongo_runtime=DisabledConversationMongoRuntime(),
    )

    import app.api.routes.admin as admin_module
    import app.api.routes.orchestration as orch_module

    monkeypatch.setattr(orch_module, "_conversation_store", _store)
    monkeypatch.setattr(admin_module, "_conversation_store", _store)

    from app.main import app

    client = TestClient(app)
    resp = client.get("/admin/saga/events")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


def test_admin_metrics_endpoint(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "orchestrator_saga_steps_total" in resp.text
