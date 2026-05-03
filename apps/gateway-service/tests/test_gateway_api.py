from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from app.services.logging import logger, parse_log_payload


REPO_ROOT = Path(__file__).resolve().parents[3]
GATEWAY_MAIN_PATH = REPO_ROOT / "apps" / "gateway-service" / "app" / "main.py"
GATEWAY_SERVICE_ROOT = REPO_ROOT / "apps" / "gateway-service"


def _load_gateway_module():
    assert GATEWAY_MAIN_PATH.exists(), "gateway-service app/main.py is missing"
    module_name = "smartcloud_gateway_service_app_main_test"
    for loaded_name in list(sys.modules):
        if loaded_name == "app" or loaded_name.startswith("app."):
            sys.modules.pop(loaded_name, None)
    if str(GATEWAY_SERVICE_ROOT) in sys.path:
        sys.path.remove(str(GATEWAY_SERVICE_ROOT))
    sys.path.insert(0, str(GATEWAY_SERVICE_ROOT))
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, GATEWAY_MAIN_PATH)
    assert spec and spec.loader, "gateway-service app/main.py could not be loaded"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_transport(
    routes: dict[tuple[str, str], Any],
    captured: list[dict[str, Any]],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8") if request.content else ""
        captured.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query.decode("utf-8"),
                "headers": dict(request.headers),
                "body": body,
            }
        )
        route = routes.get((request.method, request.url.path))
        if route is None:
            return httpx.Response(status_code=404, json={"detail": "not configured"})
        if callable(route):
            return route(request)
        status_code, payload, headers = route
        if isinstance(payload, bytes):
            return httpx.Response(status_code=status_code, content=payload, headers=headers)
        return httpx.Response(status_code=status_code, json=payload, headers=headers)

    return httpx.MockTransport(handler)


def _build_test_client(
    *,
    auth_routes: dict[tuple[str, str], Any] | None = None,
    orchestrator_routes: dict[tuple[str, str], Any] | None = None,
    tool_hub_routes: dict[tuple[str, str], Any] | None = None,
    business_tools_routes: dict[tuple[str, str], Any] | None = None,
    knowledge_routes: dict[tuple[str, str], Any] | None = None,
    rag_routes: dict[tuple[str, str], Any] | None = None,
    marketing_routes: dict[tuple[str, str], Any] | None = None,
    research_routes: dict[tuple[str, str], Any] | None = None,
    settings_overrides: dict[str, Any] | None = None,
) -> tuple[TestClient, dict[str, list[dict[str, Any]]]]:
    module = _load_gateway_module()

    captures: dict[str, list[dict[str, Any]]] = {
        "auth-user-service": [],
        "orchestrator-service": [],
        "tool-hub-service": [],
        "business-tools-service": [],
        "knowledge-service": [],
        "rag-service": [],
        "marketing-service": [],
        "research-service": [],
    }

    temp_gateway_store = Path(tempfile.mkdtemp(prefix="smartcloud-gateway-test-")) / "gateway-store.json"
    settings_kwargs = {
        "cors_allowed_origins": ["http://localhost:5173"],
        "auth_user_service_base_url": "http://auth-user-service",
        "orchestrator_service_base_url": "http://orchestrator-service",
        "tool_hub_service_base_url": "http://tool-hub-service",
        "business_tools_service_base_url": "http://business-tools-service",
        "knowledge_service_base_url": "http://knowledge-service",
        "rag_service_base_url": "http://rag-service",
        "marketing_service_base_url": "http://marketing-service",
        "research_service_base_url": "http://research-service",
        "gateway_store_path": str(temp_gateway_store),
        "rate_limit_requests": 100,
        "rate_limit_window_seconds": 60,
    }
    if settings_overrides:
        settings_kwargs.update(settings_overrides)
    settings = module.GatewaySettings(**settings_kwargs)

    app = module.create_app(
        settings=settings,
        upstream_transports={
            "auth-user-service": _make_transport(auth_routes or {}, captures["auth-user-service"]),
            "orchestrator-service": _make_transport(orchestrator_routes or {}, captures["orchestrator-service"]),
            "tool-hub-service": _make_transport(tool_hub_routes or {}, captures["tool-hub-service"]),
            "business-tools-service": _make_transport(
                business_tools_routes or {}, captures["business-tools-service"]
            ),
            "knowledge-service": _make_transport(knowledge_routes or {}, captures["knowledge-service"]),
            "rag-service": _make_transport(rag_routes or {}, captures["rag-service"]),
            "marketing-service": _make_transport(marketing_routes or {}, captures["marketing-service"]),
            "research-service": _make_transport(research_routes or {}, captures["research-service"]),
        },
    )
    return TestClient(app), captures


def _auth_internal_validate_user() -> tuple[int, dict[str, Any], dict[str, str]]:
    return (
        200,
        {
            "success": True,
            "requestId": "req-auth-validate",
            "data": {
                "subject_type": "user",
                "subject_id": "u-1",
                "tenant_id": "tenant-a",
                "roles": ["end_user"],
                "permissions": [
                    "user:chat.use",
                    "user:billing.read",
                    "user:order.read",
                    "user:ticket.read",
                    "user:ticket.write",
                    "user:icp.read",
                    "user:icp.write",
                    "user:marketing.read",
                    "user:marketing.write",
                    "user:research.read",
                    "user:research.write",
                ],
                "expired_at": "2026-04-18T00:00:00Z",
            },
        },
        {},
    )


def _auth_internal_validate_admin() -> tuple[int, dict[str, Any], dict[str, str]]:
    return (
        200,
        {
            "success": True,
            "requestId": "req-auth-validate-admin",
            "data": {
                "subject_type": "admin",
                "subject_id": "admin-1",
                "tenant_id": "tenant-a",
                "roles": ["admin"],
                "permissions": ["admin:kb.read", "admin:kb.write", "admin:job.read", "admin:ops.read"],
                "expired_at": "2026-04-18T00:00:00Z",
            },
        },
        {},
    )


def test_healthz_and_readyz_summarize_upstreams() -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("GET", "/healthz"): (200, {"status": "ok"}, {}),
            ("GET", "/readyz"): (200, {"status": "ready", "service": "auth-user-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        orchestrator_routes={
            ("GET", "/healthz"): (200, {"status": "ok"}, {}),
            ("GET", "/readyz"): (200, {"status": "ready"}, {}),
        },
        business_tools_routes={
            ("GET", "/healthz"): (200, {"status": "ok"}, {}),
            ("GET", "/readyz"): (200, {"status": "ready"}, {}),
        },
        knowledge_routes={
            ("GET", "/healthz"): (200, {"status": "ok", "ready": True}, {}),
            ("GET", "/readyz"): (200, {"status": "ready", "service": "knowledge-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        rag_routes={
            ("GET", "/healthz"): (200, {"status": "ok", "ready": True}, {}),
            ("GET", "/readyz"): (200, {"status": "ready", "service": "rag-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        marketing_routes={
            ("GET", "/healthz"): (200, {"status": "ok"}, {}),
            ("GET", "/readyz"): (200, {"status": "ready", "service": "marketing-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        research_routes={
            ("GET", "/healthz"): (503, {"status": "not_ready"}, {}),
            ("GET", "/readyz"): (503, {"status": "not_ready", "service": "research-service", "not_ready_components": ["runtime"], "runtime": {}}, {}),
        },
    )

    health = client.get("/healthz")
    assert health.status_code == 200
    payload = health.json()["data"]
    assert payload["service"] == "gateway-service"
    assert payload["upstreams"]["auth-user-service"]["status"] == "ok"
    assert payload["upstreams"]["research-service"]["status"] == "not_ready"

    ready = client.get("/readyz")
    assert ready.status_code == 503
    ready_payload = ready.json()["data"]
    assert "research-service" in ready_payload["not_ready_upstreams"]
    assert ready_payload["upstreams"]["orchestrator-service"]["contract"] == "readyz"
    assert ready_payload["upstreams"]["orchestrator-service"]["status"] == "ready"
    assert ready_payload["upstreams"]["auth-user-service"]["contract"] == "readyz"
    assert ready_payload["upstreams"]["auth-user-service"]["status"] == "ready"
    assert ready_payload["upstreams"]["auth-user-service"]["http_status"] == 200
    assert ready_payload["upstreams"]["research-service"]["contract"] == "readyz"
    assert ready_payload["upstreams"]["research-service"]["status"] == "not_ready"




def test_readyz_query_params_are_ignored_when_upstreams_are_ready() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "auth-user-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        orchestrator_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "orchestrator-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        tool_hub_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "tool-hub-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        business_tools_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "business-tools-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        knowledge_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "knowledge-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        rag_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "rag-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        marketing_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "marketing-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        research_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "research-service", "not_ready_components": [], "runtime": {}}, {}),
        },
    )

    response = client.get("/readyz?probe=1&unused=yes")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "ready"
    assert payload["not_ready_upstreams"] == []
    for service_name in (
        "auth-user-service",
        "orchestrator-service",
        "tool-hub-service",
        "business-tools-service",
        "knowledge-service",
        "rag-service",
        "marketing-service",
        "research-service",
    ):
        assert payload["upstreams"][service_name]["contract"] == "readyz"


def test_readyz_marks_unreachable_readyz_as_not_ready_even_when_other_upstreams_are_ready() -> None:
    client, _ = _build_test_client(
        auth_routes={},
        orchestrator_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "orchestrator-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        tool_hub_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "tool-hub-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        business_tools_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "business-tools-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        knowledge_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "knowledge-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        rag_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "rag-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        marketing_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "marketing-service", "not_ready_components": [], "runtime": {}}, {}),
        },
        research_routes={
            ("GET", "/readyz"): (200, {"status": "ready", "service": "research-service", "not_ready_components": [], "runtime": {}}, {}),
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()["data"]
    assert payload["status"] == "not_ready"
    assert payload["not_ready_upstreams"] == ["auth-user-service"]
    assert payload["upstreams"]["auth-user-service"]["contract"] == "readyz"
    assert payload["upstreams"]["auth-user-service"]["status"] == "not_ready"
    assert payload["upstreams"]["auth-user-service"]["http_status"] == 404
    assert payload["upstreams"]["auth-user-service"]["payload"] == {"detail": "not configured"}


def test_auth_login_is_proxied_and_request_headers_are_forwarded() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("POST", "/api/v1/auth/login"): (
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "request_id": "upstream-login",
                    "timestamp": 1776300000000,
                    "data": {
                        "access_token": "user-access-token",
                        "refresh_token": "user-r...oken",
                        "expires_in": 7200,
                        "user": {
                            "user_id": "u-1",
                            "tenant_id": "tenant-a",
                            "name": "Demo User",
                            "email": "demo@smartcloud.local",
                            "mobile": "13800000001",
                            "locale": "zh-CN",
                            "time_zone": "Asia/Shanghai",
                            "permissions": ["user:chat.use"],
                        },
                    },
                },
                {"X-Upstream": "auth-user-service"},
            )
        }
    )

    response = client.post(
        "/api/v1/auth/login",
        headers={"X-Request-Id": "req-login", "X-Trace-Id": "trace-login"},
        json={
            "login_type": "password",
            "account": "demo@smartcloud.local",
            "password": "***",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["access_token"] == "user-access-token"
    assert response.headers["X-Upstream"] == "auth-user-service"
    forwarded = captures["auth-user-service"][0]
    assert forwarded["headers"]["x-request-id"] == "req-login"
    assert forwarded["headers"]["x-trace-id"] == "trace-login"


def test_gateway_missing_bearer_token_returns_canonical_401() -> None:
    client, _ = _build_test_client()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    payload = response.json()
    assert payload["detail"]["code"] == 4010002
    assert payload["detail"]["message"] == "missing bearer token"


def test_gateway_missing_admin_permission_returns_canonical_403() -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/admin/auth/me"): (
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "request_id": "req-admin-me",
                    "timestamp": 1776326400000,
                    "data": {
                        "admin_id": "admin-1",
                        "roles": ["admin"],
                        "permissions": ["admin:kb.read"],
                    },
                },
                {},
            ),
        }
    )

    response = client.get(
        "/api/v1/admin/dashboard/summary",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["detail"]["code"] == 4030001
    assert payload["detail"]["message"] == "missing permission: admin:ops.read"




def test_chat_completions_creates_conversation_when_missing_for_non_stream() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/api/v1/chat/sessions"): (
                200,
                {
                    "success": True,
                    "requestId": "req-session-create",
                    "data": {"conversation_id": "conv-auto-1"},
                },
                {},
            ),
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                {"status": "success", "conversation_id": "conv-auto-1"},
                {},
            ),
        },
    )

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "user_input": "你好",
            "stream": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["conversation_id"] == "conv-auto-1"
    assert len(captures["orchestrator-service"]) == 2
    session_request = captures["orchestrator-service"][0]
    chat_request = captures["orchestrator-service"][1]
    assert session_request["path"] == "/api/v1/chat/sessions"
    assert session_request["headers"]["content-type"] == "application/json"
    forwarded = json.loads(chat_request["body"])
    assert forwarded["chat_request"]["conversation_id"] == "conv-auto-1"
    assert forwarded["chat_request"]["stream"] is False



def test_chat_stream_creates_conversation_when_missing() -> None:
    sse_body = (
        'event: meta\n'
        'data: {"conversation_id":"conv-auto-stream-1","message_id":"msg-1"}\n\n'
        'event: done\n'
        'data: {"finish_reason":"stop"}\n\n'
    ).encode("utf-8")
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/api/v1/chat/sessions"): (
                200,
                {
                    "success": True,
                    "requestId": "req-session-create-stream",
                    "data": {"conversation_id": "conv-auto-stream-1"},
                },
                {},
            ),
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                sse_body,
                {"content-type": "text/event-stream"},
            ),
        },
    )

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "user_input": "stream me",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: done" in body
    assert len(captures["orchestrator-service"]) == 2
    session_request = captures["orchestrator-service"][0]
    chat_request = captures["orchestrator-service"][1]
    assert session_request["path"] == "/api/v1/chat/sessions"
    assert session_request["headers"]["content-type"] == "application/json"
    forwarded = json.loads(chat_request["body"])
    assert forwarded["chat_request"]["conversation_id"] == "conv-auto-stream-1"
    assert forwarded["chat_request"]["stream"] is True




def test_chat_completions_creates_conversation_when_missing_for_retrieval_payload() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/api/v1/chat/sessions"): (
                200,
                {
                    "success": True,
                    "requestId": "req-session-create-rag",
                    "data": {"conversation_id": "conv-auto-rag-1"},
                },
                {},
            ),
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                {"status": "success", "conversation_id": "conv-auto-rag-1", "citations": []},
                {},
            ),
        },
    )

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "user_input": "请帮我查一下 SmartCloud-X 的检索链路。",
            "scene": "technical_support",
            "stream": False,
            "context": {"channel": "web", "locale": "zh-CN"},
            "options": {"use_rag": True, "max_history_turns": 6},
        },
    )

    assert response.status_code == 200
    assert len(captures["orchestrator-service"]) == 2
    session_request = captures["orchestrator-service"][0]
    chat_request = captures["orchestrator-service"][1]
    assert session_request["path"] == "/api/v1/chat/sessions"
    assert session_request["headers"]["content-type"] == "application/json"
    session_payload = json.loads(session_request["body"])
    assert session_payload == {
        "scene": "technical_support",
        "initial_context": {"channel": "web", "locale": "zh-CN"},
    }
    forwarded = json.loads(chat_request["body"])
    assert forwarded["chat_request"]["scene"] == "technical_support"
    assert forwarded["chat_request"]["conversation_id"] == "conv-auto-rag-1"
    assert forwarded["chat_request"]["scene"] == "technical_support"
    assert forwarded["chat_request"]["context"]["channel"] == "web"
    assert forwarded["chat_request"]["context"]["user_id"] == "u-1"
    assert forwarded["chat_request"]["options"]["use_rag"] is True


def test_chat_completions_normalize_legacy_general_scene() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/api/v1/chat/sessions"): (
                200,
                {
                    "success": True,
                    "requestId": "req-session-create-general",
                    "data": {"conversation_id": "conv-auto-general-1"},
                },
                {},
            ),
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                {"status": "success", "conversation_id": "conv-auto-general-1"},
                {},
            ),
        },
    )

    response = client.post(
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "user_input": "你好",
            "scene": "general",
            "stream": False,
        },
    )

    assert response.status_code == 200
    session_request = captures["orchestrator-service"][0]
    chat_request = captures["orchestrator-service"][1]
    assert json.loads(session_request["body"])["scene"] == "customer_service"
    assert json.loads(chat_request["body"])["chat_request"]["scene"] == "customer_service"



def test_chat_stream_forwards_stream_flag_to_internal_orchestrator_request() -> None:
    sse_body = (
        'event: meta\n'
        'data: {"conversation_id":"conv-1","message_id":"msg-1"}\n\n'
        'event: done\n'
        'data: {"finish_reason":"stop"}\n\n'
    ).encode("utf-8")
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                sse_body,
                {"content-type": "text/event-stream"},
            )
        },
    )

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "conversation_id": "conv-1",
            "user_input": "stream me",
            "stream": True,
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in body
    forwarded = json.loads(captures["orchestrator-service"][0]["body"])
    assert forwarded["chat_request"]["stream"] is True




def test_chat_stream_returns_sse_even_when_accept_header_present() -> None:
    sse_body = (
        'event: meta\n'
        'data: {"conversation_id":"conv-1","message_id":"msg-1"}\n\n'
        'event: message.completed\n'
        'data: {"finish_reason":"stop"}\n\n'
    ).encode("utf-8")
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                sse_body,
                {"content-type": "text/event-stream; charset=utf-8"},
            )
        },
    )

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token", "Accept": "text/event-stream"},
        json={
            "conversation_id": "conv-1",
            "message_id": "probe-msg-1",
            "user_input": "帮我查本月账单",
            "stream": True,
            "scene": "billing",
            "attachments": [],
            "context": {
                "user_id": "u-1",
                "tenant_id": "tenant-a",
                "channel": "web",
                "locale": "zh-CN",
            },
            "options": {"use_rag": True, "use_tools": True, "max_history_turns": 10},
        },
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: message.completed" in body
    forwarded = json.loads(captures["orchestrator-service"][0]["body"])
    assert forwarded["chat_request"]["stream"] is True


def test_chat_stream_caches_camel_case_real_citation_entries_only() -> None:
    sse_body = (
        'event: citation.delta\n'
        'data: {"id":"cite-camel-1","backendUsed":"knowledge-service-search","sourceId":"src-1","docId":"doc-1","chunkId":"chunk-1","title":"Camel Case Citation"}\n\n'
        'event: citation.delta\n'
        'data: {"id":"cite-camel-2"}\n\n'
        'event: citation.delta\n'
        'data: {"citation_id":"cite-snake-1","uri":"kb://technical_support/doc-2#chunk-2","title":"Snake Case Citation"}\n\n'
        'event: citation.delta\n'
        'data: {"citation_id":"cite-placeholder","uri":"baseline://router-retrieval","title":"Placeholder Citation"}\n\n'
        'event: citation.delta\n'
        'data: {"citation_id":"cite-empty","backendUsed":"","sourceId":"","docId":"","chunkId":"","uri":""}\n\n'
        'event: message.completed\n'
        'data: {"finish_reason":"stop"}\n\n'
    ).encode("utf-8")
    client, _ = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                sse_body,
                {"content-type": "text/event-stream"},
            )
        },
    )

    with client.stream(
        "POST",
        "/api/v1/chat/completions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "messages": [{"role": "user", "content": "请给我真实 citation"}],
            "stream": True,
        },
    ) as response:
        assert response.status_code == 200
        _ = "".join(chunk for chunk in response.iter_text())

    camel_case_citation = client.get(
        "/api/v1/citations/cite-camel-1",
        headers={"Authorization": "Bearer user-token"},
    )
    assert camel_case_citation.status_code == 200
    assert camel_case_citation.json()["data"]["id"] == "cite-camel-1"
    assert camel_case_citation.json()["data"]["backendUsed"] == "knowledge-service-search"

    snake_case_citation = client.get(
        "/api/v1/citations/cite-snake-1",
        headers={"Authorization": "Bearer user-token"},
    )
    assert snake_case_citation.status_code == 200
    assert snake_case_citation.json()["data"]["citation_id"] == "cite-snake-1"

    id_only_citation = client.get(
        "/api/v1/citations/cite-camel-2",
        headers={"Authorization": "Bearer user-token"},
    )
    assert id_only_citation.status_code == 404

    placeholder_citation = client.get(
        "/api/v1/citations/cite-placeholder",
        headers={"Authorization": "Bearer user-token"},
    )
    assert placeholder_citation.status_code == 404

    empty_source_citation = client.get(
        "/api/v1/citations/cite-empty",
        headers={"Authorization": "Bearer user-token"},
    )
    assert empty_source_citation.status_code == 404



def test_chat_completions_rejects_non_object_body_with_canonical_4001001() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                {"status": "unexpected"},
                {},
            )
        },
    )

    response = client.post(
        "/api/v1/chat/completions",
        headers={
            "Authorization": "Bearer user-token",
            "Content-Type": "application/json",
        },
        content=json.dumps([{"role": "user", "content": "not-an-object"}]),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["message"] == "request validation failed"
    assert payload["error"]["type"] == "validation_error"
    assert payload["error"]["field"] == "body"
    assert payload["error"]["reason"] == "must be an object"
    assert captures["orchestrator-service"] == []


def test_stream_logging_emits_lifecycle_events_without_payload_leak(caplog) -> None:
    sse_body = (
        b'event: message.started\n'
        b'data: {"conversation_id":"conv-2"}\n\n'
        b'event: citation.delta\n'
        b'data: {"citation_id":"cite-2","source_id":"src-2","doc_id":"doc-2","snippet":"sensitive payload should not be logged"}\n\n'
        b'event: message.completed\n'
        b'data: {"finish_reason":"stop"}\n\n'
    )
    client, _ = _build_test_client(
        auth_routes={("GET", "/api/v1/auth/me"): _auth_internal_validate_user()},
        orchestrator_routes={
            ("POST", "/internal/v1/orchestrator/chat"): (
                200,
                sse_body,
                {"content-type": "text/event-stream"},
            )
        },
    )

    original_propagate = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level("INFO", logger=logger.name):
            with client.stream(
                "POST",
                "/api/v1/chat/completions",
                headers={"Authorization": "Bearer user-token", "X-Request-Id": "req-stream", "X-Trace-Id": "trace-stream"},
                json={"messages": [{"role": "user", "content": "stream me"}], "stream": True},
            ) as response:
                body = "".join(response.iter_text())
    finally:
        logger.propagate = original_propagate

    assert response.status_code == 200
    assert "citation.delta" in body
    payloads = [payload for record in caplog.records if (payload := parse_log_payload(record.getMessage()))]
    started = next(payload for payload in payloads if payload.get("event") == "stream_started")
    completed = next(payload for payload in payloads if payload.get("event") == "stream_completed")
    assert started["request_id"] == "req-stream"
    assert started["trace_id"] == "trace-stream"
    assert started["upstream_service"] == "orchestrator-service"
    assert completed["event_count"] == 3
    assert completed["citation_cache_count"] == 1
    assert completed["total_bytes"] > 0
    assert all("sensitive payload should not be logged" not in record.getMessage() for record in caplog.records)


def test_admin_header_forwarding_supports_utf8_repair() -> None:
    module = _load_gateway_module()
    repaired = module.decode_header_value("æ¹éå¯¼å¥ GPU äº§åææ¡£")
    assert repaired == "批量导入 GPU 产品文档"


def test_admin_knowledge_base_create_is_proxied_with_operator_reason() -> None:
    operator_reason = "批量导入 GPU 产品文档"
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/admin/auth/me"): _auth_internal_validate_admin(),
        },
        knowledge_routes={
            ("POST", "/api/v1/admin/knowledge-bases"): (
                201,
                {
                    "success": True,
                    "requestId": "kb-create",
                    "data": {
                        "id": "kb-live-001",
                        "name": "GPU 产品知识库",
                        "status": "ready",
                    },
                },
                {"X-KB-Upstream": "knowledge-service"},
            )
        },
    )

    response = client.post(
        "/api/v1/admin/knowledge-bases",
        headers={
            "Authorization": "Bearer admin-token",
            "X-Operator-Reason": b"\xe6\x89\xb9\xe9\x87\x8f\xe5\xaf\xbc\xe5\x85\xa5 GPU \xe4\xba\xa7\xe5\x93\x81\xe6\x96\x87\xe6\xa1\xa3",
        },
        json={"name": "GPU 产品知识库"},
    )

    assert response.status_code == 201
    assert response.json()["data"]["id"] == "kb-live-001"
    assert response.headers["X-KB-Upstream"] == "knowledge-service"
    forwarded = captures["knowledge-service"][0]
    assert forwarded["headers"]["x-operator-reason"] == operator_reason


def test_orders_and_refunds_bff_read_through_and_cache_business_tool_results() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        business_tools_routes={
            ("POST", "/internal/v1/execute/order.query_order"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "order detail",
                    "result": {
                        "order_no": "ord_live_001",
                        "order_status": "paid",
                        "paid_amount": 1288.32,
                        "currency": "CNY",
                        "refund_status": "not_requested",
                        "invoice_status": "ready",
                    },
                    "data": {
                        "order_no": "ord_live_001",
                        "order_status": "paid",
                        "paid_amount": 1288.32,
                        "currency": "CNY",
                        "refund_status": "not_requested",
                        "invoice_status": "ready",
                    },
                },
                {},
            ),
            ("POST", "/internal/v1/execute/order.create_refund"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "refund created",
                    "result": {
                        "refund_no": "refund_ord_live_001",
                        "status": "processing",
                        "requested_amount": 1288.32,
                    },
                    "data": {
                        "refund_no": "refund_ord_live_001",
                        "status": "processing",
                        "requested_amount": 1288.32,
                    },
                },
                {},
            ),
        },
    )

    order_detail = client.get(
        "/api/v1/orders/ord_live_001",
        headers={"Authorization": "Bearer user-token"},
    )
    assert order_detail.status_code == 200
    detail_payload = order_detail.json()["data"]
    assert detail_payload["order"]["order_no"] == "ord_live_001"
    assert detail_payload["order"]["status"] == "paid"

    cached_orders = client.get(
        "/api/v1/orders",
        headers={"Authorization": "Bearer user-token"},
    )
    assert cached_orders.status_code == 200
    orders_payload = cached_orders.json()["data"]
    assert orders_payload["items"][0]["order_no"] == "ord_live_001"

    create_refund = client.post(
        "/api/v1/orders/ord_live_001/refunds",
        headers={"Authorization": "Bearer user-token"},
        json={"reason": "业务暂不需要，申请退款", "amount": "1288.32", "attachments": []},
    )
    assert create_refund.status_code == 200
    refund_payload = create_refund.json()["data"]
    assert refund_payload["refund_no"] == "refund_ord_live_001"
    assert refund_payload["status"] == "processing"

    refunds = client.get(
        "/api/v1/refunds",
        headers={"Authorization": "Bearer user-token"},
    )
    assert refunds.status_code == 200
    refund_list = refunds.json()["data"]["items"]
    assert refund_list[0]["refund_no"] == "refund_ord_live_001"

    assert captures["business-tools-service"][0]["path"] == "/internal/v1/execute/order.query_order"
    refund_call_body = json.loads(captures["business-tools-service"][1]["body"])
    assert refund_call_body["payload"]["order_no"] == "ord_live_001"
    assert refund_call_body["subject"]["account_id"] == "u-1"


def test_file_upload_lifecycle_and_report_file_lookup() -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        }
    )

    upload_policy = client.post(
        "/api/v1/files/upload-policy",
        headers={"Authorization": "Bearer user-token"},
        json={
            "file_name": "gpu-checklist.pdf",
            "size": 1024,
            "mime_type": "application/pdf",
            "biz_type": "support_attachment",
        },
    )
    assert upload_policy.status_code == 200
    policy_payload = upload_policy.json()["data"]
    assert policy_payload["upload_url"].endswith(f"/uploads/{policy_payload['file_id']}")

    file_complete = client.post(
        "/api/v1/files/complete",
        headers={"Authorization": "Bearer user-token"},
        json={
            "file_id": policy_payload["file_id"],
            "object_key": policy_payload["object_key"],
            "size": 1024,
        },
    )
    assert file_complete.status_code == 200
    file_payload = file_complete.json()["data"]
    assert file_payload["status"] == "ready"

    file_detail = client.get(
        f"/api/v1/files/{policy_payload['file_id']}",
        headers={"Authorization": "Bearer user-token"},
    )
    assert file_detail.status_code == 200
    assert file_detail.json()["data"]["download_url"].endswith(policy_payload["file_id"])

    report_detail = client.get(
        "/api/v1/files/report-task-001",
        headers={"Authorization": "Bearer user-token"},
    )
    assert report_detail.status_code == 200
    assert report_detail.json()["data"]["file_name"] == "report-task-001.md"


def test_create_session_normalizes_legacy_general_scene() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        orchestrator_routes={
            ("POST", "/api/v1/chat/sessions"): (
                200,
                {
                    "success": True,
                    "requestId": "req-create-session-general",
                    "data": {
                        "conversation_id": "conv-general-1",
                        "title": "客服助手 会话",
                        "scene": "customer_service",
                        "status": "active",
                    },
                },
                {},
            ),
        },
    )

    response = client.post(
        "/api/v1/chat/sessions",
        headers={"Authorization": "Bearer user-token"},
        json={
            "scene": "general",
            "title": "客服助手 会话",
            "initial_context": "我想咨询通用问题",
        },
    )

    assert response.status_code == 200
    forwarded = captures["orchestrator-service"][0]
    payload = json.loads(forwarded["body"])
    assert payload["scene"] == "customer_service"
    assert payload["initial_context"] == {"history_summary": "我想咨询通用问题"}



def test_admin_dashboard_summary_aggregates_conversation_and_upstream_status() -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/admin/auth/me"): _auth_internal_validate_admin(),
        },
        orchestrator_routes={
            ("GET", "/healthz"): (200, {"status": "ok"}, {}),
            ("GET", "/readyz"): (200, {"status": "ready"}, {}),
            ("GET", "/api/v1/chat/sessions"): (
                200,
                {
                    "success": True,
                    "requestId": "req-sessions",
                    "data": {
                        "total": 12,
                        "items": [],
                    },
                },
                {},
            ),
        },
        knowledge_routes={
            ("GET", "/healthz"): (503, {"status": "degraded"}, {}),
        },
        rag_routes={
            ("GET", "/healthz"): (200, {"status": "ok"}, {}),
        },
    )

    response = client.get(
        "/api/v1/admin/dashboard/summary",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["conversation_count"] == 12
    assert payload["error_count"] == 1
    assert payload["active_alert_count"] == 1
    assert payload["p95_latency_ms"] >= 0


def test_marketing_and_research_routes_are_proxied_for_live_user_paths() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        marketing_routes={
            ("GET", "/api/v1/marketing/campaigns"): (
                200,
                {
                    "success": True,
                    "requestId": "req-campaigns",
                    "data": {
                        "items": [
                            {
                                "campaign_id": "camp-1",
                                "campaign_name": "春季算力活动",
                                "status": "active",
                            }
                        ]
                    },
                },
                {},
            )
        },
        research_routes={
            ("POST", "/api/v1/research/tasks"): (
                202,
                {
                    "success": True,
                    "requestId": "req-research-create",
                    "data": {"task_id": "task-1", "status": "queued"},
                },
                {},
            ),
            ("GET", "/api/v1/research/tasks"): (
                200,
                {
                    "success": True,
                    "requestId": "req-research-list",
                    "data": {"items": [{"task_id": "task-1", "status": "queued"}]},
                },
                {},
            ),
        },
    )

    campaigns = client.get(
        "/api/v1/marketing/campaigns",
        headers={"Authorization": "Bearer user-token"},
    )
    assert campaigns.status_code == 200
    assert campaigns.json()["data"]["items"][0]["campaign_id"] == "camp-1"

    create_task = client.post(
        "/api/v1/research/tasks",
        headers={"Authorization": "Bearer user-token"},
        json={
            "topic": "GPU 行业趋势",
            "scope": "global",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": ["https://example.com/a"],
        },
    )
    assert create_task.status_code == 202
    assert create_task.json()["data"]["task_id"] == "task-1"

    list_tasks = client.get(
        "/api/v1/research/tasks",
        headers={"Authorization": "Bearer user-token"},
    )
    assert list_tasks.status_code == 200
    assert list_tasks.json()["data"]["items"][0]["task_id"] == "task-1"

    captured_research = captures["research-service"]
    assert captured_research[0]["path"] == "/api/v1/research/tasks"
    assert json.loads(captured_research[0]["body"])["topic"] == "GPU 行业趋势"


def test_ticket_and_icp_bff_routes_update_local_store() -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): _auth_internal_validate_user(),
        },
        business_tools_routes={
            ("POST", "/internal/v1/execute/ticket.create"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "ticket created",
                    "result": {"ticket_no": "tk_live_001", "status": "processing"},
                    "data": {"ticket_no": "tk_live_001", "status": "processing"},
                },
                {},
            ),
            ("POST", "/internal/v1/execute/ticket.reply"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "ticket replied",
                    "result": {"reply_no": "reply_001", "status": "processing"},
                    "data": {"reply_no": "reply_001", "status": "processing"},
                },
                {},
            ),
            ("POST", "/internal/v1/execute/icp.material_check"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "material checked",
                    "result": {"passed": False, "issues": ["法人证件缺失"], "required_materials": ["法人身份证"]},
                    "data": {"passed": False, "issues": ["法人证件缺失"], "required_materials": ["法人身份证"]},
                },
                {},
            ),
            ("POST", "/internal/v1/execute/icp.submit_application"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "application submitted",
                    "result": {
                        "application_no": "icp_live_001",
                        "status": "submitted",
                        "current_step": "provider_review",
                    },
                    "data": {
                        "application_no": "icp_live_001",
                        "status": "submitted",
                        "current_step": "provider_review",
                    },
                },
                {},
            ),
            ("POST", "/internal/v1/execute/icp.query_application"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "application detail",
                    "result": {
                        "application_no": "icp_live_001",
                        "status": "submitted",
                        "current_step": "provider_review",
                        "domain": "gpu.example.com",
                    },
                    "data": {
                        "application_no": "icp_live_001",
                        "status": "submitted",
                        "current_step": "provider_review",
                        "domain": "gpu.example.com",
                    },
                },
                {},
            ),
        },
    )

    ticket_create = client.post(
        "/api/v1/tickets",
        headers={"Authorization": "Bearer user-token"},
        json={
            "subject": "实例无法启动",
            "content": "请帮我排查 GPU 实例无法启动的问题",
            "category": "instance",
            "priority": "high",
            "attachments": [],
        },
    )
    assert ticket_create.status_code == 200
    assert ticket_create.json()["data"]["ticket_no"] == "tk_live_001"

    ticket_reply = client.post(
        "/api/v1/tickets/tk_live_001/replies",
        headers={"Authorization": "Bearer user-token"},
        json={"content": "补充一下报错截图", "attachments": []},
    )
    assert ticket_reply.status_code == 200
    assert ticket_reply.json()["data"]["reply_no"] == "reply_001"

    ticket_detail = client.get(
        "/api/v1/tickets/tk_live_001",
        headers={"Authorization": "Bearer user-token"},
    )
    assert ticket_detail.status_code == 200
    detail_payload = ticket_detail.json()["data"]
    assert detail_payload["ticket"]["ticket_no"] == "tk_live_001"
    assert detail_payload["replies"][0]["reply_no"] == "reply_001"

    material_check = client.post(
        "/api/v1/icp/materials/check",
        headers={"Authorization": "Bearer user-token"},
        json={"subject_type": "enterprise", "materials": []},
    )
    assert material_check.status_code == 200
    material_payload = material_check.json()["data"]
    assert material_payload["passed"] is False
    assert material_payload["issues"][0]["message"] == "法人证件缺失"

    create_application = client.post(
        "/api/v1/icp/applications",
        headers={"Authorization": "Bearer user-token"},
        json={
            "subject_type": "enterprise",
            "domain": "gpu.example.com",
            "website_name": "GPU 智算平台",
            "contacts": ["13800000001"],
            "materials": [{"file_id": "file-1"}],
        },
    )
    assert create_application.status_code == 200
    assert create_application.json()["data"]["application_no"] == "icp_live_001"

    list_applications = client.get(
        "/api/v1/icp/applications",
        headers={"Authorization": "Bearer user-token"},
    )
    assert list_applications.status_code == 200
    assert list_applications.json()["data"]["items"][0]["application_no"] == "icp_live_001"

    detail_application = client.get(
        "/api/v1/icp/applications/icp_live_001",
        headers={"Authorization": "Bearer user-token"},
    )
    assert detail_application.status_code == 200
    assert detail_application.json()["data"]["domain"] == "gpu.example.com"


def test_rate_limit_and_cors_headers_are_applied() -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("POST", "/api/v1/auth/login"): (
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "request_id": "req-auth-login",
                    "timestamp": 1776326400000,
                    "data": {"access_token": "***", "refresh_token": "***", "expires_in": 7200},
                },
                {},
            )
        },
        settings_overrides={"rate_limit_requests": 1, "rate_limit_window_seconds": 60},
    )

    allowed = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"login_type": "password", "account": "demo", "password": "***"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert allowed.headers["X-RateLimit-Limit"] == "1"
    assert allowed.headers["X-RateLimit-Remaining"] == "0"

    rejected = client.post(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173"},
        json={"login_type": "password", "account": "demo", "password": "***"},
    )
    assert rejected.status_code == 429
    rejected_payload = rejected.json()
    assert rejected_payload["error"]["message"] == "rate limit exceeded"
    assert rejected.headers["Retry-After"] == "60"
    assert rejected.headers["X-RateLimit-Limit"] == "1"
    assert rejected.headers["X-RateLimit-Remaining"] == "0"


def test_rate_limit_exempts_health_routes() -> None:
    client, _ = _build_test_client(settings_overrides={"rate_limit_requests": 1, "rate_limit_window_seconds": 60})

    first = client.get("/healthz")
    second = client.get("/healthz")

    assert first.status_code == 200
    assert second.status_code == 200


def test_owner_local_routes_require_admin_subject() -> None:
    def admin_me_route(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "requestId": "req-auth-admin",
                "data": {
                    "admin_id": "admin-1",
                    "tenant_id": "tenant-a",
                    "permissions": ["admin:kb.read"],
                },
            },
        )

    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/admin/auth/me"): admin_me_route,
        },
        knowledge_routes={
            ("GET", "/api/knowledge/v1/overview"): (
                200,
                {
                    "success": True,
                    "requestId": "req-overview",
                    "data": {"total_documents": 12},
                },
                {},
            )
        },
    )

    unauthorized = client.get("/api/knowledge/v1/overview")
    assert unauthorized.status_code == 401

    authorized = client.get(
        "/api/knowledge/v1/overview",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["data"]["total_documents"] == 12
    assert captures["knowledge-service"][0]["path"] == "/api/knowledge/v1/overview"


def test_retrying_same_write_without_idempotency_header_keeps_same_fallback_key() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): (
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "request_id": "req-auth-me",
                    "timestamp": 1776326400000,
                    "data": {
                        "user_id": "u-1",
                        "tenant_id": "tenant-a",
                        "permissions": [
                            "user:chat.use",
                            "user:research.write",
                        ],
                    },
                },
                {},
            ),
        },
        research_routes={
            ("POST", "/api/v1/research/tasks"): (
                202,
                {
                    "code": 0,
                    "message": "accepted",
                    "request_id": "research-create",
                    "timestamp": 1776326400000,
                    "data": {"task_id": "task-1", "status": "queued"},
                },
                {},
            )
        },
    )

    headers = {"Authorization": "Bearer user-token"}
    payload = {
        "topic": "gateway retry test",
        "scope": "qa",
        "depth": "standard",
        "output_format": "markdown",
        "reference_urls": [],
    }

    first = client.post("/api/v1/research/tasks", headers=headers, json=payload)
    second = client.post("/api/v1/research/tasks", headers=headers, json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    first_key = captures["research-service"][0]["headers"]["idempotency-key"]
    second_key = captures["research-service"][1]["headers"]["idempotency-key"]
    assert first_key
    assert first_key == second_key


def test_business_tool_writes_generate_stable_fallback_idempotency_keys() -> None:
    client, captures = _build_test_client(
        auth_routes={
            ("GET", "/api/v1/auth/me"): (
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "request_id": "req-auth-me",
                    "timestamp": 1776326400000,
                    "data": {
                        "user_id": "u-1",
                        "account_id": "acct-real-1",
                        "tenant_id": "tenant-a",
                        "permissions": ["user:order.read"],
                    },
                },
                {},
            ),
        },
        business_tools_routes={
            ("POST", "/internal/v1/execute/order.create_refund"): (
                200,
                {
                    "success": True,
                    "code": 0,
                    "message": "ok",
                    "status": "completed",
                    "summary": "refund created",
                    "result": {
                        "refund_no": "refund_ord_live_001",
                        "status": "processing",
                        "requested_amount": 1288.32,
                    },
                    "data": {
                        "refund_no": "refund_ord_live_001",
                        "status": "processing",
                        "requested_amount": 1288.32,
                    },
                },
                {},
            )
        },
    )

    payload = {
        "order_no": "ord_live_001",
        "reason": "业务暂不需要，申请退款",
        "amount": "1288.32",
        "attachments": [],
    }
    headers = {"Authorization": "Bearer user-token"}

    first = client.post("/api/v1/orders/ord_live_001/refunds", headers=headers, json=payload)
    second = client.post("/api/v1/orders/ord_live_001/refunds", headers=headers, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_key = captures["business-tools-service"][0]["headers"]["idempotency-key"]
    second_key = captures["business-tools-service"][1]["headers"]["idempotency-key"]
    assert first_key
    assert first_key == second_key


def test_request_logging_emits_required_structured_fields(caplog) -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("POST", "/api/v1/auth/login"): (
                200,
                {
                    "code": 0,
                    "message": "ok",
                    "request_id": "upstream-login",
                    "timestamp": 1776300000000,
                    "data": {"access_token": "***", "refresh_token": "***", "expires_in": 7200, "user": {}},
                },
                {},
            )
        }
    )

    original_propagate = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level("INFO", logger=logger.name):
            response = client.post(
                "/api/v1/auth/login",
                headers={"X-Request-Id": "req-log", "X-Trace-Id": "trace-log", "X-Tenant-Id": "tenant-log"},
                json={"login_type": "password", "account": "demo@smartcloud.local", "password": "***"},
            )
    finally:
        logger.propagate = original_propagate

    assert response.status_code == 200
    payloads = [payload for record in caplog.records if (payload := parse_log_payload(record.getMessage()))]
    request_log = next(payload for payload in payloads if payload.get("event") == "request_completed")
    upstream_log = next(payload for payload in payloads if payload.get("event") == "upstream_call")

    assert request_log["request_id"] == "req-log"
    assert request_log["trace_id"] == "trace-log"
    assert request_log["method"] == "POST"
    assert request_log["path"] == "/api/v1/auth/login"
    assert request_log["subject_type"] == "anonymous"
    assert request_log["subject_id"] is None
    assert request_log["tenant_id"] == "tenant-log"
    assert request_log["response_status"] == 200
    assert isinstance(request_log["latency_ms"], int)
    assert request_log["rate_limit_remaining"] == 99

    assert upstream_log["upstream_service"] == "auth-user-service"
    assert upstream_log["upstream_method"] == "POST"
    assert upstream_log["upstream_path"] == "/api/v1/auth/login"
    assert upstream_log["upstream_status"] == 200
    assert isinstance(upstream_log["upstream_latency_ms"], int)
    assert upstream_log["error_category"] is None


def test_upstream_timeout_is_mapped_and_logged(caplog) -> None:
    def timeout_route(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client, _ = _build_test_client(
        auth_routes={("POST", "/api/v1/auth/login"): timeout_route},
    )

    original_propagate = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level("INFO", logger=logger.name):
            response = client.post(
                "/api/v1/auth/login",
                headers={"X-Request-Id": "req-timeout", "X-Trace-Id": "trace-timeout"},
                json={"login_type": "password", "account": "demo", "password": "***"},
            )
    finally:
        logger.propagate = original_propagate

    assert response.status_code == 504
    payload = response.json()
    assert payload["detail"]["code"] == 5040001
    logs = [payload for record in caplog.records if (payload := parse_log_payload(record.getMessage()))]
    upstream_log = next(payload for payload in logs if payload.get("event") == "upstream_call")
    request_log = next(payload for payload in logs if payload.get("event") == "request_completed")
    assert upstream_log["upstream_service"] == "auth-user-service"
    assert upstream_log["upstream_status"] == 504
    assert upstream_log["error_category"] == "timeout"
    assert request_log["response_status"] == 504


def test_upstream_error_passthrough_preserves_status_and_logs_classification(caplog) -> None:
    client, _ = _build_test_client(
        auth_routes={
            ("POST", "/api/v1/auth/login"): (
                401,
                {"detail": {"code": 4010001, "message": "token invalid"}},
                {},
            )
        }
    )

    original_propagate = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level("INFO", logger=logger.name):
            response = client.post(
                "/api/v1/auth/login",
                json={"login_type": "password", "account": "demo", "password": "***"},
            )
    finally:
        logger.propagate = original_propagate

    assert response.status_code == 401
    assert response.json()["detail"]["message"] == "token invalid"
    logs = [payload for record in caplog.records if (payload := parse_log_payload(record.getMessage()))]
    upstream_log = next(payload for payload in logs if payload.get("event") == "upstream_call")
    assert upstream_log["upstream_status"] == 401
    assert upstream_log["error_category"] == "unauthorized"
