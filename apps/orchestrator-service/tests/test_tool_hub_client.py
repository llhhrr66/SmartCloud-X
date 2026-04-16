import httpx

from app.core.config import Settings
from app.models.common import TraceContext
from app.models.orchestration import ToolPlanItem, UserProfile
from app.services.tool_hub_client import ToolHubClient


def test_tool_hub_client_degrades_http_timeout_to_failed_tool_invocation(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)

    def _raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(client, "_request_tool_call", _raise_timeout)

    tool_calls = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-timeout-1",
                tool_name="billing.query_statement",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="timeout test",
                payload={"range": "this_month", "conversation_id": "conv-timeout-1"},
            )
        ],
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        TraceContext(requestId="req-timeout-1", conversationId="conv-timeout-1", traceId="trace-timeout-1"),
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].status == "failed"
    assert tool_calls[0].success is False
    assert tool_calls[0].code == 5003002
    assert tool_calls[0].retryable is True
    assert tool_calls[0].provider == "tool-hub-service"


def test_tool_hub_client_preserves_idempotency_conflict_status_from_http(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)

    def _ok_response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
            json={
                "success": False,
                "code": 4090001,
                "message": "idempotency conflict",
                "status": "idempotency-conflict",
                "summary": "幂等键已被其他写入请求占用。",
                "result": {"idempotency_key": "tool-conflict-1"},
                "data": {"idempotency_key": "tool-conflict-1"},
                "citations": [],
                "tool_call_id": "tc-conflict-1",
                "latency_ms": 12,
                "provider": "tool-hub-service",
                "error": {"retryable": False, "details": {"reason": "idempotency_conflict"}},
                "idempotency_key": "tool-conflict-1",
            },
        )

    monkeypatch.setattr(client, "_request_tool_call", _ok_response)

    tool_calls = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-conflict-1",
                tool_name="billing.create_invoice",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="conflict test",
                payload={"statement_nos": ["stmt_1"], "_confirmed": True},
            )
        ],
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        TraceContext(requestId="req-conflict-1", conversationId="conv-conflict-1", traceId="trace-conflict-1"),
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].status == "idempotency-conflict"
    assert tool_calls[0].summary == "幂等键已被其他写入请求占用。"
    assert tool_calls[0].success is False
    assert tool_calls[0].code == 4090001
    assert tool_calls[0].payload == {"idempotency_key": "tool-conflict-1"}


def test_tool_hub_client_preserves_summary_and_citations_from_http(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)

    def _ok_response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
            json={
                "success": True,
                "code": 0,
                "message": "ok",
                "status": "completed",
                "summary": "账单周期 2026-04 总金额 1288.32 CNY。",
                "result": {"billing_cycle": "2026-04", "total_amount": 1288.32},
                "data": {"billing_cycle": "2026-04", "total_amount": 1288.32},
                "citations": ["billing://statement"],
                "tool_call_id": "tc-summary-1",
                "latency_ms": 12,
                "provider": "tool-hub-service",
                "audit_tags": ["finance-order", "execute", "query"],
                "idempotency_key": "tool-summary-1",
            },
        )

    monkeypatch.setattr(client, "_request_tool_call", _ok_response)

    tool_calls = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-summary-1",
                tool_name="billing.query_statement",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="summary test",
                payload={"range": "this_month"},
            )
        ],
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        TraceContext(requestId="req-summary-1", conversationId="conv-summary-1", traceId="trace-summary-1"),
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].status == "completed"
    assert tool_calls[0].summary == "账单周期 2026-04 总金额 1288.32 CNY。"
    assert tool_calls[0].payload == {"billing_cycle": "2026-04", "total_amount": 1288.32}
    assert tool_calls[0].citations == ["billing://statement"]


def test_tool_hub_client_preserves_user_action_hint_from_http(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)

    def _ok_response(*args, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
            json={
                "success": False,
                "code": 4030001,
                "message": "auth context missing",
                "status": "auth-required",
                "summary": "ticket.create 执行前需补充鉴权上下文。",
                "result": {"missing_context": ["permission:user:ticket.write"]},
                "data": {"missing_context": ["permission:user:ticket.write"]},
                "citations": [],
                "tool_call_id": "tc-auth-1",
                "latency_ms": 12,
                "provider": "tool-hub-service",
                "error": {"retryable": False, "details": {"missing_context": ["permission:user:ticket.write"]}},
                "user_action_hint": {
                    "action": "collect-auth-context",
                    "message": "ticket.create 执行前需补充鉴权上下文。",
                    "missing_auth_context": ["permission:user:ticket.write"],
                    "required_permissions": ["user:ticket.write"],
                },
                "idempotency_key": "tool-auth-1",
            },
        )

    monkeypatch.setattr(client, "_request_tool_call", _ok_response)

    tool_calls = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-auth-1",
                tool_name="ticket.create",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="auth test",
                payload={"subject": "账单异常", "content": "请帮我排查"},
            )
        ],
        UserProfile(user_id="u-1"),
        TraceContext(requestId="req-auth-1", conversationId="conv-auth-1", traceId="trace-auth-1"),
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].status == "auth-required"
    assert tool_calls[0].user_action_hint is not None
    assert tool_calls[0].user_action_hint.action == "collect-auth-context"
    assert tool_calls[0].user_action_hint.required_permissions == ["user:ticket.write"]


def test_tool_hub_client_uses_configured_internal_prefix_for_http_calls() -> None:
    client = ToolHubClient()
    client.settings = Settings.model_validate(
        {
            "APP_ENV": "dev",
            "TOOL_HUB_TRANSPORT": "http",
            "MCP_GATEWAY_URL": "http://tool-hub.local",
            "TOOL_HUB_INTERNAL_API_PREFIX": "/internal/tool-hub",
            "SMARTCLOUD_MESSAGE_ID_HEADER": "X-Message-Token",
        }
    )

    class FakeHttpClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object], dict[str, str]]] = []

        def post(self, path: str, json: dict[str, object], headers: dict[str, str]):
            self.calls.append((path, json, headers))
            return httpx.Response(200, request=httpx.Request("POST", f"http://tool-hub.local{path}"))

    fake_client = FakeHttpClient()
    item = ToolPlanItem(
        tool_call_id="tc-prefix-1",
        tool_name="billing.query_statement",
        assigned_agent="finance_order_agent",
        operation="execute",
        reason="prefix test",
        payload={"range": "this_month"},
    )
    profile = UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"])
    trace = TraceContext(requestId="req-prefix-1", conversationId="conv-prefix-1", traceId="trace-prefix-1")

    client._request_tool_call(
        fake_client,
        item,
        profile,
        trace,
        "finance_order_agent",
        "tool-prefix-1",
        "msg-prefix-1",
    )
    client._request_tool_preflight(
        fake_client,
        item,
        profile,
        trace,
        "finance_order_agent",
        "tool-prefix-1",
        "msg-prefix-1",
    )

    assert fake_client.calls[0][0] == "/internal/tool-hub/tools/call"
    assert fake_client.calls[1][0] == "/internal/tool-hub/tools/preflight"
    assert fake_client.calls[0][1]["message_id"] == "msg-prefix-1"
    assert fake_client.calls[0][2]["X-Message-Token"] == "msg-prefix-1"
