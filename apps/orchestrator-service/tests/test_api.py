import threading
import time

from fastapi.testclient import TestClient

from app.main import app
from app.api.routes import orchestration as orchestration_routes
from app.services.agent_runtime import AgentRuntime


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


def test_orchestrate_message_finishes_completed_multi_agent_chain_without_pending_handoff() -> None:
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
    assert len(payload["executions"]) == 2
    assert payload["executions"][0]["status"] == "handoff"
    assert payload["executions"][-1]["status"] == "success"
    assert payload["next_action"] == "respond-with-agent-summary"
    agent_routes = payload["state_snapshot"]["agent_routes"]
    assert [item["status"] for item in agent_routes] == ["handoff", "success"]
    assert agent_routes[0]["handoff_to"] == "ops_marketing_agent"


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
    assert items[1]["status"] == "success"


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


def test_orchestrate_message_stream_emits_spec_like_events() -> None:
    with client.stream(
        "POST",
        "/api/v1/sessions/conv-stream/messages/stream",
        json={
            "message_id": "msg-stream-1",
            "user_query": "给我一份 GPU 部署最佳实践和排查方案",
            "scene": "technical_support",
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



def test_orchestrate_message_returns_failure_on_idempotency_conflict() -> None:
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
    assert first.json()["data"]["next_action"] == "respond-with-agent-summary"

    conflict = client.post(
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
    assert conflict.status_code == 200
    payload = conflict.json()["data"]
    assert payload["next_action"] == "retry-or-escalate"
    assert payload["executions"][0]["tool_calls"][0]["status"] == "idempotency-conflict"


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
    assert payload["status"] == "success"
    assert payload["response"]["route"]["primary_agent"] == "finance_order_agent"
    assert payload["response"]["route"]["requires_retrieval"] is True
    assert payload["tool_calls"] == []
    assert payload["citations"] == ["baseline://router-retrieval"]
    assert payload["finish_reason"] == "stop"


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
    create_response = client.post("/api/v1/chat/sessions", json={"scene": "billing", "title": "Cancel me"})
    conversation_id = create_response.json()["data"]["conversation_id"]
    message_id = "msg-cancel-1"
    started = threading.Event()
    result: dict[str, object] = {}

    original_invoke_plan = orchestration_routes._runtime.tool_hub_client.invoke_plan

    def _slow_invoke_plan(tool_plan, user_profile, trace=None, operator_id="orchestrator", message_id=None):
        started.set()
        deadline = time.time() + 2
        while time.time() < deadline:
            if orchestration_routes._run_control.is_cancelled(conversation_id, message_id):
                orchestration_routes._run_control.ensure_not_cancelled(conversation_id, message_id)
            time.sleep(0.01)
        return original_invoke_plan(
            tool_plan,
            user_profile,
            trace=trace,
            operator_id=operator_id,
            message_id=message_id,
        )

    monkeypatch.setattr(
        orchestration_routes._runtime.tool_hub_client,
        "invoke_plan",
        _slow_invoke_plan,
    )

    def _run_completion() -> None:
        background_client = TestClient(app)
        result["response"] = background_client.post(
            "/api/v1/chat/completions",
            json={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "user_input": "帮我查本月账单",
                "scene": "billing",
                "user_profile": {
                    "user_id": "u-1",
                    "account_id": "acct-1",
                    "permissions": ["user:billing.read"],
                },
            },
        )

    thread = threading.Thread(target=_run_completion, daemon=True)
    thread.start()
    assert started.wait(1), "expected completion flow to reach tool invocation"

    cancel_response = client.post(
        f"/api/v1/chat/sessions/{conversation_id}/cancel",
        json={"message_id": message_id},
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["data"]["status"] == "cancelled"

    thread.join(2)
    response = result["response"]
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CHAT_MESSAGE_CANCELLED"

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
    orchestrate_response = client.post(
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
    assert orchestrate_response.status_code == 200
    stack = orchestrate_response.json()["data"]["state_snapshot"]["compensation_stack"]
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


def test_orchestrate_message_honors_explicit_tool_candidates_across_agents() -> None:
    response = client.post(
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

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["route"]["primary_agent"] == "finance_order_agent"
    assert payload["route"]["supporting_agents"] == ["ops_marketing_agent"]
    assert [execution["agent"] for execution in payload["executions"]] == [
        "finance_order_agent",
        "ops_marketing_agent",
    ]
    assert payload["executions"][0]["tool_calls"][0]["tool_name"] == "billing.query_statement"
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
