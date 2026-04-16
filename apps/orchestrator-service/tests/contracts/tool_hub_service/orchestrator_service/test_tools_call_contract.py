from __future__ import annotations

import json
from pathlib import Path

import httpx

from app.models.common import TraceContext
from app.models.orchestration import ToolPlanItem, UserProfile
from app.services.tool_hub_client import ToolHubClient


STUB_ROOT = (
    Path(__file__).resolve().parents[5]
    / "tool-hub-service"
    / "tests"
    / "stubs"
    / "tool-hub"
)


def _load_stub(name: str) -> dict:
    return json.loads((STUB_ROOT / name).read_text(encoding="utf-8"))


def test_tools_call_contract_maps_success_stub(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    stub_payload = _load_stub("tools-call-success.json")

    def _ok_response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
            json=stub_payload,
        )

    client._request_tool_call = _ok_response  # type: ignore[method-assign]
    result = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-contract-success-1",
                tool_name="billing.query_statement",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="contract success",
                payload={"range": "this_month"},
            )
        ],
        UserProfile(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
        ),
        TraceContext(
            requestId="req-contract-success-1",
            conversationId="conv-contract-success-1",
            traceId="trace-contract-success-1",
        ),
    )[0]

    assert result.status == "completed"
    assert result.summary == stub_payload["summary"]
    assert result.payload == stub_payload["data"]
    assert result.citations == stub_payload["citations"]
    assert result.audit_tags == stub_payload["audit_tags"]
    assert result.session_context_patch == stub_payload["session_context_patch"]
    assert result.provider == stub_payload["provider"]
    assert result.idempotency_key == stub_payload["idempotency_key"]


def test_tools_call_contract_preserves_conflict_stub(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    stub_payload = _load_stub("tools-call-idempotency-conflict.json")

    def _ok_response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
            json=stub_payload,
        )

    client._request_tool_call = _ok_response  # type: ignore[method-assign]
    result = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-contract-conflict-1",
                tool_name="billing.create_invoice",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="contract conflict",
                payload={"statement_nos": ["stmt_001"], "_confirmed": True},
            )
        ],
        UserProfile(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
        ),
        TraceContext(
            requestId="req-contract-conflict-1",
            conversationId="conv-contract-conflict-1",
            traceId="trace-contract-conflict-1",
        ),
    )[0]

    assert result.status == "idempotency-conflict"
    assert result.summary == stub_payload["summary"]
    assert result.success is False
    assert result.code == stub_payload["code"]
    assert result.payload == stub_payload["result"]
    assert result.citations == stub_payload["citations"]
    assert result.error_detail == stub_payload["error"]["details"]
    assert result.idempotency_key == stub_payload["idempotency_key"]
