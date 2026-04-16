import httpx

from app.core.business_tools_sdk import ToolDefinition
from app.core.config import Settings
from app.services.registry import ToolRegistry


def test_registry_exposes_spec_aligned_finance_tools() -> None:
    registry = ToolRegistry()
    names = {tool.name for tool in registry.list_tools()}
    assert "billing.query_statement" in names
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
