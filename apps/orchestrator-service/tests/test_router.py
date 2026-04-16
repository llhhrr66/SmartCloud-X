from app.core.business_tools_sdk import build_catalog
from app.models.orchestration import AgentConfigUpdateRequest, RouteRequest
from app.services.agent_config_store import AgentConfigStore
from app.services.router import AgentRouter
from app.services.tool_hub_client import ToolHubDiscoveryUnavailableError



def test_router_matches_finance_domain_with_spec_tools() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下这个月账单并准备开票",
            conversation_id="conv-1",
            scene="billing",
        )
    )
    assert decision.primary_agent == "finance_order_agent"
    assert decision.requires_tools is True
    assert {tool.tool_name for tool in decision.tool_plan} >= {"billing.query_statement", "billing.create_invoice"}
    query_tool = next(tool for tool in decision.tool_plan if tool.tool_name == "billing.query_statement")
    assert query_tool.tool_mode == "query"
    assert query_tool.timeout_ms == 5000
    assert query_tool.idempotent is True
    assert query_tool.cache_ttl_seconds == 30


def test_router_uses_order_status_query_tool_for_refund_progress_questions() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下退款进度",
            conversation_id="conv-order-query-1",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:order.read"],
            },
            session_context={
                "attributes": {
                    "refund_order_no": "ord_20260416_001",
                    "refund_no": "refund_ord_20260416_001",
                },
            },
        )
    )

    assert decision.primary_agent == "finance_order_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["order.query_order"]
    assert decision.tool_plan[0].missing_payload_fields == []


def test_router_uses_instance_cost_query_tool_for_followup_cost_questions() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下这台实例费用",
            conversation_id="conv-instance-cost-route-1",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            session_context={
                "attributes": {
                    "primary_instance_id": "gpu-cn-sh2-01",
                    "billing_cycle": "2026-04",
                },
            },
        )
    )

    assert decision.primary_agent == "finance_order_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["billing.query_instance_cost"]
    assert decision.tool_plan[0].missing_payload_fields == []


def test_router_allows_explicit_billing_range_to_override_persisted_instance_cycle() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下上个月这台实例费用",
            conversation_id="conv-instance-cost-route-2",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            session_context={
                "attributes": {
                    "primary_instance_id": "gpu-cn-sh2-01",
                    "billing_cycle": "2026-04",
                },
            },
        )
    )

    tool = decision.tool_plan[0]
    assert tool.tool_name == "billing.query_instance_cost"
    assert tool.payload["range"] == "last_month"
    assert "billing_cycle" not in tool.payload


def test_router_uses_invoice_status_query_tool_for_invoice_status_questions() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下发票状态",
            conversation_id="conv-invoice-query-1",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:billing.read"],
            },
            session_context={
                "attributes": {
                    "invoice_no": "inv_001_20260416",
                },
            },
        )
    )

    assert decision.primary_agent == "finance_order_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["invoice.query_invoice"]
    assert decision.tool_plan[0].missing_payload_fields == []


def test_router_uses_icp_subject_verification_tool_for_real_name_questions() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="请帮我核验备案实名认证",
            conversation_id="conv-icp-verify-1",
            scene="icp",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:icp.read"],
            },
            session_context={
                "attributes": {
                    "subject_type": "enterprise",
                    "subject_name": "上海示例科技有限公司",
                    "certificate_no": "91310000MA1CTEST88",
                    "contact_name": "张三",
                    "contact_phone": "13800138000",
                },
            },
        )
    )

    assert decision.primary_agent == "icp_service_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["icp.verify_subject"]
    assert decision.tool_plan[0].missing_payload_fields == []


def test_router_uses_service_status_tool_for_technical_incident_followup() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下这台实例现在是不是故障了",
            conversation_id="conv-service-status-route-1",
            scene="technical_support",
            session_context={
                "attributes": {
                    "primary_instance_id": "gpu-cn-sh2-01",
                },
            },
        )
    )

    assert decision.primary_agent == "product_tech_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["support.query_service_status"]
    assert decision.tool_plan[0].missing_payload_fields == []
    assert decision.tool_plan[0].payload["instance_id"] == "gpu-cn-sh2-01"


def test_available_agents_include_spec_metadata_versions() -> None:
    router = AgentRouter()
    finance_agent = next(agent for agent in router.available_agents() if agent.name == "finance_order_agent")

    assert finance_agent.version == "1.0.0"
    assert finance_agent.owner == "smartcloud-ai-team"
    assert finance_agent.input_schema_version == "1.0"
    assert finance_agent.output_schema_version == "1.0"


def test_router_skips_disabled_supporting_agents() -> None:
    router = AgentRouter(agent_config_store=AgentConfigStore())
    router.update_agent_config("ops_marketing", AgentConfigUpdateRequest(enabled=False))

    decision = router.route(
        RouteRequest(
            user_query="有没有 GPU 活动，我要部署大模型",
            conversation_id="conv-disabled-agent-1",
            scene="technical_support",
        )
    )

    assert decision.primary_agent == "product_tech_agent"
    assert decision.supporting_agents == []
    assert all(step.agent != "ops_marketing_agent" for step in decision.handoff_plan)


def test_router_uses_configured_primary_fallback_when_agent_is_disabled() -> None:
    router = AgentRouter(agent_config_store=AgentConfigStore())
    router.update_agent_config(
        "finance_order",
        AgentConfigUpdateRequest(enabled=False, fallback_agent="product_tech_agent"),
    )

    decision = router.route(
        RouteRequest(
            user_query="帮我查下这个月账单",
            conversation_id="conv-primary-fallback-1",
            scene="billing",
        )
    )

    assert decision.primary_agent == "product_tech_agent"


def test_router_honors_agent_max_tool_calls_override() -> None:
    router = AgentRouter(agent_config_store=AgentConfigStore())
    router.update_agent_config("finance_order", AgentConfigUpdateRequest(max_tool_calls=1))

    decision = router.route(
        RouteRequest(
            user_query="帮我查下这个月账单并准备开票",
            conversation_id="conv-agent-limit-1",
            scene="billing",
        )
    )

    finance_tools = [tool.tool_name for tool in decision.tool_plan if tool.assigned_agent == "finance_order_agent"]
    assert finance_tools == ["billing.query_statement"]



def test_router_assigns_marketing_support_for_gpu_campaign() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="有没有 GPU 活动，我要部署大模型",
            conversation_id="conv-2",
            scene="technical_support",
        )
    )
    assert decision.primary_agent == "product_tech_agent"
    assert "ops_marketing_agent" in decision.supporting_agents
    assert len(decision.handoff_plan) == 2
    assert any(tool.tool_name == "product.recommend_instance" for tool in decision.tool_plan)
    assert any(tool.tool_name == "marketing.campaign_lookup" for tool in decision.tool_plan)


def test_router_routes_gpu_marketing_copy_through_product_grounding_when_no_recommendation_context() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我给 GPU 实例写一段营销文案",
            conversation_id="conv-product-marketing-copy",
            scene="marketing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        )
    )

    assert decision.primary_agent == "product_tech_agent"
    assert decision.supporting_agents == ["ops_marketing_agent"]
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "product.catalog_lookup",
        "product.recommend_instance",
        "marketing.campaign_lookup",
        "marketing.generate_copy",
    ]
    assert decision.handoff_plan[0].agent == "product_tech_agent"
    assert decision.handoff_plan[1].agent == "ops_marketing_agent"


def test_router_keeps_marketing_primary_when_recommendation_context_exists() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="把刚才推荐的 GPU 实例写成营销文案",
            conversation_id="conv-product-marketing-followup",
            scene="marketing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
            session_context={
                "active_products": ["GPU 实例"],
                "attributes": {
                    "recommended_instance_summary": "gi4.2xlarge / NVIDIA L40S x2",
                    "recommended_instance_type": "gi4.2xlarge",
                    "recommended_gpu_model": "NVIDIA L40S",
                },
            },
        )
    )

    assert decision.primary_agent == "ops_marketing_agent"
    assert decision.supporting_agents == []
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "marketing.campaign_lookup",
        "marketing.generate_copy",
    ]
    assert decision.tool_plan[0].payload["product"] == "GPU"
    assert decision.tool_plan[0].payload["product_summary"] == "gi4.2xlarge / NVIDIA L40S x2"
    assert decision.tool_plan[1].payload["product_summary"] == "gi4.2xlarge / NVIDIA L40S x2"


def test_router_uses_product_recommendation_tool_for_gpu_sizing_questions() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="我准备部署 32B 大模型推理服务，帮我推荐 GPU 实例规格",
            conversation_id="conv-product-sizing-1",
            scene="technical_support",
        )
    )

    assert decision.primary_agent == "product_tech_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "product.catalog_lookup",
        "product.recommend_instance",
    ]
    recommend_tool = decision.tool_plan[1]
    assert recommend_tool.assigned_agent == "product_tech_agent"
    assert recommend_tool.payload["workload"] == "inference"
    assert recommend_tool.payload["model_family"] == "llm"
    assert recommend_tool.payload["budget_level"] == "balanced"
    assert recommend_tool.readiness == "ready"


def test_router_flags_human_handoff_requests() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="我要投诉账单异常，帮我转人工",
            conversation_id="conv-3",
            scene="billing",
        )
    )
    assert decision.needs_human_handoff is True
    assert decision.intent.needs_human_handoff is True


def test_router_adds_handoff_brief_tool_for_human_escalation() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="服务异常我要转人工",
            conversation_id="conv-human-brief-route",
            scene="technical_support",
        )
    )

    assert decision.primary_agent == "product_tech_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["support.handoff_brief"]
    handoff_tool = decision.tool_plan[0]
    assert handoff_tool.payload["scene"] == "technical_support"
    assert handoff_tool.payload["urgency"] == "high"
    assert handoff_tool.payload["reason"] == "service_exception"


def test_router_routes_technical_incident_ticket_requests_through_support_then_ticket() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="GPU 实例异常帮我转人工并创建工单",
            conversation_id="conv-tech-ticket-route",
            scene="technical_support",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:ticket.write"],
            },
        )
    )

    assert decision.primary_agent == "product_tech_agent"
    assert decision.supporting_agents == ["finance_order_agent"]
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "support.query_service_status",
        "support.handoff_brief",
        "ticket.create",
    ]
    ticket_tool = decision.tool_plan[2]
    assert ticket_tool.assigned_agent == "finance_order_agent"
    assert ticket_tool.readiness == "ready_after_dependencies"
    assert ticket_tool.deferred_payload_fields == ["subject", "content"]
    assert ticket_tool.payload["scene"] == "technical_support"


def test_router_handoff_brief_infers_domain_scene_from_customer_service_requests() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="账单异常我要转人工",
            conversation_id="conv-human-brief-route-2",
            scene="customer_service",
        )
    )

    assert decision.primary_agent == "finance_order_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["support.handoff_brief"]
    assert decision.tool_plan[0].payload["scene"] == "billing"
    assert decision.tool_plan[0].payload["reason"] == "service_exception"


def test_router_adds_collect_user_input_checkpoint_for_high_risk_write() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我开票",
            conversation_id="conv-4",
            scene="billing",
        )
    )
    checkpoint_names = {checkpoint.name: checkpoint.status for checkpoint in decision.checkpoints}
    assert checkpoint_names["collect-user-input"] == "planned"
    assert checkpoint_names["review-answer"] == "planned"


def test_router_skips_collect_user_input_when_auth_context_is_already_present() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查下这个月账单",
            conversation_id="conv-5",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        )
    )
    checkpoint_names = {checkpoint.name: checkpoint.status for checkpoint in decision.checkpoints}
    assert checkpoint_names["collect-user-input"] == "skipped"


def test_router_uses_preview_for_ready_high_risk_write_before_confirmation() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我开票",
            conversation_id="conv-5b",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            session_context={
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        )
    )
    invoice_tool = next(tool for tool in decision.tool_plan if tool.tool_name == "billing.create_invoice")
    assert invoice_tool.operation == "preview"
    assert invoice_tool.readiness == "ready"
    checkpoint_names = {checkpoint.name: checkpoint.status for checkpoint in decision.checkpoints}
    assert checkpoint_names["collect-user-input"] == "planned"


def test_router_forces_retrieval_when_must_cite_is_enabled() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查本月账单",
            conversation_id="conv-6",
            scene="billing",
            constraints={"must_cite": True, "allow_handoff": True, "max_tool_calls": 5},
        )
    )
    assert decision.requires_retrieval is True


def test_router_marks_missing_required_tool_fields_for_clarification() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查账单",
            conversation_id="conv-7",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        )
    )
    tool_plan = {tool.tool_name: tool for tool in decision.tool_plan}
    assert tool_plan["billing.query_statement"].missing_payload_fields == ["range"]
    checkpoint_names = {checkpoint.name: checkpoint.status for checkpoint in decision.checkpoints}
    assert checkpoint_names["collect-user-input"] == "planned"


def test_router_reorders_tools_to_satisfy_prerequisites() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查本月账单并开票",
            conversation_id="conv-8",
            scene="billing",
            tool_candidates=["billing.create_invoice", "billing.query_statement"],
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            session_context={
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        )
    )
    assert [tool.tool_name for tool in decision.tool_plan[:2]] == [
        "billing.query_statement",
        "billing.create_invoice",
    ]


def test_router_marks_dependency_resolved_fields_as_deferred_not_missing() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我查本月账单并开票",
            conversation_id="conv-9",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            session_context={
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        )
    )
    query_tool, invoice_tool = decision.tool_plan[:2]
    assert query_tool.tool_name == "billing.query_statement"
    assert invoice_tool.tool_name == "billing.create_invoice"
    assert invoice_tool.missing_payload_fields == []
    assert invoice_tool.deferred_payload_fields == ["statement_nos"]
    assert invoice_tool.depends_on_tool_call_ids == [query_tool.tool_call_id]
    assert invoice_tool.readiness == "ready_after_dependencies"
    assert "attributes.statement_nos" in decision.handoff_plan[0].session_context_inputs
    checkpoint_names = {checkpoint.name: checkpoint.status for checkpoint in decision.checkpoints}
    assert checkpoint_names["collect-user-input"] == "skipped"


def test_router_expands_explicit_tool_candidates_and_assigns_each_owner_once() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="请按计划处理",
            conversation_id="conv-10",
            scene="customer_service",
            tool_candidates=["billing.create_invoice", "marketing.campaign_lookup"],
        )
    )

    assert decision.primary_agent == "finance_order_agent"
    assert decision.supporting_agents == ["ops_marketing_agent"]
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "billing.query_statement",
        "billing.create_invoice",
        "marketing.campaign_lookup",
    ]
    assigned_agents = {tool.tool_name: tool.assigned_agent for tool in decision.tool_plan}
    assert assigned_agents["billing.query_statement"] == "finance_order_agent"
    assert assigned_agents["billing.create_invoice"] == "finance_order_agent"
    assert assigned_agents["marketing.campaign_lookup"] == "ops_marketing_agent"
    assert decision.tool_plan[1].depends_on_tool_call_ids == [decision.tool_plan[0].tool_call_id]


def test_router_plans_promotion_link_after_campaign_lookup() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="给我生成 GPU 活动推广链接",
            conversation_id="conv-12",
            scene="marketing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        )
    )

    assert decision.primary_agent == "ops_marketing_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "marketing.campaign_lookup",
        "marketing.generate_promotion_link",
    ]
    promotion_tool = decision.tool_plan[1]
    assert promotion_tool.deferred_payload_fields == ["campaign_name"]
    assert promotion_tool.depends_on_tool_call_ids == [decision.tool_plan[0].tool_call_id]
    assert promotion_tool.readiness == "ready_after_dependencies"


def test_router_plans_poster_generation_after_brief_and_campaign_lookup() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我生成 GPU 活动海报",
            conversation_id="conv-12a",
            scene="marketing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:marketing.read", "user:marketing.write"],
            },
        )
    )

    assert decision.primary_agent == "ops_marketing_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "marketing.campaign_lookup",
        "marketing.poster_brief",
        "marketing.generate_poster",
    ]
    poster_tool = decision.tool_plan[-1]
    assert poster_tool.deferred_payload_fields == ["theme"]
    assert set(poster_tool.depends_on_tool_call_ids) == {decision.tool_plan[1].tool_call_id}
    assert poster_tool.readiness == "ready_after_dependencies"


def test_router_plans_marketing_copy_after_campaign_lookup() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我生成 GPU 活动宣传文案",
            conversation_id="conv-12b",
            scene="marketing",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:marketing.write"],
            },
        )
    )

    assert decision.primary_agent == "ops_marketing_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "marketing.campaign_lookup",
        "marketing.generate_copy",
    ]
    copy_tool = decision.tool_plan[1]
    assert copy_tool.deferred_payload_fields == ["campaign_name"]
    assert copy_tool.depends_on_tool_call_ids == [decision.tool_plan[0].tool_call_id]
    assert copy_tool.readiness == "ready_after_dependencies"


def test_router_plans_report_export_after_research_generation() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="帮我导出 LangGraph 选型调研报告 markdown",
            conversation_id="conv-13",
            scene="research",
            user_profile={
                "user_id": "u-1",
                "permissions": ["user:research.write"],
            },
        )
    )

    assert decision.primary_agent == "deep_research_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == [
        "research.generate_report",
        "research.reference_search",
        "research.export_report",
    ]
    export_tool = decision.tool_plan[-1]
    assert export_tool.deferred_payload_fields == ["topic"]
    assert set(export_tool.depends_on_tool_call_ids) == {
        decision.tool_plan[0].tool_call_id,
        decision.tool_plan[1].tool_call_id,
    }
    assert export_tool.payload["format"] == "markdown"
    assert export_tool.readiness == "ready_after_dependencies"


def test_router_skips_unknown_explicit_tool_candidates_when_selecting_primary_agent() -> None:
    router = AgentRouter()
    decision = router.route(
        RouteRequest(
            user_query="请按计划处理",
            conversation_id="conv-11",
            scene="customer_service",
            tool_candidates=["unknown.tool", "marketing.campaign_lookup"],
        )
    )

    assert decision.primary_agent == "ops_marketing_agent"
    assert [tool.tool_name for tool in decision.tool_plan] == ["marketing.campaign_lookup"]


def test_router_uses_tool_hub_contract_metadata_when_http_transport_enabled(monkeypatch) -> None:
    local_definitions = [
        tool.definition.model_copy(deep=True)
        for tool in build_catalog().values()
    ]
    for definition in local_definitions:
        if definition.name == "billing.query_statement":
            definition.timeout_ms = 4321
            definition.cache_ttl_seconds = 66

    class StubToolHubClient:
        def list_tool_definitions(self):
            return local_definitions

    router = AgentRouter(tool_hub_client=StubToolHubClient())
    monkeypatch.setattr(router._settings, "tool_hub_transport", "http", raising=False)

    decision = router.route(
        RouteRequest(
            user_query="帮我查本月账单",
            conversation_id="conv-http-1",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        )
    )

    query_tool = next(tool for tool in decision.tool_plan if tool.tool_name == "billing.query_statement")
    assert query_tool.timeout_ms == 4321
    assert query_tool.cache_ttl_seconds == 66


def test_router_does_not_reuse_local_tool_metadata_when_http_discovery_is_unavailable_in_prod(monkeypatch) -> None:
    class StubToolHubClient:
        def list_tool_definitions(self):
            raise ToolHubDiscoveryUnavailableError("tool-hub discovery unavailable")

    router = AgentRouter(tool_hub_client=StubToolHubClient())
    monkeypatch.setattr(router._settings, "tool_hub_transport", "http", raising=False)
    monkeypatch.setattr(router._settings, "app_env", "prod", raising=False)

    decision = router.route(
        RouteRequest(
            user_query="帮我查本月账单",
            conversation_id="conv-http-prod-1",
            scene="billing",
            user_profile={
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        )
    )

    query_tool = next(tool for tool in decision.tool_plan if tool.tool_name == "billing.query_statement")
    assert query_tool.operation == "preview"
    assert query_tool.tool_mode is None
    assert query_tool.timeout_ms is None
    assert query_tool.cache_ttl_seconds is None
