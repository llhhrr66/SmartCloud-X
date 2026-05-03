from pathlib import Path

import business_tools.runtime_backend as runtime_backend_module
from business_tools import (
    ToolExecutionContext,
    ToolExecutionResult,
    configure_idempotency_store,
    configure_query_cache,
    get_idempotency_store,
    get_query_cache_store,
)
from business_tools.idempotency import ToolIdempotencyStore
from business_tools.query_cache import ToolQueryCacheStore


class FakeRedisClient:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.expiry[key] = ttl

    def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.expiry.pop(key, None)

    def ttl(self, key: str) -> int:
        if key not in self.values:
            return -2
        return self.expiry.get(key, -1)

    def scan_iter(self, match: str):
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.values):
            if key.startswith(prefix):
                yield key


class FailingRedisClient(FakeRedisClient):
    def get(self, key: str) -> str | None:
        raise RuntimeError("redis unavailable")

    def set(self, key: str, value: str) -> None:
        raise RuntimeError("redis unavailable")

    def setex(self, key: str, ttl: int, value: str) -> None:
        raise RuntimeError("redis unavailable")


class PingFailingRedisClient(FakeRedisClient):
    def ping(self) -> None:
        raise RuntimeError("redis unavailable")


def test_idempotency_store_can_reload_persisted_records(tmp_path: Path) -> None:
    store_path = tmp_path / "idempotency.json"
    configure_idempotency_store(persistence_path=store_path)
    store = get_idempotency_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_001"},
        success=True,
        idempotency_key="tool-idem-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )

    configure_idempotency_store(persistence_path=store_path)
    replay, conflict = get_idempotency_store().get(
        "billing.create_invoice",
        "tool-idem-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_001"
    assert "idempotent-replay" in replay.audit_tags

    configure_idempotency_store(persistence_path=None)


def test_query_cache_store_can_reload_persisted_records(tmp_path: Path) -> None:
    store_path = tmp_path / "query-cache.json"
    configure_query_cache(
        enabled=True,
        ttl_cap_seconds=300,
        persistence_path=store_path,
    )
    store = get_query_cache_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    result = ToolExecutionResult(
        tool_name="billing.query_statement",
        operation="execute",
        status="completed",
        summary="done",
        result={"billing_cycle": "2026-04", "total_amount": 1288.32},
        success=True,
    )

    store.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        result,
    )

    configure_query_cache(
        enabled=True,
        ttl_cap_seconds=300,
        persistence_path=store_path,
    )
    replay = get_query_cache_store().get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"
    assert "cache-hit" in replay.audit_tags

    configure_query_cache(enabled=True, ttl_cap_seconds=300, persistence_path=None)


def test_idempotency_store_expires_local_fallback_records(tmp_path: Path, monkeypatch) -> None:
    store_path = tmp_path / "idempotency-expiring.json"
    configure_idempotency_store(persistence_path=store_path)
    store = get_idempotency_store()
    current_time = {"value": 1_000.0}
    monkeypatch.setattr("business_tools.idempotency.time.time", lambda: current_time["value"])
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-expiring-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_expiring_001"},
        success=True,
        idempotency_key="tool-idem-expiring-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-expiring-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        1,
        result,
    )
    current_time["value"] = 1_002.0

    replay, conflict = store.get(
        "billing.create_invoice",
        "tool-idem-expiring-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    assert conflict is False
    assert replay is None


def test_idempotency_store_uses_redis_when_configured(monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    configure_idempotency_store(
        persistence_path=None,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )
    store = get_idempotency_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-redis-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_redis_001"},
        success=True,
        idempotency_key="tool-idem-redis-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-redis-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )
    replay, conflict = store.get(
        "billing.create_invoice",
        "tool-idem-redis-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_redis_001"
    assert "idempotent-replay" in replay.audit_tags
    assert fake_redis.values
    assert fake_redis.expiry
    redis_key = next(iter(fake_redis.values))
    assert "tenant-a" not in redis_key
    assert "user-1" not in redis_key
    assert "acct-1" not in redis_key
    assert store.describe_backend()["backend"] == "redis"


def test_idempotency_store_scopes_same_key_by_subject_context() -> None:
    configure_idempotency_store(persistence_path=None)
    store = get_idempotency_store()
    tenant_a = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-scope-1",
    )
    tenant_b = ToolExecutionContext(
        tenant_id="tenant-b",
        user_id="user-2",
        account_id="acct-2",
        idempotency_key="tool-idem-scope-1",
    )
    payload = {"statement_nos": ["stmt_001"], "_confirmed": True}
    result_a = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="tenant-a done",
        result={"invoice_no": "inv_tenant_a"},
        success=True,
        idempotency_key="tool-idem-scope-1",
    )
    result_b = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="tenant-b done",
        result={"invoice_no": "inv_tenant_b"},
        success=True,
        idempotency_key="tool-idem-scope-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-scope-1",
        payload,
        tenant_a,
        86400,
        result_a,
    )

    replay_b_before_save, conflict_b_before_save = store.get(
        "billing.create_invoice",
        "tool-idem-scope-1",
        payload,
        tenant_b,
    )

    assert replay_b_before_save is None
    assert conflict_b_before_save is False

    store.save(
        "billing.create_invoice",
        "tool-idem-scope-1",
        payload,
        tenant_b,
        86400,
        result_b,
    )

    replay_a, conflict_a = store.get(
        "billing.create_invoice",
        "tool-idem-scope-1",
        payload,
        tenant_a,
    )
    replay_b, conflict_b = store.get(
        "billing.create_invoice",
        "tool-idem-scope-1",
        payload,
        tenant_b,
    )

    assert conflict_a is False
    assert replay_a is not None
    assert replay_a.result["invoice_no"] == "inv_tenant_a"
    assert conflict_b is False
    assert replay_b is not None
    assert replay_b.result["invoice_no"] == "inv_tenant_b"


def test_idempotency_store_keeps_degraded_json_mirror_after_redis_read_failure(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    store_path = tmp_path / "degraded-idempotency-mirror.json"
    configure_idempotency_store(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )
    store = get_idempotency_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-mirror-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_mirror_001"},
        success=True,
        idempotency_key="tool-idem-mirror-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-mirror-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )
    assert not store_path.exists()
    monkeypatch.setattr(fake_redis, "get", lambda key: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    replay, conflict = store.get(
        "billing.create_invoice",
        "tool-idem-mirror-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    description = store.describe_backend()
    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_mirror_001"
    assert store_path.exists()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis"
    assert description["fallbackPath"] == str(store_path)


def test_idempotency_store_warms_degraded_mirror_from_redis_reads(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-read-mirror-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_read_mirror_001"},
        success=True,
        idempotency_key="tool-idem-read-mirror-1",
    )
    primary = ToolIdempotencyStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )
    primary.save(
        "billing.create_invoice",
        "tool-idem-read-mirror-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )

    store_path = tmp_path / "degraded-idempotency-read-mirror.json"
    replica = ToolIdempotencyStore(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )

    replay, conflict = replica.get(
        "billing.create_invoice",
        "tool-idem-read-mirror-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_read_mirror_001"
    assert not store_path.exists()

    monkeypatch.setattr(fake_redis, "get", lambda key: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    replay, conflict = replica.get(
        "billing.create_invoice",
        "tool-idem-read-mirror-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    description = replica.describe_backend()
    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_read_mirror_001"
    assert store_path.exists()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis"
    assert description["fallbackPath"] == str(store_path)


def test_idempotency_store_keeps_redis_authority_over_stale_degraded_json_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-authority-1",
    )
    fallback_path = tmp_path / "stale-idempotency.json"
    local_store = ToolIdempotencyStore(persistence_path=fallback_path)
    local_store.save(
        "billing.create_invoice",
        "tool-idem-authority-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        ToolExecutionResult(
            tool_name="billing.create_invoice",
            operation="execute",
            status="completed",
            summary="local",
            result={"invoice_no": "inv_local_001"},
            success=True,
            idempotency_key="tool-idem-authority-1",
        ),
    )

    primary = ToolIdempotencyStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency-authority",
    )
    primary.save(
        "billing.create_invoice",
        "tool-idem-authority-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        ToolExecutionResult(
            tool_name="billing.create_invoice",
            operation="execute",
            status="completed",
            summary="redis",
            result={"invoice_no": "inv_redis_001"},
            success=True,
            idempotency_key="tool-idem-authority-1",
        ),
    )

    replica = ToolIdempotencyStore(
        persistence_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency-authority",
    )
    monkeypatch.setattr(fake_redis, "get", lambda key: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    replay, conflict = replica.get(
        "billing.create_invoice",
        "tool-idem-authority-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_redis_001"


def test_query_cache_store_uses_redis_when_configured(monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    configure_query_cache(
        enabled=True,
        ttl_cap_seconds=300,
        persistence_path=None,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache",
    )
    store = get_query_cache_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    result = ToolExecutionResult(
        tool_name="billing.query_statement",
        operation="execute",
        status="completed",
        summary="done",
        result={"billing_cycle": "2026-04", "total_amount": 1288.32},
        success=True,
    )

    store.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        result,
    )
    replay = store.get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"
    assert "cache-hit" in replay.audit_tags
    assert fake_redis.values
    assert fake_redis.expiry
    redis_key = next(iter(fake_redis.values))
    assert "tenant-a" not in redis_key
    assert "user-1" not in redis_key
    assert "acct-1" not in redis_key
    assert "this_month" not in redis_key
    assert store.describe_backend()["backend"] == "redis-ttl"


def test_query_cache_store_warms_degraded_mirror_from_redis_reads(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    result = ToolExecutionResult(
        tool_name="billing.query_statement",
        operation="execute",
        status="completed",
        summary="done",
        result={"billing_cycle": "2026-04", "total_amount": 1288.32},
        success=True,
    )
    primary = ToolQueryCacheStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache",
    )
    primary.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        result,
    )

    store_path = tmp_path / "degraded-query-cache-read-mirror.json"
    replica = ToolQueryCacheStore(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache",
    )

    replay = replica.get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"
    assert not store_path.exists()

    monkeypatch.setattr(fake_redis, "get", lambda key: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    replay = replica.get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    description = replica.describe_backend()
    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"
    assert store_path.exists()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis-ttl"
    assert description["fallbackPath"] == str(store_path)


def test_query_cache_store_keeps_redis_authority_over_stale_degraded_json_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    fallback_path = tmp_path / "stale-query-cache.json"
    local_store = ToolQueryCacheStore(persistence_path=fallback_path)
    local_store.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        ToolExecutionResult(
            tool_name="billing.query_statement",
            operation="execute",
            status="completed",
            summary="local",
            result={"billing_cycle": "2026-03"},
            success=True,
        ),
    )

    primary = ToolQueryCacheStore(
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache-authority",
    )
    primary.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        ToolExecutionResult(
            tool_name="billing.query_statement",
            operation="execute",
            status="completed",
            summary="redis",
            result={"billing_cycle": "2026-04"},
            success=True,
        ),
    )

    replica = ToolQueryCacheStore(
        persistence_path=fallback_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache-authority",
    )
    monkeypatch.setattr(fake_redis, "get", lambda key: (_ for _ in ()).throw(RuntimeError("redis unavailable")))

    replay = replica.get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"


def test_idempotency_store_degrades_at_startup_when_redis_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: PingFailingRedisClient())}),
    )

    store_path = tmp_path / "degraded-idempotency-startup.json"
    configure_idempotency_store(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )
    store = get_idempotency_store()

    description = store.describe_backend()

    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis"
    assert description["fallbackPath"] == str(store_path)


def test_idempotency_store_recovers_redis_after_startup_degradation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: PingFailingRedisClient())}),
    )
    store_path = tmp_path / "recovering-idempotency-startup.json"
    configure_idempotency_store(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency-recover",
    )
    store = get_idempotency_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-recover-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_recover_001"},
        success=True,
        idempotency_key="tool-idem-recover-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-recover-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )
    assert store_path.exists()

    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    store._next_recovery_attempt_at = 0.0

    replay, conflict = store.get(
        "billing.create_invoice",
        "tool-idem-recover-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_recover_001"
    assert store.describe_backend()["backend"] == "redis"
    assert not store_path.exists()
    assert fake_redis.values


def test_idempotency_store_degrades_to_json_file_when_redis_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: FailingRedisClient())}),
    )

    store_path = tmp_path / "degraded-idempotency.json"
    configure_idempotency_store(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )
    store = get_idempotency_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-degraded-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_degraded_001"},
        success=True,
        idempotency_key="tool-idem-degraded-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-degraded-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )
    replay, conflict = store.get(
        "billing.create_invoice",
        "tool-idem-degraded-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
    )

    description = store.describe_backend()
    assert conflict is False
    assert replay is not None
    assert replay.result["invoice_no"] == "inv_degraded_001"
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis"
    assert description["fallbackPath"] == str(store_path)


def test_query_cache_store_recovers_redis_after_startup_degradation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: PingFailingRedisClient())}),
    )
    store_path = tmp_path / "recovering-query-cache-startup.json"
    configure_query_cache(
        enabled=True,
        ttl_cap_seconds=300,
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache-recover",
    )
    store = get_query_cache_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    result = ToolExecutionResult(
        tool_name="billing.query_statement",
        operation="execute",
        status="completed",
        summary="done",
        result={"billing_cycle": "2026-04", "total_amount": 1288.32},
        success=True,
    )

    store.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        result,
    )
    assert store_path.exists()

    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )
    store._next_recovery_attempt_at = 0.0

    replay = store.get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"
    assert store.describe_backend()["backend"] == "redis-ttl"
    assert not store_path.exists()
    assert fake_redis.values


def test_query_cache_store_degrades_to_json_file_when_redis_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: FailingRedisClient())}),
    )

    store_path = tmp_path / "degraded-query-cache.json"
    configure_query_cache(
        enabled=True,
        ttl_cap_seconds=300,
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache",
    )
    store = get_query_cache_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    result = ToolExecutionResult(
        tool_name="billing.query_statement",
        operation="execute",
        status="completed",
        summary="done",
        result={"billing_cycle": "2026-04", "total_amount": 1288.32},
        success=True,
    )

    store.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        result,
    )
    replay = store.get(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
    )

    description = store.describe_backend()
    assert replay is not None
    assert replay.result["billing_cycle"] == "2026-04"
    assert store_path.exists()
    assert description["backend"] == "json-file"
    assert description["degradedFrom"] == "redis-ttl"
    assert description["fallbackPath"] == str(store_path)


def test_idempotency_store_skips_degraded_spool_while_redis_is_healthy(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    store_path = tmp_path / "healthy-idempotency-spool.json"
    configure_idempotency_store(
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:idempotency",
    )
    store = get_idempotency_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        idempotency_key="tool-idem-healthy-1",
    )
    result = ToolExecutionResult(
        tool_name="billing.create_invoice",
        operation="execute",
        status="completed",
        summary="done",
        result={"invoice_no": "inv_healthy_001"},
        success=True,
        idempotency_key="tool-idem-healthy-1",
    )

    store.save(
        "billing.create_invoice",
        "tool-idem-healthy-1",
        {"statement_nos": ["stmt_001"], "_confirmed": True},
        context,
        86400,
        result,
    )

    assert not store_path.exists()


def test_query_cache_store_skips_degraded_spool_while_redis_is_healthy(tmp_path: Path, monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    monkeypatch.setattr(
        runtime_backend_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    store_path = tmp_path / "healthy-query-cache-spool.json"
    configure_query_cache(
        enabled=True,
        ttl_cap_seconds=300,
        persistence_path=store_path,
        redis_url="redis://redis.test:6379/0",
        redis_namespace="smartcloud:test:query-cache",
    )
    store = get_query_cache_store()
    context = ToolExecutionContext(
        tenant_id="tenant-a",
        user_id="user-1",
        account_id="acct-1",
        locale="zh-CN",
    )
    result = ToolExecutionResult(
        tool_name="billing.query_statement",
        operation="execute",
        status="completed",
        summary="done",
        result={"billing_cycle": "2026-04", "total_amount": 1288.32},
        success=True,
    )

    store.save(
        "billing.query_statement",
        "execute",
        {"range": "this_month"},
        context,
        60,
        result,
    )

    assert not store_path.exists()
