from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.models.tools import ToolCallError, ToolCallRequest, ToolCallResponse
from app.services.business_tools_client import BusinessToolsClient
from app.services.registry import ToolRegistry


STUB_ROOT = (
    Path(__file__).resolve().parents[5]
    / "business-tools"
    / "tests"
    / "stubs"
    / "business-tools"
)


def _load_stub(name: str) -> dict:
    return json.loads((STUB_ROOT / name).read_text(encoding="utf-8"))


def _response_from_stub(stub_payload: dict, tool_call_id: str, latency_ms: int) -> ToolCallResponse:
    error = None
    if not stub_payload["success"]:
        error = ToolCallError(
            retryable=stub_payload.get("retryable", False),
            provider=stub_payload.get("provider", "business-tools"),
            details=stub_payload.get("error_detail", {}),
        )
    return ToolCallResponse(
        success=stub_payload["success"],
        code=stub_payload["code"],
        message=stub_payload["message"],
        status=stub_payload.get("status"),
        summary=stub_payload.get("summary"),
        result=stub_payload.get("result", stub_payload.get("data", {})),
        data=stub_payload.get("data", {}),
        citations=stub_payload.get("citations", []),
        audit_tags=stub_payload.get("audit_tags", []),
        session_context_patch=stub_payload.get("session_context_patch", {}),
        tool_call_id=tool_call_id,
        latency_ms=latency_ms,
        provider=stub_payload.get("provider", "business-tools"),
        error=error,
        compensation=stub_payload.get("compensation"),
        idempotency_key=stub_payload.get("idempotency_key"),
    )


def test_execute_tool_contract_maps_success_stub(monkeypatch) -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.query_statement")
    assert tool is not None

    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://business-tools.local",
            }
        )
    )
    stub_payload = _load_stub("execute-success.json")
    monkeypatch.setattr(
        client,
        "_invoke_via_http",
        lambda *args, **kwargs: _response_from_stub(stub_payload, "tc-biz-contract-success-1", 14),
    )

    result = client.invoke_call(
        tool,
        ToolCallRequest(
            trace_id="trace-biz-contract-success-1",
            conversation_id="conv-biz-contract-success-1",
            tool_call_id="tc-biz-contract-success-1",
            tool_name="billing.query_statement",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            payload={"range": "this_month"},
            idempotency_key="tool-biz-contract-success-1",
            operation="execute",
        ),
    )

    assert result.success is True
    assert result.status == stub_payload["status"]
    assert result.summary == stub_payload["summary"]
    assert result.result == stub_payload["result"]
    assert result.citations == stub_payload["citations"]
    assert result.data == stub_payload["data"]
    assert result.audit_tags == stub_payload["audit_tags"]
    assert result.session_context_patch == stub_payload["session_context_patch"]
    assert result.idempotency_key == stub_payload["idempotency_key"]


def test_execute_tool_contract_maps_invalid_payload_stub(monkeypatch) -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("order.create_refund")
    assert tool is not None

    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://business-tools.local",
            }
        )
    )
    stub_payload = _load_stub("execute-invalid-payload.json")
    monkeypatch.setattr(
        client,
        "_invoke_via_http",
        lambda *args, **kwargs: _response_from_stub(stub_payload, "tc-biz-contract-invalid-1", 16),
    )

    result = client.invoke_call(
        tool,
        ToolCallRequest(
            trace_id="trace-biz-contract-invalid-1",
            conversation_id="conv-biz-contract-invalid-1",
            tool_call_id="tc-biz-contract-invalid-1",
            tool_name="order.create_refund",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={
                "user_id": "u-1",
                "permissions": ["user:order.read"],
            },
            payload={"reason": "误购"},
            idempotency_key="tool-biz-contract-invalid-1",
            operation="execute",
        ),
    )

    assert result.success is False
    assert result.status == stub_payload["status"]
    assert result.summary == stub_payload["summary"]
    assert result.result == stub_payload["result"]
    assert result.citations == stub_payload["citations"]
    assert result.code == 4001001
    assert result.error is not None
    assert result.error.details == stub_payload["error_detail"]
