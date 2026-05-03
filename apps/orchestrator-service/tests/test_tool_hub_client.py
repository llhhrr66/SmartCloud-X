import httpx

from app.core.business_tools_sdk import ToolExecutionResult, ToolPreflightResult, describe_local_runtime
from app.core.config import Settings
from app.models.common import TraceContext
from app.models.orchestration import ToolPlanItem, UserProfile
from app.services.tool_hub_client import ToolHubClient


def test_tool_hub_client_falls_back_to_local_on_http_connect_error(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    monkeypatch.setattr(
        client.settings,
        "business_tools_redis_namespace",
        "smartcloud:test:business-tools",
        raising=False,
    )
    assert describe_local_runtime()["idempotency"]["active"] is False

    def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError(
            "connect failed",
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
        )

    monkeypatch.setattr(client, "_request_tool_call", _raise_connect_error)

    tool_calls = client.invoke_plan(
        [
            ToolPlanItem(
                tool_call_id="tc-connect-fallback-1",
                tool_name="billing.query_statement",
                assigned_agent="finance_order_agent",
                operation="execute",
                reason="connect fallback test",
                payload={"range": "this_month"},
            )
        ],
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        TraceContext(
            requestId="req-connect-fallback-1",
            conversationId="conv-connect-fallback-1",
            traceId="trace-connect-fallback-1",
        ),
    )

    assert len(tool_calls) == 1
    assert tool_calls[0].status == "completed"
    assert tool_calls[0].success is True
    assert "degraded-http-connect-fallback" in tool_calls[0].audit_tags
    runtime = describe_local_runtime()
    assert runtime["idempotency"]["active"] is True
    assert runtime["idempotency"]["activationMode"] == "degraded-fallback"
    assert runtime["idempotency"]["redisNamespace"] == "smartcloud:test:business-tools:idempotency"
    assert runtime["queryCache"]["redisNamespace"] == "smartcloud:test:business-tools:query-cache"
    assert runtime["queryCache"]["active"] is True


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


def test_tool_hub_client_disables_env_proxy_for_loopback_http_calls(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    monkeypatch.setattr(client.settings, "tool_hub_base_url", "http://127.0.0.1:8020", raising=False)
    seen_kwargs: list[dict[str, object]] = []

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            seen_kwargs.append(dict(kwargs))

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, headers: dict[str, str]):
            return httpx.Response(
                200,
                request=httpx.Request("GET", f"http://127.0.0.1:8020{path}"),
                json={
                    "data": [
                        {
                            "name": "billing.query_statement",
                            "capability": "billing",
                            "description": "remote billing",
                        }
                    ]
                },
            )

    monkeypatch.setattr("app.services.tool_hub_client.httpx.Client", FakeHttpClient)
    definitions = client.list_tool_definitions()

    assert definitions
    assert seen_kwargs
    assert seen_kwargs[0]["trust_env"] is False


def test_tool_hub_client_marks_preflight_unavailable_on_http_timeout(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)

    def _raise_timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(client, "_request_tool_preflight", _raise_timeout)

    result = client.preflight(
        ToolPlanItem(
            tool_call_id="tc-preflight-timeout-1",
            tool_name="billing.query_statement",
            assigned_agent="finance_order_agent",
            operation="execute",
            reason="preflight timeout test",
            payload={"range": "this_month"},
        ),
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        TraceContext(
            requestId="req-preflight-timeout-1",
            conversationId="conv-preflight-timeout-1",
            traceId="trace-preflight-timeout-1",
        ),
    )

    assert result.ready is False
    assert result.available is False
    assert result.tool_mode == "query"
    assert result.required_permissions == ["user:billing.read"]


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
                    "user_profile_bindings": {"permissions": ["permissions"]},
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
    assert tool_calls[0].user_action_hint.user_profile_bindings == {"permissions": ["permissions"]}


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


def test_tool_hub_client_scopes_http_tool_idempotency_key_by_message_id(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    seen_keys: list[str] = []

    def _ok_response(*args, **kwargs):
        seen_keys.append(kwargs["idempotency_key"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/call"),
            json={
                "success": True,
                "code": 0,
                "message": "ok",
                "status": "completed",
                "summary": "ok",
                "result": {},
                "data": {},
                "citations": [],
                "tool_call_id": "tc-turn-scope-1",
                "latency_ms": 5,
                "provider": "tool-hub-service",
                "idempotency_key": kwargs["idempotency_key"],
            },
        )

    monkeypatch.setattr(client, "_request_tool_call", _ok_response)

    item = ToolPlanItem(
        tool_call_id="tc-turn-scope-1",
        tool_name="billing.create_invoice",
        assigned_agent="finance_order_agent",
        operation="execute",
        reason="turn scope test",
        payload={"statement_nos": ["stmt_1"], "_confirmed": True},
    )
    profile = UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.write"])
    trace = TraceContext(requestId="req-turn-scope-1", conversationId="conv-turn-scope-1", traceId="trace-turn-scope-1")

    first = client.invoke_plan([item], profile, trace, message_id="msg-turn-scope-1")
    second = client.invoke_plan([item], profile, trace, message_id="msg-turn-scope-2")
    replay = client.invoke_plan([item], profile, trace, message_id="msg-turn-scope-1")

    assert seen_keys == [
        "tool-conv-turn-scope-1-msg-turn-scope-1-tc-turn-scope-1",
        "tool-conv-turn-scope-1-msg-turn-scope-2-tc-turn-scope-1",
        "tool-conv-turn-scope-1-msg-turn-scope-1-tc-turn-scope-1",
    ]
    assert first[0].idempotency_key == seen_keys[0]
    assert second[0].idempotency_key == seen_keys[1]
    assert replay[0].idempotency_key == seen_keys[2]


def test_tool_hub_client_scopes_preflight_idempotency_key_by_message_id(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    seen_keys: list[str] = []

    def _ok_response(*args, **kwargs):
        seen_keys.append(kwargs["idempotency_key"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", "http://tool-hub.local/internal/v1/tools/preflight"),
            json={
                "tool_name": "billing.create_invoice",
                "operation": "execute",
                "status": "ready",
                "ready": True,
                "available": True,
                "tool_mode": "write",
                "summary": "ready",
                "required_permissions": ["user:billing.write"],
                "missing_permissions": [],
                "missing_auth_context": [],
            },
        )

    monkeypatch.setattr(client, "_request_tool_preflight", _ok_response)

    result = client.preflight(
        ToolPlanItem(
            tool_call_id="tc-turn-scope-2",
            tool_name="billing.create_invoice",
            assigned_agent="finance_order_agent",
            operation="execute",
            reason="turn scope preflight test",
            payload={"statement_nos": ["stmt_1"], "_confirmed": True},
        ),
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.write"]),
        TraceContext(
            requestId="req-turn-scope-2",
            conversationId="conv-turn-scope-2",
            traceId="trace-turn-scope-2",
        ),
        message_id="msg-turn-scope-2",
    )

    assert result.ready is True
    assert seen_keys == ["tool-conv-turn-scope-2-msg-turn-scope-2-tc-turn-scope-2"]


def test_tool_hub_client_scopes_local_tool_idempotency_key_by_message_id(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "local", raising=False)
    seen_keys: list[str] = []

    class FakeTool:
        def invoke(self, request):
            seen_keys.append(request.context.idempotency_key)
            return ToolExecutionResult(
                tool_name=request.tool_name,
                operation=request.operation,
                status="completed",
                summary="ok",
                result={},
                provider="fake-local",
                idempotency_key=request.context.idempotency_key,
            )

    monkeypatch.setattr(client, "_catalog", {"billing.create_invoice": FakeTool()})

    item = ToolPlanItem(
        tool_call_id="tc-local-turn-scope-1",
        tool_name="billing.create_invoice",
        assigned_agent="finance_order_agent",
        operation="execute",
        reason="local turn scope test",
        payload={"statement_nos": ["stmt_1"], "_confirmed": True},
    )
    profile = UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.write"])
    trace = TraceContext(
        requestId="req-local-turn-scope-1",
        conversationId="conv-local-turn-scope-1",
        traceId="trace-local-turn-scope-1",
    )

    first = client.invoke_plan([item], profile, trace, message_id="msg-local-turn-scope-1")
    second = client.invoke_plan([item], profile, trace, message_id="msg-local-turn-scope-2")

    assert seen_keys == [
        "tool-conv-local-turn-scope-1-msg-local-turn-scope-1-tc-local-turn-scope-1",
        "tool-conv-local-turn-scope-1-msg-local-turn-scope-2-tc-local-turn-scope-1",
    ]
    assert first[0].idempotency_key == seen_keys[0]
    assert second[0].idempotency_key == seen_keys[1]


def test_tool_hub_client_scopes_local_preflight_idempotency_key_by_message_id(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "local", raising=False)
    seen_keys: list[str] = []

    class FakeTool:
        definition = object()

    def _fake_preflight(definition, request):
        seen_keys.append(request.context.idempotency_key)
        return ToolPreflightResult(
            tool_name=request.tool_name,
            operation=request.operation,
            status="ready",
            ready=True,
            available=True,
            tool_mode="write",
        )

    monkeypatch.setattr(client, "_catalog", {"billing.create_invoice": FakeTool()})
    monkeypatch.setattr("app.services.tool_hub_client.preflight_tool_invocation", _fake_preflight)

    result = client.preflight(
        ToolPlanItem(
            tool_call_id="tc-local-turn-scope-2",
            tool_name="billing.create_invoice",
            assigned_agent="finance_order_agent",
            operation="execute",
            reason="local preflight turn scope test",
            payload={"statement_nos": ["stmt_1"], "_confirmed": True},
        ),
        UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.write"]),
        TraceContext(
            requestId="req-local-turn-scope-2",
            conversationId="conv-local-turn-scope-2",
            traceId="trace-local-turn-scope-2",
        ),
        message_id="msg-local-turn-scope-2",
    )

    assert result.ready is True
    assert seen_keys == ["tool-conv-local-turn-scope-2-msg-local-turn-scope-2-tc-local-turn-scope-2"]


def test_tool_hub_client_preserves_legacy_idempotency_key_without_message_id() -> None:
    key = ToolHubClient._build_idempotency_key(
        ToolPlanItem(
            tool_call_id="tc-legacy-scope-1",
            tool_name="billing.create_invoice",
            assigned_agent="finance_order_agent",
            operation="execute",
            reason="legacy scope test",
            payload={"statement_nos": ["stmt_1"], "_confirmed": True},
        ),
        TraceContext(
            requestId="req-legacy-scope-1",
            conversationId="conv-legacy-scope-1",
            traceId="trace-legacy-scope-1",
        ),
    )

    assert key == "tool-conv-legacy-scope-1-tc-legacy-scope-1"


def test_tool_hub_client_ignores_payload_message_id_when_turn_message_id_absent() -> None:
    key = ToolHubClient._build_idempotency_key(
        ToolPlanItem(
            tool_call_id="tc-legacy-scope-2",
            tool_name="billing.create_invoice",
            assigned_agent="finance_order_agent",
            operation="execute",
            reason="legacy scope payload message id test",
            payload={
                "statement_nos": ["stmt_1"],
                "_confirmed": True,
                "message_id": "payload-message-id-should-not-scope-keys",
            },
        ),
        TraceContext(
            requestId="req-legacy-scope-2",
            conversationId="conv-legacy-scope-2",
            traceId="trace-legacy-scope-2",
        ),
    )

    assert key == "tool-conv-legacy-scope-2-tc-legacy-scope-2"


def test_tool_hub_client_reports_dependency_readiness_over_http(monkeypatch) -> None:
    client = ToolHubClient()
    monkeypatch.setattr(client.settings, "tool_hub_transport", "http", raising=False)
    monkeypatch.setattr(client.settings, "tool_hub_base_url", "http://tool-hub.local", raising=False)

    class FakeHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get(self, path: str, headers: dict[str, str]):
            assert path == "/readyz"
            assert headers["X-Caller-Service"] == "orchestrator-service"
            return httpx.Response(
                200,
                request=httpx.Request("GET", "http://tool-hub.local/readyz"),
                json={
                    "status": "ready",
                    "service": "tool-hub-service",
                    "not_ready_components": [],
                    "runtime": {
                        "businessToolsTransport": {
                            "strictRemoteDiscoveryEnabled": True,
                        }
                    },
                },
            )

    monkeypatch.setattr("app.services.tool_hub_client.httpx.Client", FakeHttpClient)

    readiness = client.dependency_readiness()

    assert readiness["ready"] is True
    assert readiness["status"] == "ready"
    assert readiness["service"] == "tool-hub-service"
    assert readiness["httpStatus"] == 200
    assert readiness["strictRemoteDiscoveryEnabled"] is True
