from business_tools import (
    CompensationExecutionRequest,
    ToolExecutionContext,
    ToolInvocationRequest,
    preflight_tool_invocation,
    build_catalog,
    execute_compensation,
)


def test_catalog_contains_spec_and_legacy_tools() -> None:
    catalog = build_catalog()
    assert "billing.query_statement" in catalog
    assert "billing.query_instance_cost" in catalog
    assert "product.recommend_instance" in catalog
    assert "support.query_service_status" in catalog
    assert "support.handoff_brief" in catalog
    assert "order.query_order" in catalog
    assert "invoice.query_invoice" in catalog
    assert "ticket.query_ticket" in catalog
    assert "icp.verify_subject" in catalog
    assert "icp.query_application" in catalog
    assert "order.create_refund" in catalog
    assert "marketing.generate_copy" in catalog
    assert "marketing.generate_promotion_link" in catalog
    assert "marketing.generate_poster" in catalog
    assert "research.generate_report" in catalog
    assert "research.export_report" in catalog
    assert "billing.summary" in catalog


def test_tool_definitions_include_spec_metadata_and_json_schema() -> None:
    catalog = build_catalog()
    definition = catalog["billing.query_statement"].definition

    assert definition.version == "1.0.0"
    assert definition.input_schema["type"] == "object"
    assert definition.input_schema["required"] == ["range"]
    assert definition.input_schema["properties"]["range"]["enum"] == [
        "this_month",
        "last_month",
        "last_3_months",
        "custom",
    ]
    assert definition.input_schema["properties"]["start_date"]["nullable"] is True
    assert definition.output_schema["properties"]["total_amount"]["type"] == "number"
    assert definition.output_schema["properties"]["statement_nos"]["type"] == "array"


def test_tool_definitions_expose_session_context_bindings_and_dependencies() -> None:
    catalog = build_catalog()
    invoice_definition = catalog["billing.create_invoice"].definition
    billing_definition = catalog["billing.query_statement"].definition
    instance_cost_definition = catalog["billing.query_instance_cost"].definition
    product_recommend_definition = catalog["product.recommend_instance"].definition
    service_status_definition = catalog["support.query_service_status"].definition
    handoff_definition = catalog["support.handoff_brief"].definition
    order_query_definition = catalog["order.query_order"].definition
    invoice_query_definition = catalog["invoice.query_invoice"].definition
    ticket_create_definition = catalog["ticket.create"].definition
    ticket_query_definition = catalog["ticket.query_ticket"].definition
    icp_verify_definition = catalog["icp.verify_subject"].definition
    icp_query_definition = catalog["icp.query_application"].definition
    copy_definition = catalog["marketing.generate_copy"].definition
    promotion_definition = catalog["marketing.generate_promotion_link"].definition
    poster_definition = catalog["marketing.generate_poster"].definition
    export_definition = catalog["research.export_report"].definition

    assert billing_definition.session_context_bindings["range"] == ["attributes.billing_range"]
    assert instance_cost_definition.session_context_bindings["instance_id"] == [
        "attributes.instance_id",
        "attributes.primary_instance_id",
    ]
    assert "attributes.last_instance_cost_total" in instance_cost_definition.session_context_output_keys
    assert product_recommend_definition.session_context_bindings["workload"] == [
        "attributes.recommended_workload"
    ]
    assert "attributes.recommended_instance_type" in product_recommend_definition.session_context_output_keys
    assert service_status_definition.session_context_bindings["instance_id"] == [
        "attributes.instance_id",
        "attributes.primary_instance_id",
        "attributes.service_affected_instance_id",
    ]
    assert "attributes.service_status_summary" in service_status_definition.session_context_output_keys
    assert handoff_definition.session_context_bindings["conversation_summary"] == ["history_summary"]
    assert handoff_definition.session_context_bindings["related_resources"] == ["active_products"]
    assert handoff_definition.session_context_bindings["service_status"] == ["attributes.service_status"]
    assert handoff_definition.session_context_bindings["incident_code"] == ["attributes.service_incident_code"]
    assert "attributes.human_handoff_summary" in handoff_definition.session_context_output_keys
    assert "attributes.human_handoff_incident_code" in handoff_definition.session_context_output_keys
    assert order_query_definition.session_context_bindings["order_no"] == [
        "attributes.order_no",
        "attributes.refund_order_no",
    ]
    assert invoice_query_definition.session_context_bindings["invoice_no"] == ["attributes.invoice_no"]
    assert invoice_definition.session_context_bindings["statement_nos"] == [
        "attributes.statement_nos",
        "attributes.statement_no",
    ]
    assert invoice_definition.session_context_bindings["title"] == ["attributes.invoice_title"]
    assert invoice_definition.prerequisite_tool_names == ["billing.query_statement"]
    assert set(billing_definition.session_context_output_keys) >= {
        "attributes.statement_nos",
        "attributes.statement_no",
        "attributes.billing_cycle",
        "attributes.primary_instance_id",
    }
    assert ticket_create_definition.session_context_bindings["subject"] == [
        "attributes.human_handoff_summary",
        "attributes.service_status_summary",
        "attributes.ticket_subject",
    ]
    assert ticket_create_definition.session_context_bindings["queue"] == [
        "attributes.human_handoff_queue",
        "attributes.ticket_queue",
    ]
    assert ticket_create_definition.session_context_bindings["incident_code"] == [
        "attributes.human_handoff_incident_code",
        "attributes.service_incident_code",
    ]
    assert "attributes.ticket_queue" in ticket_create_definition.session_context_output_keys
    assert "attributes.ticket_incident_code" in ticket_create_definition.session_context_output_keys
    assert ticket_query_definition.session_context_bindings["ticket_no"] == ["open_ticket_id"]
    assert "attributes.ticket_latest_action" in ticket_query_definition.session_context_output_keys
    assert icp_verify_definition.session_context_bindings["subject_name"] == [
        "attributes.subject_name",
        "attributes.icp_subject_name",
    ]
    assert icp_verify_definition.session_context_bindings["contact_email"] == [
        "attributes.contact_email",
        "attributes.icp_contact_email",
        "attributes.contacts.contact_email",
    ]
    assert "attributes.contacts" in icp_verify_definition.session_context_output_keys
    submit_definition = catalog["icp.submit_application"].definition
    assert submit_definition.session_context_bindings["contacts"] == ["attributes.contacts"]
    assert submit_definition.session_context_bindings["contact_phone"] == [
        "attributes.contact_phone",
        "attributes.icp_contact_phone",
        "attributes.contacts.contact_phone",
    ]
    assert "attributes.website_name" in submit_definition.session_context_output_keys
    assert icp_query_definition.session_context_bindings["application_no"] == ["attributes.application_no"]
    assert "attributes.icp_current_step" in icp_query_definition.session_context_output_keys
    campaign_definition = catalog["marketing.campaign_lookup"].definition
    assert campaign_definition.session_context_bindings["product"] == [
        "attributes.recommended_instance_type",
        "attributes.recommended_instance_family",
        "active_products",
    ]
    assert campaign_definition.session_context_bindings["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert copy_definition.session_context_bindings["campaign_name"] == ["attributes.last_campaign_name"]
    assert copy_definition.session_context_bindings["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert copy_definition.prerequisite_tool_names == ["marketing.campaign_lookup"]
    assert promotion_definition.session_context_bindings["campaign_name"] == ["attributes.last_campaign_name"]
    assert promotion_definition.prerequisite_tool_names == ["marketing.campaign_lookup"]
    poster_brief_definition = catalog["marketing.poster_brief"].definition
    assert poster_brief_definition.session_context_bindings["theme"] == [
        "attributes.poster_theme",
        "attributes.recommended_instance_summary",
    ]
    assert poster_definition.session_context_bindings["theme"] == ["attributes.poster_theme"]
    assert poster_definition.session_context_bindings["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert poster_definition.session_context_bindings["headline"] == [
        "attributes.poster_headline",
        "attributes.last_marketing_copy_headline",
    ]
    assert poster_definition.prerequisite_tool_names == ["marketing.poster_brief"]
    assert export_definition.session_context_bindings["topic"] == ["attributes.research_topic"]
    assert export_definition.prerequisite_tool_names == ["research.reference_search"]


def test_billing_execute_flags_missing_auth_context() -> None:
    catalog = build_catalog()
    result = catalog["billing.query_statement"].invoke(
        ToolInvocationRequest(
            tool_name="billing.query_statement",
            operation="execute",
            payload={"range": "this_month"},
            context=ToolExecutionContext(),
        )
    )
    assert result.status == "auth-required"
    assert "account_id" in result.result["missing_context"]
    assert "permission:user:billing.read" in result.result["missing_context"]
    assert result.user_action_hint is not None
    assert result.user_action_hint.user_profile_bindings == {
        "user_id": ["user_id"],
        "account_id": ["account_id"],
        "permissions": ["permissions"],
    }


def test_billing_execute_returns_session_context_patch() -> None:
    catalog = build_catalog()
    result = catalog["billing.query_statement"].invoke(
        ToolInvocationRequest(
            tool_name="billing.query_statement",
            operation="execute",
            payload={"range": "this_month"},
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
            ),
        )
    )
    assert result.success is True
    assert result.session_context_patch["attributes"]["billing_range"] == "this_month"
    assert result.session_context_patch["attributes"]["billing_cycle"] == "2026-04"
    assert result.session_context_patch["attributes"]["statement_no"] == "stmt_2026_04_001"
    assert result.session_context_patch["attributes"]["primary_instance_id"] == "gpu-cn-sh2-01"
    assert "GPU 实例" in result.session_context_patch["active_products"]


def test_billing_instance_cost_query_returns_session_context_patch() -> None:
    catalog = build_catalog()
    result = catalog["billing.query_instance_cost"].invoke(
        ToolInvocationRequest(
            tool_name="billing.query_instance_cost",
            operation="execute",
            payload={"instance_id": "gpu-cn-sh2-01", "range": "this_month"},
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
            ),
        )
    )

    assert result.success is True
    assert result.result["product"] == "GPU 实例"
    assert result.result["billing_cycle"] == "2026-04"
    assert result.session_context_patch["attributes"]["instance_id"] == "gpu-cn-sh2-01"
    assert result.session_context_patch["attributes"]["last_instance_cost_total"] == 412.68
    assert result.session_context_patch["attributes"]["instance_statement_no"] == "stmt_2026_04_001"
    assert result.session_context_patch["active_products"] == ["GPU 实例"]


def test_product_recommendation_returns_session_context_patch() -> None:
    catalog = build_catalog()
    result = catalog["product.recommend_instance"].invoke(
        ToolInvocationRequest(
            tool_name="product.recommend_instance",
            operation="execute",
            payload={
                "user_query": "我准备部署 32B 大模型推理服务，帮我推荐 GPU 实例",
                "workload": "inference",
                "model_family": "llm",
                "budget_level": "balanced",
            },
            context=ToolExecutionContext(),
        )
    )

    assert result.success is True
    assert result.result["recommended_instance_type"] == "gi4.2xlarge"
    assert result.result["gpu_model"] == "NVIDIA L40S"
    assert result.session_context_patch["attributes"]["recommended_instance_type"] == "gi4.2xlarge"
    assert result.session_context_patch["attributes"]["recommended_gpu_model"] == "NVIDIA L40S"
    assert "GPU-GI4" in result.session_context_patch["active_products"]


def test_service_status_query_returns_diagnostic_session_context_patch() -> None:
    catalog = build_catalog()
    result = catalog["support.query_service_status"].invoke(
        ToolInvocationRequest(
            tool_name="support.query_service_status",
            operation="execute",
            payload={
                "user_query": "gpu-cn-sh2-01 网络异常，帮我查下服务状态",
                "instance_id": "gpu-cn-sh2-01",
            },
            context=ToolExecutionContext(),
        )
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.result["status"] == "degraded"
    assert result.result["region"] == "cn-shanghai-2"
    assert result.result["incident_code"].startswith("INC-CNSHANGHAI2-")
    assert result.session_context_patch["attributes"]["service_status"] == "degraded"
    assert result.session_context_patch["attributes"]["service_affected_instance_id"] == "gpu-cn-sh2-01"
    assert result.session_context_patch["attributes"]["service_name"] == "实例网络连通性"
    assert result.session_context_patch["active_products"] == ["实例网络连通性"]


def test_handoff_brief_returns_human_operator_packet_and_session_patch() -> None:
    catalog = build_catalog()
    result = catalog["support.handoff_brief"].invoke(
        ToolInvocationRequest(
            tool_name="support.handoff_brief",
            operation="execute",
            payload={
                "user_query": "服务异常我要转人工",
                "scene": "technical_support",
                "urgency": "high",
                "conversation_summary": "用户反馈 GPU 推理服务不可用。",
                "related_resources": ["GPU 实例", "gpu-cn-sh2-01"],
                "service_status": "degraded",
                "incident_code": "INC-CNSHANGHAI2-GPU-042",
                "status_summary": "gpu-cn-sh2-01 当前为 degraded，建议尽快处理。",
                "recommended_action": "建议优先检查网络和安全组，并安排值班支持跟进。",
            },
            context=ToolExecutionContext(),
        )
    )

    assert result.success is True
    assert result.status == "completed"
    assert result.result["queue"] == "technical-support-l2"
    assert result.result["severity"] == "high"
    assert result.result["reason"] == "service_exception"
    assert "用户请求人工介入" in result.result["summary"]
    assert "状态检查" in result.result["summary"]
    assert result.result["incident_code"] == "INC-CNSHANGHAI2-GPU-042"
    assert result.session_context_patch["attributes"]["human_handoff_queue"] == "technical-support-l2"
    assert result.session_context_patch["attributes"]["human_handoff_service_status"] == "degraded"
    assert result.session_context_patch["attributes"]["human_handoff_incident_code"] == "INC-CNSHANGHAI2-GPU-042"
    assert result.session_context_patch["attributes"]["human_handoff_related_resources"] == [
        "GPU 实例",
        "gpu-cn-sh2-01",
    ]


def test_order_and_invoice_query_tools_return_session_context_patch() -> None:
    catalog = build_catalog()
    order_result = catalog["order.query_order"].invoke(
        ToolInvocationRequest(
            tool_name="order.query_order",
            operation="execute",
            payload={"order_no": "ord_20260416_001", "refund_no": "refund_ord_20260416_001"},
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:order.read"],
            ),
        )
    )
    invoice_result = catalog["invoice.query_invoice"].invoke(
        ToolInvocationRequest(
            tool_name="invoice.query_invoice",
            operation="execute",
            payload={"invoice_no": "inv_001_20260416", "title": "某某科技"},
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:billing.read"],
            ),
        )
    )

    assert order_result.success is True
    assert order_result.session_context_patch["attributes"]["order_no"] == "ord_20260416_001"
    assert order_result.session_context_patch["attributes"]["refund_status"] == "processing"
    assert invoice_result.success is True
    assert invoice_result.session_context_patch["attributes"]["invoice_no"] == "inv_001_20260416"
    assert invoice_result.session_context_patch["attributes"]["invoice_title"] == "某某科技"


def test_ticket_and_icp_query_tools_return_session_context_patch() -> None:
    catalog = build_catalog()
    ticket_result = catalog["ticket.query_ticket"].invoke(
        ToolInvocationRequest(
            tool_name="ticket.query_ticket",
            operation="execute",
            payload={"ticket_no": "tk_billing_001", "subject": "账单异常"},
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:ticket.read"],
            ),
        )
    )
    verify_result = catalog["icp.verify_subject"].invoke(
        ToolInvocationRequest(
            tool_name="icp.verify_subject",
            operation="execute",
            payload={
                "subject_type": "enterprise",
                "subject_name": "上海示例科技有限公司",
                "certificate_no": "91310000MA1CTEST88",
                "contact_name": "张三",
                "contact_phone": "13800138000",
                "contact_email": "icp@example.com",
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:icp.read"],
            ),
        )
    )
    icp_result = catalog["icp.query_application"].invoke(
        ToolInvocationRequest(
            tool_name="icp.query_application",
            operation="execute",
            payload={"application_no": "icp_demo_example_com", "domain": "demo.example.com"},
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:icp.read"],
            ),
        )
    )

    assert ticket_result.success is True
    assert ticket_result.session_context_patch["open_ticket_id"] == "tk_billing_001"
    assert ticket_result.session_context_patch["attributes"]["ticket_status"] == "processing"
    assert verify_result.success is True
    assert verify_result.session_context_patch["attributes"]["subject_name"] == "上海示例科技有限公司"
    assert verify_result.session_context_patch["attributes"]["icp_real_name_verified"] is True
    assert verify_result.session_context_patch["attributes"]["contacts"]["contact_phone"] == "13800138000"
    assert verify_result.session_context_patch["attributes"]["contacts"]["contact_email"] == "icp@example.com"
    assert verify_result.session_context_patch["attributes"]["icp_certificate_no"] == "91310000MA1CTEST88"
    assert icp_result.success is True
    assert icp_result.session_context_patch["attributes"]["application_no"] == "icp_demo_example_com"
    assert icp_result.session_context_patch["attributes"]["icp_status"] == "provider_review"


def test_icp_submit_application_persists_contact_and_website_context() -> None:
    catalog = build_catalog()
    result = catalog["icp.submit_application"].invoke(
        ToolInvocationRequest(
            tool_name="icp.submit_application",
            operation="execute",
            payload={
                "subject_type": "enterprise",
                "domain": "demo.example.com",
                "website_name": "演示站点",
                "contacts": {
                    "contact_name": "张三",
                    "contact_phone": "13800138000",
                    "contact_email": "icp@example.com",
                },
                "materials": [{"name": "营业执照"}],
                "_confirmed": True,
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:icp.write"],
            ),
        )
    )

    assert result.success is True
    assert result.session_context_patch["attributes"]["icp_domain"] == "demo.example.com"
    assert result.session_context_patch["attributes"]["website_name"] == "演示站点"
    assert result.session_context_patch["attributes"]["contacts"]["contact_email"] == "icp@example.com"


def test_query_tool_reuses_cached_result_with_audit_tag() -> None:
    catalog = build_catalog()
    request = ToolInvocationRequest(
        tool_name="billing.query_statement",
        operation="execute",
        payload={"range": "this_month"},
        context=ToolExecutionContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
        ),
    )
    first = catalog["billing.query_statement"].invoke(request)
    second = catalog["billing.query_statement"].invoke(request)
    assert first.success is True
    assert second.success is True
    assert second.result == first.result
    assert "cache-hit" in second.audit_tags


def test_high_risk_write_requires_confirmation() -> None:
    catalog = build_catalog()
    result = catalog["billing.create_invoice"].invoke(
        ToolInvocationRequest(
            tool_name="billing.create_invoice",
            operation="execute",
            payload={
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "上海某某科技有限公司",
            },
            context=ToolExecutionContext(user_id="u-1", permissions=["user:billing.read"]),
        )
    )
    assert result.status == "confirmation-required"
    assert result.success is False


def test_high_risk_write_preview_returns_confirmation_hint() -> None:
    catalog = build_catalog()
    result = catalog["billing.create_invoice"].invoke(
        ToolInvocationRequest(
            tool_name="billing.create_invoice",
            operation="preview",
            payload={
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "上海某某科技有限公司",
            },
            context=ToolExecutionContext(user_id="u-1", permissions=["user:billing.read"]),
        )
    )
    assert result.success is True
    assert result.status == "preview-ready"
    assert result.user_action_hint is not None
    assert result.user_action_hint.action == "user-confirmation"
    assert result.user_action_hint.confirm_tool_names == ["billing.create_invoice"]


def test_ticket_create_requires_ticket_write_permission() -> None:
    catalog = build_catalog()
    result = catalog["ticket.create"].invoke(
        ToolInvocationRequest(
            tool_name="ticket.create",
            operation="execute",
            payload={"subject": "账单异常", "content": "请帮我排查"},
            context=ToolExecutionContext(user_id="u-1"),
        )
    )
    assert result.status == "auth-required"
    assert "permission:user:ticket.write" in result.result["missing_context"]


def test_ticket_create_reuses_handoff_context_for_ticket_summary() -> None:
    catalog = build_catalog()
    result = catalog["ticket.create"].invoke(
        ToolInvocationRequest(
            tool_name="ticket.create",
            operation="execute",
            payload={
                "scene": "technical_support",
                "subject": "gpu-cn-sh2-01 异常工单",
                "content": "gpu-cn-sh2-01 当前为 degraded，建议确认受影响资源范围。",
                "queue": "technical-support-l2",
                "incident_code": "INC-CNSHANGHAI2-GPUINSTANCE-042",
                "service_status": "degraded",
                "status_summary": "gpu-cn-sh2-01 当前为 degraded，建议确认受影响资源范围。",
                "related_resources": ["gpu-cn-sh2-01", "GPU 实例服务"],
                "recommended_action": "建议优先检查网络和安全组，并安排值班支持跟进。",
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:ticket.write"],
            ),
        )
    )

    assert result.success is True
    assert result.result["queue"] == "technical-support-l2"
    assert result.result["incident_code"] == "INC-CNSHANGHAI2-GPUINSTANCE-042"
    assert result.result["subject"].startswith("gpu-cn-sh2-01 异常工单")
    assert "关联事件：INC-CNSHANGHAI2-GPUINSTANCE-042" in result.result["content"]
    assert result.session_context_patch["attributes"]["ticket_queue"] == "technical-support-l2"
    assert result.session_context_patch["attributes"]["ticket_incident_code"] == "INC-CNSHANGHAI2-GPUINSTANCE-042"


def test_refund_create_requires_order_permission_before_confirmation() -> None:
    catalog = build_catalog()
    result = catalog["order.create_refund"].invoke(
        ToolInvocationRequest(
            tool_name="order.create_refund",
            operation="execute",
            payload={"order_no": "ord-1", "reason": "误购", "amount": 88.8},
            context=ToolExecutionContext(user_id="u-1"),
        )
    )
    assert result.status == "auth-required"
    assert "permission:user:order.read" in result.result["missing_context"]


def test_refund_create_rejects_missing_required_fields_before_confirmation() -> None:
    catalog = build_catalog()
    result = catalog["order.create_refund"].invoke(
        ToolInvocationRequest(
            tool_name="order.create_refund",
            operation="execute",
            payload={"reason": "误购"},
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:order.read"],
            ),
        )
    )
    assert result.success is False
    assert result.status == "invalid-payload"
    assert result.code == 4001001
    assert result.result["missing_fields"] == ["order_no", "amount"]


def test_tool_preflight_returns_missing_payload_hints_before_execution() -> None:
    catalog = build_catalog()
    tool = catalog["order.create_refund"]
    preflight = preflight_tool_invocation(
        tool.definition,
        ToolInvocationRequest(
            tool_name="order.create_refund",
            operation="execute",
            payload={"reason": "误购"},
            context=ToolExecutionContext(user_id="u-1"),
        ),
    )
    assert preflight.ready is False
    assert preflight.status == "missing-payload"
    assert preflight.tool_mode == "write"
    assert preflight.timeout_ms == 10000
    assert preflight.idempotent is True
    assert preflight.cache_ttl_seconds is None
    assert preflight.missing_payload_fields == ["order_no", "amount"]
    assert "订单号" in preflight.missing_payload_hints["order_no"]
    assert "退款金额" in preflight.missing_payload_hints["amount"]
    assert "permission:user:order.read" in preflight.missing_auth_context


def test_tool_preflight_marks_confirmation_required_for_ready_high_risk_write() -> None:
    catalog = build_catalog()
    tool = catalog["billing.create_invoice"]
    preflight = preflight_tool_invocation(
        tool.definition,
        ToolInvocationRequest(
            tool_name="billing.create_invoice",
            operation="execute",
            payload={
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "上海某某科技有限公司",
            },
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
            ),
        ),
    )
    assert preflight.ready is False
    assert preflight.status == "confirmation-required"
    assert preflight.confirmation_required is True
    assert preflight.high_risk is True


def test_query_tool_preflight_surfaces_cache_and_timeout_metadata() -> None:
    catalog = build_catalog()
    tool = catalog["billing.query_statement"]
    preflight = preflight_tool_invocation(
        tool.definition,
        ToolInvocationRequest(
            tool_name="billing.query_statement",
            operation="execute",
            payload={"range": "this_month"},
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
            ),
        ),
    )
    assert preflight.ready is True
    assert preflight.tool_mode == "query"
    assert preflight.timeout_ms == 5000
    assert preflight.idempotent is True
    assert preflight.cache_ttl_seconds == 30


def test_marketing_copy_execute_returns_session_context_patch() -> None:
    catalog = build_catalog()
    result = catalog["marketing.generate_copy"].invoke(
        ToolInvocationRequest(
            tool_name="marketing.generate_copy",
            operation="execute",
            payload={
                "campaign_name": "GPU 新客满减",
                "product": "GPU 实例",
                "product_summary": "gi4.2xlarge / NVIDIA L40S x2",
                "channel": "wechat",
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:marketing.write"],
            ),
        )
    )
    assert result.success is True
    assert result.result["headline"].startswith("GPU 新客满减")
    assert result.result["product_summary"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert result.session_context_patch["attributes"]["last_marketing_copy_campaign_name"] == "GPU 新客满减"
    assert result.session_context_patch["attributes"]["last_marketing_copy_channel"] == "wechat"
    assert (
        result.session_context_patch["attributes"]["last_marketing_product_summary"]
        == "gi4.2xlarge / NVIDIA L40S x2"
    )


def test_marketing_campaign_lookup_prefers_recommended_product_summary() -> None:
    catalog = build_catalog()
    result = catalog["marketing.campaign_lookup"].invoke(
        ToolInvocationRequest(
            tool_name="marketing.campaign_lookup",
            operation="execute",
            payload={
                "product_summary": "gi4.2xlarge / NVIDIA L40S x2",
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:marketing.read"],
            ),
        )
    )

    assert result.success is True
    assert result.result["matched_product"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert result.result["product_summary"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert result.result["campaigns"][0]["segment"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert (
        result.session_context_patch["attributes"]["last_marketing_product_summary"]
        == "gi4.2xlarge / NVIDIA L40S x2"
    )


def test_marketing_poster_execute_returns_compensation_and_session_patch() -> None:
    catalog = build_catalog()
    result = catalog["marketing.generate_poster"].invoke(
        ToolInvocationRequest(
            tool_name="marketing.generate_poster",
            operation="execute",
            payload={
                "theme": "GPU 算力活动海报",
                "campaign_name": "GPU 新客满减",
                "headline": "GPU 新客满减限时开启",
                "size": "portrait",
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:marketing.write"],
                idempotency_key="poster-execute-1",
            ),
        )
    )
    assert result.success is True
    assert result.result["poster_asset_id"].startswith("poster_")
    assert result.compensation is not None
    assert result.compensation.action_name == "delete_poster_asset"
    assert result.session_context_patch["attributes"]["poster_asset_id"] == result.result["poster_asset_id"]
    assert result.session_context_patch["attributes"]["poster_download_path"] == result.result["download_path"]


def test_confirmed_write_returns_compensation_metadata() -> None:
    catalog = build_catalog()
    result = catalog["billing.create_invoice"].invoke(
        ToolInvocationRequest(
            tool_name="billing.create_invoice",
            operation="execute",
            payload={
                "statement_nos": ["stmt_001"],
                "invoice_type": "vat_special",
                "title": "上海某某科技有限公司",
                "_confirmed": True,
            },
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
                idempotency_key="tool-tc-3",
            ),
        )
    )
    assert result.status == "completed"
    assert result.success is True
    assert result.compensation is not None
    assert result.compensation.action_name == "cancel_invoice_request"
    assert result.idempotency_key == "tool-tc-3"


def test_confirmed_write_replays_same_idempotency_key() -> None:
    catalog = build_catalog()
    first = catalog["billing.create_invoice"].invoke(
        ToolInvocationRequest(
            tool_name="billing.create_invoice",
            operation="execute",
            payload={
                "statement_nos": ["stmt_100"],
                "invoice_type": "vat_special",
                "title": "上海某某科技有限公司",
                "_confirmed": True,
            },
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
                idempotency_key="tool-replay-1",
            ),
        )
    )
    replay = catalog["billing.create_invoice"].invoke(
        ToolInvocationRequest(
            tool_name="billing.create_invoice",
            operation="execute",
            payload={
                "statement_nos": ["stmt_100"],
                "invoice_type": "vat_special",
                "title": "上海某某科技有限公司",
                "_confirmed": True,
            },
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
                idempotency_key="tool-replay-1",
            ),
        )
    )
    assert replay.success is True
    assert replay.result["invoice_no"] == first.result["invoice_no"]
    assert "idempotent-replay" in replay.audit_tags


def test_promotion_link_execute_returns_compensation_and_session_patch() -> None:
    catalog = build_catalog()
    result = catalog["marketing.generate_promotion_link"].invoke(
        ToolInvocationRequest(
            tool_name="marketing.generate_promotion_link",
            operation="execute",
            payload={"campaign_name": "GPU 新客满减", "channel": "wechat"},
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:marketing.write"],
                idempotency_key="promo-link-1",
            ),
        )
    )
    assert result.success is True
    assert result.status == "completed"
    assert result.result["short_url"].startswith("https://scx.example/p/")
    assert result.compensation is not None
    assert result.compensation.action_name == "deactivate_promotion_link"
    assert result.session_context_patch["attributes"]["last_promotion_link"] == result.result["short_url"]


def test_delete_poster_asset_compensation_executes() -> None:
    result = execute_compensation(
        CompensationExecutionRequest(
            action_name="delete_poster_asset",
            payload={
                "poster_asset_id": "poster_gpu_campaign_portrait",
                "preview_url": "https://cdn.smartcloud.example/posters/gpu/preview.png",
                "download_path": "/artifacts/posters/gpu-portrait.png",
            },
            context=ToolExecutionContext(
                operator_type="system",
                operator_id="orchestrator-service",
                idempotency_key="comp-delete-poster-1",
            ),
        )
    )
    assert result.success is True
    assert result.result["poster_asset_id"] == "poster_gpu_campaign_portrait"
    assert result.result["status"] == "deleted"


def test_research_export_report_generates_markdown_artifact() -> None:
    catalog = build_catalog()
    result = catalog["research.export_report"].invoke(
        ToolInvocationRequest(
            tool_name="research.export_report",
            operation="execute",
            payload={
                "topic": "LangGraph 选型调研",
                "format": "markdown",
                "outline": ["业务背景与目标", "候选方案对比"],
                "reference_titles": ["LangGraph overview"],
            },
            context=ToolExecutionContext(
                user_id="u-1",
                permissions=["user:research.write"],
                idempotency_key="report-export-1",
            ),
        )
    )
    assert result.success is True
    assert result.status == "completed"
    assert result.result["format"] == "markdown"
    assert result.result["download_path"].endswith(".md")
    assert result.session_context_patch["attributes"]["last_report_export_format"] == "markdown"



def test_confirmed_write_rejects_idempotency_payload_conflict() -> None:
    catalog = build_catalog()
    first_request = ToolInvocationRequest(
        tool_name="billing.create_invoice",
        operation="execute",
        payload={
            "statement_nos": ["stmt_200"],
            "invoice_type": "vat_special",
            "title": "上海某某科技有限公司",
            "_confirmed": True,
        },
        context=ToolExecutionContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            idempotency_key="tool-conflict-1",
        ),
    )
    conflict_request = ToolInvocationRequest(
        tool_name="billing.create_invoice",
        operation="execute",
        payload={
            "statement_nos": ["stmt_200", "stmt_201"],
            "invoice_type": "vat_special",
            "title": "上海某某科技有限公司",
            "_confirmed": True,
        },
        context=ToolExecutionContext(
            user_id="u-1",
            account_id="acct-1",
            permissions=["user:billing.read"],
            idempotency_key="tool-conflict-1",
        ),
    )

    assert catalog["billing.create_invoice"].invoke(first_request).success is True
    conflict = catalog["billing.create_invoice"].invoke(conflict_request)
    assert conflict.success is False
    assert conflict.code == 4090001
    assert conflict.status == "idempotency-conflict"


def test_legacy_billing_summary_uses_month_alias_payload() -> None:
    catalog = build_catalog()
    result = catalog["billing.summary"].invoke(
        ToolInvocationRequest(
            tool_name="billing.summary",
            operation="execute",
            payload={"month": "2026-03"},
            context=ToolExecutionContext(
                user_id="u-1",
                account_id="acct-1",
                permissions=["user:billing.read"],
            ),
        )
    )
    assert result.success is True
    assert result.result["billing_cycle"] == "2026-03"
    assert result.result["total_amount"] == 1199.50


def test_execute_compensation_cancels_invoice_request() -> None:
    result = execute_compensation(
        CompensationExecutionRequest(
            action_name="cancel_invoice_request",
            payload={"invoice_no": "inv_001", "statement_nos": ["stmt_001"]},
            context=ToolExecutionContext(idempotency_key="comp-1"),
        )
    )
    assert result.success is True
    assert result.status == "completed"
    assert result.result["status"] == "cancelled"
    assert result.idempotency_key == "comp-1"
