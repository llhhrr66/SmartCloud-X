from pathlib import Path

from app.models.tools import (
    ToolCallOperator,
    ToolCallRequest,
    ToolCallResponse,
    ToolCallUserContext,
)
from app.services.audit_store import ToolCallAuditStore


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
