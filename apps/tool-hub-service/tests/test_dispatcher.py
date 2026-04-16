from app.models.tools import ToolInvokeRequest
from app.services.dispatcher import ToolDispatcher, ToolInvocationError
from app.services.registry import ToolRegistry



def test_dispatcher_blocks_billing_execute_without_auth_context() -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.query_statement")
    assert tool is not None

    dispatcher = ToolDispatcher()
    try:
        dispatcher.invoke(tool, ToolInvokeRequest(operation="execute", payload={"range": "this_month"}))
    except ToolInvocationError as exc:
        assert exc.code == "ORCH_TOOL_AUTH_REQUIRED"
    else:
        raise AssertionError("Expected auth validation error.")



def test_dispatcher_returns_poster_preview() -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("marketing.poster_brief")
    assert tool is not None

    dispatcher = ToolDispatcher()
    response = dispatcher.invoke(
        tool,
        ToolInvokeRequest(operation="preview", payload={"theme": "GPU 算力推广", "cta": "立即抢购"}),
    )
    assert response.status == "preview-ready"
    assert response.result["theme"] == "GPU 算力推广"



def test_dispatcher_executes_poster_generation_write() -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("marketing.generate_poster")
    assert tool is not None

    dispatcher = ToolDispatcher()
    response = dispatcher.invoke(
        tool,
        ToolInvokeRequest(
            operation="execute",
            payload={
                "theme": "GPU 算力活动海报",
                "campaign_name": "GPU 新客满减",
                "headline": "GPU 新客满减限时开启",
            },
            context={"user_id": "u-1", "permissions": ["user:marketing.write"]},
        ),
    )
    assert response.status == "completed"
    assert response.success is True
    assert response.result["poster_asset_id"].startswith("poster_")
    assert response.compensation is not None
    assert response.compensation.action_name == "delete_poster_asset"


def test_dispatcher_surfaces_confirmation_required_result() -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.create_invoice")
    assert tool is not None

    dispatcher = ToolDispatcher()
    response = dispatcher.invoke(
        tool,
        ToolInvokeRequest(
            operation="execute",
            payload={"statement_nos": ["stmt_1"], "invoice_type": "vat_special", "title": "某某科技"},
            context={"user_id": "u-1", "permissions": ["user:billing.read"]},
        ),
    )
    assert response.status == "confirmation-required"
    assert response.success is False


def test_dispatcher_returns_preview_confirmation_hint() -> None:
    registry = ToolRegistry()
    tool = registry.get_tool("billing.create_invoice")
    assert tool is not None

    dispatcher = ToolDispatcher()
    response = dispatcher.invoke(
        tool,
        ToolInvokeRequest(
            operation="preview",
            payload={"statement_nos": ["stmt_1"], "invoice_type": "vat_special", "title": "某某科技"},
            context={"user_id": "u-1", "permissions": ["user:billing.read"]},
        ),
    )
    assert response.status == "preview-ready"
    assert response.success is True
    assert response.user_action_hint is not None
    assert response.user_action_hint.action == "user-confirmation"
