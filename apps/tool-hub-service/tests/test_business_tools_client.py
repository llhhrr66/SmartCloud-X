import httpx

from app.core.business_tools_sdk import ToolDefinition, ToolExecutionContext, ToolInvocationRequest
from app.core.config import Settings
from app.models.tools import CompensationCallRequest, ToolCallRequest
from app.services.business_tools_client import BusinessToolsClient
from app.services.registry import ToolRegistry



def test_business_tools_client_retries_timeout_for_idempotent_tool(monkeypatch) -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.query_statement")
    assert tool is not None

    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
                "TOOL_RETRY_ATTEMPTS": 1,
            }
        )
    )
    attempts = {"count": 0}

    def _raise_timeout(*args, **kwargs):
        attempts["count"] += 1
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(client, "_invoke_via_http", _raise_timeout)
    response = client.invoke_call(
        tool,
        ToolCallRequest(
            trace_id="trace-timeout-1",
            conversation_id="conv-timeout-1",
            tool_call_id="tc-timeout-1",
            tool_name="billing.query_statement",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            payload={"range": "this_month"},
            idempotency_key="tool-timeout-1",
            operation="execute",
        ),
    )

    assert attempts["count"] == 2
    assert response.success is False
    assert response.code == 5003002
    assert response.error is not None
    assert response.error.retryable is True
    assert response.attempts == 2


def test_business_tools_client_degrades_compensation_timeout(monkeypatch) -> None:
    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        )
    )

    def _raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(client, "_invoke_compensation_via_http", _raise_timeout)
    response = client.invoke_compensation(
        CompensationCallRequest(
            trace_id="trace-comp-timeout-1",
            conversation_id="conv-comp-timeout-1",
            compensation_id="cmp-timeout-1",
            action_name="cancel_invoice_request",
            operator={"type": "system", "id": "orchestrator-service"},
            payload={"invoice_no": "inv_001"},
            idempotency_key="comp-timeout-1",
        )
    )

    assert response.success is False
    assert response.code == 5003002
    assert response.error is not None
    assert response.error.retryable is True
    assert response.attempts == 1


def test_business_tools_client_uses_configured_header_names() -> None:
    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "SMARTCLOUD_REQUEST_ID_HEADER": "X-Request-Token",
                "SMARTCLOUD_TRACE_ID_HEADER": "X-Trace-Token",
                "SMARTCLOUD_CONVERSATION_ID_HEADER": "X-Conversation-Token",
                "SMARTCLOUD_MESSAGE_ID_HEADER": "X-Message-Token",
                "SMARTCLOUD_TENANT_ID_HEADER": "X-Tenant-Token",
                "SMARTCLOUD_CALLER_SERVICE_HEADER": "X-Service-Token",
                "SMARTCLOUD_TOOL_CALL_ID_HEADER": "X-Tool-Token",
                "SMARTCLOUD_IDEMPOTENCY_KEY_HEADER": "X-Idempotency-Token",
            }
        )
    )
    discovery_headers = client._discovery_headers()
    headers = client._tool_execution_headers(
        ToolCallRequest(
            trace_id="trace-headers-1",
            conversation_id="conv-headers-1",
            message_id="msg-headers-1",
            tool_call_id="tc-headers-1",
            tool_name="billing.query_statement",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={
                "user_id": "u-1",
                "account_id": "acct-1",
                "tenant_id": "tenant-a",
                "permissions": ["user:billing.read"],
            },
            payload={"range": "this_month"},
            idempotency_key="tool-headers-1",
            operation="execute",
        )
    )

    assert discovery_headers["X-Service-Token"] == "tool-hub-service"
    assert headers["X-Request-Token"] == "tc-headers-1"
    assert headers["X-Trace-Token"] == "trace-headers-1"
    assert headers["X-Conversation-Token"] == "conv-headers-1"
    assert headers["X-Message-Token"] == "msg-headers-1"
    assert headers["X-Tenant-Token"] == "tenant-a"
    assert headers["X-Service-Token"] == "tool-hub-service"
    assert headers["X-Tool-Token"] == "tc-headers-1"
    assert headers["X-Idempotency-Token"] == "tool-headers-1"


def test_business_tools_client_uses_configured_internal_prefix_for_http_calls(monkeypatch) -> None:
    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
                "BUSINESS_TOOLS_INTERNAL_API_PREFIX": "/internal/custom",
            }
        )
    )
    requested_paths: list[str] = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, headers: dict[str, str], params: dict[str, str] | None = None):
            assert headers["X-Caller-Service"] == "tool-hub-service"
            assert params in ({}, None)
            requested_paths.append(path)
            if path.endswith("/tools"):
                payload = {
                    "tools": [
                        {
                            "name": "billing.query_statement",
                            "capability": "billing",
                            "description": "remote billing",
                        }
                    ]
                }
            else:
                payload = {
                    "name": "billing.query_statement",
                    "capability": "billing",
                    "description": "remote billing",
                }
            return httpx.Response(200, request=httpx.Request("GET", f"http://example.local{path}"), json=payload)

        def post(self, path: str, json: dict[str, object], headers: dict[str, str]):
            requested_paths.append(path)
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://example.local{path}"),
                json={
                    "tool_name": "billing.query_statement",
                    "operation": "execute",
                    "status": "ready",
                    "ready": True,
                    "available": True,
                },
            )

    monkeypatch.setattr("app.services.business_tools_client.httpx.Client", FakeHttpClient)
    request = ToolCallRequest(
        trace_id="trace-prefix-1",
        conversation_id="conv-prefix-1",
        message_id="msg-prefix-1",
        tool_call_id="tc-prefix-1",
        tool_name="billing.query_statement",
        operator={"type": "agent", "id": "Finance_Order_Agent"},
        user_context={
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:billing.read"],
        },
        payload={"range": "this_month"},
        idempotency_key="tool-prefix-1",
        operation="execute",
    )
    client.list_tools()
    client.describe_tool("billing.query_statement")
    client.preflight_call("billing.query_statement", request)

    assert requested_paths == [
        "/internal/custom/tools",
        "/internal/custom/tools/billing.query_statement",
        "/internal/custom/tools/billing.query_statement",
        "/internal/custom/preflight/billing.query_statement",
    ]


def test_business_tools_client_forwards_discovery_filters(monkeypatch) -> None:
    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        )
    )
    requested_params: list[dict[str, str] | None] = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, headers: dict[str, str], params: dict[str, str] | None = None):
            requested_params.append(params)
            return httpx.Response(
                200,
                request=httpx.Request("GET", f"http://example.local{path}"),
                json={
                    "tools": [
                        {
                            "name": "billing.create_invoice",
                            "capability": "finance-order",
                            "description": "remote invoice tool",
                            "mode": "write",
                        }
                    ]
                },
            )

    monkeypatch.setattr("app.services.business_tools_client.httpx.Client", FakeHttpClient)
    tools = client.list_tools(capability="finance-order", mode="write", tag="invoice", query="invoice")

    assert [tool.name for tool in tools] == ["billing.create_invoice"]
    assert requested_params == [
        {
            "capability": "finance-order",
            "mode": "write",
            "tag": "invoice",
            "query": "invoice",
        }
    ]


def test_business_tools_client_invokes_tool_via_http_with_execution_contract(monkeypatch) -> None:
    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
                "BUSINESS_TOOLS_INTERNAL_API_PREFIX": "/internal/custom",
            }
        )
    )
    requested_paths: list[str] = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def post(self, path: str, json: dict[str, object], headers: dict[str, str]):
            requested_paths.append(path)
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://example.local{path}"),
                json={
                    "tool_name": "billing.query_statement",
                    "operation": "execute",
                    "status": "completed",
                    "summary": "remote billing summary",
                    "result": {"billing_cycle": "2026-04"},
                    "data": {"billing_cycle": "2026-04"},
                    "citations": ["billing://statement"],
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "provider": "business-tools",
                },
            )

    monkeypatch.setattr("app.services.business_tools_client.httpx.Client", FakeHttpClient)

    result = client.invoke_tool(
        ToolDefinition(
            name="billing.query_statement",
            capability="billing",
            description="remote billing",
            timeout_ms=4321,
        ),
        ToolInvocationRequest(
            tool_name="billing.query_statement",
            operation="execute",
            payload={"range": "this_month"},
            context=ToolExecutionContext(
                request_id="tc-remote-1",
                trace_id="trace-remote-1",
                conversation_id="conv-remote-1",
                tenant_id="tenant-a",
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
                operator_id="Finance_Order_Agent",
                operator_type="agent",
                idempotency_key="tool-remote-1",
            ),
        ),
    )

    assert requested_paths == ["/internal/custom/execute/billing.query_statement"]
    assert result.tool_name == "billing.query_statement"
    assert result.status == "completed"
    assert result.summary == "remote billing summary"
    assert result.result["billing_cycle"] == "2026-04"
    assert result.citations == ["billing://statement"]


def test_business_tools_client_preserves_richer_tool_call_fields_from_http_execute(monkeypatch) -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.query_statement")
    assert tool is not None

    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        )
    )

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, headers: dict[str, str], params: dict[str, str] | None = None):
            assert headers["X-Caller-Service"] == "tool-hub-service"
            return httpx.Response(
                200,
                request=httpx.Request("GET", f"http://example.local{path}"),
                json={
                    "name": "billing.query_statement",
                    "capability": "billing",
                    "description": "remote billing",
                },
            )

        def post(self, path: str, json: dict[str, object], headers: dict[str, str]):
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://example.local{path}"),
                json={
                    "tool_name": "billing.query_statement",
                    "operation": "execute",
                    "status": "completed",
                    "summary": "remote billing summary",
                    "result": {"billing_cycle": "2026-04"},
                    "data": {"billing_cycle": "2026-04"},
                    "citations": ["billing://statement"],
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "provider": "business-tools",
                },
            )

    monkeypatch.setattr("app.services.business_tools_client.httpx.Client", FakeHttpClient)

    response = client.invoke_call(
        tool,
        ToolCallRequest(
            trace_id="trace-tool-call-1",
            conversation_id="conv-tool-call-1",
            tool_call_id="tc-tool-call-1",
            tool_name="billing.query_statement",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            payload={"range": "this_month"},
            idempotency_key="tool-tool-call-1",
            operation="execute",
        ),
    )

    assert response.status == "completed"
    assert response.summary == "remote billing summary"
    assert response.result == {"billing_cycle": "2026-04"}
    assert response.data == {"billing_cycle": "2026-04"}
    assert response.citations == ["billing://statement"]


def test_business_tools_client_preserves_user_action_hint_from_http_execute(monkeypatch) -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("ticket.create")
    assert tool is not None

    client = BusinessToolsClient(
        Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        )
    )

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, headers: dict[str, str], params: dict[str, str] | None = None):
            assert headers["X-Caller-Service"] == "tool-hub-service"
            return httpx.Response(
                200,
                request=httpx.Request("GET", f"http://example.local{path}"),
                json={
                    "name": "ticket.create",
                    "capability": "ticket",
                    "description": "remote ticket create",
                    "mode": "write",
                    "required_permissions": ["user:ticket.write"],
                },
            )

        def post(self, path: str, json: dict[str, object], headers: dict[str, str]):
            return httpx.Response(
                200,
                request=httpx.Request("POST", f"http://example.local{path}"),
                json={
                    "tool_name": "ticket.create",
                    "operation": "execute",
                    "status": "auth-required",
                    "summary": "ticket.create 执行前需补充鉴权上下文。",
                    "result": {"missing_context": ["permission:user:ticket.write"]},
                    "data": {"missing_context": ["permission:user:ticket.write"]},
                    "success": False,
                    "code": 4030001,
                    "message": "auth context missing",
                    "provider": "business-tools",
                    "error_detail": {"missing_context": ["permission:user:ticket.write"]},
                    "user_action_hint": {
                        "action": "collect-auth-context",
                        "message": "ticket.create 执行前需补充鉴权上下文。",
                        "missing_auth_context": ["permission:user:ticket.write"],
                        "required_permissions": ["user:ticket.write"],
                    },
                },
            )

    monkeypatch.setattr("app.services.business_tools_client.httpx.Client", FakeHttpClient)

    response = client.invoke_call(
        tool,
        ToolCallRequest(
            trace_id="trace-tool-call-auth-1",
            conversation_id="conv-tool-call-auth-1",
            tool_call_id="tc-tool-call-auth-1",
            tool_name="ticket.create",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={"user_id": "u-1"},
            payload={"subject": "账单异常", "content": "请帮我排查"},
            idempotency_key="tool-tool-call-auth-1",
            operation="execute",
        ),
    )

    assert response.status == "auth-required"
    assert response.user_action_hint is not None
    assert response.user_action_hint.action == "collect-auth-context"
    assert response.user_action_hint.required_permissions == ["user:ticket.write"]
