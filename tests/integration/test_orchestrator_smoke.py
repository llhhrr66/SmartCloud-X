from __future__ import annotations

from pathlib import Path

from scripts.qa.contract_policy import validate_live_response_contract
from scripts.qa.openapi_contracts import OpenApiContract
from tests.qa_helpers.service_loader import assert_standard_headers, service_test_client


ORCHESTRATOR_CONTRACT = OpenApiContract("openapi/orchestrator-service.openapi.yaml")


def _orchestrator_env(tmp_path: Path) -> dict[str, str]:
    return {
        "CONVERSATION_STORE_PATH": str(tmp_path / "conversation-store.json"),
        "STATE_STORE_PATH": str(tmp_path / "state-store.json"),
        "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "idempotency-store.json"),
        "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "query-cache-store.json"),
        "SSE_EVENT_STORE_PATH": str(tmp_path / "sse-event-store.json"),
    }


def test_orchestrator_billing_flow_persists_context_and_compensation(tmp_path: Path) -> None:
    with service_test_client("orchestrator-service", env_overrides=_orchestrator_env(tmp_path)) as client:
        created = client.post("/api/v1/chat/sessions", json={"scene": "billing", "title": "QA pytest"})
        assert created.status_code == 200
        assert_standard_headers(created.headers)
        validate_live_response_contract(
            {"orchestrator-service": ORCHESTRATOR_CONTRACT},
            "orchestrator-service",
            "/api/v1/chat/sessions",
            "post",
            200,
            created.json(),
        )
        conversation_id = created.json()["data"]["conversation_id"]

        first = client.post(
            "/api/v1/chat/completions",
            json={
                "conversation_id": conversation_id,
                "message_id": "pytest-msg-1",
                "user_input": "帮我查本月账单",
                "scene": "billing",
                "user_profile": {
                    "user_id": "u-1",
                    "account_id": "acct-1",
                    "permissions": ["user:billing.read"],
                },
            },
        )
        assert first.status_code == 200
        assert_standard_headers(first.headers)
        validate_live_response_contract(
            {"orchestrator-service": ORCHESTRATOR_CONTRACT},
            "orchestrator-service",
            "/api/v1/chat/completions",
            "post",
            200,
            first.json(),
        )
        first_payload = first.json()["data"]
        assert first_payload["tool_calls"][0]["tool_name"] == "billing.query_statement"
        assert (
            first_payload["response"]["state_snapshot"]["session_context"]["attributes"]["statement_no"]
            == "stmt_2026_04_001"
        )

        second = client.post(
            "/api/v1/chat/completions",
            json={
                "conversation_id": conversation_id,
                "message_id": "pytest-msg-2",
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
        assert second.status_code == 200
        assert_standard_headers(second.headers)
        validate_live_response_contract(
            {"orchestrator-service": ORCHESTRATOR_CONTRACT},
            "orchestrator-service",
            "/api/v1/chat/completions",
            "post",
            200,
            second.json(),
        )
        second_payload = second.json()["data"]["response"]
        assert second_payload["executions"][0]["tool_calls"][0]["tool_name"] == "billing.create_invoice"
        assert second_payload["state_snapshot"]["session_context"]["attributes"]["invoice_no"].startswith("inv_")

        state = client.get(f"/api/v1/sessions/{conversation_id}/state")
        assert state.status_code == 200
        assert_standard_headers(state.headers)
        validate_live_response_contract(
            {"orchestrator-service": ORCHESTRATOR_CONTRACT},
            "orchestrator-service",
            "/api/v1/sessions/{conversation_id}/state",
            "get",
            200,
            state.json(),
        )
        state_payload = state.json()["data"]
        assert state_payload["version"] >= 2
        assert state_payload["compensation_stack"][0]["tool_name"] == "billing.create_invoice"


def test_orchestrator_stream_endpoint_emits_expected_sse_sequence(tmp_path: Path) -> None:
    with service_test_client("orchestrator-service", env_overrides=_orchestrator_env(tmp_path)) as client:
        with client.stream(
            "POST",
            "/api/v1/sessions/conv-stream-qa/messages/stream",
            json={
                "message_id": "msg-stream-qa-1",
                "user_query": "给我一份 GPU 部署最佳实践和排查方案",
                "scene": "technical_support",
            },
            headers={"X-Request-Id": "req-stream-qa-1", "X-Trace-Id": "trace-stream-qa-1"},
        ) as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert_standard_headers(response.headers)
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [line for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "event: meta"
    assert "event: reasoning" in events
    assert "event: retrieval" in events
    assert "event: tool_call" in events
    assert "event: tool_result" in events
    assert "event: citation" in events
    assert events[-1] == "event: done"


def test_orchestrator_marketing_flow_collects_auth_context_after_read_step(tmp_path: Path) -> None:
    with service_test_client("orchestrator-service", env_overrides=_orchestrator_env(tmp_path)) as client:
        created = client.post(
            "/api/v1/chat/sessions",
            json={"scene": "marketing", "title": "QA marketing auth follow-up"},
        )
        assert created.status_code == 200
        conversation_id = created.json()["data"]["conversation_id"]

        completion = client.post(
            "/api/v1/chat/completions",
            json={
                "conversation_id": conversation_id,
                "message_id": "msg-marketing-auth-1",
                "user_input": "帮我生成营销文案",
                "scene": "marketing",
                "user_profile": {
                    "user_id": "u-1",
                    "account_id": "acct-1",
                    "permissions": ["user:marketing.read"],
                },
            },
        )

    assert completion.status_code == 200
    assert_standard_headers(completion.headers)
    validate_live_response_contract(
        {"orchestrator-service": ORCHESTRATOR_CONTRACT},
        "orchestrator-service",
        "/api/v1/chat/completions",
        "post",
        200,
        completion.json(),
    )
    payload = completion.json()["data"]
    assert payload["status"] == "need_user_input"
    assert payload["response"]["next_action"] == "collect-user-input"
    assert payload["response"]["pending_actions"] == ["collect-auth-context"]
    assert [tool_call["status"] for tool_call in payload["tool_calls"]] == ["completed", "auth-required"]
    assert payload["tool_calls"][0]["tool_name"] == "marketing.campaign_lookup"
    assert payload["tool_calls"][1]["tool_name"] == "marketing.generate_copy"
    assert payload["tool_calls"][1]["user_action_hint"]["action"] == "collect-auth-context"
    assert payload["tool_calls"][1]["user_action_hint"]["required_permissions"] == [
        "user:marketing.write"
    ]
    assert payload["pending_user_actions"][0]["required_permissions"] == ["user:marketing.write"]
    assert (
        payload["response"]["state_snapshot"]["session_context"]["attributes"]["last_campaign_name"]
        == "春季通用云上云活动"
    )


def test_message_stream_events_can_be_replayed_and_resumed_from_last_event_id(tmp_path: Path) -> None:
    with service_test_client("orchestrator-service", env_overrides=_orchestrator_env(tmp_path)) as client:
        created = client.post(
            "/api/v1/chat/sessions",
            json={"scene": "technical_support", "title": "QA replay"},
        )
        assert created.status_code == 200
        conversation_id = created.json()["data"]["conversation_id"]

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
        assert_standard_headers(completion.headers)

        events_response = client.get(
            f"/api/v1/chat/sessions/{conversation_id}/messages/asst_msg-replay-1/events"
        )
        assert events_response.status_code == 200
        assert_standard_headers(events_response.headers)
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
    assert_standard_headers(replay_response.headers)
    assert replay_response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" not in replay_body
    assert "event: done" in replay_body
