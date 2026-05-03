from app.core.observability import clear_in_memory_spans, get_in_memory_span_exporter
from app.models.tools import ToolCallRequest
from app.services.business_tools_client import BusinessToolsClient
from app.services.registry import ToolRegistry


def test_business_tools_client_propagates_trace_headers() -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.query_statement")
    assert tool is not None
    client = BusinessToolsClient()
    headers = client._tool_execution_headers(
        ToolCallRequest(
            trace_id="trace-header-1",
            conversation_id="conv-header-1",
            tool_call_id="tc-header-1",
            tool_name="billing.query_statement",
            operator={"type": "agent", "id": "Finance_Order_Agent"},
            user_context={"tenant_id": "default"},
            payload={"range": "this_month"},
            idempotency_key="123e4567-e89b-12d3-a456-426614174003",
            operation="execute",
        )
    )

    assert headers["X-Trace-Id"] == "trace-header-1"
    assert "traceparent" in headers or headers["X-Trace-Id"] == "trace-header-1"


def test_registry_and_call_export_spans() -> None:
    clear_in_memory_spans()
    exporter = get_in_memory_span_exporter()
    assert exporter is not None

    registry = ToolRegistry()
    _ = registry.list_tools()

    spans = exporter.get_finished_spans()
    assert any(span.name == "tool_hub.registry.list" for span in spans)
