from fastapi.testclient import TestClient

from app.core.business_tools_sdk import ToolDefinition, ToolExecutionResult, ToolPreflightResult
from app.main import app
from app.api.routes import tools as tools_routes


client = TestClient(app)
internal_client = TestClient(app, headers={"X-Caller-Service": "orchestrator-service"})


def test_internal_tools_call_executes_query_tool() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-1",
            "conversation_id": "conv-1",
            "tool_call_id": "tc-1",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "tool-tc-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["summary"]
    assert payload["result"]["currency"] == "CNY"
    assert payload["data"]["currency"] == "CNY"
    assert payload["citations"] == ["baseline://billing-query-statement"]
    assert "cache-hit" not in payload["audit_tags"]
    assert payload["session_context_patch"]["attributes"]["statement_no"] == "stmt_2026_04_001"


def test_internal_tools_call_executes_order_status_query_tool() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-order-query-1",
            "conversation_id": "conv-order-query-1",
            "tool_call_id": "tc-order-query-1",
            "tool_name": "order.query_order",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:order.read"],
            },
            "payload": {
                "order_no": "ord_20260416_001",
                "refund_no": "refund_ord_20260416_001",
            },
            "idempotency_key": "tool-order-query-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["result"]["order_status"] == "refunding"
    assert payload["session_context_patch"]["attributes"]["refund_status"] == "processing"


def test_internal_tools_call_executes_ticket_and_icp_status_query_tools() -> None:
    ticket_response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-ticket-query-1",
            "conversation_id": "conv-ticket-query-1",
            "tool_call_id": "tc-ticket-query-1",
            "tool_name": "ticket.query_ticket",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:ticket.read"],
            },
            "payload": {
                "ticket_no": "tk_billing_001",
                "subject": "账单异常",
            },
            "idempotency_key": "tool-ticket-query-1",
            "operation": "execute",
        },
    )
    icp_response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-icp-query-1",
            "conversation_id": "conv-icp-query-1",
            "tool_call_id": "tc-icp-query-1",
            "tool_name": "icp.query_application",
            "operator": {"type": "agent", "id": "ICP_Service_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:icp.read"],
            },
            "payload": {
                "application_no": "icp_demo_example_com",
                "domain": "demo.example.com",
            },
            "idempotency_key": "tool-icp-query-1",
            "operation": "execute",
        },
    )

    assert ticket_response.status_code == 200
    assert icp_response.status_code == 200
    ticket_payload = ticket_response.json()
    icp_payload = icp_response.json()
    assert ticket_payload["success"] is True
    assert ticket_payload["status"] == "completed"
    assert ticket_payload["result"]["status"] == "processing"
    assert ticket_payload["session_context_patch"]["open_ticket_id"] == "tk_billing_001"
    assert icp_payload["success"] is True
    assert icp_payload["status"] == "completed"
    assert icp_payload["result"]["status"] == "provider_review"
    assert icp_payload["session_context_patch"]["attributes"]["application_no"] == "icp_demo_example_com"


def test_internal_tools_call_executes_icp_subject_verification_tool() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-icp-verify-1",
            "conversation_id": "conv-icp-verify-1",
            "tool_call_id": "tc-icp-verify-1",
            "tool_name": "icp.verify_subject",
            "operator": {"type": "agent", "id": "ICP_Service_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:icp.read"],
            },
            "payload": {
                "subject_type": "enterprise",
                "subject_name": "上海示例科技有限公司",
                "certificate_no": "91310000MA1CTEST88",
                "contact_name": "张三",
                "contact_phone": "13800138000",
            },
            "idempotency_key": "tool-icp-verify-1",
            "operation": "execute",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["result"]["verification_status"] == "verified"
    assert payload["session_context_patch"]["attributes"]["contacts"]["contact_phone"] == "13800138000"


def test_internal_tools_call_returns_preview_confirmation_hint_and_audits_it() -> None:
    tool_call_id = "tc-preview-confirm-1"
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-preview-confirm-1",
            "conversation_id": "conv-preview-confirm-1",
            "tool_call_id": tool_call_id,
            "tool_name": "billing.create_invoice",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "某某科技",
            },
            "idempotency_key": "tool-preview-confirm-1",
            "operation": "preview",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "preview-ready"
    assert payload["user_action_hint"]["action"] == "user-confirmation"
    assert payload["user_action_hint"]["confirm_tool_names"] == ["billing.create_invoice"]

    audit_response = client.get(f"/api/v1/tool-calls/{tool_call_id}")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()["data"]
    assert audit_payload["status"] == "preview-ready"
    assert audit_payload["user_action_hint"]["action"] == "user-confirmation"


def test_internal_tools_preflight_returns_missing_field_hints() -> None:
    response = internal_client.post(
        "/internal/v1/tools/preflight",
        json={
            "trace_id": "trace-preflight-1",
            "conversation_id": "conv-preflight-1",
            "tool_call_id": "tc-preflight-1",
            "tool_name": "order.create_refund",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:order.read"],
            },
            "payload": {"reason": "误购"},
            "idempotency_key": "tool-preflight-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is False
    assert payload["status"] == "missing-payload"
    assert payload["tool_mode"] == "write"
    assert payload["timeout_ms"] == 10000
    assert payload["idempotent"] is True
    assert payload["cache_ttl_seconds"] is None
    assert payload["missing_payload_fields"] == ["order_no", "amount"]
    assert "订单号" in payload["missing_payload_hints"]["order_no"]
    assert "退款金额" in payload["missing_payload_hints"]["amount"]
    assert payload["missing_auth_context"] == []
    assert payload["session_context_bindings"]["order_no"] == ["attributes.order_no"]
    assert payload["session_context_bindings"]["amount"] == ["attributes.refund_amount"]


def test_public_tools_preflight_exposes_canonical_route_without_audit_record() -> None:
    tool_call_id = "tc-public-preflight-1"
    response = client.post(
        "/api/v1/tools/preflight",
        json={
            "trace_id": "trace-public-preflight-1",
            "conversation_id": "conv-public-preflight-1",
            "tool_call_id": tool_call_id,
            "tool_name": "order.create_refund",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:order.read"],
            },
            "payload": {"reason": "误购"},
            "idempotency_key": "tool-public-preflight-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing-payload"
    assert payload["missing_payload_fields"] == ["order_no", "amount"]
    assert payload["session_context_bindings"]["order_no"] == ["attributes.order_no"]

    detail = client.get(f"/api/v1/tool-calls/{tool_call_id}")
    assert detail.status_code == 404


def test_tool_detail_uses_remote_business_tools_descriptor_when_http_transport_enabled(monkeypatch) -> None:
    class StubBusinessToolsClient:
        def describe_tool(self, tool_name: str):
            assert tool_name == "billing.query_statement"
            return ToolDefinition.model_validate(
                {
                    "name": "billing.query_statement",
                    "capability": "billing",
                    "description": "remote descriptor",
                    "timeout_ms": 4321,
                    "cache_ttl_seconds": 77,
                    "session_context_bindings": {"range": ["attributes.billing_range"]},
                }
            )

        def list_tools(self, **filters):
            assert filters == {"capability": None, "mode": None, "tag": None, "query": None}
            return [
                self.describe_tool("billing.query_statement"),
            ]

    monkeypatch.setattr(tools_routes._settings, "business_tools_transport", "http", raising=False)
    monkeypatch.setattr(tools_routes._registry._settings, "business_tools_transport", "http", raising=False)
    monkeypatch.setattr(tools_routes._registry, "_business_tools_client", StubBusinessToolsClient(), raising=False)

    response = client.get("/api/v1/tools/billing.query_statement")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["timeout_ms"] == 4321
    assert payload["cache_ttl_seconds"] == 77


def test_internal_tools_preflight_uses_remote_business_tools_preflight_when_http_transport_enabled(monkeypatch) -> None:
    class StubBusinessToolsClient:
        def preflight_call(self, tool_name, request):
            assert tool_name == "order.create_refund"
            return ToolPreflightResult(
                tool_name=tool_name,
                operation=request.operation,
                status="missing-payload",
                ready=False,
                available=True,
                tool_mode="write",
                timeout_ms=8765,
                idempotent=True,
                missing_payload_fields=["order_no"],
                missing_payload_hints={"order_no": "请提供订单号"},
            )

    remote_descriptor = ToolDefinition.model_validate(
        {
            "name": "order.create_refund",
            "capability": "order",
            "description": "remote refund",
            "mode": "write",
            "timeout_ms": 8765,
            "session_context_bindings": {"order_no": ["attributes.order_no"]},
        }
    )

    monkeypatch.setattr(tools_routes._settings, "business_tools_transport", "http", raising=False)
    monkeypatch.setattr(tools_routes._registry._settings, "business_tools_transport", "http", raising=False)
    monkeypatch.setattr(tools_routes._registry, "_business_tools_client", tools_routes._business_tools_client, raising=False)
    monkeypatch.setattr(tools_routes._registry, "describe_tool", lambda tool_name: remote_descriptor if tool_name == "order.create_refund" else None, raising=False)
    monkeypatch.setattr(tools_routes, "_business_tools_client", StubBusinessToolsClient(), raising=False)

    response = internal_client.post(
        "/internal/v1/tools/preflight",
        json={
            "trace_id": "trace-preflight-http-1",
            "conversation_id": "conv-preflight-http-1",
            "tool_call_id": "tc-preflight-http-1",
            "tool_name": "order.create_refund",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {"user_id": "u-1", "permissions": ["user:order.read"]},
            "payload": {"reason": "误购"},
            "idempotency_key": "tool-preflight-http-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing-payload"
    assert payload["timeout_ms"] == 8765
    assert payload["session_context_bindings"]["order_no"] == ["attributes.order_no"]


def test_direct_invoke_uses_remote_business_tools_execution_when_http_transport_enabled(monkeypatch) -> None:
    remote_descriptor = ToolDefinition.model_validate(
        {
            "name": "billing.query_statement",
            "capability": "billing",
            "description": "remote billing",
            "timeout_ms": 4321,
            "auth_requirements": {"require_user_id": True, "required_permissions": ["user:billing.read"]},
        }
    )

    class StubBusinessToolsClient:
        def invoke_tool(self, definition, request):
            assert definition.name == "billing.query_statement"
            assert request.operation == "execute"
            assert request.payload == {"range": "this_month"}
            assert request.context.user_id == "u-1"
            return ToolExecutionResult(
                tool_name=definition.name,
                operation=request.operation,
                status="completed",
                summary="remote billing summary",
                result={"billing_cycle": "2026-04"},
                citations=["billing://statement"],
                success=True,
                code=0,
                message="ok",
                provider=definition.provider,
            )

    monkeypatch.setattr(tools_routes._settings, "business_tools_transport", "http", raising=False)
    monkeypatch.setattr(tools_routes._registry._settings, "business_tools_transport", "http", raising=False)
    monkeypatch.setattr(tools_routes._registry, "describe_tool", lambda tool_name: remote_descriptor if tool_name == "billing.query_statement" else None, raising=False)
    monkeypatch.setattr(tools_routes._registry, "get_tool", lambda tool_name: None, raising=False)
    monkeypatch.setattr(tools_routes, "_business_tools_client", StubBusinessToolsClient(), raising=False)

    response = client.post(
        "/api/v1/tools/billing.query_statement/invoke",
        json={
            "operation": "execute",
            "payload": {"range": "this_month"},
            "context": {
                "request_id": "tc-remote-invoke-1",
                "trace_id": "trace-remote-invoke-1",
                "conversation_id": "conv-remote-invoke-1",
                "tenant_id": "tenant-a",
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
                "operator_type": "agent",
                "operator_id": "Finance_Order_Agent",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "completed"
    assert payload["summary"] == "remote billing summary"
    assert payload["result"]["billing_cycle"] == "2026-04"
    assert payload["citations"] == ["billing://statement"]


def test_direct_invoke_creates_public_audit_record() -> None:
    response = client.post(
        "/api/v1/tools/billing.query_statement/invoke",
        json={
            "operation": "execute",
            "payload": {"range": "this_month"},
            "context": {
                "request_id": "tc-public-invoke-1",
                "trace_id": "trace-public-invoke-1",
                "conversation_id": "conv-public-invoke-1",
                "tenant_id": "tenant-public",
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
                "operator_type": "user",
                "operator_id": "u-1",
            },
        },
    )

    assert response.status_code == 200
    audit_response = client.get("/api/v1/tool-calls", params={"trace_id": "trace-public-invoke-1"})
    assert audit_response.status_code == 200
    records = audit_response.json()["data"]
    assert len(records) == 1
    assert records[0]["tool_name"] == "billing.query_statement"
    assert "public-direct-invoke" in records[0]["audit_tags"]
    assert records[0]["operation"] == "execute"
    assert records[0]["operator"]["type"] == "user"


def test_direct_invoke_audits_validation_errors() -> None:
    response = client.post(
        "/api/v1/tools/billing.query_statement/invoke",
        json={
            "operation": "execute",
            "payload": {},
            "context": {
                "request_id": "tc-public-invalid-1",
                "trace_id": "trace-public-invalid-1",
                "conversation_id": "conv-public-invalid-1",
                "tenant_id": "tenant-public",
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
                "operator_type": "user",
                "operator_id": "u-1",
            },
        },
    )

    assert response.status_code == 422
    audit_response = client.get("/api/v1/tool-calls", params={"trace_id": "trace-public-invalid-1"})
    assert audit_response.status_code == 200
    records = audit_response.json()["data"]
    assert len(records) == 1
    assert records[0]["status"] == "invalid-payload"
    assert "public-direct-invoke" in records[0]["audit_tags"]
    assert "request-rejected" in records[0]["audit_tags"]


def test_mcp_tools_list_exposes_tool_catalog() -> None:
    response = client.get("/tools/list")
    assert response.status_code == 200
    payload = response.json()
    assert any(tool["name"] == "billing.query_statement" for tool in payload["tools"])


def test_tool_detail_exposes_dependency_and_session_context_metadata() -> None:
    response = client.get("/api/v1/tools/billing.create_invoice")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["session_context_bindings"]["statement_nos"] == [
        "attributes.statement_nos",
        "attributes.statement_no",
    ]
    assert payload["prerequisite_tool_names"] == ["billing.query_statement"]
    assert "attributes.invoice_no" in payload["session_context_output_keys"]


def test_tool_detail_exposes_new_order_and_invoice_query_metadata() -> None:
    order_response = client.get("/api/v1/tools/order.query_order")
    invoice_response = client.get("/api/v1/tools/invoice.query_invoice")

    assert order_response.status_code == 200
    assert invoice_response.status_code == 200

    order_payload = order_response.json()["data"]
    invoice_payload = invoice_response.json()["data"]
    assert order_payload["session_context_bindings"]["order_no"] == [
        "attributes.order_no",
        "attributes.refund_order_no",
    ]
    assert order_payload["output_schema"]["properties"]["refund_status"]["type"] == "string"
    assert invoice_payload["session_context_bindings"]["invoice_no"] == ["attributes.invoice_no"]
    assert invoice_payload["output_schema"]["properties"]["status"]["type"] == "string"


def test_tool_detail_exposes_icp_subject_verification_metadata() -> None:
    response = client.get("/api/v1/tools/icp.verify_subject")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["session_context_bindings"]["subject_name"] == [
        "attributes.subject_name",
        "attributes.icp_subject_name",
    ]
    assert payload["session_context_bindings"]["contact_email"] == [
        "attributes.contact_email",
        "attributes.icp_contact_email",
        "attributes.contacts.contact_email",
    ]
    assert "attributes.contacts" in payload["session_context_output_keys"]
    assert payload["output_schema"]["properties"]["verification_status"]["type"] == "string"


def test_tool_detail_exposes_new_promotion_link_metadata() -> None:
    response = client.get("/api/v1/tools/marketing.generate_promotion_link")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["prerequisite_tool_names"] == ["marketing.campaign_lookup"]
    assert payload["session_context_bindings"]["campaign_name"] == ["attributes.last_campaign_name"]
    assert "attributes.last_promotion_link" in payload["session_context_output_keys"]


def test_tool_detail_exposes_marketing_copy_metadata() -> None:
    response = client.get("/api/v1/tools/marketing.generate_copy")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["prerequisite_tool_names"] == ["marketing.campaign_lookup"]
    assert payload["session_context_bindings"]["campaign_name"] == ["attributes.last_campaign_name"]
    assert "attributes.last_marketing_copy_headline" in payload["session_context_output_keys"]


def test_tool_detail_exposes_marketing_poster_metadata() -> None:
    response = client.get("/api/v1/tools/marketing.generate_poster")
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["prerequisite_tool_names"] == ["marketing.poster_brief"]
    assert payload["session_context_bindings"]["theme"] == ["attributes.poster_theme"]
    assert "attributes.poster_asset_id" in payload["session_context_output_keys"]


def test_internal_tools_call_returns_compensation_for_confirmed_write() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-2",
            "conversation_id": "conv-2",
            "tool_call_id": "tc-2",
            "tool_name": "billing.create_invoice",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "某某科技",
                "_confirmed": True,
            },
            "idempotency_key": "tool-tc-2",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["summary"]
    assert payload["compensation"]["action_name"] == "cancel_invoice_request"
    assert payload["idempotency_key"] == "tool-tc-2"


def test_internal_tools_call_executes_promotion_link_write() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-promo-1",
            "conversation_id": "conv-promo-1",
            "tool_call_id": "tc-promo-1",
            "tool_name": "marketing.generate_promotion_link",
            "operator": {"type": "agent", "id": "Ops_Marketing_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:marketing.write"],
            },
            "payload": {
                "campaign_name": "GPU 新客满减",
                "channel": "wechat",
            },
            "idempotency_key": "tool-promo-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["result"]["short_url"].startswith("https://scx.example/p/")
    assert payload["compensation"]["action_name"] == "deactivate_promotion_link"
    assert payload["session_context_patch"]["attributes"]["last_promotion_link"] == payload["result"]["short_url"]


def test_internal_tools_call_executes_poster_generation_write() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-poster-1",
            "conversation_id": "conv-poster-1",
            "tool_call_id": "tc-poster-1",
            "tool_name": "marketing.generate_poster",
            "operator": {"type": "agent", "id": "Ops_Marketing_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:marketing.write"],
            },
            "payload": {
                "theme": "GPU 算力活动海报",
                "campaign_name": "GPU 新客满减",
                "headline": "GPU 新客满减限时开启",
                "size": "portrait",
            },
            "idempotency_key": "tool-poster-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "completed"
    assert payload["result"]["poster_asset_id"].startswith("poster_")
    assert payload["compensation"]["action_name"] == "delete_poster_asset"
    assert payload["session_context_patch"]["attributes"]["poster_asset_id"] == payload["result"]["poster_asset_id"]


def test_internal_tools_call_returns_invalid_payload_and_audit_status() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-invalid-1",
            "conversation_id": "conv-invalid-1",
            "tool_call_id": "tc-invalid-1",
            "tool_name": "order.create_refund",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "permissions": ["user:order.read"],
            },
            "payload": {"reason": "误购"},
            "idempotency_key": "tool-invalid-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["code"] == 4001001
    assert payload["user_action_hint"]["action"] == "clarify-tool-input"
    assert payload["user_action_hint"]["missing_fields"] == ["order_no", "amount"]

    audit_response = client.get("/api/v1/tool-calls/tc-invalid-1")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()["data"]
    assert audit_payload["status"] == "invalid-payload"
    assert audit_payload["error"]["details"]["missing_fields"] == ["order_no", "amount"]
    assert audit_payload["user_action_hint"]["action"] == "clarify-tool-input"


def test_tool_list_envelope_uses_configured_request_id_header(monkeypatch) -> None:
    monkeypatch.setattr(tools_routes._settings, "request_id_header", "X-Correlation-Id", raising=False)
    response = client.get("/api/v1/tools", headers={"X-Correlation-Id": "req-custom-1"})
    assert response.status_code == 200
    assert response.json()["requestId"] == "req-custom-1"


def test_tool_list_supports_capability_mode_and_query_filters() -> None:
    response = client.get(
        "/api/v1/tools",
        params={"capability": "finance-order", "mode": "write", "query": "invoice"},
    )
    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["data"]}
    assert names == {"billing.create_invoice"}


def test_internal_tools_call_surfaces_permission_failure_and_audits_it() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-ticket-1",
            "conversation_id": "conv-ticket-1",
            "tool_call_id": "tc-ticket-1",
            "tool_name": "ticket.create",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {"user_id": "u-1"},
            "payload": {"subject": "账单异常", "content": "请帮我排查"},
            "idempotency_key": "tool-tc-ticket-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["code"] == 4030001
    assert payload["error"]["details"]["missing_context"] == ["permission:user:ticket.write"]
    assert payload["user_action_hint"]["action"] == "collect-auth-context"
    assert payload["user_action_hint"]["required_permissions"] == ["user:ticket.write"]

    audit_response = client.get("/api/v1/tool-calls/tc-ticket-1")
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()["data"]
    assert audit_payload["status"] == "auth-required"
    assert audit_payload["error"]["details"]["missing_context"] == ["permission:user:ticket.write"]
    assert audit_payload["user_action_hint"]["action"] == "collect-auth-context"


def test_tool_call_audit_routes_expose_record() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-audit-1",
            "conversation_id": "conv-audit-1",
            "tool_call_id": "tc-audit-1",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "tool-tc-audit-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 200

    detail_response = client.get("/api/v1/tool-calls/tc-audit-1")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["trace_id"] == "trace-audit-1"
    assert detail_payload["status"] == "completed"
    assert detail_payload["summary"]
    assert detail_payload["citations"] == ["baseline://billing-query-statement"]
    assert detail_payload["session_context_patch"]["attributes"]["statement_no"] == "stmt_2026_04_001"

    list_response = client.get("/api/v1/tool-calls", params={"tool_name": "billing.query_statement", "trace_id": "trace-audit-1"})
    assert list_response.status_code == 200
    items = list_response.json()["data"]
    assert any(item["tool_call_id"] == "tc-audit-1" for item in items)


def test_tool_call_audit_list_supports_conversation_and_idempotency_filters() -> None:
    response = internal_client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-audit-2",
            "conversation_id": "conv-audit-2",
            "message_id": "msg-audit-2",
            "tool_call_id": "tc-audit-2",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "tool-conv-audit-2",
            "operation": "execute",
        },
    )
    assert response.status_code == 200

    list_response = client.get(
        "/api/v1/tool-calls",
        params={"conversation_id": "conv-audit-2", "idempotency_key": "tool-conv-audit-2"},
    )
    assert list_response.status_code == 200
    items = list_response.json()["data"]
    assert len(items) == 1
    assert items[0]["tool_call_id"] == "tc-audit-2"
    assert items[0]["message_id"] == "msg-audit-2"

    message_filtered = client.get("/api/v1/tool-calls", params={"message_id": "msg-audit-2"})
    assert message_filtered.status_code == 200
    assert message_filtered.json()["data"][0]["tool_call_id"] == "tc-audit-2"


def test_tool_call_audit_surfaces_query_cache_hits_and_filtering() -> None:
    request_payload = {
        "trace_id": "trace-cache-1",
        "conversation_id": "conv-cache-1",
        "tool_name": "billing.query_statement",
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "user_context": {
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:billing.read"],
        },
        "payload": {"range": "this_month"},
        "idempotency_key": "tool-cache-1",
        "operation": "execute",
    }
    first = client.post(
        "/internal/v1/tools/call",
        headers={"X-Caller-Service": "orchestrator-service"},
        json={**request_payload, "tool_call_id": "tc-cache-1"},
    )
    second = client.post(
        "/internal/v1/tools/call",
        headers={"X-Caller-Service": "orchestrator-service"},
        json={**request_payload, "tool_call_id": "tc-cache-2"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert "cache-hit" in second.json()["audit_tags"]

    audit_response = client.get("/api/v1/tool-calls/tc-cache-2")
    assert audit_response.status_code == 200
    assert "cache-hit" in audit_response.json()["data"]["audit_tags"]

    filtered = client.get("/api/v1/tool-calls", params={"audit_tag": "cache-hit"})
    assert filtered.status_code == 200
    assert any(item["tool_call_id"] == "tc-cache-2" for item in filtered.json()["data"])


def test_internal_compensation_call_executes_business_tools_compensation() -> None:
    response = internal_client.post(
        "/internal/v1/tool-compensations/call",
        json={
            "trace_id": "trace-comp-1",
            "conversation_id": "conv-comp-1",
            "compensation_id": "cmp-1",
            "action_name": "cancel_invoice_request",
            "operator": {"type": "system", "id": "orchestrator-service"},
            "payload": {"invoice_no": "inv_001", "statement_nos": ["stmt_001"]},
            "idempotency_key": "comp-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["compensation_id"] == "cmp-1"
    assert payload["data"]["status"] == "cancelled"


def test_internal_tool_routes_require_allowed_caller() -> None:
    response = client.post(
        "/internal/v1/tools/call",
        json={
            "trace_id": "trace-forbidden-1",
            "conversation_id": "conv-forbidden-1",
            "tool_call_id": "tc-forbidden-1",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "tool-forbidden-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TOOL_HUB_CALLER_FORBIDDEN"


def test_internal_tool_routes_are_not_exposed_on_public_api_prefix() -> None:
    response = client.post(
        "/api/v1/tools/call",
        json={
            "trace_id": "trace-public-1",
            "conversation_id": "conv-public-1",
            "tool_call_id": "tc-public-1",
            "tool_name": "billing.query_statement",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "idempotency_key": "tool-public-1",
            "operation": "execute",
        },
    )
    assert response.status_code == 405
