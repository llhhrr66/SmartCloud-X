import sqlite3
import time
from pathlib import Path

import app.services.runtime_mysql as runtime_mysql_module
import app.services.runtime_redis as runtime_redis_module
import pytest
from app.models.common import TraceContext
from app.models.orchestration import (
    AgentRouteRecord,
    ExecutionCheckpoint,
    IntentSummary,
    MessageRequest,
    OrchestratorResponse,
    PendingUserAction,
    RouteDecision,
    SessionCreateRequest,
    SessionStateSnapshot,
    StreamEventRecord,
)
from app.services.conversation_store import ConversationStore
from app.services.agent_config_store import AgentConfigStore
from app.services.run_control import (
    ActiveRunConflictError,
    OrchestrationCancelled,
    OrchestrationRunControl,
)
from app.services.sse_event_store import SseEventStore
from app.services.state_store import OrchestrationStateStore


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


class FakeRedisClient:
    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.values: dict[str, list[str]] = {}
        self.expires_at: dict[str, float] = {}
        self.lrange_calls: list[tuple[str, int, int]] = []

    def _purge_expired(self, key: str) -> None:
        expires_at = self.expires_at.get(key)
        if expires_at is None or expires_at > time.time():
            return
        self.expires_at.pop(key, None)
        self.strings.pop(key, None)
        self.values.pop(key, None)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            self._purge_expired(key)
            deleted += int(key in self.strings or key in self.values)
            self.strings.pop(key, None)
            self.values.pop(key, None)
            self.expires_at.pop(key, None)
        return deleted

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        self._purge_expired(key)
        if nx and (key in self.strings or key in self.values):
            return False
        self.strings[key] = value
        self.values.pop(key, None)
        if ex is not None:
            self.expires_at[key] = time.time() + max(int(ex), 1)
        else:
            self.expires_at.pop(key, None)
        return True

    def get(self, key: str) -> str | None:
        self._purge_expired(key)
        return self.strings.get(key)

    def expire(self, key: str, seconds: int) -> bool:
        self._purge_expired(key)
        if key not in self.strings and key not in self.values:
            return False
        self.expires_at[key] = time.time() + max(int(seconds), 1)
        return True

    def rpush(self, key: str, *values: str) -> None:
        self._purge_expired(key)
        self.values.setdefault(key, []).extend(values)
        self.strings.pop(key, None)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        self._purge_expired(key)
        self.lrange_calls.append((key, start, end))
        items = list(self.values.get(key, []))
        if end == -1:
            end = len(items) - 1
        return items[start : end + 1]

    def llen(self, key: str) -> int:
        self._purge_expired(key)
        return len(self.values.get(key, []))

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list({*self.strings.keys(), *self.values.keys()}):
            self._purge_expired(key)
        for key in list({*self.strings.keys(), *self.values.keys()}):
            if key.startswith(prefix):
                yield key


class FailingRedisClient(FakeRedisClient):
    def rpush(self, key: str, *values: str) -> None:
        raise RuntimeError("redis unavailable")


class FailingRedisKeyClient(FakeRedisClient):
    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        raise RuntimeError("redis unavailable")


class PingFailingRedisClient(FakeRedisClient):
    def ping(self) -> None:
        raise RuntimeError("redis unavailable")


def _route_decision() -> RouteDecision:
    return RouteDecision(
        primary_agent="finance_order_agent",
        intent=IntentSummary(
            domain="finance_order",
            matched_domains=["finance_order_agent"],
            urgency="low",
            needs_human_handoff=False,
            scene="billing",
        ),
        summary="finance_order_agent handled billing baseline.",
    )


def test_conversation_store_reloads_persisted_messages_and_retry_snapshots(tmp_path: Path) -> None:
    store_path = tmp_path / "conversations.json"
    store = ConversationStore(file_path=store_path)
    conversation = store.create(SessionCreateRequest(scene="billing", title="账单会话"))
    request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回账单汇总。",
        pending_actions=[],
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )

    store.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-1",
        assistant_message_id="asst_msg-1",
        message_request=request,
        response=response,
        status="completed",
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )

    reloaded = ConversationStore(file_path=store_path)
    messages = reloaded.list_messages(conversation.conversation_id).items
    retry_request = reloaded.build_retry_request(conversation.conversation_id, message_id="asst_msg-1")

    assert len(messages) == 2
    assert messages[0].content == "帮我查本月账单"
    assert messages[1].content == "已返回账单汇总。"
    assert retry_request.user_query == "帮我查本月账单"
    assert retry_request.message_id is None


def test_state_store_reloads_persisted_snapshots(tmp_path: Path) -> None:
    store_path = tmp_path / "state.json"
    store = OrchestrationStateStore(file_path=store_path)
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[
            AgentRouteRecord(
                step_id="step-1-finance-order-agent",
                order=1,
                agent="finance_order_agent",
                objective="主处理账单问题。",
                status="success",
                tool_names=["billing.query_statement"],
                tool_call_ids=["tc-1"],
                tool_statuses=["completed"],
            )
        ],
        checkpoints=[
            ExecutionCheckpoint(
                name="intent-classified",
                description="完成意图识别与主 agent 路由。",
                status="completed",
            )
        ],
        pending_user_actions=[
            PendingUserAction(
                tool_name="billing.query_statement",
                tool_call_id="tc-1",
                agent="finance_order_agent",
                action="clarify-tool-input",
                message="请提供账单范围。",
                missing_fields=["range"],
            )
        ],
        final_response_summary="已持久化。",
        trace=TraceContext(requestId="req-state-1", conversationId="conv-state-1", traceId="trace-state-1"),
    )

    store.save(snapshot)

    reloaded = OrchestrationStateStore(file_path=store_path)
    persisted = reloaded.get("conv-state-1")

    assert persisted is not None
    assert persisted.version == 1
    assert persisted.agent_routes[0].tool_call_ids == ["tc-1"]
    assert persisted.checkpoints[0].name == "intent-classified"
    assert persisted.pending_user_actions[0].action == "clarify-tool-input"
    assert persisted.trace.trace_id == "trace-state-1"


def test_sse_event_store_reloads_persisted_events(tmp_path: Path) -> None:
    store_path = tmp_path / "stream-events.json"
    store = SseEventStore(file_path=store_path)
    store.save(
        "conv-stream-1",
        "msg-stream-1",
        [
            StreamEventRecord(
                event_id="evt-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-1"},
                created_at="2026-04-16T00:00:00+00:00",
            ),
            StreamEventRecord(
                event_id="evt-0002",
                sequence=2,
                event="done",
                data={"finish_reason": "stop"},
                created_at="2026-04-16T00:00:01+00:00",
            ),
        ],
    )

    reloaded = SseEventStore(file_path=store_path)
    page = reloaded.get_page("conv-stream-1", "msg-stream-1", after_event_id="evt-0001", limit=10)

    assert page is not None
    assert page.conversation_id == "conv-stream-1"
    assert page.message_id == "msg-stream-1"
    assert [item.event for item in page.items] == ["done"]


def test_conversation_store_uses_mysql_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "orchestrator-runtime.db"
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
    fallback_path = tmp_path / "degraded-conversations.json"
    store = ConversationStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    conversation = store.create(SessionCreateRequest(scene="billing", title="账单会话"))
    request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回账单汇总。",
        pending_actions=[],
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )

    store.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-1",
        assistant_message_id="asst_msg-1",
        message_request=request,
        response=response,
        status="completed",
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )

    messages = store.list_messages(conversation.conversation_id).items
    retry_request = store.build_retry_request(conversation.conversation_id, message_id="asst_msg-1")

    assert len(messages) == 2
    assert messages[1].content == "已返回账单汇总。"
    assert retry_request.user_query == "帮我查本月账单"
    assert not fallback_path.exists()
    description = store.describe_backend()
    assert description["backend"] == "mysql"
    assert description["fallbackPath"] == str(fallback_path)
    assert description["runtimeCache"]["backend"] == "memory"


def test_conversation_store_uses_redis_runtime_cache_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "orchestrator-runtime-redis-cache.db"
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
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    primary = ConversationStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:conversation",
    )
    conversation = primary.create(SessionCreateRequest(scene="billing", title="账单会话"))
    request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回账单汇总。",
        pending_actions=[],
        trace=TraceContext(requestId="req-cache-1", conversationId=conversation.conversation_id, traceId="trace-cache-1"),
    )
    primary.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-cache-1",
        assistant_message_id="asst_msg-cache-1",
        message_request=request,
        response=response,
        status="completed",
        trace=response.trace,
    )

    replica = ConversationStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:conversation",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(
        backend,
        "get",
        lambda conversation_id: (_ for _ in ()).throw(AssertionError("mysql get should not be hit on cache hit")),
    )
    monkeypatch.setattr(
        backend,
        "get_context",
        lambda conversation_id: (_ for _ in ()).throw(AssertionError("mysql context should not be hit on cache hit")),
    )
    monkeypatch.setattr(
        backend,
        "fetch_messages",
        lambda conversation_id: (_ for _ in ()).throw(AssertionError("mysql messages should not be hit on cache hit")),
    )
    monkeypatch.setattr(
        backend,
        "get_request_snapshot",
        lambda conversation_id, *, message_id: (_ for _ in ()).throw(
            AssertionError("mysql snapshots should not be hit on cache hit")
        ),
    )
    monkeypatch.setattr(
        backend,
        "resolve_request_message_id",
        lambda conversation_id, message_id: (_ for _ in ()).throw(
            AssertionError("mysql assistant mapping should not be hit on cache hit")
        ),
    )

    record = replica.get(conversation.conversation_id)
    context = replica.get_context(conversation.conversation_id)
    messages = replica.list_messages(conversation.conversation_id, page_size=10)
    retry_request = replica.build_retry_request(conversation.conversation_id, message_id="asst_msg-cache-1")
    latest_message_id = replica.latest_message_id(conversation.conversation_id, role="assistant")
    resolved_message_id = replica.resolve_request_message_id(conversation.conversation_id, "asst_msg-cache-1")

    assert record is not None
    assert record.summary == "已返回账单汇总。"
    assert context is not None
    assert context.history_summary
    assert [item.message_id for item in messages.items] == ["msg-cache-1", "asst_msg-cache-1"]
    assert retry_request.user_query == "帮我查本月账单"
    assert latest_message_id == "asst_msg-cache-1"
    assert resolved_message_id == "msg-cache-1"
    assert replica.describe_backend()["runtimeCache"]["backend"] == "redis-json"


def test_conversation_store_backfills_redis_runtime_cache_from_mysql_on_cache_miss(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "orchestrator-runtime-redis-backfill.db"
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
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    primary = ConversationStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:conversation-backfill",
    )
    conversation = primary.create(SessionCreateRequest(scene="billing", title="账单会话"))
    request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="需要回填缓存。",
        pending_actions=[],
        trace=TraceContext(
            requestId="req-cache-backfill-1",
            conversationId=conversation.conversation_id,
            traceId="trace-cache-backfill-1",
        ),
    )
    primary.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-cache-backfill-1",
        assistant_message_id="asst_msg-cache-backfill-1",
        message_request=request,
        response=response,
        status="completed",
        trace=response.trace,
    )
    fake_redis.delete(
        primary._record_cache_key(conversation.conversation_id),
        primary._context_cache_key(conversation.conversation_id),
        primary._messages_cache_key(conversation.conversation_id),
        primary._request_snapshot_cache_key(conversation.conversation_id, "msg-cache-backfill-1"),
        primary._assistant_mapping_cache_key(conversation.conversation_id, "asst_msg-cache-backfill-1"),
    )

    replica = ConversationStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:conversation-backfill",
    )

    record = replica.get(conversation.conversation_id)
    context = replica.get_context(conversation.conversation_id)
    messages = replica.list_messages(conversation.conversation_id, page_size=10)
    retry_request = replica.build_retry_request(conversation.conversation_id, message_id="asst_msg-cache-backfill-1")

    assert record is not None
    assert record.summary == "需要回填缓存。"
    assert context is not None
    assert context.history_summary
    assert [item.message_id for item in messages.items] == ["msg-cache-backfill-1", "asst_msg-cache-backfill-1"]
    assert retry_request.user_query == "帮我查本月账单"
    assert fake_redis.get(replica._record_cache_key(conversation.conversation_id)) is not None
    assert fake_redis.get(replica._context_cache_key(conversation.conversation_id)) is not None
    assert fake_redis.get(replica._messages_cache_key(conversation.conversation_id)) is not None
    assert fake_redis.get(
        replica._request_snapshot_cache_key(conversation.conversation_id, "msg-cache-backfill-1")
    ) is not None
    assert fake_redis.get(
        replica._assistant_mapping_cache_key(conversation.conversation_id, "asst_msg-cache-backfill-1")
    ) == "msg-cache-backfill-1"


def test_conversation_store_bootstraps_mysql_from_degraded_json(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "orchestrator-runtime-bootstrap.db"
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
    store_path = tmp_path / "bootstrap-conversations.json"
    local_store = ConversationStore(file_path=store_path)
    conversation = local_store.create(SessionCreateRequest(scene="billing", title="迁移账单会话"))
    request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回账单汇总。",
        pending_actions=[],
        trace=TraceContext(requestId="req-bootstrap-1", conversationId=conversation.conversation_id, traceId="trace-bootstrap-1"),
    )
    local_store.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-bootstrap-1",
        assistant_message_id="asst_msg-bootstrap-1",
        message_request=request,
        response=response,
        status="completed",
        trace=response.trace,
    )

    ConversationStore(
        file_path=store_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    replica = ConversationStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )

    migrated = replica.get(conversation.conversation_id)
    messages = replica.list_messages(conversation.conversation_id).items
    retry_request = replica.build_retry_request(conversation.conversation_id, message_id="asst_msg-bootstrap-1")

    assert migrated is not None
    assert migrated.title == "迁移账单会话"
    assert [item.message_id for item in messages] == ["msg-bootstrap-1", "asst_msg-bootstrap-1"]
    assert retry_request.user_query == "帮我查本月账单"


def test_conversation_store_keeps_mysql_authority_over_stale_degraded_json_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_db = tmp_path / "orchestrator-runtime-authority.db"
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
    conversation_id = "conv-authority-1"
    fallback_path = tmp_path / "stale-conversations.json"

    local_store = ConversationStore(file_path=fallback_path)
    local_store.ensure(conversation_id, scene="billing", title="本地旧会话")
    local_store.store_exchange(
        conversation_id=conversation_id,
        user_message_id="msg-local-1",
        assistant_message_id="asst-local-1",
        message_request=MessageRequest(user_query="本地旧请求", scene="billing"),
        response=OrchestratorResponse(
            conversation_id=conversation_id,
            route=_route_decision(),
            executions=[],
            next_action="respond-with-agent-summary",
            final_response_summary="本地旧摘要。",
            pending_actions=[],
            trace=TraceContext(requestId="req-local-1", conversationId=conversation_id, traceId="trace-local-1"),
        ),
        status="completed",
        trace=TraceContext(requestId="req-local-1", conversationId=conversation_id, traceId="trace-local-1"),
    )

    primary = ConversationStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    primary.ensure(conversation_id, scene="billing", title="数据库新会话")
    primary.store_exchange(
        conversation_id=conversation_id,
        user_message_id="msg-db-1",
        assistant_message_id="asst-db-1",
        message_request=MessageRequest(user_query="数据库新请求", scene="billing"),
        response=OrchestratorResponse(
            conversation_id=conversation_id,
            route=_route_decision(),
            executions=[],
            next_action="respond-with-agent-summary",
            final_response_summary="数据库新摘要。",
            pending_actions=[],
            trace=TraceContext(requestId="req-db-1", conversationId=conversation_id, traceId="trace-db-1"),
        ),
        status="completed",
        trace=TraceContext(requestId="req-db-1", conversationId=conversation_id, traceId="trace-db-1"),
    )

    replica = ConversationStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(backend, "get", lambda conversation_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))
    monkeypatch.setattr(
        backend,
        "fetch_messages",
        lambda conversation_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")),
    )
    monkeypatch.setattr(
        backend,
        "get_request_snapshot",
        lambda conversation_id, *, message_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")),
    )

    record = replica.get(conversation_id)
    messages = replica.list_messages(conversation_id).items
    retry_request = replica.build_retry_request(conversation_id, message_id="asst-db-1")

    assert record is not None
    assert record.title == "数据库新会话"
    assert record.summary == "数据库新摘要。"
    assert [item.message_id for item in messages] == ["msg-db-1", "asst-db-1"]
    assert retry_request.user_query == "数据库新请求"


def test_conversation_store_mysql_message_pagination_uses_stable_cursor_order(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "orchestrator-runtime-pagination.db"
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
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    conversation = store.create(SessionCreateRequest(scene="billing", title="账单会话"))

    first_request = MessageRequest(user_query="帮我查本月账单", scene="billing")
    second_request = MessageRequest(user_query="顺便查一下上个月", scene="billing")
    first_response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回本月账单。",
        pending_actions=[],
        trace=TraceContext(requestId="req-1", conversationId=conversation.conversation_id, traceId="trace-1"),
    )
    second_response = OrchestratorResponse(
        conversation_id=conversation.conversation_id,
        route=_route_decision(),
        executions=[],
        next_action="respond-with-agent-summary",
        final_response_summary="已返回上月账单。",
        pending_actions=[],
        trace=TraceContext(requestId="req-2", conversationId=conversation.conversation_id, traceId="trace-2"),
    )

    store.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-1",
        assistant_message_id="asst_msg-1",
        message_request=first_request,
        response=first_response,
        status="completed",
        trace=first_response.trace,
    )
    store.store_exchange(
        conversation_id=conversation.conversation_id,
        user_message_id="msg-2",
        assistant_message_id="asst_msg-2",
        message_request=second_request,
        response=second_response,
        status="completed",
        trace=second_response.trace,
    )

    first_page = store.list_messages(conversation.conversation_id, page_size=2)
    second_page = store.list_messages(
        conversation.conversation_id,
        cursor=first_page.next_cursor,
        page_size=2,
    )

    assert [item.message_id for item in first_page.items] == ["msg-1", "asst_msg-1"]
    assert first_page.has_more is True
    assert [item.message_id for item in second_page.items] == ["msg-2", "asst_msg-2"]
    assert second_page.has_more is False


def test_state_store_uses_mysql_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "state-runtime.db"
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
    fallback_path = tmp_path / "degraded-state.json"
    store = OrchestrationStateStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-mysql-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[],
        checkpoints=[],
        pending_user_actions=[],
        final_response_summary="已持久化。",
        trace=TraceContext(requestId="req-state-1", conversationId="conv-state-mysql-1", traceId="trace-state-1"),
    )

    store.save(snapshot)
    persisted = store.get("conv-state-mysql-1")

    assert persisted is not None
    assert persisted.version == 1
    assert persisted.trace.trace_id == "trace-state-1"
    assert not fallback_path.exists()
    description = store.describe_backend()
    assert description["backend"] == "mysql"
    assert description["fallbackPath"] == str(fallback_path)
    assert description["runtimeCache"]["backend"] == "memory"


def test_state_store_uses_redis_runtime_cache_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "state-runtime-redis-cache.db"
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
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    primary = OrchestrationStateStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:state",
    )
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-redis-cache-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[],
        checkpoints=[],
        pending_user_actions=[],
        final_response_summary="已写入缓存。",
        trace=TraceContext(
            requestId="req-state-redis-cache-1",
            conversationId="conv-state-redis-cache-1",
            traceId="trace-state-redis-cache-1",
        ),
    )
    primary.save(snapshot)

    replica = OrchestrationStateStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:state",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(
        backend,
        "get",
        lambda conversation_id: (_ for _ in ()).throw(AssertionError("mysql should not be hit on cache hit")),
    )

    persisted = replica.get("conv-state-redis-cache-1")

    assert persisted is not None
    assert persisted.trace.trace_id == "trace-state-redis-cache-1"
    assert replica.describe_backend()["runtimeCache"]["backend"] == "redis-json"


def test_state_store_backfills_redis_runtime_cache_from_mysql_on_cache_miss(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "state-runtime-redis-backfill.db"
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
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    primary = OrchestrationStateStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:state-backfill",
    )
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-redis-backfill-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[],
        checkpoints=[],
        pending_user_actions=[],
        final_response_summary="需要回填缓存。",
        trace=TraceContext(
            requestId="req-state-redis-backfill-1",
            conversationId="conv-state-redis-backfill-1",
            traceId="trace-state-redis-backfill-1",
        ),
    )
    primary.save(snapshot)
    fake_redis.delete(primary._cache_key("conv-state-redis-backfill-1"))

    replica = OrchestrationStateStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:state-backfill",
    )

    persisted = replica.get("conv-state-redis-backfill-1")

    assert persisted is not None
    assert persisted.trace.trace_id == "trace-state-redis-backfill-1"
    assert fake_redis.get(replica._cache_key("conv-state-redis-backfill-1")) is not None


def test_state_store_bootstraps_mysql_from_degraded_json(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "state-runtime-bootstrap.db"
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
    store_path = tmp_path / "bootstrap-state.json"
    local_store = OrchestrationStateStore(file_path=store_path)
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-bootstrap-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[],
        checkpoints=[],
        pending_user_actions=[],
        final_response_summary="已迁移。",
        trace=TraceContext(
            requestId="req-state-bootstrap-1",
            conversationId="conv-state-bootstrap-1",
            traceId="trace-state-bootstrap-1",
        ),
    )
    local_store.save(snapshot)

    OrchestrationStateStore(
        file_path=store_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    replica = OrchestrationStateStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )

    persisted = replica.get("conv-state-bootstrap-1")

    assert persisted is not None
    assert persisted.version == 1
    assert persisted.trace.trace_id == "trace-state-bootstrap-1"


def test_state_store_keeps_mysql_authority_over_stale_degraded_json_on_startup(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "state-runtime-authority.db"
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
    conversation_id = "conv-state-authority-1"
    fallback_path = tmp_path / "stale-state.json"

    local_store = OrchestrationStateStore(file_path=fallback_path)
    local_store.save(
        SessionStateSnapshot(
            conversation_id=conversation_id,
            primary_agent="finance_order_agent",
            current_agent="finance_order_agent",
            agent_routes=[],
            checkpoints=[],
            pending_user_actions=[],
            final_response_summary="本地旧状态。",
        )
    )

    primary = OrchestrationStateStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    primary.save(
        SessionStateSnapshot(
            conversation_id=conversation_id,
            primary_agent="finance_order_agent",
            current_agent="finance_order_agent",
            agent_routes=[],
            checkpoints=[],
            pending_user_actions=[],
            final_response_summary="数据库版本一。",
        )
    )
    primary.save(
        SessionStateSnapshot(
            conversation_id=conversation_id,
            primary_agent="finance_order_agent",
            current_agent="finance_order_agent",
            agent_routes=[],
            checkpoints=[],
            pending_user_actions=[],
            final_response_summary="数据库版本二。",
        )
    )

    replica = OrchestrationStateStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(backend, "get", lambda conversation_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))

    persisted = replica.get(conversation_id)

    assert persisted is not None
    assert persisted.version == 2
    assert persisted.final_response_summary == "数据库版本二。"


def test_state_store_keeps_degraded_json_mirror_after_mysql_read_failure(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "state-runtime-mirror.db"
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
    fallback_path = tmp_path / "degraded-state-mirror.json"
    store = OrchestrationStateStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    snapshot = SessionStateSnapshot(
        conversation_id="conv-state-mirror-1",
        primary_agent="finance_order_agent",
        current_agent="finance_order_agent",
        agent_routes=[],
        checkpoints=[],
        pending_user_actions=[],
        final_response_summary="已镜像。",
        trace=TraceContext(requestId="req-state-mirror-1", conversationId="conv-state-mirror-1", traceId="trace-state-mirror-1"),
    )

    store.save(snapshot)
    backend = store._backend
    assert backend is not None
    monkeypatch.setattr(backend, "get", lambda conversation_id: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))

    persisted = store.get("conv-state-mirror-1")

    assert persisted is not None
    assert persisted.trace.trace_id == "trace-state-mirror-1"
    description = store.describe_backend()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "mysql"
    assert description["path"] == str(fallback_path)


def test_agent_config_store_uses_mysql_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "agent-config-runtime.db"
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
    fallback_path = tmp_path / "degraded-agent-config.json"
    store = AgentConfigStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    override = store.upsert(
        agent_name="finance_order_agent",
        agent_code="Finance_Order_Agent",
        values={"enabled": False, "timeout_seconds": 45},
    )

    persisted = store.get("finance_order_agent")

    assert override.enabled is False
    assert persisted is not None
    assert persisted.timeout_seconds == 45
    assert store.list()[0].agent_name == "finance_order_agent"
    description = store.describe_backend()
    assert description["backend"] == "mysql"
    assert description["fallbackPath"] == str(fallback_path)
    assert description["runtimeCache"]["backend"] == "memory"


def test_agent_config_store_uses_redis_runtime_cache_when_configured(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "agent-config-runtime-redis-cache.db"
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
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    primary = AgentConfigStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:agent-config",
    )
    primary.upsert(
        agent_name="finance_order_agent",
        agent_code="Finance_Order_Agent",
        values={"enabled": False, "timeout_seconds": 45},
    )

    replica = AgentConfigStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:agent-config",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(
        backend,
        "get",
        lambda agent_name: (_ for _ in ()).throw(AssertionError("mysql should not be hit on cache hit")),
    )
    override = replica.get("finance_order_agent")
    monkeypatch.setattr(
        backend,
        "list",
        lambda: (_ for _ in ()).throw(AssertionError("mysql should not be hit on cache-backed list")),
    )
    overrides = replica.list()

    assert override is not None
    assert override.enabled is False
    assert overrides[0].timeout_seconds == 45
    assert replica.describe_backend()["runtimeCache"]["backend"] == "redis-json"


def test_agent_config_store_bootstraps_mysql_from_degraded_json(tmp_path: Path, monkeypatch) -> None:
    runtime_db = tmp_path / "agent-config-runtime-bootstrap.db"
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
    store_path = tmp_path / "bootstrap-agent-config.json"
    local_store = AgentConfigStore(file_path=store_path)
    local_store.upsert(
        agent_name="finance_order_agent",
        agent_code="Finance_Order_Agent",
        values={"enabled": False, "timeout_seconds": 45},
    )

    AgentConfigStore(
        file_path=store_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    replica = AgentConfigStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )

    persisted = replica.get("finance_order_agent")

    assert persisted is not None
    assert persisted.enabled is False
    assert persisted.timeout_seconds == 45


def test_agent_config_store_keeps_mysql_authority_over_stale_degraded_json_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_db = tmp_path / "agent-config-runtime-authority.db"
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
    fallback_path = tmp_path / "stale-agent-config.json"
    local_store = AgentConfigStore(file_path=fallback_path)
    local_store.upsert(
        agent_name="finance_order_agent",
        agent_code="Finance_Order_Agent",
        values={"enabled": False, "timeout_seconds": 30},
    )

    primary = AgentConfigStore(
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    primary.upsert(
        agent_name="finance_order_agent",
        agent_code="Finance_Order_Agent",
        values={"enabled": True, "timeout_seconds": 90},
    )

    replica = AgentConfigStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    backend = replica._backend
    assert backend is not None
    monkeypatch.setattr(backend, "get", lambda agent_name: (_ for _ in ()).throw(RuntimeError("mysql unavailable")))

    persisted = replica.get("finance_order_agent")

    assert persisted is not None
    assert persisted.enabled is True
    assert persisted.timeout_seconds == 90


def test_conversation_store_degrades_at_startup_when_mysql_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FailingPyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mysql unavailable"))),
            },
        ),
    )

    fallback_path = tmp_path / "degraded-conversations-startup.json"
    store = ConversationStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
    )
    conversation = store.create(SessionCreateRequest(scene="billing", title="账单会话"))

    assert conversation.conversation_id.startswith("conv_")
    description = store.describe_backend()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "mysql"
    assert description["path"] == str(fallback_path)


def test_conversation_store_recovers_mysql_and_runtime_cache_after_startup_degradation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        runtime_mysql_module,
        "pymysql",
        type(
            "FailingPyMySQLModule",
            (),
            {
                "cursors": type("FakeCursors", (), {"DictCursor": object}),
                "connect": staticmethod(lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mysql unavailable"))),
            },
        ),
    )
    fallback_path = tmp_path / "recovering-conversations-startup.json"
    store = ConversationStore(
        file_path=fallback_path,
        mysql_dsn="mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:conversation-recover",
    )
    conversation = store.create(SessionCreateRequest(scene="billing", title="账单会话"))
    assert fallback_path.exists()

    runtime_db = tmp_path / "orchestrator-conversation-recover.db"
    fake_redis = FakeRedisClient()
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
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    store._next_backend_recovery_at = 0.0
    store._next_cache_recovery_at = 0.0

    restored = store.get(conversation.conversation_id)

    assert restored is not None
    assert restored.title == "账单会话"
    description = store.describe_backend()
    assert description["backend"] == "mysql"
    assert description["runtimeCache"]["backend"] == "redis-json"
    assert not fallback_path.exists()
    assert fake_redis.strings


def test_sse_event_store_uses_redis_when_configured(monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    store = SseEventStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse",
    )
    store.save(
        "conv-stream-redis-1",
        "msg-stream-redis-1",
        [
            StreamEventRecord(
                event_id="evt-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-redis-1"},
                created_at="2026-04-16T00:00:00+00:00",
            ),
            StreamEventRecord(
                event_id="evt-0002",
                sequence=2,
                event="done",
                data={"finish_reason": "stop"},
                created_at="2026-04-16T00:00:01+00:00",
            ),
        ],
    )

    page = store.get_page("conv-stream-redis-1", "msg-stream-redis-1", after_event_id="evt-0001", limit=10)

    assert page is not None
    assert [item.event for item in page.items] == ["done"]
    assert fake_redis.values
    assert fake_redis.expires_at
    description = store.describe_backend()
    assert description["backend"] == "redis-list"
    assert description["ttlSeconds"] == 86400
    assert description["fallbackBackend"] == "memory"
    assert fake_redis.lrange_calls[-1][1:] == (1, 10)


def test_sse_event_store_bootstraps_redis_from_degraded_json(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    store_path = tmp_path / "bootstrap-stream-events.json"
    local_store = SseEventStore(file_path=store_path)
    local_store.save(
        "conv-stream-bootstrap-1",
        "msg-stream-bootstrap-1",
        [
            StreamEventRecord(
                event_id="evt-bootstrap-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-bootstrap-1"},
                created_at="2026-04-16T00:00:00+00:00",
            ),
            StreamEventRecord(
                event_id="evt-bootstrap-0002",
                sequence=2,
                event="done",
                data={"finish_reason": "stop"},
                created_at="2026-04-16T00:00:01+00:00",
            ),
        ],
    )

    SseEventStore(
        file_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse",
    )
    replica = SseEventStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse",
    )

    page = replica.get_page(
        "conv-stream-bootstrap-1",
        "msg-stream-bootstrap-1",
        after_event_id="evt-bootstrap-0001",
        limit=10,
    )

    assert page is not None
    assert [item.event for item in page.items] == ["done"]


def test_sse_event_store_keeps_redis_authority_over_stale_degraded_json_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    fallback_path = tmp_path / "stale-stream-events.json"
    local_store = SseEventStore(file_path=fallback_path)
    local_store.save(
        "conv-stream-authority-1",
        "msg-stream-authority-1",
        [
            StreamEventRecord(
                event_id="evt-local-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-authority-1", "source": "local"},
                created_at="2026-04-16T00:00:00+00:00",
            )
        ],
    )

    primary = SseEventStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse-authority",
    )
    primary.save(
        "conv-stream-authority-1",
        "msg-stream-authority-1",
        [
            StreamEventRecord(
                event_id="evt-redis-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-authority-1", "source": "redis"},
                created_at="2026-04-16T00:00:01+00:00",
            ),
            StreamEventRecord(
                event_id="evt-redis-0002",
                sequence=2,
                event="done",
                data={"finish_reason": "stop"},
                created_at="2026-04-16T00:00:02+00:00",
            ),
        ],
    )

    replica = SseEventStore(
        file_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse-authority",
    )
    monkeypatch.setattr(fake_redis, "lrange", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    page = replica.get_page("conv-stream-authority-1", "msg-stream-authority-1", limit=10)

    assert page is not None
    assert [item.event for item in page.items] == ["meta", "done"]
    assert page.items[0].data["source"] == "redis"


def test_sse_event_store_keeps_degraded_json_mirror_after_redis_read_failure(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    fallback_path = tmp_path / "degraded-stream-events-mirror.json"
    store = SseEventStore(
        file_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse",
    )
    store.save(
        "conv-stream-mirror-1",
        "msg-stream-mirror-1",
        [
            StreamEventRecord(
                event_id="evt-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-mirror-1"},
                created_at="2026-04-16T00:00:00+00:00",
            )
        ],
    )
    assert not fallback_path.exists()
    monkeypatch.setattr(fake_redis, "lrange", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    page = store.get_page("conv-stream-mirror-1", "msg-stream-mirror-1", limit=10)

    assert page is not None
    assert [item.event for item in page.items] == ["meta"]
    assert fallback_path.exists()
    description = store.describe_backend()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis-list"
    assert description["path"] == str(fallback_path)


def test_sse_event_store_degrades_at_startup_when_redis_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: PingFailingRedisClient())}),
    )
    fallback_path = tmp_path / "degraded-stream-events-startup.json"
    store = SseEventStore(
        file_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse",
    )

    description = store.describe_backend()

    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis-list"
    assert description["path"] == str(fallback_path)


def test_sse_event_store_recovers_redis_after_startup_degradation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: PingFailingRedisClient())}),
    )
    fallback_path = tmp_path / "recovering-stream-events-startup.json"
    store = SseEventStore(
        file_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse-recover",
    )
    store.save(
        "conv-stream-recover-1",
        "msg-stream-recover-1",
        [
            StreamEventRecord(
                event_id="evt-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-recover-1"},
                created_at="2026-04-16T00:00:00+00:00",
            )
        ],
    )
    assert fallback_path.exists()

    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    store._next_recovery_attempt_at = 0.0

    page = store.get_page("conv-stream-recover-1", "msg-stream-recover-1", limit=10)

    assert page is not None
    assert [item.event for item in page.items] == ["meta"]
    assert store.describe_backend()["backend"] == "redis-list"
    assert not fallback_path.exists()
    assert fake_redis.values


def test_sse_event_store_degrades_to_json_file_when_redis_fails(tmp_path: Path, monkeypatch) -> None:
    fallback_path = tmp_path / "degraded-stream-events.json"
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: FailingRedisClient())}),
    )
    store = SseEventStore(
        file_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:sse",
    )

    store.save(
        "conv-stream-degraded-1",
        "msg-stream-degraded-1",
        [
            StreamEventRecord(
                event_id="evt-0001",
                sequence=1,
                event="meta",
                data={"message_id": "msg-stream-degraded-1"},
                created_at="2026-04-16T00:00:00+00:00",
            )
        ],
    )

    page = store.get_page("conv-stream-degraded-1", "msg-stream-degraded-1", limit=10)
    description = store.describe_backend()

    assert page is not None
    assert [item.event for item in page.items] == ["meta"]
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis-list"
    assert description["path"] == str(fallback_path)


def test_run_control_uses_redis_for_cross_instance_coordination(monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    primary = OrchestrationRunControl(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:run-control",
        lease_seconds=120,
    )
    replica = OrchestrationRunControl(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:run-control",
        lease_seconds=120,
    )

    primary.start("conv-run-1", "msg-run-1")

    assert replica.is_running("conv-run-1") is True
    with pytest.raises(ActiveRunConflictError):
        replica.start("conv-run-1", "msg-run-2")
    assert replica.cancel("conv-run-1", "msg-run-1") is True
    with pytest.raises(OrchestrationCancelled):
        primary.ensure_not_cancelled("conv-run-1", "msg-run-1")

    primary.finish("conv-run-1", "msg-run-1")

    assert replica.is_running("conv-run-1") is False
    description = primary.describe_backend()
    assert description["backend"] == "redis-lock"
    assert description["redisNamespace"] == "smartcloud:test:orchestrator:run-control"
    assert description["fallbackBackend"] == "memory"


def test_run_control_degrades_to_memory_when_redis_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: FailingRedisKeyClient())}),
    )
    control = OrchestrationRunControl(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:run-control",
        lease_seconds=60,
    )

    control.start("conv-run-degraded-1", "msg-run-degraded-1")

    assert control.is_running("conv-run-degraded-1", "msg-run-degraded-1") is True
    assert control.cancel("conv-run-degraded-1", "msg-run-degraded-1") is True
    with pytest.raises(OrchestrationCancelled):
        control.ensure_not_cancelled("conv-run-degraded-1", "msg-run-degraded-1")

    description = control.describe_backend()
    assert description["backend"] == "memory"
    assert description["degradedFrom"] == "redis-lock"


def test_run_control_recovers_redis_after_startup_degradation(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: PingFailingRedisClient())}),
    )
    control = OrchestrationRunControl(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:orchestrator:run-control-recover",
        lease_seconds=60,
    )
    control.start("conv-run-recover-1", "msg-run-recover-1")

    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_redis_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    control._next_recovery_attempt_at = 0.0

    control.ensure_not_cancelled("conv-run-recover-1", "msg-run-recover-1")

    description = control.describe_backend()
    assert description["backend"] == "redis-lock"
    assert control.is_running("conv-run-recover-1", "msg-run-recover-1") is True
    assert any(key.startswith("smartcloud:test:orchestrator:run-control-recover:active:") for key in fake_redis.strings)
