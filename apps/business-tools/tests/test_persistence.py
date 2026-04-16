from pathlib import Path

from business_tools import (
    ToolExecutionContext,
    ToolExecutionResult,
    configure_idempotency_store,
    configure_query_cache,
    get_idempotency_store,
    get_query_cache_store,
)


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
