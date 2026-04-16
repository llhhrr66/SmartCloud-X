from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.qa_helpers.service_loader import assert_standard_headers, service_test_client


AUTH_ENV = {
    "SMARTCLOUD_JWT_SECRET": "qa-test-secret",
    "SMARTCLOUD_AUTH_ISSUER": "qa-test-issuer",
    "SMARTCLOUD_AUTH_AUDIENCE": "qa-test-audience",
}


def _assert_structured_error(payload: dict[str, Any], code: int) -> None:
    assert payload["code"] == code
    assert payload["message"]
    assert payload["request_id"]
    assert payload["timestamp"]


def _login_demo_user(tmp_path: Path) -> str:
    with service_test_client(
        "auth-user-service",
        env_overrides={
            **AUTH_ENV,
            "AUTH_USER_SERVICE_DATA_PATH": str(tmp_path / "auth-store.json"),
        },
    ) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "login_type": "password",
                "account": "demo@smartcloud.local",
                "password": "Password123!",
            },
        )
        assert response.status_code == 200
        assert_standard_headers(response.headers)
        return str(response.json()["data"]["access_token"])


def test_marketing_error_envelopes_cover_401_and_409(tmp_path: Path) -> None:
    access_token = _login_demo_user(tmp_path / "auth")
    with service_test_client(
        "marketing-service",
        env_overrides={
            **AUTH_ENV,
            "MARKETING_SERVICE_DATA_PATH": str(tmp_path / "marketing-store.json"),
        },
    ) as client:
        unauthorized = client.get("/api/v1/marketing/campaigns?page=1&page_size=20")
        assert unauthorized.status_code == 401
        assert_standard_headers(unauthorized.headers)
        _assert_structured_error(unauthorized.json(), 4010002)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Idempotency-Key": "qa-marketing-conflict-001",
        }
        first = client.post(
            "/api/v1/marketing/posters",
            headers=headers,
            json={
                "campaign_id": "cmp_gpu_launch_001",
                "theme": "QA baseline",
                "slogan": "initial request",
                "size": "1080x1080",
            },
        )
        assert first.status_code == 202
        assert_standard_headers(first.headers)

        conflict = client.post(
            "/api/v1/marketing/posters",
            headers=headers,
            json={
                "campaign_id": "cmp_gpu_launch_001",
                "theme": "QA baseline changed",
                "slogan": "different body should conflict",
                "size": "1080x1080",
            },
        )
        assert conflict.status_code == 409
        assert_standard_headers(conflict.headers)
        _assert_structured_error(conflict.json(), 4090001)


def test_research_error_envelopes_cover_401_and_409(tmp_path: Path) -> None:
    access_token = _login_demo_user(tmp_path / "auth")
    with service_test_client(
        "research-service",
        env_overrides={
            **AUTH_ENV,
            "RESEARCH_SERVICE_DATA_PATH": str(tmp_path / "research-store.json"),
        },
    ) as client:
        unauthorized = client.get("/api/v1/research/tasks?page=1&page_size=20")
        assert unauthorized.status_code == 401
        assert_standard_headers(unauthorized.headers)
        _assert_structured_error(unauthorized.json(), 4010002)

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Idempotency-Key": "qa-research-conflict-001",
        }
        first = client.post(
            "/api/v1/research/tasks",
            headers=headers,
            json={
                "topic": "QA baseline topic",
                "scope": "first accepted request",
                "depth": "standard",
                "output_format": "markdown",
                "reference_urls": [],
            },
        )
        assert first.status_code == 202
        assert_standard_headers(first.headers)

        conflict = client.post(
            "/api/v1/research/tasks",
            headers=headers,
            json={
                "topic": "QA baseline changed topic",
                "scope": "different body should conflict",
                "depth": "deep",
                "output_format": "pdf",
                "reference_urls": [],
            },
        )
        assert conflict.status_code == 409
        assert_standard_headers(conflict.headers)
        _assert_structured_error(conflict.json(), 4090001)


def test_research_permission_denial_returns_structured_403(tmp_path: Path) -> None:
    with service_test_client(
        "research-service",
        env_overrides={
            **AUTH_ENV,
            "RESEARCH_SERVICE_DATA_PATH": str(tmp_path / "research-store.json"),
        },
    ) as client:
        from app.security import get_token_codec

        get_token_codec.cache_clear()
        access_token = get_token_codec().issue_access_token(
            subject_type="user",
            subject_id="u-forbidden",
            tenant_id="default",
            roles=["user"],
            permissions=["user:marketing.read"],
        ).token

        forbidden = client.get(
            "/api/v1/research/tasks?page=1&page_size=20",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert forbidden.status_code == 403
        assert_standard_headers(forbidden.headers)
        payload = forbidden.json()
        _assert_structured_error(payload, 4030001)
        assert payload["error"]["details"]["missing_permissions"] == ["user:research.read"]


def test_tool_hub_permission_denial_is_audited_as_auth_required(tmp_path: Path) -> None:
    with service_test_client(
        "tool-hub-service",
        env_overrides={
            "AUDIT_STORE_PATH": str(tmp_path / "tool-hub-audit.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "tool-hub-idempotency.json"),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "tool-hub-query-cache.json"),
        },
    ) as client:
        response = client.post(
            "/internal/v1/tools/call",
            headers={"X-Caller-Service": "orchestrator-service"},
            json={
                "trace_id": "trace-ticket-qa-1",
                "conversation_id": "conv-ticket-qa-1",
                "tool_call_id": "tc-ticket-qa-1",
                "tool_name": "ticket.create",
                "operator": {"type": "agent", "id": "Finance_Order_Agent"},
                "user_context": {"user_id": "u-1"},
                "payload": {"subject": "账单异常", "content": "请帮我排查"},
                "idempotency_key": "tool-ticket-qa-1",
                "operation": "execute",
            },
        )

        assert response.status_code == 200
        assert_standard_headers(response.headers)
        payload = response.json()
        assert payload["success"] is False
        assert payload["code"] == 4030001
        assert payload["status"] == "auth-required"
        assert payload["error"]["details"]["missing_context"] == ["permission:user:ticket.write"]
        assert payload["user_action_hint"]["action"] == "collect-auth-context"
        assert payload["user_action_hint"]["required_permissions"] == ["user:ticket.write"]

        audit = client.get("/api/v1/tool-calls/tc-ticket-qa-1")
        assert audit.status_code == 200
        assert_standard_headers(audit.headers)
        audit_payload = audit.json()["data"]
        assert audit_payload["status"] == "auth-required"
        assert audit_payload["code"] == 4030001
        assert audit_payload["error"]["details"]["missing_context"] == ["permission:user:ticket.write"]
        assert audit_payload["user_action_hint"]["required_permissions"] == ["user:ticket.write"]


def test_tool_hub_timeout_returns_retryable_timeout_and_audits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with service_test_client(
        "tool-hub-service",
        env_overrides={
            "BUSINESS_TOOLS_TRANSPORT": "http",
            "BUSINESS_TOOLS_URL": "http://127.0.0.1:9",
            "AUDIT_STORE_PATH": str(tmp_path / "tool-hub-timeout-audit.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "tool-hub-timeout-idempotency.json"),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "tool-hub-timeout-query-cache.json"),
        },
    ) as client:
        from app.api.routes import tools as tools_routes

        definition = tools_routes._registry.get_tool("billing.query_statement").definition
        monkeypatch.setattr(
            tools_routes._business_tools_client,
            "describe_tool",
            lambda tool_name: definition if tool_name == "billing.query_statement" else None,
        )

        def raise_timeout(*_args, **_kwargs):
            raise httpx.ReadTimeout("qa timeout", request=None)

        monkeypatch.setattr(tools_routes._business_tools_client, "_invoke_via_http", raise_timeout)

        response = client.post(
            "/internal/v1/tools/call",
            headers={"X-Caller-Service": "orchestrator-service"},
            json={
                "trace_id": "trace-timeout-qa-1",
                "conversation_id": "conv-timeout-qa-1",
                "tool_call_id": "tc-timeout-qa-1",
                "tool_name": "billing.query_statement",
                "operator": {"type": "agent", "id": "Finance_Order_Agent"},
                "user_context": {
                    "user_id": "u-1",
                    "account_id": "acct-1",
                    "permissions": ["user:billing.read"],
                },
                "payload": {"range": "this_month"},
                "idempotency_key": "tool-timeout-qa-1",
                "operation": "execute",
            },
        )

        assert response.status_code == 200
        assert_standard_headers(response.headers)
        payload = response.json()
        assert payload["success"] is False
        assert payload["code"] == 5003002
        assert payload["status"] == "timeout"
        assert payload["summary"] == "downstream timeout"
        assert payload["message"] == "downstream timeout"
        assert payload["error"]["retryable"] is True
        assert payload["error"]["details"]["exception"] == "ReadTimeout"
        assert payload["attempts"] >= 1

        audit = client.get("/api/v1/tool-calls/tc-timeout-qa-1")
        assert audit.status_code == 200
        assert_standard_headers(audit.headers)
        audit_payload = audit.json()["data"]
        assert audit_payload["status"] == "timeout"
        assert audit_payload["success"] is False
        assert audit_payload["code"] == 5003002
        assert audit_payload["retryable"] is True
        assert audit_payload["error"]["details"]["exception"] == "ReadTimeout"


def test_rag_answer_handles_empty_and_degraded_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    with service_test_client("rag-service") as client:
        from app.api.routes import rag as rag_routes
        from app.services import knowledge_client as knowledge_client_module
        from app.services.query_rewriter import QueryRewriter
        from app.services.retrieval import RetrievalService

        async def empty_search(self, payload, knowledge_client, upstream_headers, cache_service=None):
            return self.rewrite_query(payload.query), []

        monkeypatch.setattr(rag_routes, "get_knowledge_client", lambda: object())
        monkeypatch.setattr(rag_routes, "get_retrieval_service", lambda: RetrievalService(QueryRewriter()))
        monkeypatch.setattr(RetrievalService, "search_candidates", empty_search)

        response = client.post(
            "/api/rag/v1/answer",
            headers={"X-Request-Id": "qa-rag-empty-1"},
            json={"query": "未知问题", "topK": 3},
        )

        assert response.status_code == 200
        assert_standard_headers(response.headers)
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["degraded"] is False
        assert "没有检索到可引用知识" in payload["data"]["answer"]
        assert any("未检索到匹配知识" in note for note in payload["data"]["coverageNotes"])

        async def broken_search(*args, **kwargs):
            raise knowledge_client_module.httpx.ReadTimeout("timed out", request=None)

        monkeypatch.setattr(RetrievalService, "search_candidates", broken_search)

        degraded = client.post(
            "/api/rag/v1/answer",
            headers={"X-Request-Id": "qa-rag-timeout-1"},
            json={"query": "GPU 部署", "topK": 3},
        )

        assert degraded.status_code == 200
        assert_standard_headers(degraded.headers)
        degraded_payload = degraded.json()
        assert degraded_payload["success"] is True
        assert degraded_payload["data"]["degraded"] is True
        assert "没有检索到可引用知识" in degraded_payload["data"]["answer"]
        assert degraded_payload["data"]["coverageNotes"][0] == "knowledge-service unavailable: ReadTimeout"
