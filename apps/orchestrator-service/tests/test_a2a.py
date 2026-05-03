from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_agent_card_exposes_a2a_entrypoint() -> None:
    response = client.get("/.well-known/agent-card.json")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "SmartCloud-X Orchestrator"
    assert payload["url"].endswith("/api/v1/a2a/jsonrpc")
    assert payload["capabilities"]["streaming"] is False


def test_a2a_send_message_and_get_task_round_trip() -> None:
    send = client.post(
        "/api/v1/a2a/jsonrpc",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "帮我查本月账单"}],
                }
            },
        },
    )
    assert send.status_code == 200
    task = send.json()["result"]["task"]
    assert task["contextId"]
    assert task["status"]["message"]["parts"][0]["text"]

    get_task = client.post(
        "/api/v1/a2a/jsonrpc",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-2",
            "method": "GetTask",
            "params": {"contextId": task["contextId"], "id": task["id"]},
        },
    )
    assert get_task.status_code == 200
    fetched = get_task.json()["result"]["task"]
    assert fetched["id"] == task["id"]
    assert fetched["contextId"] == task["contextId"]
    assert fetched["status"]["state"] == "input-required"
    assert fetched["history"][0]["role"] == "user"
    assert fetched["history"][1]["role"] == "agent"


def test_get_task_pages_until_target_message_is_found(monkeypatch) -> None:
    from app.api.routes import a2a as a2a_routes

    user_message = SimpleNamespace(
        message_id="msg-page-1",
        content="older task",
        status="completed",
        updated_at="2026-04-18T00:00:00Z",
        finish_reason="collect-user-input",
        agent_name=None,
        citations=[],
    )
    assistant_message = SimpleNamespace(
        message_id="asst_msg-page-1",
        content="need more input",
        status="need_user_input",
        updated_at="2026-04-18T00:00:01Z",
        finish_reason="collect-user-input",
        agent_name="finance_order_agent",
        citations=[],
    )
    pages = [
        SimpleNamespace(items=[], has_more=True, next_cursor="cursor-1"),
        SimpleNamespace(items=[user_message, assistant_message], has_more=False, next_cursor=None),
    ]

    class FakeStore:
        def __init__(self) -> None:
            self.calls = []

        def resolve_request_message_id(self, conversation_id: str, task_id: str) -> str:
            return task_id

        def list_messages(self, conversation_id: str, *, cursor=None, page_size=20):
            self.calls.append((conversation_id, cursor, page_size))
            return pages[len(self.calls) - 1]

    fake_store = FakeStore()
    monkeypatch.setattr(a2a_routes, "_conversation_store", fake_store)

    task = a2a_routes._task_from_store("conv-page-1", "msg-page-1")
    assert task["status"]["state"] == "input-required"
    assert fake_store.calls == [
        ("conv-page-1", None, 200),
        ("conv-page-1", "cursor-1", 200),
    ]
