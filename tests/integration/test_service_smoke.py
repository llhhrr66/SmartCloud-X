from __future__ import annotations

import json
from pathlib import Path

from scripts.qa.baseline_expectations import REPO_ROOT
from tests.qa_helpers.service_loader import assert_standard_headers, service_test_client


AUTH_LOGIN_PAYLOAD = {
    "login_type": "password",
    "account": "demo@smartcloud.local",
    "password": "Password123!",
}


def _auth_env(tmp_path: Path) -> dict[str, str]:
    return {
        "AUTH_USER_SERVICE_DATA_PATH": str(tmp_path / "auth-store.json"),
        "SMARTCLOUD_JWT_SECRET": "qa-test-secret",
        "SMARTCLOUD_AUTH_ISSUER": "qa-test-issuer",
        "SMARTCLOUD_AUTH_AUDIENCE": "qa-test-audience",
        "SMARTCLOUD_INTERNAL_AUTH_AUDIENCE": "qa-test-internal",
    }


def _orchestrator_env(tmp_path: Path) -> dict[str, str]:
    return {
        "CONVERSATION_STORE_PATH": str(tmp_path / "conversation-store.json"),
        "STATE_STORE_PATH": str(tmp_path / "state-store.json"),
        "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "idempotency-store.json"),
        "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "query-cache-store.json"),
        "SSE_EVENT_STORE_PATH": str(tmp_path / "sse-event-store.json"),
    }


def _knowledge_env(tmp_path: Path) -> dict[str, str]:
    service_root = REPO_ROOT / "apps" / "knowledge-service"
    return {
        "SMARTCLOUD_KNOWLEDGE_DATA_PATH": str(tmp_path / "knowledge-store.json"),
        "SMARTCLOUD_KNOWLEDGE_AUDIT_PATH": str(tmp_path / "knowledge-audit.jsonl"),
        "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH": str(service_root / "data" / "starter-catalog.json"),
        "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT": str(service_root / "data" / "imports"),
    }


def _load_json(rel_path: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / rel_path).read_text(encoding="utf-8"))


def test_auth_demo_login_smoke_returns_tokens_and_chat_permission(tmp_path: Path) -> None:
    with service_test_client("auth-user-service", env_overrides=_auth_env(tmp_path)) as client:
        response = client.post("/api/v1/auth/login", json=AUTH_LOGIN_PAYLOAD)

    assert response.status_code == 200
    assert_standard_headers(response.headers)
    payload = response.json()["data"]
    assert payload["access_token"]
    assert payload["refresh_token"]
    assert payload["user"]["email"] == "demo@smartcloud.local"
    assert "user:chat.use" in payload["user"]["permissions"]


def test_auth_invalid_password_returns_canonical_401(tmp_path: Path) -> None:
    with service_test_client("auth-user-service", env_overrides=_auth_env(tmp_path)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={**AUTH_LOGIN_PAYLOAD, "password": "wrong-password"},
        )

    assert response.status_code == 401
    assert_standard_headers(response.headers)
    payload = response.json()
    assert payload["code"] == 4010002
    assert payload["message"] == "invalid account or credential"
    assert payload["data"] is None


def test_orchestrator_agent_registry_exposes_current_agents_and_tools() -> None:
    with service_test_client("orchestrator-service") as client:
        response = client.get("/api/v1/agents")

    assert response.status_code == 200
    assert_standard_headers(response.headers)
    registry = {agent["name"]: agent for agent in response.json()["data"]}
    assert {
        "product_tech_agent",
        "finance_order_agent",
        "icp_service_agent",
        "ops_marketing_agent",
        "deep_research_agent",
    } <= set(registry)
    assert "billing.create_invoice" in registry["finance_order_agent"]["allowed_tools"]
    assert "research.generate_report" in registry["deep_research_agent"]["allowed_tools"]


def test_orchestrator_billing_lookup_requires_auth_context(tmp_path: Path) -> None:
    with service_test_client("orchestrator-service", env_overrides=_orchestrator_env(tmp_path)) as client:
        created = client.post(
            "/api/v1/chat/sessions",
            json={"scene": "billing", "title": "QA billing auth context"},
        )
        conversation_id = created.json()["data"]["conversation_id"]
        response = client.post(
            "/api/v1/chat/completions",
            json={
                "conversation_id": conversation_id,
                "message_id": "msg-auth-required",
                "user_input": "帮我查询最近三个月账单",
                "stream": False,
                "scene": "billing",
                "user_profile": {
                    "user_id": "u_qa",
                    "tenant_id": "default",
                    "permissions": [],
                },
            },
        )

    assert created.status_code == 200
    assert response.status_code == 200
    assert_standard_headers(response.headers)
    payload = response.json()["data"]
    tool_call = payload["tool_calls"][0]
    pending_action = payload["pending_user_actions"][0]
    assert payload["status"] == "need_user_input"
    assert payload["finish_reason"] == "need_user_input"
    assert tool_call["status"] == "auth-required"
    assert pending_action["action"] == "collect-auth-context"
    assert "user:billing.read" in pending_action["required_permissions"]
    assert "account_id" in pending_action["missing_auth_context"]


def test_knowledge_bootstrap_and_search_cover_the_starter_catalog(tmp_path: Path) -> None:
    with service_test_client("knowledge-service", env_overrides=_knowledge_env(tmp_path)) as client:
        overview_before = client.get("/api/knowledge/v1/overview")
        bootstrap = client.post("/api/knowledge/v1/catalog:bootstrap")
        search = client.post("/api/knowledge/v1/search", json={"query": "GPU", "topK": 3})
        overview_after = client.get("/api/knowledge/v1/overview")

    assert overview_before.status_code == 200
    assert bootstrap.status_code == 200
    assert search.status_code == 200
    assert overview_after.status_code == 200
    assert_standard_headers(bootstrap.headers)
    assert overview_before.json()["data"]["counts"]["documents"] == 0
    bootstrap_payload = bootstrap.json()["data"]
    assert bootstrap_payload["seededDocuments"] >= 3
    search_payload = search.json()["data"]
    assert search_payload["total"] >= 1
    assert search_payload["results"][0]["chunk"]["documentTitle"] == "GPU 云主机部署检查清单"
    assert overview_after.json()["data"]["counts"]["documents"] >= bootstrap_payload["seededDocuments"]


def test_rag_capabilities_and_degraded_health_reflect_current_baseline() -> None:
    with service_test_client("rag-service") as client:
        capabilities = client.get("/api/rag/v1/capabilities")
        health = client.get("/healthz")

    assert capabilities.status_code == 200
    assert health.status_code == 200
    assert_standard_headers(capabilities.headers)
    capabilities_payload = capabilities.json()["data"]
    assert capabilities_payload["rewrite"] == "keyword-and-synonym"
    assert capabilities_payload["retrieval"] == "knowledge-service-search"
    assert capabilities_payload["cache"] in {"memory-ttl", "redis-ttl-with-memory-fallback"}

    health_payload = health.json()["data"]
    assert health_payload["status"] == "degraded"
    assert health_payload["ready"] is False
    assert health_payload["upstream"]["ready"] is False
    assert health_payload["warnings"]


def test_web_user_and_frontend_sdk_assets_match_current_repo_contract() -> None:
    web_user_package = _load_json("apps/web-user/package.json")
    frontend_sdk_package = _load_json("packages/frontend-sdk/package.json")
    shared_sdk_source = (REPO_ROOT / "apps" / "web-user" / "src" / "shared-sdk.ts").read_text(
        encoding="utf-8"
    )

    assert {"dev", "build", "typecheck", "test:e2e", "docker:build"} <= set(
        web_user_package["scripts"]
    )
    assert {".", "./core", "./web-user", "./web-admin"} <= set(frontend_sdk_package["exports"])
    assert "packages/frontend-sdk/src/core" in shared_sdk_source
    assert "packages/frontend-sdk/src/web-user" in shared_sdk_source
    assert (REPO_ROOT / "apps" / "web-user" / "public" / "runtime-config.js").exists()
    assert (REPO_ROOT / "apps" / "web-user" / "tests" / "e2e" / "mock-api-server.mjs").exists()
