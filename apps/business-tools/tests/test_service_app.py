from fastapi.testclient import TestClient

from business_tools_service.main import app
from business_tools_service.api.routes import health as health_routes
from business_tools_service.api.routes import tools as tools_routes


client = TestClient(app)
internal_client = TestClient(app, headers={"X-Caller-Service": "tool-hub-service"})


def test_business_tools_service_executes_internal_query_tool() -> None:
    response = internal_client.post(
        "/internal/v1/execute/billing.query_statement",
        headers={
            "X-Trace-Id": "trace-1",
            "X-Tool-Call-Id": "tc-1",
            "X-Tenant-Id": "tenant-a",
        },
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "tenant_id": "tenant-a",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["tool_name"] == "billing.query_statement"
    assert payload["operation"] == "execute"
    assert payload["status"] == "completed"
    assert payload["summary"]
    assert payload["data"]["billing_cycle"].startswith("2026-")
    assert payload["result"]["billing_cycle"].startswith("2026-")
    assert "cache-hit" not in payload["audit_tags"]
    assert payload["session_context_patch"]["attributes"]["statement_no"].startswith("stmt_")


def test_business_tools_service_executes_instance_cost_query_tool() -> None:
    response = internal_client.post(
        "/internal/v1/execute/billing.query_instance_cost",
        headers={
            "X-Trace-Id": "trace-instance-cost-1",
            "X-Tool-Call-Id": "tc-instance-cost-1",
            "X-Tenant-Id": "tenant-a",
        },
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "tenant_id": "tenant-a",
                "permissions": ["user:billing.read"],
            },
            "payload": {"instance_id": "gpu-cn-sh2-01", "range": "this_month"},
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["tool_name"] == "billing.query_instance_cost"
    assert payload["status"] == "completed"
    assert payload["result"]["total_amount"] == 0
    assert payload["session_context_patch"]["attributes"]["instance_id"] == "gpu-cn-sh2-01"
    assert payload["session_context_patch"]["attributes"]["instance_statement_no"].startswith("stmt_")


def test_business_tools_service_executes_product_recommendation_tool() -> None:
    response = internal_client.post(
        "/internal/v1/execute/product.recommend_instance",
        headers={
            "X-Trace-Id": "trace-product-1",
            "X-Tool-Call-Id": "tc-product-1",
        },
        json={
            "operator": {"type": "agent", "id": "Product_Tech_Agent"},
            "subject": {"tenant_id": "tenant-a"},
            "payload": {
                "user_query": "我准备部署 32B 大模型推理服务，帮我推荐 GPU 实例",
                "workload": "inference",
                "model_family": "llm",
                "budget_level": "balanced",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["tool_name"] == "product.recommend_instance"
    assert payload["status"] == "completed"
    assert payload["result"]["recommended_instance_type"] == ""
    # recommended_gpu_model is stripped from attributes when empty (no DB data)
    assert "recommended_gpu_model" not in payload["session_context_patch"]["attributes"]


def test_business_tools_service_executes_service_status_query_tool() -> None:
    response = internal_client.post(
        "/internal/v1/execute/support.query_service_status",
        headers={
            "X-Trace-Id": "trace-service-status-1",
            "X-Tool-Call-Id": "tc-service-status-1",
        },
        json={
            "operator": {"type": "agent", "id": "Product_Tech_Agent"},
            "subject": {"tenant_id": "tenant-a"},
            "payload": {
                "user_query": "gpu-cn-sh2-01 网络异常，帮我查下服务状态",
                "instance_id": "gpu-cn-sh2-01",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["tool_name"] == "support.query_service_status"
    assert payload["status"] == "completed"
    assert payload["result"]["status"] == "degraded"
    assert payload["result"]["region"] == ""
    assert payload["session_context_patch"]["attributes"]["service_status"] == "degraded"
    assert payload["session_context_patch"]["attributes"]["service_affected_instance_id"] == "gpu-cn-sh2-01"


def test_business_tools_service_executes_handoff_brief_tool() -> None:
    response = internal_client.post(
        "/internal/v1/execute/support.handoff_brief",
        headers={
            "X-Trace-Id": "trace-handoff-1",
            "X-Tool-Call-Id": "tc-handoff-1",
        },
        json={
            "operator": {"type": "agent", "id": "Product_Tech_Agent"},
            "subject": {"tenant_id": "tenant-a"},
            "payload": {
                "user_query": "服务异常我要转人工",
                "scene": "technical_support",
                "urgency": "high",
                "conversation_summary": "用户反馈 GPU 推理服务不可用。",
                "related_resources": ["GPU 实例", "gpu-cn-sh2-01"],
                "service_status": "degraded",
                "incident_code": "INC-CNSHANGHAI2-GPUINSTANCE-042",
                "status_summary": "gpu-cn-sh2-01 当前为 degraded，建议尽快处理。",
                "recommended_action": "建议优先检查网络和安全组，并安排值班支持跟进。",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["tool_name"] == "support.handoff_brief"
    assert payload["status"] == "completed"
    assert payload["result"]["queue"] == "technical-support-l2"
    assert payload["result"]["incident_code"] == "INC-CNSHANGHAI2-GPUINSTANCE-042"
    assert payload["session_context_patch"]["attributes"]["human_handoff_severity"] == "high"
    assert payload["session_context_patch"]["attributes"]["human_handoff_incident_code"] == "INC-CNSHANGHAI2-GPUINSTANCE-042"


def test_business_tools_service_lists_input_field_hints() -> None:
    response = internal_client.get("/internal/v1/tools")
    assert response.status_code == 200
    tools = response.json()["tools"]
    instance_cost_tool = next(tool for tool in tools if tool["name"] == "billing.query_instance_cost")
    product_recommend_tool = next(tool for tool in tools if tool["name"] == "product.recommend_instance")
    service_status_tool = next(tool for tool in tools if tool["name"] == "support.query_service_status")
    handoff_tool = next(tool for tool in tools if tool["name"] == "support.handoff_brief")
    ticket_create_tool = next(tool for tool in tools if tool["name"] == "ticket.create")
    refund_tool = next(tool for tool in tools if tool["name"] == "order.create_refund")
    order_query_tool = next(tool for tool in tools if tool["name"] == "order.query_order")
    billing_tool = next(tool for tool in tools if tool["name"] == "billing.query_statement")
    invoice_tool = next(tool for tool in tools if tool["name"] == "billing.create_invoice")
    invoice_query_tool = next(tool for tool in tools if tool["name"] == "invoice.query_invoice")
    ticket_query_tool = next(tool for tool in tools if tool["name"] == "ticket.query_ticket")
    icp_verify_tool = next(tool for tool in tools if tool["name"] == "icp.verify_subject")
    icp_query_tool = next(tool for tool in tools if tool["name"] == "icp.query_application")
    copy_tool = next(tool for tool in tools if tool["name"] == "marketing.generate_copy")
    promotion_tool = next(tool for tool in tools if tool["name"] == "marketing.generate_promotion_link")
    poster_tool = next(tool for tool in tools if tool["name"] == "marketing.generate_poster")
    assert product_recommend_tool["session_context_bindings"]["workload"] == [
        "attributes.recommended_workload"
    ]
    assert instance_cost_tool["session_context_bindings"]["instance_id"] == [
        "attributes.instance_id",
        "attributes.primary_instance_id",
    ]
    assert "attributes.last_instance_cost_total" in instance_cost_tool["session_context_output_keys"]
    assert "attributes.recommended_instance_type" in product_recommend_tool["session_context_output_keys"]
    assert service_status_tool["session_context_bindings"]["instance_id"] == [
        "attributes.instance_id",
        "attributes.primary_instance_id",
        "attributes.service_affected_instance_id",
    ]
    assert "attributes.service_status_summary" in service_status_tool["session_context_output_keys"]
    assert handoff_tool["session_context_bindings"]["conversation_summary"] == ["history_summary"]
    assert handoff_tool["session_context_bindings"]["related_resources"] == ["active_products"]
    assert handoff_tool["session_context_bindings"]["service_status"] == ["attributes.service_status"]
    assert handoff_tool["session_context_bindings"]["incident_code"] == ["attributes.service_incident_code"]
    assert "attributes.human_handoff_summary" in handoff_tool["session_context_output_keys"]
    assert "attributes.human_handoff_incident_code" in handoff_tool["session_context_output_keys"]
    assert ticket_create_tool["session_context_bindings"]["subject"] == [
        "attributes.human_handoff_summary",
        "attributes.service_status_summary",
        "attributes.ticket_subject",
    ]
    assert ticket_create_tool["session_context_bindings"]["incident_code"] == [
        "attributes.human_handoff_incident_code",
        "attributes.service_incident_code",
    ]
    assert "attributes.ticket_queue" in ticket_create_tool["session_context_output_keys"]
    assert billing_tool["session_context_bindings"]["range"] == ["attributes.billing_range"]
    assert order_query_tool["session_context_bindings"]["order_no"] == [
        "attributes.order_no",
        "attributes.refund_order_no",
    ]
    assert ticket_query_tool["session_context_bindings"]["ticket_no"] == ["open_ticket_id"]
    assert icp_verify_tool["session_context_bindings"]["subject_name"] == [
        "attributes.subject_name",
        "attributes.icp_subject_name",
    ]
    assert icp_verify_tool["session_context_bindings"]["contact_email"] == [
        "attributes.contact_email",
        "attributes.icp_contact_email",
        "attributes.contacts.contact_email",
    ]
    assert "attributes.contacts" in icp_verify_tool["session_context_output_keys"]
    assert icp_query_tool["session_context_bindings"]["application_no"] == ["attributes.application_no"]
    icp_submit_tool = next(tool for tool in tools if tool["name"] == "icp.submit_application")
    assert icp_submit_tool["session_context_bindings"]["contacts"] == ["attributes.contacts"]
    assert icp_submit_tool["session_context_bindings"]["contact_name"] == [
        "attributes.contact_name",
        "attributes.icp_contact_name",
        "attributes.contacts.contact_name",
    ]
    assert refund_tool["version"] == "1.0.0"
    assert "order_no" in refund_tool["input_field_hints"]
    assert "amount" in refund_tool["input_field_hints"]
    assert refund_tool["input_schema"]["required"] == ["order_no", "reason", "amount"]
    assert refund_tool["input_schema"]["properties"]["attachments"]["type"] == "array"
    assert refund_tool["output_schema"]["properties"]["requested_amount"]["type"] == "number"
    assert refund_tool["session_context_bindings"]["order_no"] == ["attributes.order_no"]
    assert invoice_tool["prerequisite_tool_names"] == ["billing.query_statement"]
    assert "attributes.invoice_no" in invoice_tool["session_context_output_keys"]
    assert invoice_query_tool["session_context_bindings"]["invoice_no"] == ["attributes.invoice_no"]
    campaign_tool = next(tool for tool in tools if tool["name"] == "marketing.campaign_lookup")
    assert campaign_tool["session_context_bindings"]["product"] == [
        "attributes.recommended_instance_type",
        "attributes.recommended_instance_family",
        "active_products",
    ]
    assert campaign_tool["session_context_bindings"]["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert copy_tool["prerequisite_tool_names"] == ["marketing.campaign_lookup"]
    assert copy_tool["session_context_bindings"]["campaign_name"] == ["attributes.last_campaign_name"]
    assert copy_tool["session_context_bindings"]["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert promotion_tool["prerequisite_tool_names"] == ["marketing.campaign_lookup"]
    assert promotion_tool["session_context_bindings"]["campaign_name"] == ["attributes.last_campaign_name"]
    poster_brief_tool = next(tool for tool in tools if tool["name"] == "marketing.poster_brief")
    assert poster_brief_tool["session_context_bindings"]["theme"] == [
        "attributes.poster_theme",
        "attributes.recommended_instance_summary",
    ]
    assert poster_tool["prerequisite_tool_names"] == ["marketing.poster_brief"]
    assert poster_tool["session_context_bindings"]["theme"] == ["attributes.poster_theme"]
    assert poster_tool["session_context_bindings"]["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert "attributes.poster_asset_id" in poster_tool["session_context_output_keys"]


def test_business_tools_service_filters_tool_catalog() -> None:
    response = internal_client.get(
        "/internal/v1/tools",
        params={"capability": "finance-order", "mode": "write", "query": "invoice"},
    )
    assert response.status_code == 200
    tools = response.json()["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {"billing.create_invoice"}

    marketing_response = internal_client.get(
        "/internal/v1/tools",
        params={"tag": "marketing", "query": "promotion"},
    )
    assert marketing_response.status_code == 200
    marketing_names = {tool["name"] for tool in marketing_response.json()["tools"]}
    assert "marketing.generate_promotion_link" in marketing_names
    assert "marketing.generate_poster" not in marketing_names
    assert "billing.query_statement" not in marketing_names


def test_business_tools_service_returns_single_tool_descriptor() -> None:
    response = internal_client.get("/internal/v1/tools/billing.create_invoice")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "billing.create_invoice"
    assert payload["prerequisite_tool_names"] == ["billing.query_statement"]
    assert payload["session_context_bindings"]["statement_nos"] == [
        "attributes.statement_nos",
        "attributes.statement_no",
    ]


def test_business_tools_service_preflight_returns_provider_contract_metadata() -> None:
    response = internal_client.post(
        "/internal/v1/preflight/order.create_refund",
        headers={"X-Tool-Call-Id": "tc-preflight-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:order.read"]},
            "payload": {"reason": "误购"},
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "missing-payload"
    assert payload["missing_payload_fields"] == ["order_no", "amount"]
    assert payload["session_context_bindings"]["order_no"] == ["attributes.order_no"]
    assert payload["tool_mode"] == "write"
    assert payload["timeout_ms"] == 10000


def test_business_tools_service_surfaces_query_cache_hits() -> None:
    request_payload = {
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "subject": {
            "user_id": "u-1",
            "account_id": "acct-1",
            "tenant_id": "tenant-a",
            "permissions": ["user:billing.read"],
        },
        "payload": {"range": "this_month"},
        "operation": "execute",
    }
    first = client.post(
        "/internal/v1/execute/billing.query_statement",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-cache-1",
            "X-Message-Id": "msg-cache-1",
            "X-Tenant-Id": "tenant-a",
        },
        json=request_payload,
    )
    second = client.post(
        "/internal/v1/execute/billing.query_statement",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-cache-2",
            "X-Message-Id": "msg-cache-2",
            "X-Tenant-Id": "tenant-a",
        },
        json=request_payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert "cache-hit" in second.json()["audit_tags"]


def test_business_tools_service_requires_confirmation_for_writes() -> None:
    response = internal_client.post(
        "/internal/v1/execute/order.create_refund",
        headers={"X-Tool-Call-Id": "tc-2"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:order.read"]},
            "payload": {"order_no": "ord-1", "reason": "误购", "amount": 88.8},
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["code"] == 4090002
    assert payload["user_action_hint"]["action"] == "user-confirmation"
    assert payload["user_action_hint"]["confirm_tool_names"] == ["order.create_refund"]


def test_business_tools_service_executes_order_and_invoice_status_queries() -> None:
    order_response = internal_client.post(
        "/internal/v1/execute/order.query_order",
        headers={"X-Tool-Call-Id": "tc-order-query-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:order.read"]},
            "payload": {
                "order_no": "ord_20260416_001",
                "refund_no": "refund_ord_20260416_001",
            },
            "operation": "execute",
        },
    )
    invoice_response = internal_client.post(
        "/internal/v1/execute/invoice.query_invoice",
        headers={"X-Tool-Call-Id": "tc-invoice-query-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:billing.read"]},
            "payload": {
                "invoice_no": "inv_001_20260416",
                "title": "某某科技",
            },
            "operation": "execute",
        },
    )

    assert order_response.status_code == 200
    assert invoice_response.status_code == 200
    order_payload = order_response.json()
    invoice_payload = invoice_response.json()
    assert order_payload["success"] is True
    assert order_payload["data"]["order_status"] == "refunding"
    assert order_payload["session_context_patch"]["attributes"]["refund_status"] == "processing"
    assert invoice_payload["success"] is True
    assert invoice_payload["data"]["status"] == ""
    assert invoice_payload["session_context_patch"]["attributes"]["invoice_no"] == "inv_001_20260416"


def test_business_tools_service_executes_ticket_and_icp_status_queries() -> None:
    ticket_response = internal_client.post(
        "/internal/v1/execute/ticket.query_ticket",
        headers={"X-Tool-Call-Id": "tc-ticket-query-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:ticket.read"]},
            "payload": {
                "ticket_no": "tk_billing_001",
                "subject": "账单异常",
            },
            "operation": "execute",
        },
    )
    icp_response = internal_client.post(
        "/internal/v1/execute/icp.query_application",
        headers={"X-Tool-Call-Id": "tc-icp-query-1"},
        json={
            "operator": {"type": "agent", "id": "ICP_Service_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:icp.read"]},
            "payload": {
                "application_no": "icp_demo_example_com",
                "domain": "demo.example.com",
            },
            "operation": "execute",
        },
    )

    assert ticket_response.status_code == 200
    assert icp_response.status_code == 200
    ticket_payload = ticket_response.json()
    icp_payload = icp_response.json()
    assert ticket_payload["success"] is True
    assert ticket_payload["data"]["status"] == "processing"
    assert ticket_payload["session_context_patch"]["open_ticket_id"] == "tk_billing_001"
    assert icp_payload["success"] is True
    assert icp_payload["data"]["status"] == "provider_review"
    assert icp_payload["session_context_patch"]["attributes"]["application_no"] == "icp_demo_example_com"


def test_business_tools_service_executes_icp_subject_verification() -> None:
    response = internal_client.post(
        "/internal/v1/execute/icp.verify_subject",
        headers={"X-Tool-Call-Id": "tc-icp-verify-1"},
        json={
            "operator": {"type": "agent", "id": "ICP_Service_Agent"},
            "subject": {"user_id": "u-1", "permissions": ["user:icp.read"]},
            "payload": {
                "subject_type": "enterprise",
                "subject_name": "上海示例科技有限公司",
                "certificate_no": "91310000MA1CTEST88",
                "contact_name": "张三",
                "contact_phone": "13800138000",
                "contact_email": "icp@example.com",
            },
            "operation": "execute",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["verification_status"] == "verified"
    assert payload["session_context_patch"]["attributes"]["subject_name"] == "上海示例科技有限公司"
    assert payload["session_context_patch"]["attributes"]["contacts"]["contact_phone"] == "13800138000"
    assert payload["session_context_patch"]["attributes"]["contacts"]["contact_email"] == "icp@example.com"


def test_business_tools_service_returns_preview_confirmation_hint_for_high_risk_write() -> None:
    response = internal_client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={"X-Tool-Call-Id": "tc-preview-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "某某科技",
            },
            "operation": "preview",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["status"] == "preview-ready"
    assert payload["user_action_hint"]["action"] == "user-confirmation"
    assert payload["user_action_hint"]["confirm_tool_names"] == ["billing.create_invoice"]


def test_business_tools_service_returns_auth_required_for_ticket_write_without_permission() -> None:
    response = internal_client.post(
        "/internal/v1/execute/ticket.create",
        headers={"X-Tool-Call-Id": "tc-ticket-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {"user_id": "u-1"},
            "payload": {"subject": "账单异常", "content": "请帮我排查"},
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["code"] == 4030001
    assert "permission:user:ticket.write" in payload["error_detail"]["missing_context"]
    assert payload["user_action_hint"]["action"] == "collect-auth-context"
    assert payload["user_action_hint"]["required_permissions"] == ["user:ticket.write"]
    assert payload["user_action_hint"]["user_profile_bindings"] == {"permissions": ["permissions"]}


def test_business_tools_service_executes_ticket_create_with_handoff_context() -> None:
    response = internal_client.post(
        "/internal/v1/execute/ticket.create",
        headers={"X-Tool-Call-Id": "tc-ticket-handoff-1"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:ticket.write"],
            },
            "payload": {
                "scene": "technical_support",
                "subject": "gpu-cn-sh2-01 异常工单",
                "content": "gpu-cn-sh2-01 当前为 degraded，建议确认受影响资源范围。",
                "queue": "technical-support-l2",
                "incident_code": "INC-CNSHANGHAI2-GPUINSTANCE-042",
                "service_status": "degraded",
                "status_summary": "gpu-cn-sh2-01 当前为 degraded，建议确认受影响资源范围。",
                "related_resources": ["gpu-cn-sh2-01", "GPU 实例服务"],
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["tool_name"] == "ticket.create"
    assert payload["result"]["queue"] == "technical-support-l2"
    assert payload["result"]["incident_code"] == "INC-CNSHANGHAI2-GPUINSTANCE-042"
    assert payload["result"]["subject"].startswith("gpu-cn-sh2-01 异常工单")
    assert payload["session_context_patch"]["attributes"]["ticket_queue"] == "technical-support-l2"
    assert payload["session_context_patch"]["attributes"]["ticket_incident_code"] == "INC-CNSHANGHAI2-GPUINSTANCE-042"


def test_business_tools_service_returns_compensation_for_confirmed_write() -> None:
    response = internal_client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={"X-Tool-Call-Id": "tc-3", "Idempotency-Key": "tool-tc-3"},
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
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
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["compensation"]["action_name"] == "cancel_invoice_request"
    assert payload["idempotency_key"] == "tool-tc-3"


def test_business_tools_service_executes_promotion_link_write() -> None:
    response = internal_client.post(
        "/internal/v1/execute/marketing.generate_promotion_link",
        headers={"X-Tool-Call-Id": "tc-promo-1", "Idempotency-Key": "promo-1"},
        json={
            "operator": {"type": "agent", "id": "Ops_Marketing_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:marketing.write"],
            },
            "payload": {
                "campaign_name": "GPU 新客满减",
                "channel": "wechat",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["short_url"].startswith(("/promo/", "/p/"))
    assert payload["compensation"]["action_name"] == "deactivate_promotion_link"
    assert payload["session_context_patch"]["attributes"]["last_promotion_link"] == payload["data"]["short_url"]


def test_business_tools_service_executes_poster_generation_write() -> None:
    response = internal_client.post(
        "/internal/v1/execute/marketing.generate_poster",
        headers={"X-Tool-Call-Id": "tc-poster-1", "Idempotency-Key": "poster-1"},
        json={
            "operator": {"type": "agent", "id": "Ops_Marketing_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:marketing.write"],
            },
            "payload": {
                "theme": "GPU 算力活动海报",
                "campaign_name": "GPU 新客满减",
                "headline": "GPU 新客满减限时开启",
                "size": "portrait",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["poster_asset_id"].startswith("poster_")
    assert payload["compensation"]["action_name"] == "delete_poster_asset"
    assert payload["session_context_patch"]["attributes"]["poster_asset_id"] == payload["data"]["poster_asset_id"]
    assert payload["session_context_patch"]["attributes"]["poster_download_path"] == payload["data"]["download_path"]


def test_business_tools_service_generates_marketing_copy() -> None:
    response = internal_client.post(
        "/internal/v1/execute/marketing.generate_copy",
        headers={"X-Tool-Call-Id": "tc-copy-1"},
        json={
            "operator": {"type": "agent", "id": "Ops_Marketing_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:marketing.write"],
            },
            "payload": {
                "campaign_name": "GPU 新客满减",
                "product": "GPU 实例",
                "product_summary": "gi4.2xlarge / NVIDIA L40S x2",
                "channel": "wechat",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["headline"].startswith("GPU 新客满减")
    assert payload["data"]["product_summary"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert payload["session_context_patch"]["attributes"]["last_marketing_copy_headline"] == payload["data"]["headline"]
    assert (
        payload["session_context_patch"]["attributes"]["last_marketing_product_summary"]
        == "gi4.2xlarge / NVIDIA L40S x2"
    )


def test_business_tools_service_campaign_lookup_uses_recommended_product_summary() -> None:
    response = internal_client.post(
        "/internal/v1/execute/marketing.campaign_lookup",
        headers={"X-Tool-Call-Id": "tc-campaign-summary-1"},
        json={
            "operator": {"type": "agent", "id": "Ops_Marketing_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:marketing.read"],
            },
            "payload": {
                "product_summary": "gi4.2xlarge / NVIDIA L40S x2",
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["matched_product"] == "gi4.2xlarge / NVIDIA L40S x2"
    # campaigns list is empty when no DB data
    assert payload["data"]["campaigns"] == []
    assert (
        payload["session_context_patch"]["attributes"]["last_marketing_product_summary"]
        == "gi4.2xlarge / NVIDIA L40S x2"
    )


def test_business_tools_service_exports_research_report() -> None:
    response = internal_client.post(
        "/internal/v1/execute/research.export_report",
        headers={"X-Tool-Call-Id": "tc-report-1", "Idempotency-Key": "report-1"},
        json={
            "operator": {"type": "agent", "id": "Deep_Research_Agent"},
            "subject": {
                "user_id": "u-1",
                "permissions": ["user:research.write"],
            },
            "payload": {
                "topic": "LangGraph 选型调研",
                "format": "markdown",
                "outline": ["业务背景与目标", "候选方案对比"],
            },
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["download_path"].endswith(".md")
    assert payload["session_context_patch"]["attributes"]["last_report_export_format"] == "markdown"


def test_business_tools_service_replays_confirmed_write_by_idempotency_key() -> None:
    payload = {
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "subject": {
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:billing.read"],
        },
        "payload": {
            "statement_nos": ["stmt_901"],
            "invoice_type": "vat_special",
            "title": "某某科技",
            "_confirmed": True,
        },
        "operation": "execute",
    }
    first = client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-idem-1",
            "Idempotency-Key": "tool-idem-1",
        },
        json=payload,
    )
    replay = client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-idem-2",
            "Idempotency-Key": "tool-idem-1",
        },
        json=payload,
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["data"]["invoice_no"] == first.json()["data"]["invoice_no"]


def test_business_tools_service_scopes_same_idempotency_key_by_tenant() -> None:
    tenant_a_payload = {
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "subject": {
            "tenant_id": "tenant-a",
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:billing.read"],
        },
        "payload": {
            "statement_nos": ["stmt_901"],
            "invoice_type": "vat_special",
            "title": "某某科技",
            "_confirmed": True,
        },
        "operation": "execute",
    }
    tenant_b_payload = {
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "subject": {
            "tenant_id": "tenant-b",
            "user_id": "u-2",
            "account_id": "acct-2",
            "permissions": ["user:billing.read"],
        },
        "payload": {
            "statement_nos": ["stmt_901"],
            "invoice_type": "vat_special",
            "title": "某某科技",
            "_confirmed": True,
        },
        "operation": "execute",
    }

    first = client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-idem-scope-1",
            "Idempotency-Key": "tool-idem-scope-1",
        },
        json=tenant_a_payload,
    )
    second = client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-idem-scope-2",
            "Idempotency-Key": "tool-idem-scope-1",
        },
        json=tenant_b_payload,
    )
    replay_first_tenant = client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Tool-Call-Id": "tc-idem-scope-3",
            "Idempotency-Key": "tool-idem-scope-1",
        },
        json=tenant_a_payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert replay_first_tenant.status_code == 200
    assert first.json()["success"] is True
    assert second.json()["success"] is True
    assert replay_first_tenant.json()["success"] is True
    assert second.json()["status"] == "completed"
    assert "idempotent-replay" not in first.json()["audit_tags"]
    assert "idempotent-replay" not in second.json()["audit_tags"]
    assert "idempotent-replay" in replay_first_tenant.json()["audit_tags"]


def test_business_tools_service_executes_compensation_route() -> None:
    response = internal_client.post(
        "/internal/v1/compensations/execute",
        headers={"X-Trace-Id": "trace-comp-1", "Idempotency-Key": "comp-1"},
        json={
            "compensation_id": "cmp-1",
            "conversation_id": "conv-comp-1",
            "action_name": "cancel_invoice_request",
            "operator": {"type": "system", "id": "orchestrator-service"},
            "payload": {"invoice_no": "inv_001", "statement_nos": ["stmt_001"]},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["compensation_id"] == "cmp-1"
    assert payload["action_name"] == "cancel_invoice_request"
    assert payload["data"]["status"] == "cancelled"


def test_business_tools_service_honors_configured_header_names(monkeypatch) -> None:
    monkeypatch.setattr(tools_routes._settings, "trace_id_header", "X-Trace-Token", raising=False)
    monkeypatch.setattr(tools_routes._settings, "tool_call_id_header", "X-Tool-Token", raising=False)
    monkeypatch.setattr(tools_routes._settings, "tenant_id_header", "X-Tenant-Token", raising=False)
    monkeypatch.setattr(tools_routes._settings, "idempotency_key_header", "X-Idempotency-Token", raising=False)

    response = client.post(
        "/internal/v1/execute/billing.create_invoice",
        headers={
            "X-Caller-Service": "tool-hub-service",
            "X-Trace-Token": "trace-custom-1",
            "X-Tool-Token": "tc-custom-1",
            "X-Tenant-Token": "tenant-custom-1",
            "X-Idempotency-Token": "tool-custom-1",
        },
        json={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
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
            "operation": "execute",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["idempotency_key"] == "tool-custom-1"


def test_business_tools_service_requires_allowed_caller() -> None:
    response = client.get("/internal/v1/tools")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "BUSINESS_TOOLS_CALLER_FORBIDDEN"


def test_business_tools_healthz_and_readyz_report_runtime_status(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "idempotency": {"backend": "redis", "configured": True},
            "queryCache": {"backend": "redis-ttl", "configured": True},
        },
    )

    health_response = client.get("/healthz")
    ready_response = client.get("/readyz")

    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert ready_response.status_code == 200
    assert ready_response.json()["status"] == "ready"
    assert ready_response.json()["not_ready_components"] == []


def test_business_tools_readyz_reports_degraded_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        health_routes,
        "_runtime_snapshot",
        lambda: {
            "idempotency": {"backend": "json-file", "degradedFrom": "redis"},
            "queryCache": {"backend": "redis-ttl", "configured": True},
        },
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["not_ready_components"] == ["idempotency"]
