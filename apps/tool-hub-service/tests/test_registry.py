import httpx
import pytest

from app.core.business_tools_sdk import ToolDefinition
from app.core.config import Settings
from app.services.business_tools_client import BusinessToolsDiscoveryUnavailableError
from app.services.registry import ToolRegistry


def test_registry_exposes_spec_aligned_finance_tools() -> None:
    registry = ToolRegistry()
    names = {tool.name for tool in registry.list_tools()}
    assert "billing.query_statement" in names
    assert "billing.query_instance_cost" in names
    assert "product.recommend_instance" in names
    assert "support.query_service_status" in names
    assert "support.handoff_brief" in names
    assert "order.query_order" in names
    assert "invoice.query_invoice" in names
    assert "ticket.query_ticket" in names
    assert "icp.verify_subject" in names
    assert "icp.query_application" in names
    assert "order.create_refund" in names
    assert "ticket.create" in names


def test_registry_filters_tools_by_capability_mode_and_query() -> None:
    registry = ToolRegistry()
    names = {
        tool.name
        for tool in registry.list_tools(capability="finance-order", mode="write", query="invoice")
    }
    assert names == {"billing.create_invoice"}


def test_registry_preserves_auth_and_risk_requirements() -> None:
    registry = ToolRegistry()
    descriptor = registry.describe_tool("billing.create_invoice")
    assert descriptor is not None
    assert descriptor.version == "1.0.0"
    assert descriptor.input_schema["required"] == ["statement_nos", "invoice_type", "title"]
    assert descriptor.output_schema["properties"]["amount"]["type"] == "number"
    assert descriptor.auth_requirements.confirmation_required is True
    assert descriptor.high_risk is True
    assert descriptor.session_context_bindings["statement_nos"] == [
        "attributes.statement_nos",
        "attributes.statement_no",
    ]
    assert descriptor.prerequisite_tool_names == ["billing.query_statement"]
    assert "attributes.invoice_no" in descriptor.session_context_output_keys

    query_descriptor = registry.describe_tool("billing.query_statement")
    assert query_descriptor is not None
    assert query_descriptor.session_context_bindings["range"] == ["attributes.billing_range"]
    instance_cost_descriptor = registry.describe_tool("billing.query_instance_cost")
    assert instance_cost_descriptor is not None
    assert instance_cost_descriptor.session_context_bindings["instance_id"] == [
        "attributes.instance_id",
        "attributes.primary_instance_id",
    ]
    assert "attributes.last_instance_cost_total" in instance_cost_descriptor.session_context_output_keys

    product_descriptor = registry.describe_tool("product.recommend_instance")
    assert product_descriptor is not None
    assert product_descriptor.session_context_bindings["workload"] == ["attributes.recommended_workload"]
    assert "attributes.recommended_instance_type" in product_descriptor.session_context_output_keys

    service_status_descriptor = registry.describe_tool("support.query_service_status")
    assert service_status_descriptor is not None
    assert service_status_descriptor.session_context_bindings["instance_id"] == [
        "attributes.instance_id",
        "attributes.primary_instance_id",
        "attributes.service_affected_instance_id",
    ]
    assert "attributes.service_status_summary" in service_status_descriptor.session_context_output_keys

    handoff_descriptor = registry.describe_tool("support.handoff_brief")
    assert handoff_descriptor is not None
    assert handoff_descriptor.session_context_bindings["conversation_summary"] == ["history_summary"]
    assert handoff_descriptor.session_context_bindings["service_status"] == ["attributes.service_status"]
    assert "attributes.human_handoff_summary" in handoff_descriptor.session_context_output_keys

    ticket_create_descriptor = registry.describe_tool("ticket.create")
    assert ticket_create_descriptor is not None
    assert ticket_create_descriptor.session_context_bindings["subject"] == [
        "attributes.human_handoff_summary",
        "attributes.service_status_summary",
        "attributes.ticket_subject",
    ]
    assert ticket_create_descriptor.session_context_bindings["incident_code"] == [
        "attributes.human_handoff_incident_code",
        "attributes.service_incident_code",
    ]
    assert "attributes.ticket_queue" in ticket_create_descriptor.session_context_output_keys

    campaign_descriptor = registry.describe_tool("marketing.campaign_lookup")
    assert campaign_descriptor is not None
    assert campaign_descriptor.session_context_bindings["product"] == [
        "attributes.recommended_instance_type",
        "attributes.recommended_instance_family",
        "active_products",
    ]
    assert campaign_descriptor.session_context_bindings["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]

    copy_descriptor = registry.describe_tool("marketing.generate_copy")
    assert copy_descriptor is not None
    assert copy_descriptor.session_context_bindings["product_summary"] == [
        "attributes.recommended_instance_summary",
        "attributes.last_marketing_product_summary",
    ]
    assert "attributes.last_marketing_product_summary" in copy_descriptor.session_context_output_keys


def test_registry_uses_remote_business_tools_contracts_when_http_transport_enabled() -> None:
    class StubBusinessToolsClient:
        def list_tools(self, **filters) -> list[ToolDefinition]:
            assert filters == {"capability": None, "mode": None, "tag": None, "query": None}
            return [
                ToolDefinition.model_validate(
                    {
                        "name": "billing.query_statement",
                        "capability": "billing",
                        "description": "remote billing",
                        "timeout_ms": 4321,
                        "cache_ttl_seconds": 88,
                    }
                )
            ]

        def describe_tool(self, tool_name: str) -> ToolDefinition | None:
            if tool_name != "billing.query_statement":
                return None
            return ToolDefinition.model_validate(
                {
                    "name": "billing.query_statement",
                    "capability": "billing",
                    "description": "remote billing",
                    "timeout_ms": 4321,
                    "cache_ttl_seconds": 88,
                }
            )

    registry = ToolRegistry(
        settings=Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        ),
        business_tools_client=StubBusinessToolsClient(),
    )

    listed = registry.list_tools()
    assert len(listed) == 1
    assert listed[0].timeout_ms == 4321
    assert listed[0].cache_ttl_seconds == 88

    described = registry.describe_tool("billing.query_statement")
    assert described is not None
    assert described.timeout_ms == 4321
    assert described.cache_ttl_seconds == 88


def test_registry_strict_remote_discovery_raises_when_business_tools_is_unavailable() -> None:
    class StubBusinessToolsClient:
        def discover_tools(self, **filters):
            raise BusinessToolsDiscoveryUnavailableError("business-tools discovery unavailable")

        def discover_tool(self, tool_name: str):
            raise BusinessToolsDiscoveryUnavailableError("business-tools discovery unavailable")

    registry = ToolRegistry(
        settings=Settings.model_validate(
            {
                "APP_ENV": "dev",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        ),
        business_tools_client=StubBusinessToolsClient(),
    )

    with pytest.raises(BusinessToolsDiscoveryUnavailableError):
        registry.list_tools(strict_remote=True)

    with pytest.raises(BusinessToolsDiscoveryUnavailableError):
        registry.describe_tool("billing.query_statement", strict_remote=True)


def test_registry_defaults_to_strict_remote_discovery_in_prod() -> None:
    class StubBusinessToolsClient:
        def discover_tools(self, **filters):
            raise BusinessToolsDiscoveryUnavailableError("business-tools discovery unavailable")

        def discover_tool(self, tool_name: str):
            raise BusinessToolsDiscoveryUnavailableError("business-tools discovery unavailable")

    registry = ToolRegistry(
        settings=Settings.model_validate(
            {
                "APP_ENV": "prod",
                "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        ),
        business_tools_client=StubBusinessToolsClient(),
    )

    with pytest.raises(BusinessToolsDiscoveryUnavailableError):
        registry.list_tools()

    with pytest.raises(BusinessToolsDiscoveryUnavailableError):
        registry.describe_tool("billing.query_statement")


def test_registry_strict_remote_discovery_does_not_fallback_when_remote_tool_is_missing() -> None:
    class StubBusinessToolsClient:
        def discover_tools(self, **filters):
            return []

        def discover_tool(self, tool_name: str):
            return None

    registry = ToolRegistry(
        settings=Settings.model_validate(
            {
                "APP_ENV": "prod",
                "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
                "BUSINESS_TOOLS_TRANSPORT": "http",
                "BUSINESS_TOOLS_URL": "http://example.local",
            }
        ),
        business_tools_client=StubBusinessToolsClient(),
    )

    assert registry.list_tools() == []
    assert registry.describe_tool("billing.query_statement") is None
