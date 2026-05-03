import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app
from app.api.routes import health as health_routes
from app.api.routes import orchestration as orchestration_routes
from app.core.config import Settings
from app.models.orchestration import AgentExecutionResult
from app.services.agent_runtime import AgentRuntime
from app.services.run_control import RunControlBackendUnavailableError


client = TestClient(app)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SlowToolHubClient:
    def __init__(self, clock: _FakeClock) -> None:
        from app.services.tool_hub_client import ToolHubClient

        self._clock = clock
        self._client = ToolHubClient()

    def preflight(self, *args, **kwargs):
        self._clock.advance(0.6)
        return self._client.preflight(*args, **kwargs)

    def invoke_plan(self, *args, **kwargs):
        self._clock.advance(0.6)
        return self._client.invoke_plan(*args, **kwargs)


def test_healthz_reports_run_control_backend() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert "runControl" in runtime
    assert runtime["runControl"]["backend"] in {"redis-lock", "memory"}
    assert runtime["conversationStore"]["runtimeCache"]["backend"] in {"redis-json", "memory"}
    assert "documentStore" in runtime["conversationStore"]
    assert runtime["conversationStore"]["documentStore"]["backend"] in {"mongodb", "inactive"}
    assert runtime["conversationStore"]["documentStore"]["required"] is False
    assert runtime["conversationStore"]["documentStore"]["ready"] in {True, False}
    assert runtime["stateStore"]["runtimeCache"]["backend"] in {"redis-json", "memory"}
    assert runtime["agentConfigStore"]["runtimeCache"]["backend"] in {"redis-json", "memory"}
    assert runtime["toolHubTransport"]["transport"] in {"local", "http"}
    assert "degradedLocalFallbackEnabled" in runtime["toolHubTransport"]
    assert "strictRemoteDiscoveryEnabled" in runtime["toolHubTransport"]
    if runtime["toolHubTransport"]["transport"] == "http":
        assert runtime["businessToolsIdempotency"]["active"] is False
        assert runtime["businessToolsIdempotency"]["backend"] == "inactive"
        assert runtime["businessToolsIdempotency"]["redisNamespace"].endswith(":idempotency")
        assert runtime["businessToolsIdempotency"]["fallbackPath"].endswith(".json")
        assert runtime["businessToolsQueryCache"]["active"] is False
        assert runtime["businessToolsQueryCache"]["redisNamespace"].endswith(":query-cache")
        assert runtime["businessToolsQueryCache"]["fallbackPath"].endswith(".json")


def test_runtime_snapshot_surfaces_tool_hub_strict_remote_discovery_state(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "APP_ENV": "staging",
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:***@mysql.local:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.local:6379/0",
            "SMARTCLOUD_MONGODB_URI": "mongodb://mongo.local:27017",
            "TOOL_HUB_TRANSPORT": "http",
            "MCP_GATEWAY_URL": "http://tool-hub.local",
        }
    )

    class _FakeToolHubClient:
        @staticmethod
        def dependency_readiness() -> dict[str, object]:
            return {
                "ready": True,
                "status": "ready",
                "mode": "http",
                "service": "tool-hub-service",
                "httpStatus": 200,
                "strictRemoteDiscoveryEnabled": True,
            }

    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr(health_routes, "_tool_hub_client", _FakeToolHubClient())

    runtime = health_routes._runtime_snapshot()

    assert runtime["toolHubTransport"]["transport"] == "http"
    assert runtime["toolHubTransport"]["strictRemoteDiscoveryEnabled"] is True
    assert runtime["toolHubTransport"]["dependencyReadiness"]["strictRemoteDiscoveryEnabled"] is True
    assert runtime["conversationStore"]["documentStore"]["required"] is True
    assert runtime["conversationStore"]["documentStore"]["ready"] is False


def test_runtime_snapshot_includes_rag_client_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_tool_hub_client",
        type(
            "_FakeToolHubClient",
            (),
            {
                "dependency_readiness": staticmethod(
                    lambda: {
                        "ready": True,
                        "status": "ready",
                        "mode": "http",
                        "service": "tool-hub-service",
                        "httpStatus": 200,
                    }
                )
            },
        )(),
    )
    monkeypatch.setattr(
        orchestration_routes._runtime,
        "_rag_client",
        type(
            "_FakeRagClient",
            (),
            {
                "describe_runtime": staticmethod(
                    lambda: {
                        "baseUrl": "http://127.0.0.1:8040",
                        "baseUrlSource": "settings.rag_service_base_url",
                        "apiPrefix": "/api/rag/v1",
                        "apiPrefixSource": "settings.rag_service_api_prefix",
                        "loopback": True,
                        "timeoutSeconds": 30.0,
                        "callerService": "orchestrator-service",
                    }
                )
            },
        )(),
    )

    runtime = health_routes._runtime_snapshot()

    assert runtime["ragServiceClient"]["baseUrl"] == "http://127.0.0.1:8040"
    assert runtime["ragServiceClient"]["baseUrlSource"] == "settings.rag_service_base_url"


def test_readyz_reports_ready_when_runtime_is_healthy(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "conversationStore": {"backend": "mysql", "configured": True},
            "stateStore": {
                "backend": "mysql",
                "configured": True,
                "runtimeCache": {"backend": "redis-json", "configured": True},
            },
            "sseStore": {"backend": "redis-list", "configured": True},
            "agentConfigStore": {
                "backend": "mysql",
                "configured": True,
                "runtimeCache": {"backend": "redis-json", "configured": True},
            },
            "runControl": {"backend": "redis-lock", "configured": True},
            "toolHubTransport": {
                "transport": "http",
                "dependencyReadiness": {"ready": True, "status": "ready"},
            },
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["not_ready_components"] == []


def test_readyz_reports_not_ready_when_tool_hub_dependency_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "conversationStore": {"backend": "mysql", "configured": True},
            "stateStore": {"backend": "mysql", "configured": True},
            "sseStore": {"backend": "redis-list", "configured": True},
            "agentConfigStore": {"backend": "mysql", "configured": True},
            "runControl": {"backend": "redis-lock", "configured": True},
            "toolHubTransport": {
                "transport": "http",
                "dependencyReadiness": {"ready": False, "status": "unreachable"},
            },
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["not_ready_components"] == ["toolHubTransport"]


def test_readyz_reports_not_ready_when_required_document_store_is_inactive(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "conversationStore": {
                "backend": "mysql",
                "configured": True,
                "documentStore": {
                    "backend": "inactive",
                    "configured": False,
                    "ready": False,
                    "required": True,
                },
                "runtimeCache": {"backend": "redis-json", "configured": True},
            },
            "stateStore": {"backend": "mysql", "configured": True},
            "sseStore": {"backend": "redis-list", "configured": True},
            "agentConfigStore": {"backend": "mysql", "configured": True},
            "runControl": {"backend": "redis-lock", "configured": True},
            "toolHubTransport": {
                "transport": "http",
                "dependencyReadiness": {"ready": True, "status": "ready"},
            },
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["not_ready_components"] == ["conversationStore"]


def test_readyz_keeps_optional_document_store_failure_out_of_readiness_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "conversationStore": {
                "backend": "mysql",
                "configured": True,
                "documentStore": {
                    "backend": "mongodb",
                    "configured": True,
                    "ready": False,
                    "degradedFrom": "mongodb",
                    "required": False,
                },
                "runtimeCache": {"backend": "redis-json", "configured": True},
            },
            "stateStore": {"backend": "mysql", "configured": True},
            "sseStore": {"backend": "redis-list", "configured": True},
            "agentConfigStore": {"backend": "mysql", "configured": True},
            "runControl": {"backend": "redis-lock", "configured": True},
            "toolHubTransport": {
                "transport": "http",
                "dependencyReadiness": {"ready": True, "status": "ready"},
            },
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["not_ready_components"] == []


def test_healthz_reports_optional_document_store_degradation_when_configured_but_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "conversationStore": {
                "backend": "mysql",
                "configured": True,
                "documentStore": {
                    "backend": "mongodb",
                    "configured": True,
                    "ready": False,
                    "degradedFrom": "mongodb",
                    "backendError": "RuntimeError: mongo unavailable",
                    "required": False,
                },
                "runtimeCache": {"backend": "redis-json", "configured": True},
            },
            "stateStore": {"backend": "mysql", "configured": True},
            "sseStore": {"backend": "redis-list", "configured": True},
            "agentConfigStore": {"backend": "mysql", "configured": True},
            "runControl": {"backend": "redis-lock", "configured": True},
            "toolHubTransport": {
                "transport": "http",
                "dependencyReadiness": {"ready": True, "status": "ready"},
            },
        },
    )

    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["degraded_components"] == ["conversationStore"]


def test_optional_mongo_startup_failure_degrades_to_unavailable_runtime(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "APP_ENV": "dev",
            "SMARTCLOUD_MONGODB_URI": "mongodb://mongo.local:27017",
            "SMARTCLOUD_MONGODB_DATABASE": "smartcloud",
        }
    )

    async def _fail_connect(cls, current_settings):
        raise RuntimeError(f"mongo unavailable for {current_settings.mongodb_database}")

    monkeypatch.setattr(main_module.ConversationMongoRuntime, "connect", classmethod(_fail_connect))

    runtime = asyncio.run(main_module._build_conversation_mongo_runtime(settings))
    description = runtime.describe_backend()

    assert getattr(runtime, "enabled", False) is False
    assert description["backend"] == "mongodb"
    assert description["configured"] is True
    assert description["ready"] is False
    assert description["degradedFrom"] == "mongodb"
    assert "mongo unavailable" in str(description["backendError"])


def test_required_mongo_startup_failure_bubbles_from_startup_helper(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "APP_ENV": "staging",
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:***@mysql.local:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.local:6379/0",
            "TOOL_HUB_TRANSPORT": "http",
            "SMARTCLOUD_MONGODB_URI": "mongodb://mongo.local:27017",
            "SMARTCLOUD_MONGODB_DATABASE": "smartcloud",
        }
    )

    async def _fail_connect(cls, current_settings):
        raise RuntimeError(f"mongo unavailable for {current_settings.mongodb_database}")

    monkeypatch.setattr(main_module.ConversationMongoRuntime, "connect", classmethod(_fail_connect))

    with pytest.raises(RuntimeError, match="mongo unavailable"):
        asyncio.run(main_module._build_conversation_mongo_runtime(settings))


def test_required_mongo_startup_helper_rejects_missing_uri() -> None:
    settings = Settings.model_construct(
        app_env="staging",
        mongodb_uri=None,
        mongodb_database="smartcloud",
        conversation_document_store_required=True,
    )

    with pytest.raises(RuntimeError, match="SMARTCLOUD_MONGODB_URI"):
        asyncio.run(main_module._build_conversation_mongo_runtime(settings))


def test_internal_orchestrator_chat_requires_allowed_caller() -> None:
    response = client.post(
        "/internal/v1/orchestrator/chat",
        json={
            "request_id": "req-1",
            "trace_id": "trace-1",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use", "user:billing.read"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-1",
                "message_id": "msg-1",
                "user_input": "帮我查本月账单",
                "stream": False,
                "scene": "billing",
                "attachments": [],
            },
        },
    )
    assert response.status_code == 403



def test_internal_orchestrator_chat_executes_finance_flow() -> None:
    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json={
            "request_id": "req-2",
            "trace_id": "trace-2",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use", "user:billing.read"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-2",
                "message_id": "msg-2",
                "user_input": "帮我查本月账单",
                "stream": False,
                "scene": "billing",
                "attachments": [],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["agent_name"] == "finance_order_agent"
    assert payload["tool_calls"][0]["tool_name"] == "billing.query_statement"
    assert payload["state_snapshot"]["checkpoints"]


def test_internal_orchestrator_chat_executes_instance_cost_followup() -> None:
    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json={
            "request_id": "req-instance-2",
            "trace_id": "trace-instance-2",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use", "user:billing.read"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-instance-2",
                "message_id": "msg-instance-2",
                "user_input": "帮我查下这台实例费用",
                "stream": False,
                "scene": "billing",
                "attachments": [],
                "session_context": {
                    "attributes": {
                        "primary_instance_id": "gpu-cn-sh2-01",
                        "billing_cycle": "2026-04",
                    }
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["agent_name"] == "finance_order_agent"
    assert payload["tool_calls"][0]["tool_name"] == "billing.query_instance_cost"
    assert payload["final_answer"].startswith("实例 gpu-cn-sh2-01")


def test_internal_orchestrator_chat_returns_503_when_run_control_backend_is_unavailable(monkeypatch) -> None:
    class _UnavailableRunControl:
        def start(self, conversation_id: str, message_id: str) -> None:
            raise RunControlBackendUnavailableError("Redis connection unavailable.")

        def finish(self, conversation_id: str, message_id: str) -> None:
            return None

        def cancel(self, conversation_id: str, message_id: str) -> bool:
            return False

        def ensure_not_cancelled(self, conversation_id: str, message_id: str) -> None:
            return None

    monkeypatch.setattr(orchestration_routes, "_run_control", _UnavailableRunControl())

    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json={
            "request_id": "req-run-control-unavailable-1",
            "trace_id": "trace-run-control-unavailable-1",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use", "user:billing.read"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-run-control-unavailable-1",
                "message_id": "msg-run-control-unavailable-1",
                "user_input": "帮我查本月账单",
                "stream": False,
                "scene": "billing",
                "attachments": [],
            },
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "CHAT_RUN_CONTROL_UNAVAILABLE"


def test_internal_orchestrator_chat_executes_service_status_followup() -> None:
    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json={
            "request_id": "req-service-status-2",
            "trace_id": "trace-service-status-2",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-service-status-2",
                "message_id": "msg-service-status-2",
                "user_input": "帮我查下这台实例现在是不是故障了",
                "stream": False,
                "scene": "technical_support",
                "attachments": [],
                "session_context": {
                    "attributes": {
                        "primary_instance_id": "gpu-cn-sh2-01",
                    }
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["agent_name"] == "product_tech_agent"
    assert payload["tool_calls"][0]["tool_name"] == "support.query_service_status"
    assert payload["state_snapshot"]["session_context"]["attributes"]["service_status"] == "degraded"
    assert "INC-" in payload["final_answer"]


def test_admin_agent_routes_list_and_patch_overrides() -> None:
    listed = client.get("/api/v1/admin/agents")
    assert listed.status_code == 200
    listed_payload = listed.json()["data"]
    assert listed_payload["total"] == 5
    finance_agent = next(item for item in listed_payload["items"] if item["code"] == "finance_order")
    assert finance_agent["enabled"] is True
    assert finance_agent["tool_whitelist"]

    updated = client.patch(
        "/api/v1/admin/agents/ops_marketing",
        json={"enabled": False, "timeout_seconds": 45},
    )
    assert updated.status_code == 200
    updated_payload = updated.json()["data"]
    assert updated_payload["enabled"] is False
    assert updated_payload["timeout_seconds"] == 45

    filtered = client.get("/api/v1/admin/agents", params={"status": "disabled"})
    assert filtered.status_code == 200
    filtered_items = filtered.json()["data"]["items"]
    assert [item["code"] for item in filtered_items] == ["ops_marketing"]

    route_response = client.post(
        "/api/v1/route",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "conversation_id": "conv-admin-agent-override-1",
            "scene": "technical_support",
        },
    )
    assert route_response.status_code == 200
    decision = route_response.json()["data"]
    assert decision["primary_agent"] == "product_tech_agent"
    assert decision["supporting_agents"] == []


def test_admin_agent_timeout_override_is_enforced_during_execution(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(
        orchestration_routes,
        "_runtime",
        AgentRuntime(
            tool_hub_client=_SlowToolHubClient(clock),
            agent_config_store=orchestration_routes._agent_config_store,
            settings=orchestration_routes._settings,
            clock=clock,
        ),
    )

    updated = client.patch(
        "/api/v1/admin/agents/finance_order",
        json={"timeout_seconds": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["timeout_seconds"] == 1

    response = client.post(
        "/api/v1/sessions/conv-admin-timeout/messages",
        json={
            "user_query": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "retry-or-escalate"
    assert payload["executions"][0]["status"] == "failed"
    assert "agent_timeout" in payload["executions"][0]["risk_flags"]
    assert "1 秒" in payload["final_response_summary"]


def test_orchestrate_message_persists_state_and_compensation_after_confirmed_write() -> None:
    response = client.post(
        "/api/v1/sessions/conv-confirm/messages",
        json={
            "user_query": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert payload["state_snapshot"]["compensation_stack"][0]["compensation"]["action_name"] == "cancel_invoice_request"

    state_response = client.get("/api/v1/sessions/conv-confirm/state")
    assert state_response.status_code == 200
    state_payload = state_response.json()["data"]
    assert state_payload["compensation_stack"][0]["tool_name"] == "billing.create_invoice"
    assert state_payload["events"][-1]["event"] == "state_persisted"


def test_orchestrate_message_sets_collect_user_input_next_action() -> None:
    response = client.post(
        "/api/v1/sessions/conv-user-input/messages",
        json={
            "user_query": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "collect-user-input"
    assert payload["pending_actions"] == ["clarify-tool-input"]
    assert payload["executions"][0]["tool_calls"][0]["status"] == "clarification-required"
    assert payload["executions"][0]["tool_calls"][0]["user_action_hint"]["action"] == "clarify-tool-input"
    assert payload["executions"][0]["tool_calls"][0]["payload"]["missing_fields"] == [
        "statement_nos",
        "invoice_type",
        "title",
    ]
    assert payload["pending_user_actions"][0]["tool_name"] == "billing.create_invoice"
    assert payload["pending_user_actions"][0]["action"] == "clarify-tool-input"
    assert payload["pending_user_actions"][0]["missing_fields"] == ["statement_nos", "invoice_type", "title"]
    assert payload["state_snapshot"]["pending_user_actions"][0]["action"] == "clarify-tool-input"


def test_orchestrate_message_requests_confirmation_after_inputs_are_ready() -> None:
    response = client.post(
        "/api/v1/sessions/conv-user-confirm/messages",
        json={
            "user_query": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "collect-user-input"
    assert payload["pending_actions"] == ["user-confirmation"]
    assert payload["executions"][0]["tool_calls"][0]["status"] == "preview-ready"
    assert payload["executions"][0]["tool_calls"][0]["user_action_hint"]["action"] == "user-confirmation"
    assert payload["pending_user_actions"][0]["action"] == "user-confirmation"
    assert payload["pending_user_actions"][0]["confirm_tool_names"] == ["billing.create_invoice"]
    assert "请确认后继续执行" in payload["final_response_summary"]


def test_orchestrate_message_requests_clarification_for_missing_billing_range() -> None:
    response = client.post(
        "/api/v1/sessions/conv-clarify-range/messages",
        json={
            "user_query": "帮我查账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "collect-user-input"
    assert payload["pending_actions"] == ["clarify-tool-input"]
    assert payload["executions"][0]["tool_calls"][0]["status"] == "clarification-required"
    assert payload["executions"][0]["tool_calls"][0]["payload"]["missing_fields"] == ["range"]


def test_continue_session_applies_field_values_via_tool_bindings() -> None:
    first = client.post(
        "/api/v1/sessions/conv-continue-range/messages",
        json={
            "user_query": "帮我查账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["next_action"] == "collect-user-input"

    resumed = client.post(
        "/api/v1/chat/sessions/conv-continue-range/continue",
        json={"field_values": {"range": "last_month"}},
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]
    assert payload["status"] == "success"
    assert payload["answer"].startswith("账单周期 2026-03")
    assert payload["tool_calls"][0]["payload"]["billing_cycle"] == "2026-03"
    assert payload["pending_user_actions"] == []
    assert payload["response"]["state_snapshot"]["session_context"]["attributes"]["billing_range"] == "last_month"


def test_continue_session_accepts_dotted_icp_contact_fields() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "icp", "title": "ICP备案联系人补充"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    first = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-icp-continue-1",
            "user_input": "继续帮我提交备案申请",
            "scene": "icp",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:icp.write"],
            },
            "session_context": {
                "confirmed_tool_names": ["icp.submit_application"],
                "attributes": {
                    "subject_type": "enterprise",
                    "domain": "demo.example.com",
                    "website_name": "演示站点",
                    "materials": [{"name": "营业执照"}, {"name": "身份证"}, {"name": "域名证书"}],
                },
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]["response"]
    assert first_payload["next_action"] == "collect-user-input"
    assert first_payload["pending_user_actions"][0]["missing_fields"] == ["contacts"]

    resumed = client.post(
        f"/api/v1/chat/sessions/{conversation_id}/continue",
        json={
            "field_values": {
                "contacts.contact_name": "张三",
                "contacts.contact_phone": "13800138000",
                "contacts.contact_email": "icp@example.com",
            }
        },
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]
    assert payload["status"] == "success"
    assert payload["answer"].startswith("备案申请 icp_demo_example_com 已提交")
    submit_payload = payload["response"]["route"]["tool_plan"][1]["payload"]["contacts"]
    assert submit_payload["contact_name"] == "张三"
    assert submit_payload["contact_phone"] == "13800138000"
    assert submit_payload["contact_email"] == "icp@example.com"
    assert (
        payload["response"]["state_snapshot"]["session_context"]["attributes"]["contacts"]["contact_email"]
        == "icp@example.com"
    )


def test_continue_session_accepts_user_profile_patch_and_persists_auth_profile() -> None:
    first = client.post(
        "/api/v1/sessions/conv-continue-auth/messages",
        json={
            "user_query": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert first_payload["next_action"] == "collect-user-input"
    assert first_payload["pending_actions"] == ["collect-auth-context"]
    assert first_payload["executions"][0]["tool_calls"][0]["status"] == "auth-required"
    assert first_payload["pending_user_actions"][0]["user_profile_bindings"] == {
        "account_id": ["account_id"],
        "permissions": ["permissions"],
    }

    resumed = client.post(
        "/api/v1/chat/sessions/conv-continue-auth/continue",
        json={
            "user_profile_patch": {
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            }
        },
    )
    assert resumed.status_code == 200
    resumed_payload = resumed.json()["data"]
    assert resumed_payload["status"] == "success"
    assert resumed_payload["tool_calls"][0]["status"] == "completed"
    assert resumed_payload["response"]["state_snapshot"]["session_context"]["attributes"]["auth_profile"] == {
        "user_id": "u-1",
        "account_id": "acct-1",
        "tenant_id": "default",
        "locale": "zh-CN",
        "channel": "web",
        "vip_level": "normal",
        "roles": ["user"],
        "permissions": ["user:billing.read"],
    }

    followup = client.post(
        "/api/v1/sessions/conv-continue-auth/messages",
        json={
            "user_query": "再查上个月账单",
            "scene": "billing",
        },
    )
    assert followup.status_code == 200
    followup_payload = followup.json()["data"]
    assert followup_payload["next_action"] == "respond-with-agent-summary"
    assert followup_payload["executions"][0]["tool_calls"][0]["status"] == "completed"
    assert followup_payload["executions"][0]["tool_calls"][0]["payload"]["billing_cycle"] == "2026-03"


def test_continue_session_applies_confirm_tool_names() -> None:
    first = client.post(
        "/api/v1/sessions/conv-continue-confirm/messages",
        json={
            "user_query": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["pending_actions"] == ["user-confirmation"]

    resumed = client.post(
        "/api/v1/chat/sessions/conv-continue-confirm/continue",
        json={"confirm_tool_names": ["billing.create_invoice"]},
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]
    assert payload["status"] == "success"
    assert payload["response"]["next_action"] == "respond-with-agent-summary"
    assert payload["tool_calls"][0]["status"] == "completed"
    assert payload["tool_calls"][0]["payload"]["invoice_no"].startswith("inv_")
    assert payload["pending_user_actions"] == []


def test_orchestrate_message_runs_preview_before_confirmed_invoice_execution() -> None:
    response = client.post(
        "/api/v1/sessions/conv-query-preview-invoice/messages",
        json={
            "user_query": "帮我查本月账单并开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "collect-user-input"
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "billing.query_statement",
        "billing.create_invoice",
    ]
    assert tool_calls[0]["status"] == "completed"
    assert tool_calls[1]["status"] == "preview-ready"
    assert tool_calls[1]["user_action_hint"]["action"] == "user-confirmation"
    assert payload["pending_actions"] == ["user-confirmation"]
    assert payload["pending_user_actions"][0]["confirm_tool_names"] == ["billing.create_invoice"]


def test_orchestrate_message_hydrates_invoice_inputs_from_same_turn_query_result() -> None:
    response = client.post(
        "/api/v1/sessions/conv-query-invoice/messages",
        json={
            "user_query": "帮我查本月账单并开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "billing.query_statement",
        "billing.create_invoice",
    ]
    assert tool_calls[0]["status"] == "completed"
    assert tool_calls[1]["status"] == "completed"
    assert tool_calls[1]["payload"]["invoice_no"].startswith("inv_")


def test_orchestrate_message_returns_product_instance_recommendation() -> None:
    response = client.post(
        "/api/v1/sessions/conv-product-sizing/messages",
        json={
            "user_query": "我准备部署 32B 大模型推理服务，帮我推荐 GPU 实例规格",
            "scene": "technical_support",
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert "gi4.2xlarge" in payload["final_response_summary"]
    assert payload["review"]["status"] == "approved"
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "product.catalog_lookup",
        "product.recommend_instance",
    ]
    attributes = payload["state_snapshot"]["session_context"]["attributes"]
    assert attributes["recommended_instance_type"] == "gi4.2xlarge"
    assert attributes["recommended_gpu_model"] == "NVIDIA L40S"


def test_orchestrate_message_generates_promotion_link_after_campaign_lookup() -> None:
    response = client.post(
        "/api/v1/sessions/conv-promotion-link/messages",
        json={
            "user_query": "给我生成 GPU 活动推广链接",
            "scene": "marketing",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert payload["final_response_summary"].startswith("已生成推广链接 https://scx.example/p/")
    assert payload["review"]["status"] == "approved"
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "marketing.campaign_lookup",
        "marketing.generate_promotion_link",
    ]
    assert tool_calls[-1]["status"] == "completed"
    assert payload["state_snapshot"]["session_context"]["attributes"]["last_promotion_link"].startswith(
        "https://scx.example/p/"
    )
    checkpoints = {item["name"]: item["status"] for item in payload["state_snapshot"]["checkpoints"]}
    assert checkpoints["review-answer"] == "completed"


def test_orchestrate_message_generates_poster_after_brief() -> None:
    response = client.post(
        "/api/v1/sessions/conv-marketing-poster/messages",
        json={
            "user_query": "帮我生成 GPU 活动海报",
            "scene": "marketing",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert payload["final_response_summary"].startswith("已生成海报资产 poster_")
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "marketing.campaign_lookup",
        "marketing.poster_brief",
        "marketing.generate_poster",
    ]
    assert tool_calls[-1]["status"] == "completed"
    assert payload["state_snapshot"]["session_context"]["attributes"]["poster_asset_id"].startswith("poster_")
    assert payload["state_snapshot"]["session_context"]["attributes"]["poster_download_path"].endswith(".png")


def test_orchestrate_message_generates_marketing_copy_after_campaign_lookup() -> None:
    response = client.post(
        "/api/v1/sessions/conv-marketing-copy/messages",
        json={
            "user_query": "帮我生成 GPU 活动宣传文案",
            "scene": "marketing",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert payload["final_response_summary"].startswith("已生成营销文案：")
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "marketing.campaign_lookup",
        "marketing.generate_copy",
    ]
    assert tool_calls[-1]["payload"]["headline"].startswith("GPU 新客满减")
    assert payload["state_snapshot"]["session_context"]["attributes"]["last_marketing_copy_campaign_name"] == "GPU 新客满减"


def test_orchestrate_marketing_greeting_does_not_generate_poster_asset() -> None:
    create_response = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "marketing", "title": "marketing-greeting"},
    )
    assert create_response.status_code == 200
    conversation_id = create_response.json()["data"]["conversation_id"]

    response = client.post(
        f"/api/v1/sessions/{conversation_id}/messages",
        json={
            "user_query": "你好",
            "scene": "marketing",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    tool_calls = payload["executions"][0]["tool_calls"]
    assert tool_calls == []
    assert "海报资产" not in payload["final_response_summary"]


def test_orchestrate_message_runs_product_to_marketing_handoff_for_gpu_copy_request() -> None:
    first = client.post(
        "/api/v1/sessions/conv-product-marketing-copy/messages",
        json={
            "user_query": "帮我给 GPU 实例写一段营销文案",
            "scene": "marketing",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert [execution["agent"] for execution in first_payload["executions"]] == ["product_tech_agent"]
    assert first_payload["executions"][0]["status"] == "handoff"
    assert first_payload["executions"][0]["tool_calls"][-1]["tool_name"] == "product.recommend_instance"
    assert first_payload["next_action"] == "continue-agent-handoff"
    assert first_payload["state_snapshot"]["session_context"]["attributes"]["recommended_instance_summary"] == (
        "gi4.2xlarge / NVIDIA L40S x2"
    )

    resumed = client.post(
        "/api/v1/chat/sessions/conv-product-marketing-copy/continue",
        json={},
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]["response"]
    assert [execution["agent"] for execution in payload["executions"]] == [
        "product_tech_agent",
        "ops_marketing_agent",
    ]
    assert payload["executions"][1]["tool_calls"][-1]["tool_name"] == "marketing.generate_copy"
    assert (
        payload["executions"][1]["tool_calls"][-1]["payload"]["product_summary"]
        == "gi4.2xlarge / NVIDIA L40S x2"
    )
    assert payload["state_snapshot"]["session_context"]["attributes"]["last_marketing_product_summary"] == (
        "gi4.2xlarge / NVIDIA L40S x2"
    )


def test_orchestrate_message_reuses_recommended_instance_summary_for_marketing_followup() -> None:
    response = client.post(
        "/api/v1/sessions/conv-product-marketing-followup/messages",
        json={
            "user_query": "把刚才推荐的 GPU 实例写成营销文案",
            "scene": "marketing",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
            "session_context": {
                "active_products": ["GPU 实例"],
                "attributes": {
                    "recommended_instance_summary": "gi4.2xlarge / NVIDIA L40S x2",
                    "recommended_instance_type": "gi4.2xlarge",
                    "recommended_gpu_model": "NVIDIA L40S",
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert [execution["agent"] for execution in payload["executions"]] == ["ops_marketing_agent"]
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "marketing.campaign_lookup",
        "marketing.generate_copy",
    ]
    assert tool_calls[-1]["payload"]["product_summary"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert "gi4.2xlarge / NVIDIA L40S x2" in tool_calls[-1]["payload"]["headline"]


def test_orchestrate_message_exports_research_report() -> None:
    response = client.post(
        "/api/v1/sessions/conv-research-export/messages",
        json={
            "user_query": "帮我导出 LangGraph 选型调研报告 markdown",
            "scene": "research",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:research.write"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert "已导出 MARKDOWN 报告" in payload["final_response_summary"]
    tool_calls = payload["executions"][0]["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == [
        "research.generate_report",
        "research.reference_search",
        "research.export_report",
    ]
    assert tool_calls[-1]["payload"]["download_path"].endswith(".md")
    assert payload["state_snapshot"]["session_context"]["attributes"]["last_report_export_format"] == "markdown"


def test_orchestrate_message_persists_dependency_metadata_in_state_events() -> None:
    response = client.post(
        "/api/v1/sessions/conv-query-invoice-plan/messages",
        json={
            "user_query": "帮我查本月账单并开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    tool_plan = payload["route"]["tool_plan"]
    invoice_plan = next(item for item in tool_plan if item["tool_name"] == "billing.create_invoice")
    query_plan = next(item for item in tool_plan if item["tool_name"] == "billing.query_statement")
    assert invoice_plan["deferred_payload_fields"] == ["statement_nos"]
    assert invoice_plan["depends_on_tool_call_ids"] == [query_plan["tool_call_id"]]
    assert invoice_plan["readiness"] == "ready_after_dependencies"

    route_event = payload["state_snapshot"]["events"][0]
    event_tool_plan = route_event["data"]["tool_plan"]
    event_invoice_plan = next(item for item in event_tool_plan if item["tool_name"] == "billing.create_invoice")
    assert event_invoice_plan["depends_on_tool_call_ids"] == [query_plan["tool_call_id"]]
    assert event_invoice_plan["deferred_payload_fields"] == ["statement_nos"]
    assert event_invoice_plan["tool_mode"] == "write"
    assert event_invoice_plan["timeout_ms"] == 10000
    assert event_invoice_plan["idempotent"] is True
    assert event_invoice_plan["cache_ttl_seconds"] is None


def test_orchestrate_message_pauses_multi_agent_chain_at_resumable_handoff() -> None:
    response = client.post(
        "/api/v1/sessions/conv-multi-agent-complete/messages",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert len(payload["executions"]) == 1
    assert payload["executions"][0]["status"] == "handoff"
    assert payload["executions"][0]["next_agent"] == "ops_marketing_agent"
    assert payload["next_action"] == "continue-agent-handoff"
    assert payload["pending_actions"] == ["continue-agent-handoff"]
    assert any(
        tool_call["tool_name"] == "product.recommend_instance"
        for tool_call in payload["executions"][0]["tool_calls"]
    )
    state_snapshot = payload["state_snapshot"]
    assert state_snapshot["current_agent"] == "ops_marketing_agent"
    assert state_snapshot["pending_agent_handoff"]["next_task_index"] == 1
    agent_routes = state_snapshot["agent_routes"]
    assert [item["status"] for item in agent_routes] == ["handoff", "planned"]
    assert agent_routes[0]["handoff_to"] == "ops_marketing_agent"



def test_continue_session_resumes_pending_agent_handoff_without_replaying_first_agent() -> None:
    first = client.post(
        "/api/v1/sessions/conv-multi-agent-resume/messages",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert first_payload["next_action"] == "continue-agent-handoff"
    assert len(first_payload["executions"]) == 1

    resumed = client.post(
        "/api/v1/chat/sessions/conv-multi-agent-resume/continue",
        json={},
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]
    assert payload["status"] == "success"
    response_payload = payload["response"]
    assert response_payload["next_action"] == "respond-with-agent-summary"
    assert len(response_payload["executions"]) == 2
    assert response_payload["executions"][0]["agent"] == "product_tech_agent"
    assert response_payload["executions"][1]["agent"] == "ops_marketing_agent"
    assert response_payload["executions"][1]["handoff_received_from"] == "product_tech_agent"
    assert response_payload["executions"][1]["status"] == "success"
    assert response_payload["pending_actions"] == []
    assert response_payload["state_snapshot"]["pending_agent_handoff"] is None
    assert [item["status"] for item in response_payload["state_snapshot"]["agent_routes"]] == ["handoff", "success"]
    assert [tool_call["tool_name"] for tool_call in response_payload["executions"][0]["tool_calls"]] == [
        "product.catalog_lookup",
        "product.recommend_instance",
    ]
    assert [tool_call["tool_name"] for tool_call in response_payload["executions"][1]["tool_calls"]] == [
        "marketing.campaign_lookup",
    ]



def test_continue_session_rejects_user_input_override_for_pending_agent_handoff() -> None:
    first = client.post(
        "/api/v1/sessions/conv-multi-agent-reject-input/messages",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["next_action"] == "continue-agent-handoff"

    resumed = client.post(
        "/api/v1/chat/sessions/conv-multi-agent-reject-input/continue",
        json={"user_input": "改成查询账单"},
    )
    assert resumed.status_code == 409
    assert resumed.json()["detail"]["code"] == "CHAT_AGENT_HANDOFF_INPUT_NOT_ALLOWED"



def test_continue_session_rejects_mismatched_message_for_pending_agent_handoff() -> None:
    first = client.post(
        "/api/v1/sessions/conv-multi-agent-reject-message/messages",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["next_action"] == "continue-agent-handoff"

    resumed = client.post(
        "/api/v1/chat/sessions/conv-multi-agent-reject-message/continue",
        json={"message_id": "msg-other-turn"},
    )
    assert resumed.status_code == 409
    assert resumed.json()["detail"]["code"] == "CHAT_AGENT_HANDOFF_MESSAGE_MISMATCH"



def test_continue_session_agent_handoff_does_not_append_duplicate_user_turn() -> None:
    first = client.post(
        "/api/v1/sessions/conv-multi-agent-history/messages",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
        },
    )
    assert first.status_code == 200
    resumed = client.post(
        "/api/v1/chat/sessions/conv-multi-agent-history/continue",
        json={},
    )
    assert resumed.status_code == 200

    messages = client.get("/api/v1/chat/sessions/conv-multi-agent-history/messages").json()["data"]["items"]
    assert [item["role"] for item in messages] == ["user", "assistant", "assistant"]
    assert [item["content"] for item in messages if item["role"] == "user"] == ["有没有 GPU 活动，我要部署大模型"]
    assert messages[-1]["finish_reason"] == "respond-with-agent-summary"



def test_orchestrate_message_marks_blocked_agent_routes_after_user_input_pause() -> None:
    response = client.post(
        "/api/v1/sessions/conv-multi-agent-blocked/messages",
        json={
            "user_query": "帮我开票并推荐营销活动",
            "scene": "customer_service",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read", "user:marketing.read"],
            },
            "tool_candidates": ["billing.create_invoice", "marketing.campaign_lookup"],
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    agent_routes = payload["state_snapshot"]["agent_routes"]
    assert [item["agent"] for item in agent_routes] == [
        "finance_order_agent",
        "ops_marketing_agent",
    ]
    assert agent_routes[0]["status"] == "need_user_input"
    assert agent_routes[0]["action_required"] == "clarify-tool-input"
    assert agent_routes[1]["status"] == "blocked"


def test_orchestrate_message_persists_handoff_brief_for_human_escalation() -> None:
    response = client.post(
        "/api/v1/sessions/conv-human-handoff/messages",
        json={
            "user_query": "服务异常我要转人工",
            "scene": "technical_support",
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["executions"][0]["status"] == "handoff"
    assert payload["executions"][0]["action_required"] == "handoff-to-human-operator"
    assert payload["executions"][0]["tool_calls"][0]["tool_name"] == "support.handoff_brief"
    assert payload["state_snapshot"]["session_context"]["attributes"]["human_handoff_queue"] == "technical-support-l2"
    assert payload["state_snapshot"]["session_context"]["attributes"]["human_handoff_reason"] == "service_exception"
    assert payload["next_action"] == "handoff-to-human"


def test_chat_session_agent_routes_endpoint_returns_state_journal() -> None:
    response = client.post(
        "/api/v1/sessions/conv-agent-routes/messages",
        json={
            "user_query": "有没有 GPU 活动，我要部署大模型",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
        },
    )
    assert response.status_code == 200

    routes_response = client.get("/api/v1/chat/sessions/conv-agent-routes/agent-routes")
    assert routes_response.status_code == 200
    items = routes_response.json()["data"]
    assert [item["agent"] for item in items] == [
        "product_tech_agent",
        "ops_marketing_agent",
    ]
    assert items[0]["status"] == "handoff"
    assert items[1]["status"] == "planned"


def test_internal_orchestrator_chat_accepts_session_context_for_confirmed_write() -> None:
    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json={
            "request_id": "req-3",
            "trace_id": "trace-3",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use", "user:billing.read"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-3",
                "message_id": "msg-3",
                "user_input": "帮我开票",
                "stream": False,
                "scene": "billing",
                "session_context": {
                    "confirmed_tool_names": ["billing.create_invoice"],
                    "attributes": {
                        "statement_nos": ["stmt_2026_04_001"],
                        "invoice_type": "vat_special",
                        "invoice_title": "甲公司",
                    },
                },
                "attachments": [],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["state_snapshot"]["compensation_stack"][0]["tool_name"] == "billing.create_invoice"


def test_internal_orchestrator_chat_accepts_configured_caller_header(monkeypatch) -> None:
    monkeypatch.setattr(orchestration_routes._settings, "caller_service_header", "X-Service-Caller", raising=False)
    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Service-Caller": "gateway-service"},
        json={
            "request_id": "req-custom-1",
            "trace_id": "trace-custom-1",
            "tenant_id": "tenant-a",
            "user": {
                "user_id": "u-1",
                "roles": ["end_user"],
                "permissions": ["user:chat.use", "user:billing.read"],
                "account_id": "acct-1",
            },
            "chat_request": {
                "conversation_id": "conv-custom-1",
                "message_id": "msg-custom-1",
                "user_input": "帮我查本月账单",
                "stream": False,
                "scene": "billing",
                "attachments": [],
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def _retrieval_internal_chat_payload(*, conversation_id: str, message_id: str, user_id: str | None = "u-1") -> dict[str, object]:
    user_payload: dict[str, object] = {
        "tenant_id": "default",
        "roles": ["end_user"],
        "permissions": ["user:chat.use", "user:billing.read"],
        "account_id": "acct-1",
    }
    if user_id is not None:
        user_payload["user_id"] = user_id
    return {
        "request_id": f"req-{message_id}",
        "trace_id": f"trace-{message_id}",
        "tenant_id": "tenant-a",
        "user": user_payload,
        "chat_request": {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "user_input": "帮我查询最近三个月账单",
            "stream": False,
            "scene": "billing",
            "attachments": [],
            "tool_candidates": [],
            "retrieval_required": True,
        },
    }






def test_rag_client_rewrites_legacy_loopback_8030_to_rag_port(monkeypatch) -> None:
    from app.services.rag_client import RagClient

    monkeypatch.setenv("SMARTCLOUD_RAG_SERVICE_BASE_URL", "http://localhost:8030")
    monkeypatch.delenv("RAG_SERVICE_BASE_URL", raising=False)
    monkeypatch.delenv("SMARTCLOUD_RAG_SERVICE_PORT", raising=False)
    monkeypatch.delenv("RAG_SERVICE_PORT", raising=False)

    client = RagClient()

    assert client._base_url == "http://localhost:8040"


def test_rag_client_prefers_settings_loaded_base_url_when_env_is_not_exported(monkeypatch) -> None:
    from app.services.rag_client import RagClient

    monkeypatch.delenv("SMARTCLOUD_RAG_SERVICE_BASE_URL", raising=False)
    monkeypatch.delenv("RAG_SERVICE_BASE_URL", raising=False)
    monkeypatch.delenv("SMARTCLOUD_RAG_SERVICE_PORT", raising=False)
    monkeypatch.delenv("RAG_SERVICE_PORT", raising=False)
    monkeypatch.setattr(
        "app.services.rag_client.get_settings",
        lambda: Settings.model_validate(
            {
                "APP_ENV": "dev",
                "SMARTCLOUD_RAG_SERVICE_BASE_URL": "http://127.0.0.1:8040",
                "SMARTCLOUD_RAG_SERVICE_API_PREFIX": "/api/rag/v1",
            }
        ),
    )

    client = RagClient()

    assert client._base_url == "http://127.0.0.1:8040"
    assert client._base_url_source == "settings.rag_service_base_url"
    assert client.describe_runtime()["apiPrefix"] == "/api/rag/v1"


def test_internal_orchestrator_chat_uses_real_rag_citations_on_success(monkeypatch) -> None:
    def _execute(route, request, trace=None, cancel_check=None, **kwargs):
        retrieval_outcome = orchestration_routes._runtime._run_retrieval(route.tasks[0], request, trace)
        execution = retrieval_outcome["failure_execution"]
        if execution is None:
                execution = AgentExecutionResult(
                    agent=route.primary_agent,
                    status="success",
                    reasoning_summary="已基于真实检索结果完成回答。",
                tool_calls=[],
                citations=retrieval_outcome["citations"],
                retrieval_result=retrieval_outcome["result"],
                confidence=0.9,
                final_answer="已返回最近三个月账单说明。",
                risk_flags=retrieval_outcome["risk_flags"],
                trace_tags=retrieval_outcome["trace_tags"],
            )
        return [execution]

    def _retrieve(payload, *, trace=None, tenant_id=None, authorization=None, timeout=None):
        assert payload["query"] == "帮我查询最近三个月账单"
        assert payload["conversationId"] == "conv-rag-success-1"
        assert tenant_id == "default"
        return {
            "query": payload["query"],
            "rewrittenQuery": "最近三个月账单 查询",
            "degraded": False,
            "backendUsed": "knowledge-service-search",
            "sources": [
                {
                    "sourceId": "src_doc_001_chunk_003",
                    "sourceType": "knowledge_base",
                    "title": "账单 FAQ",
                    "docId": "doc_001",
                    "chunkId": "chunk_003",
                    "score": 0.92,
                    "uri": "kb://billing/doc_001#chunk_003",
                    "snippet": "支持最近三个月账单查询。",
                    "backendUsed": "knowledge-service-search",
                    "domain": "billing",
                }
            ],
        }

    monkeypatch.setattr(orchestration_routes._runtime, "execute", _execute)
    monkeypatch.setattr(orchestration_routes._runtime._rag_client, "retrieve", _retrieve)

    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json=_retrieval_internal_chat_payload(
            conversation_id="conv-rag-success-1",
            message_id="msg-rag-success-1",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["citations"] == ["kb://billing/doc_001#chunk_003"]
    execution = payload["executions"][0]
    assert execution["retrieval_result"]["backend_used"] == "knowledge-service-search"
    assert execution["retrieval_result"]["degraded"] is False
    assert execution["retrieval_result"]["sources"][0]["uri"] == "kb://billing/doc_001#chunk_003"
    assert "baseline://router-retrieval" not in payload["citations"]


def test_internal_orchestrator_chat_marks_degraded_retrieval_without_baseline_placeholder(monkeypatch) -> None:
    def _execute(route, request, trace=None, cancel_check=None, **kwargs):
        retrieval_outcome = orchestration_routes._runtime._run_retrieval(route.tasks[0], request, trace)
        execution = retrieval_outcome["failure_execution"]
        if execution is None:
                execution = AgentExecutionResult(
                    agent=route.primary_agent,
                    status="success",
                    reasoning_summary="检索链路降级，未返回可引用知识。",
                tool_calls=[],
                citations=retrieval_outcome["citations"],
                retrieval_result=retrieval_outcome["result"],
                confidence=0.5,
                final_answer="当前没有检索到可引用知识。",
                risk_flags=retrieval_outcome["risk_flags"],
                trace_tags=retrieval_outcome["trace_tags"],
            )
        return [execution]

    def _retrieve(payload, *, trace=None, tenant_id=None, authorization=None, timeout=None):
        return {
            "query": payload["query"],
            "rewrittenQuery": payload["query"],
            "degraded": True,
            "degradationNote": "knowledge-service unavailable: ReadTimeout",
            "backendUsed": "knowledge-service-unavailable",
            "sources": [],
        }

    monkeypatch.setattr(orchestration_routes._runtime, "execute", _execute)
    monkeypatch.setattr(orchestration_routes._runtime._rag_client, "retrieve", _retrieve)

    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json=_retrieval_internal_chat_payload(
            conversation_id="conv-rag-degraded-1",
            message_id="msg-rag-degraded-1",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["citations"] == []
    execution = payload["executions"][0]
    assert execution["retrieval_result"]["degraded"] is True
    assert execution["retrieval_result"]["backend_used"] == "knowledge-service-unavailable"
    assert execution["risk_flags"] == ["retrieval_degraded"]
    assert "baseline://router-retrieval" not in str(payload)


def test_internal_orchestrator_chat_returns_failed_when_rag_hard_failure_occurs(monkeypatch) -> None:
    from app.services.rag_client import RagClientUnavailableError

    def _execute(route, request, trace=None, cancel_check=None, **kwargs):
        retrieval_outcome = orchestration_routes._runtime._run_retrieval(route.tasks[0], request, trace)
        execution = retrieval_outcome["failure_execution"]
        assert execution is not None
        return [execution]

    def _retrieve(payload, *, trace=None, tenant_id=None, authorization=None, timeout=None):
        raise RagClientUnavailableError("rag-service request timed out or could not connect.")

    monkeypatch.setattr(orchestration_routes._runtime, "execute", _execute)
    monkeypatch.setattr(orchestration_routes._runtime._rag_client, "retrieve", _retrieve)

    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json=_retrieval_internal_chat_payload(
            conversation_id="conv-rag-failure-1",
            message_id="msg-rag-failure-1",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["citations"] == []
    execution = payload["executions"][0]
    assert execution["status"] == "failed"
    assert execution["retrieval_result"] is None
    assert execution["risk_flags"] == ["retrieval_failed"]
    assert payload["final_answer"] == "finance_order_agent 当前无法完成实时检索，请稍后重试。"
    assert "baseline://router-retrieval" not in str(payload)


def test_internal_orchestrator_chat_rejects_missing_user_context_for_retrieval(monkeypatch) -> None:
    def _execute(route, request, trace=None, cancel_check=None, **kwargs):
        retrieval_outcome = orchestration_routes._runtime._run_retrieval(route.tasks[0], request, trace)
        execution = retrieval_outcome["failure_execution"]
        assert execution is not None
        return [execution]

    monkeypatch.setattr(orchestration_routes._runtime, "execute", _execute)
    response = client.post(
        "/internal/v1/orchestrator/chat",
        headers={"X-Caller-Service": "gateway-service"},
        json=_retrieval_internal_chat_payload(
            conversation_id="conv-rag-missing-user-1",
            message_id="msg-rag-missing-user-1",
            user_id=None,
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    execution = payload["executions"][0]
    assert execution["status"] == "failed"
    assert execution["tool_calls"] == []
    assert execution["risk_flags"] == ["missing_user_context"]
    assert payload["citations"] == []


def test_orchestrate_message_stream_emits_spec_like_events(monkeypatch) -> None:
    def _retrieve(payload, *, trace=None, tenant_id=None, authorization=None, timeout=None):
        assert payload["query"] == "给我一份 GPU 部署最佳实践和排查方案"
        return {
            "query": payload["query"],
            "rewrittenQuery": "GPU 部署 最佳实践 排查方案",
            "degraded": False,
            "backendUsed": "knowledge-service-search",
            "sources": [
                {
                    "sourceId": "src_gpu_playbook_chunk_001",
                    "sourceType": "knowledge_base",
                    "title": "GPU 部署最佳实践",
                    "docId": "doc_gpu_001",
                    "chunkId": "chunk_001",
                    "score": 0.97,
                    "uri": "kb://technical_support/doc_gpu_001#chunk_001",
                    "snippet": "先检查驱动、CUDA 与实例规格匹配。",
                    "backendUsed": "knowledge-service-search",
                    "domain": "technical_support",
                }
            ],
        }

    monkeypatch.setattr(orchestration_routes._runtime._rag_client, "retrieve", _retrieve)

    with client.stream(
        "POST",
        "/api/v1/sessions/conv-stream/messages/stream",
        json={
            "message_id": "msg-stream-1",
            "user_query": "给我一份 GPU 部署最佳实践和排查方案",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-stream-1",
                "tenant_id": "default",
            },
        },
        headers={"X-Request-Id": "req-stream-1", "X-Trace-Id": "trace-stream-1"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: evt-0001" in body
    events = [line for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "event: meta"
    assert "event: reasoning" in events
    assert "event: retrieval" in events
    assert "event: tool_call" in events
    assert "event: tool_result" in events
    assert "event: citation" in events
    assert events[-1] == "event: done"


def test_message_stream_events_can_be_replayed_and_resumed_from_last_event_id() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "technical_support"})
    assert create_response.status_code == 200
    conversation_id = create_response.json()["data"]["conversation_id"]

    completion = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-replay-1",
            "user_input": "给我一份 GPU 部署最佳实践和排查方案",
            "scene": "technical_support",
        },
    )
    assert completion.status_code == 200

    events_response = client.get(
        f"/api/v1/chat/sessions/{conversation_id}/messages/asst_msg-replay-1/events",
    )
    assert events_response.status_code == 200
    items = events_response.json()["data"]["items"]
    assert items[0]["event"] == "meta"
    assert items[-1]["event"] == "done"

    with client.stream(
        "GET",
        f"/api/v1/chat/sessions/{conversation_id}/messages/msg-replay-1/events/stream",
        headers={"Last-Event-ID": "evt-0001"},
    ) as replay_response:
        replay_body = "".join(replay_response.iter_text())

    assert replay_response.status_code == 200
    assert "event: meta" not in replay_body
    assert "event: done" in replay_body



def test_orchestrate_message_scopes_write_tool_idempotency_by_turn() -> None:
    first = client.post(
        "/api/v1/sessions/conv-idem/messages",
        json={
            "user_query": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert first_payload["next_action"] == "respond-with-agent-summary"
    first_tool = first_payload["executions"][0]["tool_calls"][0]
    assert first_tool["status"] == "completed"

    second = client.post(
        "/api/v1/sessions/conv-idem/messages",
        json={
            "user_query": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "乙公司",
                },
            },
        },
    )
    assert second.status_code == 200
    second_payload = second.json()["data"]
    assert second_payload["next_action"] == "respond-with-agent-summary"
    second_tool = second_payload["executions"][0]["tool_calls"][0]
    assert second_tool["status"] == "completed"
    assert first_tool["idempotency_key"] != second_tool["idempotency_key"]


def test_chat_session_routes_persist_messages_and_support_retry() -> None:
    create_response = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "billing", "title": "账单会话"},
    )
    assert create_response.status_code == 200
    conversation_id = create_response.json()["data"]["conversation_id"]

    completion_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-chat-1",
            "user_input": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert completion_response.status_code == 200
    completion_payload = completion_response.json()["data"]
    assert completion_payload["status"] == "success"

    messages_response = client.get(f"/api/v1/chat/sessions/{conversation_id}/messages")
    assert messages_response.status_code == 200
    items = messages_response.json()["data"]["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[0]["message_id"] == "msg-chat-1"

    retry_response = client.post(
        f"/api/v1/chat/sessions/{conversation_id}/retry",
        json={"message_id": "msg-chat-1", "override_input": "帮我查上个月账单"},
    )
    assert retry_response.status_code == 200
    retry_payload = retry_response.json()["data"]
    assert retry_payload["message_id"] != "msg-chat-1"
    assert retry_payload["response"]["conversation_id"] == conversation_id

    messages_after_retry = client.get(f"/api/v1/chat/sessions/{conversation_id}/messages").json()["data"]["items"]
    assert len(messages_after_retry) == 4


def test_chat_completions_accepts_spec_style_context_and_options() -> None:
    create_response = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "billing", "title": "Spec chat"},
    )
    conversation_id = create_response.json()["data"]["conversation_id"]

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-spec-1",
            "user_input": "帮我查询最近三个月账单",
            "scene": "billing",
            "stream": False,
            "context": {
                "user_id": "u-1",
                "tenant_id": "tenant-a",
                "account_id": "acct-1",
                "locale": "zh-CN",
                "permissions": ["user:billing.read"],
            },
            "options": {
                "use_rag": True,
                "use_tools": False,
                "agent_hint": "Finance_Order_Agent",
                "max_history_turns": 5,
            },
            "context_control": {
                "use_history": False,
                "must_cite": True,
            },
            "client_meta": {"page": "/chat", "user_agent": "pytest"},
        },
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "failed"
    assert payload["response"]["route"]["primary_agent"] == "finance_order_agent"
    assert payload["response"]["route"]["requires_retrieval"] is True
    assert payload["tool_calls"] == []
    assert payload["citations"] == []
    assert payload["finish_reason"] == "retry"


def test_chat_session_delete_soft_deletes_conversation() -> None:
    create_response = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "billing", "title": "Delete me"},
    )
    conversation_id = create_response.json()["data"]["conversation_id"]

    delete_response = client.delete(f"/api/v1/chat/sessions/{conversation_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["data"]["status"] == "deleted"

    list_response = client.get("/api/v1/chat/sessions")
    items = list_response.json()["data"]["items"]
    assert all(item["conversation_id"] != conversation_id for item in items)

    detail_response = client.get(f"/api/v1/chat/sessions/{conversation_id}")
    assert detail_response.status_code == 404


def test_orchestrator_propagates_query_cache_audit_tags() -> None:
    first = client.post(
        "/api/v1/sessions/conv-cache/messages",
        json={
            "user_query": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    second = client.post(
        "/api/v1/sessions/conv-cache/messages",
        json={
            "user_query": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert "cache-hit" in second.json()["data"]["executions"][0]["tool_calls"][0]["audit_tags"]


def test_chat_session_archive_and_restore_controls_completion_flow() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    archive_response = client.post(f"/api/v1/chat/sessions/{conversation_id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["data"]["status"] == "archived"

    blocked_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-archived-1",
            "user_input": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert blocked_response.status_code == 409

    restore_response = client.post(f"/api/v1/chat/sessions/{conversation_id}/restore")
    assert restore_response.status_code == 200
    assert restore_response.json()["data"]["status"] == "active"

    completion_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-archived-2",
            "user_input": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert completion_response.status_code == 200
    assert completion_response.json()["data"]["status"] == "success"


def test_chat_session_list_applies_status_scene_and_keyword_filters() -> None:
    archived_billing = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "billing", "title": "归档账单会话"},
    ).json()["data"]["conversation_id"]
    active_billing = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "billing", "title": "活跃账单会话"},
    ).json()["data"]["conversation_id"]
    client.post(f"/api/v1/chat/sessions/{archived_billing}/archive")

    archived_response = client.get("/api/v1/chat/sessions?status=archived")
    archived_items = archived_response.json()["data"]["items"]
    archived_ids = {item["conversation_id"] for item in archived_items}
    assert archived_billing in archived_ids
    assert active_billing not in archived_ids
    assert all(item["status"] == "archived" for item in archived_items)

    scene_response = client.get("/api/v1/chat/sessions?scene=billing")
    scene_items = scene_response.json()["data"]["items"]
    scene_ids = {item["conversation_id"] for item in scene_items}
    assert archived_billing in scene_ids
    assert active_billing in scene_ids
    assert all(item["scene"] == "billing" for item in scene_items)

    keyword_response = client.get("/api/v1/chat/sessions?keyword=归档账单")
    keyword_items = keyword_response.json()["data"]["items"]
    keyword_ids = {item["conversation_id"] for item in keyword_items}
    assert archived_billing in keyword_ids
    assert active_billing not in keyword_ids


def test_chat_session_cancel_rejects_non_running_message() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    cancel_response = client.post(
        f"/api/v1/chat/sessions/{conversation_id}/cancel",
        json={"message_id": "msg-not-running-1"},
    )
    assert cancel_response.status_code == 409
    assert cancel_response.json()["detail"]["code"] == "CHAT_MESSAGE_NOT_RUNNING"


def test_chat_session_cancel_marks_running_message_cancelled(monkeypatch) -> None:
    from fastapi import HTTPException

    from app.models.common import TraceContext
    from app.models.orchestration import MessageRequest, UserProfile

    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing", "title": "Cancel me"})
    conversation_id = create_response.json()["data"]["conversation_id"]
    message_id = "msg-cancel-1"
    result: dict[str, object] = {}

    original_run_orchestration = orchestration_routes._run_orchestration

    def _blocking_run_orchestration(route_request, message_request, trace, cancel_check=None, **kwargs):
        from app.services.run_control import OrchestrationCancelled

        deadline = time.time() + 2
        while time.time() < deadline:
            if cancel_check is not None:
                try:
                    cancel_check()
                except OrchestrationCancelled:
                    raise
            time.sleep(0.01)
        return original_run_orchestration(
            route_request,
            message_request,
            trace,
            cancel_check=cancel_check,
            **kwargs,
        )

    monkeypatch.setattr(orchestration_routes, "_run_orchestration", _blocking_run_orchestration)

    def _run_completion() -> None:
        try:
            orchestration_routes._execute_message(
                conversation_id,
                MessageRequest(
                    user_query="帮我查本月账单",
                    message_id=message_id,
                    scene="billing",
                    user_profile=UserProfile(
                        user_id="u-1",
                        account_id="acct-1",
                        permissions=["user:billing.read"],
                    ),
                ),
                TraceContext(
                    requestId=message_id,
                    conversationId=conversation_id,
                    traceId=f"trace-{message_id}",
                ),
                strict_session=True,
            )
            result["response"] = {"status_code": 200, "detail": None}
        except HTTPException as exc:
            result["response"] = {"status_code": exc.status_code, "detail": exc.detail}
        except BaseException as exc:  # pragma: no cover - defensive capture for threaded failure visibility
            result["error"] = repr(exc)

    thread = threading.Thread(target=_run_completion, daemon=True)
    thread.start()
    deadline = time.time() + 2
    while time.time() < deadline and not orchestration_routes._run_control.is_running(conversation_id, message_id):
        time.sleep(0.01)
    assert orchestration_routes._run_control.is_running(
        conversation_id,
        message_id,
    ), "expected completion flow to enter running state"

    cancel_response = client.post(
        f"/api/v1/chat/sessions/{conversation_id}/cancel",
        json={"message_id": message_id},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "cancelled"

    thread.join(20)
    assert "response" in result
    response = result["response"]
    assert response["status_code"] == 409
    assert response["detail"]["code"] == "CHAT_MESSAGE_CANCELLED"

    messages_response = client.get(f"/api/v1/chat/sessions/{conversation_id}/messages")
    assert messages_response.status_code == 200
    messages = messages_response.json()["data"]["items"]
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["status"] == "cancelled"
    assert messages[-1]["finish_reason"] == "cancelled"

    state_response = client.get(f"/api/v1/sessions/{conversation_id}/state")
    assert state_response.status_code == 200
    assert state_response.json()["data"]["final_response_summary"] == "生成已取消。"


def test_session_rollback_executes_compensation_stack_in_reverse_order() -> None:
    first = client.post(
        "/api/v1/sessions/conv-rollback/messages",
        json={
            "user_query": "帮我申请发票并提交备案申请",
            "scene": "customer_service",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read", "user:icp.write"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice", "icp.submit_application"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                    "subject_type": "enterprise",
                    "domain": "demo.example.com",
                    "website_name": "演示站点",
                    "contacts": {"name": "张三", "phone": "13800000000"},
                    "materials": [{"name": "营业执照"}, {"name": "身份证"}, {"name": "域名证书"}],
                },
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert first_payload["next_action"] == "continue-agent-handoff"
    assert len(first_payload["state_snapshot"]["compensation_stack"]) == 1

    resumed = client.post(
        "/api/v1/chat/sessions/conv-rollback/continue",
        json={},
    )
    assert resumed.status_code == 200
    stack = resumed.json()["data"]["response"]["state_snapshot"]["compensation_stack"]
    assert len(stack) == 2

    rollback_response = client.post(
        "/api/v1/sessions/conv-rollback/rollback",
        headers={"X-Request-Id": "req-rollback-1", "X-Trace-Id": "trace-rollback-1"},
    )
    assert rollback_response.status_code == 200
    payload = rollback_response.json()["data"]
    assert payload["status"] == "completed"
    assert [item["action_name"] for item in payload["compensated_steps"]] == [
        "withdraw_icp_application",
        "cancel_invoice_request",
    ]
    assert all(item["status"] == "completed" for item in payload["compensated_steps"])
    assert [item["status"] for item in payload["state_snapshot"]["compensation_stack"]] == [
        "completed",
        "completed",
    ]
    assert payload["state_snapshot"]["events"][-2]["event"] == "compensation_result"
    assert payload["state_snapshot"]["events"][-1]["event"] == "state_persisted"


def test_chat_session_followup_uses_persisted_billing_context_for_invoice() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing", "title": "账单续接"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    first_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-billing-1",
            "user_input": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]["response"]
    assert first_payload["state_snapshot"]["session_context"]["attributes"]["statement_no"] == "stmt_2026_04_001"
    assert first_payload["state_snapshot"]["version"] == 1

    second_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-billing-2",
            "user_input": "继续帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()["data"]["response"]
    assert second_payload["next_action"] == "respond-with-agent-summary"
    assert second_payload["executions"][0]["tool_calls"][0]["tool_name"] == "billing.create_invoice"
    assert second_payload["state_snapshot"]["session_context"]["attributes"]["invoice_no"].startswith("inv_")
    assert second_payload["state_snapshot"]["tool_context"][-1]["tool_name"] == "billing.create_invoice"
    assert second_payload["state_snapshot"]["version"] == 2


def test_chat_session_followup_uses_persisted_invoice_context_for_status_query() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing", "title": "发票状态续接"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    invoice_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-invoice-1",
            "user_input": "帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    assert invoice_response.status_code == 200
    assert invoice_response.json()["data"]["response"]["state_snapshot"]["session_context"]["attributes"]["invoice_no"].startswith(
        "inv_"
    )

    status_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-invoice-2",
            "user_input": "帮我查下发票状态",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert status_response.status_code == 200
    payload = status_response.json()["data"]["response"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert payload["executions"][0]["tool_calls"][0]["tool_name"] == "invoice.query_invoice"
    assert payload["final_response_summary"].startswith("发票申请 inv_")
    assert payload["state_snapshot"]["session_context"]["attributes"]["invoice_status"] == "processing"
    assert payload["state_snapshot"]["version"] == 2


def test_chat_session_followup_uses_persisted_primary_instance_for_cost_query() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing", "title": "实例费用续接"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    billing_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-billing-1",
            "user_input": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert billing_response.status_code == 200
    first_attributes = billing_response.json()["data"]["response"]["state_snapshot"]["session_context"]["attributes"]
    assert first_attributes["primary_instance_id"] == "gpu-cn-sh2-01"

    instance_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-billing-2",
            "user_input": "帮我查下这台实例费用",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    assert instance_response.status_code == 200
    payload = instance_response.json()["data"]["response"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert payload["executions"][0]["tool_calls"][0]["tool_name"] == "billing.query_instance_cost"
    assert payload["final_response_summary"].startswith("实例 gpu-cn-sh2-01")
    assert payload["state_snapshot"]["session_context"]["attributes"]["last_instance_cost_total"] == 412.68
    assert payload["state_snapshot"]["version"] == 2


def test_chat_session_followup_uses_persisted_icp_verification_context_for_submit() -> None:
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "icp", "title": "ICP备案续接"})
    conversation_id = create_response.json()["data"]["conversation_id"]

    verify_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-icp-verify-1",
            "user_input": "请帮我核验备案实名认证",
            "scene": "icp",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:icp.read"],
            },
            "session_context": {
                "attributes": {
                    "subject_type": "enterprise",
                    "subject_name": "上海示例科技有限公司",
                    "certificate_no": "91310000MA1CTEST88",
                    "contact_name": "张三",
                    "contact_phone": "13800138000",
                },
            },
        },
    )
    assert verify_response.status_code == 200
    verify_payload = verify_response.json()["data"]["response"]
    assert verify_payload["executions"][0]["tool_calls"][0]["tool_name"] == "icp.verify_subject"
    assert verify_payload["state_snapshot"]["session_context"]["attributes"]["contacts"]["contact_phone"] == "13800138000"

    submit_response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-icp-submit-2",
            "user_input": "继续帮我提交备案申请",
            "scene": "icp",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:icp.write"],
            },
            "session_context": {
                "confirmed_tool_names": ["icp.submit_application"],
                "attributes": {
                    "domain": "demo.example.com",
                    "website_name": "演示站点",
                    "materials": [{"name": "营业执照"}, {"name": "身份证"}, {"name": "域名证书"}],
                },
            },
        },
    )
    assert submit_response.status_code == 200
    payload = submit_response.json()["data"]["response"]
    assert payload["next_action"] == "respond-with-agent-summary"
    assert [tool["tool_name"] for tool in payload["executions"][0]["tool_calls"]] == [
        "icp.material_check",
        "icp.submit_application",
    ]
    assert payload["route"]["tool_plan"][1]["payload"]["contacts"]["contact_phone"] == "13800138000"
    assert payload["final_response_summary"].startswith("备案申请 icp_demo_example_com 已提交")
    assert payload["state_snapshot"]["session_context"]["attributes"]["application_no"] == "icp_demo_example_com"
    assert payload["state_snapshot"]["session_context"]["attributes"]["contacts"]["contact_phone"] == "13800138000"
    assert payload["state_snapshot"]["version"] == 2


def test_session_context_persists_open_ticket_id_for_followup_reply() -> None:
    first_response = client.post(
        "/api/v1/sessions/conv-ticket-context/messages",
        json={
            "user_query": "帮我创建一个售后工单",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:ticket.write"],
            },
        },
    )
    assert first_response.status_code == 200
    first_payload = first_response.json()["data"]
    ticket_no = first_payload["executions"][0]["tool_calls"][0]["payload"]["ticket_no"]
    assert first_payload["state_snapshot"]["session_context"]["open_ticket_id"] == ticket_no

    second_response = client.post(
        "/api/v1/sessions/conv-ticket-context/messages",
        json={
            "user_query": "继续回复这个工单：实例已经重启",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:ticket.write"],
            },
        },
    )
    assert second_response.status_code == 200
    second_payload = second_response.json()["data"]
    assert second_payload["executions"][0]["tool_calls"][0]["tool_name"] == "ticket.reply"
    assert second_payload["executions"][0]["tool_calls"][0]["payload"]["ticket_no"] == ticket_no
    assert second_payload["state_snapshot"]["version"] == 2


def test_orchestrate_message_creates_ticket_after_technical_handoff_brief() -> None:
    first = client.post(
        "/api/v1/sessions/conv-human-ticket/messages",
        json={
            "user_query": "GPU 实例异常帮我转人工并创建工单",
            "scene": "technical_support",
            "user_profile": {
                "user_id": "u-1",
                "permissions": ["user:ticket.write"],
            },
        },
    )
    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert first_payload["next_action"] == "continue-agent-handoff"
    assert [execution["agent"] for execution in first_payload["executions"]] == ["product_tech_agent"]
    assert first_payload["executions"][0]["tool_calls"][0]["tool_name"] == "support.query_service_status"

    resumed = client.post(
        "/api/v1/chat/sessions/conv-human-ticket/continue",
        json={},
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]["response"]
    assert payload["next_action"] == "handoff-to-human"
    assert [execution["agent"] for execution in payload["executions"]] == [
        "product_tech_agent",
        "finance_order_agent",
    ]
    assert payload["executions"][1]["tool_calls"][0]["tool_name"] == "ticket.create"
    assert payload["executions"][1]["tool_calls"][0]["payload"]["queue"] == "technical-support-l2"
    assert "工单 tk_technical-support_001 已创建" in payload["final_response_summary"]
    assert payload["state_snapshot"]["session_context"]["open_ticket_id"] == "tk_technical-support_001"
    assert payload["state_snapshot"]["session_context"]["attributes"]["human_handoff_queue"] == "technical-support-l2"
    assert payload["state_snapshot"]["session_context"]["attributes"]["ticket_incident_code"].startswith("INC-")


def test_orchestrate_message_honors_explicit_tool_candidates_across_agents() -> None:
    first = client.post(
        "/api/v1/sessions/conv-explicit-tools/messages",
        json={
            "user_query": "请按计划处理",
            "scene": "customer_service",
            "tool_candidates": ["billing.query_statement", "marketing.campaign_lookup"],
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read", "user:marketing.read"],
            },
            "session_context": {
                "attributes": {
                    "billing_range": "this_month",
                }
            },
        },
    )

    assert first.status_code == 200
    first_payload = first.json()["data"]
    assert first_payload["route"]["primary_agent"] == "finance_order_agent"
    assert first_payload["route"]["supporting_agents"] == ["ops_marketing_agent"]
    assert [execution["agent"] for execution in first_payload["executions"]] == ["finance_order_agent"]
    assert first_payload["next_action"] == "continue-agent-handoff"
    assert first_payload["executions"][0]["tool_calls"][0]["tool_name"] == "billing.query_statement"

    resumed = client.post(
        "/api/v1/chat/sessions/conv-explicit-tools/continue",
        json={},
    )
    assert resumed.status_code == 200
    payload = resumed.json()["data"]["response"]
    assert [execution["agent"] for execution in payload["executions"]] == [
        "finance_order_agent",
        "ops_marketing_agent",
    ]
    assert payload["executions"][1]["tool_calls"][0]["tool_name"] == "marketing.campaign_lookup"


def test_chat_completions_options_tool_candidates_drive_route_selection() -> None:
    create_response = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "customer_service", "title": "explicit tool candidates"},
    )
    assert create_response.status_code == 200
    conversation_id = create_response.json()["data"]["conversation_id"]

    response = client.post(
        "/api/v1/chat/completions",
        json={
            "conversation_id": conversation_id,
            "message_id": "msg-tool-candidate-1",
            "user_input": "请按计划处理",
            "stream": False,
            "scene": "customer_service",
            "context": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
            "options": {
                "tool_candidates": ["marketing.campaign_lookup"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["response"]["route"]["primary_agent"] == "ops_marketing_agent"
    assert payload["tool_calls"][0]["tool_name"] == "marketing.campaign_lookup"



def test_list_chat_messages_returns_404_for_missing_conversation() -> None:
    """Regression test: list_chat_messages should return 404 for a
    non-existent conversation, not 500.

    Before the fix, ConversationStoreError raised by require() inside
    list_messages() was uncaught, causing FastAPI to return 500.
    """
    response = client.get("/api/v1/chat/sessions/nonexistent-conv-id/messages")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body or "detail" in body


def test_list_chat_messages_returns_items_for_valid_conversation() -> None:
    """A valid conversation with messages should return the items array."""
    create_response = client.post(
        "/api/v1/chat/sessions",
        json={"scene": "customer_service", "title": "messages-list-test"},
    )
    assert create_response.status_code == 200
    conversation_id = create_response.json()["data"]["conversation_id"]

    # Post a user message via the session messages endpoint
    client.post(
        f"/api/v1/sessions/{conversation_id}/messages",
        json={
            "user_query": "hello",
            "scene": "customer_service",
            "user_profile": {"user_id": "u-1"},
        },
    )

    # Now fetch messages for this conversation
    messages_response = client.get(f"/api/v1/chat/sessions/{conversation_id}/messages")
    assert messages_response.status_code == 200
    data = messages_response.json()["data"]
    assert "items" in data
    assert isinstance(data["items"], list)
