from fastapi.testclient import TestClient

from app.api.routes import tools as tools_routes
from app.main import app

client = TestClient(app)


def test_metrics_endpoint_exposes_prometheus_counters() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "tool_hub_requests_total" in body
    assert "tool_hub_readiness_state" in body


def test_mcp_describe_endpoint_returns_tool_schema() -> None:
    response = client.get("/tools/describe/billing.query_statement")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "billing.query_statement"
    assert payload["input_schema"]["type"] == "object"


def test_mcp_call_streaming_returns_sse() -> None:
    response = client.post(
        "/tools/call?stream=true",
        json={
            "trace_id": "trace-stream-1",
            "conversation_id": "conv-stream-1",
            "tool_call_id": "tc-stream-1",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "123e4567-e89b-12d3-a456-426614174000",
            "operation": "execute",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: status" in response.text
    assert "event: result" in response.text


def test_tool_call_rejects_invalid_idempotency_key() -> None:
    response = client.post(
        "/api/v1/tools/call",
        json={
            "trace_id": "trace-idem-invalid-1",
            "conversation_id": "conv-idem-invalid-1",
            "tool_call_id": "tc-idem-invalid-1",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "bad key",
            "operation": "execute",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ORCH_TOOL_IDEMPOTENCY_INVALID"


def test_tool_call_replays_same_idempotency_key_and_sets_expiry_header() -> None:
    payload = {
        "trace_id": "trace-idem-replay-1",
        "conversation_id": "conv-idem-replay-1",
        "tool_call_id": "tc-idem-replay-1",
        "tool_name": "billing.query_statement",
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "user_context": {
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:billing.read"],
        },
        "payload": {"range": "this_month"},
        "idempotency_key": "123e4567-e89b-12d3-a456-426614174001",
        "operation": "execute",
    }
    first = client.post("/api/v1/tools/call", json=payload)
    second = client.post("/api/v1/tools/call", json={**payload, "tool_call_id": "tc-idem-replay-2"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["tool_call_id"] == "tc-idem-replay-1"
    assert "X-Idempotency-Expires-At" in second.headers


def test_tool_call_returns_conflict_for_concurrent_same_idempotency_key(monkeypatch) -> None:
    original = tools_routes._business_tools_client.invoke_call

    def _blocked_invoke(tool, request, definition=None):
        import threading
        if request.tool_call_id == "tc-conflict-1":
            threading.Event().wait(0.3)
        return original(tool, request, definition=definition)

    monkeypatch.setattr(tools_routes._business_tools_client, "invoke_call", _blocked_invoke)

    import threading

    results = []

    def _call(tool_call_id: str):
        results.append(
            client.post(
                "/api/v1/tools/call",
                json={
                    "trace_id": f"trace-{tool_call_id}",
                    "conversation_id": "conv-conflict-1",
                    "tool_call_id": tool_call_id,
                    "tool_name": "billing.query_statement",
                    "operator": {"type": "agent", "id": "Finance_Order_Agent"},
                    "user_context": {
                        "user_id": "u-1",
                        "account_id": "acct-1",
                        "permissions": ["user:billing.read"],
                    },
                    "payload": {"range": "this_month"},
                    "idempotency_key": "123e4567-e89b-12d3-a456-426614174002",
                    "operation": "execute",
                },
            )
        )

    t1 = threading.Thread(target=_call, args=("tc-conflict-1",))
    t2 = threading.Thread(target=_call, args=("tc-conflict-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    statuses = sorted(response.status_code for response in results)
    assert statuses == [200, 409]


def test_healthz_includes_metrics_snapshot_and_idempotency_stats() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    runtime = response.json()["runtime"]
    assert "metrics" in runtime
    assert "toolHubIdempotency" in runtime
