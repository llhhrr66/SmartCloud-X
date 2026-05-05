from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.models.mcp_protocol import (
    ERROR_INTERNAL,
    ERROR_INVALID_PARAMS,
    ERROR_INVALID_REQUEST,
    ERROR_METHOD_NOT_FOUND,
    ERROR_PARSE,
    MCP_METHOD_INITIALIZE,
    MCP_METHOD_PING,
    MCP_METHOD_PROMPTS_GET,
    MCP_METHOD_PROMPTS_LIST,
    MCP_METHOD_RESOURCES_LIST,
    MCP_METHOD_RESOURCES_READ,
    MCP_METHOD_TOOLS_CALL,
    MCP_METHOD_TOOLS_LIST,
    PROTOCOL_VERSION,
    CallToolResult,
    GetPromptResult,
    InitializeRequestParams,
    InitializeResponseResult,
    JSONRPCError,
    JSONRPCRequest,
    JSONRPCResponse,
    ListPromptsResult,
    ListResourcesResult,
    ListToolsResult,
    McpErrorContent,
    McpTextContent,
    McpToolItem,
    PromptArgument,
    PromptItem,
    PromptMessage,
    ReadResourceResult,
    ResourceItem,
    ServerCapabilities,
    TextResourceContents,
)
from app.services.registry import ToolRegistry
from app.services.dispatcher import ToolDispatcher

logger = logging.getLogger(__name__)
mcp_lifecycle_router = APIRouter(tags=["mcp-lifecycle"])

_settings = get_settings()
_registry = ToolRegistry()
_dispatcher = ToolDispatcher()

# In-memory session store
_sessions: dict[str, dict[str, Any]] = {}


def _build_server_capabilities() -> ServerCapabilities:
    return ServerCapabilities(
        tools={"listChanged": False},
        resources={"subscribe": False, "listChanged": False},
        prompts={"listChanged": False},
        logging={},
    )


def _build_server_info() -> dict[str, str]:
    return {
        "name": _settings.app_name,
        "version": _settings.app_version,
    }


def _rpc_error(code: int, message: str, data: Any = None, req_id: str | int | None = None) -> dict:
    return JSONRPCResponse(
        id=req_id,
        error=JSONRPCError(code=code, message=message, data=data),
    ).model_dump()


def _rpc_result(req_id: str | int | None, result: Any) -> dict:
    return JSONRPCResponse(id=req_id, result=result).model_dump()


def _handle_initialize(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    if not params:
        return _rpc_error(ERROR_INVALID_PARAMS, "Missing params for initialize")

    try:
        init_params = InitializeRequestParams.model_validate(params)
    except Exception as exc:
        return _rpc_error(ERROR_INVALID_PARAMS, f"Invalid initialize params: {exc}")

    if init_params.protocol_version != PROTOCOL_VERSION:
        logger.warning(
            "Client requested protocol_version=%s, server supports %s",
            init_params.protocol_version,
            PROTOCOL_VERSION,
        )

    session_id = str(request_id) if request_id is not None else "default"
    _sessions[session_id] = {
        "client_capabilities": init_params.capabilities.model_dump(),
        "client_info": init_params.client_info.model_dump(),
        "protocol_version": PROTOCOL_VERSION,
    }

    result = InitializeResponseResult(
        protocolVersion=PROTOCOL_VERSION,
        capabilities=_build_server_capabilities(),
        serverInfo=_build_server_info(),
        instructions="SmartCloud-X Tool Hub Service - MCP protocol endpoint.",
    )

    logger.info(
        "MCP initialize for client %s v%s (session=%s)",
        init_params.client_info.name,
        init_params.client_info.version,
        session_id,
    )
    return _rpc_result(request_id, result.model_dump(by_alias=True))


def _handle_resources_list(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    try:
        tools = _registry.list_tools()
    except Exception as exc:
        logger.error("Failed to list tools for resources: %s", exc)
        return _rpc_error(ERROR_INTERNAL, "Failed to enumerate resources")

    resources: list[dict] = []
    for tool in tools:
        resources.append(
            ResourceItem(
                uri=f"tool://{tool.name}",
                name=tool.name,
                description=tool.description or "",
                mimeType="application/json",
            ).model_dump(by_alias=True)
        )

    result = ListResourcesResult(resources=resources)
    return _rpc_result(request_id, result.model_dump(by_alias=True))


def _handle_resources_read(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    if not params or "uri" not in params:
        return _rpc_error(ERROR_INVALID_PARAMS, "Missing 'uri' in params")

    uri = params["uri"]
    if not uri.startswith("tool://"):
        return _rpc_error(ERROR_INVALID_PARAMS, f"Unsupported URI scheme: {uri}")

    tool_name = uri.replace("tool://", "", 1)
    try:
        descriptor = _registry.describe_tool(tool_name)
    except Exception as exc:
        logger.error("Failed to describe tool %s: %s", tool_name, exc)
        return _rpc_error(ERROR_INTERNAL, f"Failed to read resource: {exc}")

    if descriptor is None:
        return _rpc_error(ERROR_INVALID_PARAMS, f"Resource not found: {uri}")

    content = TextResourceContents(
        uri=uri,
        mimeType="application/json",
        text=descriptor.model_dump_json(indent=2),
    )
    result = ReadResourceResult(contents=[content])
    return _rpc_result(request_id, result.model_dump(by_alias=True))


def _handle_prompts_list(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    prompt_defs = [
        (
            "billing_diagnosis",
            "诊断云产品计费问题，分析账单异常并提供优化建议",
            [
                PromptArgument(name="account_id", description="用户账户ID", required=True),
                PromptArgument(name="time_range", description="查询时间范围，如 2025-01", required=False),
            ],
        ),
        (
            "product_selection",
            "根据业务需求推荐合适的云产品组合",
            [
                PromptArgument(name="scenario", description="业务场景描述，如 电商高并发", required=True),
                PromptArgument(name="budget", description="预算范围（元/月）", required=False),
            ],
        ),
        (
            "icp_guidance",
            "ICP备案流程指引与常见问题解答",
            [
                PromptArgument(name="domain", description="待备案域名", required=True),
                PromptArgument(name="region", description="备案地区", required=False),
            ],
        ),
        (
            "security_compliance",
            "云安全合规检查与加固建议",
            [
                PromptArgument(name="service_type", description="云服务类型，如 ECS, RDS", required=True),
                PromptArgument(name="compliance_standard", description="合规标准，如 等保2.0", required=False),
            ],
        ),
    ]

    prompts = [
        PromptItem(name=name, description=desc, arguments=args)
        for name, desc, args in prompt_defs
    ]
    result = ListPromptsResult(prompts=prompts)
    return _rpc_result(request_id, result.model_dump(by_alias=True))


def _handle_prompts_get(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    if not params or "name" not in params:
        return _rpc_error(ERROR_INVALID_PARAMS, "Missing 'name' in params")

    name = params["name"]
    args = params.get("arguments", {})

    templates = {
        "billing_diagnosis": (
            "诊断云产品计费问题",
            [
                PromptMessage(role="system", content="你是云产品计费诊断专家，请根据用户的账户信息和时间范围，分析账单异常、识别费用趋势，并提供优化建议。"),
                PromptMessage(
                    role="user",
                    content=f"请诊断账户 {args.get('account_id', '未指定')} 在 {args.get('time_range', '最近一个月')} 的计费情况。",
                ),
            ],
        ),
        "product_selection": (
            "推荐云产品组合",
            [
                PromptMessage(role="system", content="你是云架构师，根据用户业务场景和预算推荐最优云产品组合。"),
                PromptMessage(
                    role="user",
                    content=f"场景：{args.get('scenario', '未指定')}，预算：{args.get('budget', '不限')}，请推荐合适的云产品组合。",
                ),
            ],
        ),
        "icp_guidance": (
            "ICP备案流程指引",
            [
                PromptMessage(role="system", content="你是ICP备案顾问，为用户提供备案流程、材料准备和常见问题的解答。"),
                PromptMessage(
                    role="user",
                    content=f"请为域名 {args.get('domain', '未指定')} 在 {args.get('region', '中国大陆')} 提供ICP备案指引。",
                ),
            ],
        ),
        "security_compliance": (
            "云安全合规检查",
            [
                PromptMessage(role="system", content="你是云安全合规专家，根据服务类型和合规标准提供检查清单和加固建议。"),
                PromptMessage(
                    role="user",
                    content=f"请对 {args.get('service_type', '未指定')} 服务进行 {args.get('compliance_standard', '等保2.0')} 合规检查。",
                ),
            ],
        ),
    }

    if name not in templates:
        return _rpc_error(ERROR_INVALID_PARAMS, f"Unknown prompt: {name}")

    description, messages = templates[name]
    result = GetPromptResult(description=description, messages=messages)
    return _rpc_result(request_id, result.model_dump(by_alias=True))


def _handle_ping(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    return _rpc_result(request_id, {})


def _handle_tools_list(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    """MCP tools/list — enumerate all available tools with their schemas."""
    try:
        descriptors = _registry.list_tools()
    except Exception as exc:
        logger.error("Failed to list tools for MCP tools/list: %s", exc)
        return _rpc_error(ERROR_INTERNAL, "Failed to enumerate tools")

    tools: list[McpToolItem] = []
    for desc in descriptors:
        # Build inputSchema from the tool definition
        properties: dict[str, Any] = {}
        required: list[str] = []
        if desc.input_schema and isinstance(desc.input_schema, dict):
            properties = desc.input_schema.get("properties", {})
            required = desc.input_schema.get("required", [])
        elif desc.input_field_hints and isinstance(desc.input_field_hints, dict):
            # Fallback: build properties from hints
            for field_name, hint in desc.input_field_hints.items():
                properties[field_name] = {
                    "type": "string",
                    "description": hint if isinstance(hint, str) else hint.get("description", ""),
                }
            if desc.input_schema_hint:
                required_fields = (
                    desc.operation_required_fields.get("execute", [])
                    if desc.operation_required_fields
                    else []
                )
                required = required_fields

        tools.append(
            McpToolItem(
                name=desc.name,
                description=desc.description or "",
                inputSchema=McpToolSchema(
                    type="object",
                    properties=properties,
                    required=required,
                ),
            )
        )

    result = ListToolsResult(tools=tools)
    return _rpc_result(request_id, result.model_dump(by_alias=True))


def _handle_tools_call(params: dict[str, Any] | None, request_id: str | int | None) -> dict:
    """MCP tools/call — invoke a tool by name with arguments."""
    import json

    from app.models.tools import ToolInvokeRequest, ToolExecutionContext

    if not params or "name" not in params:
        return _rpc_error(ERROR_INVALID_PARAMS, "Missing 'name' in params")

    tool_name = params["name"]
    arguments = params.get("arguments", {})

    # Resolve the tool from the registry
    tool = _registry.get_tool(tool_name)
    if tool is None:
        return _rpc_result(
            request_id,
            CallToolResult(
                content=[McpErrorContent(text=f"Tool not found: {tool_name}")],
                is_error=True,
            ).model_dump(by_alias=True),
        )

    # Build execution context — MCP calls have no pre-established auth context
    context = ToolExecutionContext(
        request_id=str(request_id) or "mcp",
        trace_id="",
        conversation_id="",
        message_id="",
        tenant_id="default",
        user_id=None,
        account_id=None,
        roles=[],
        permissions=[],
        locale="zh-CN",
        operator_type="mcp_client",
        operator_id="mcp",
    )

    # Determine operation: use "preview" for high-risk tools unless confirmed
    definition = tool.definition
    operation = "execute"
    if definition.high_risk and not arguments.get("_confirmed"):
        operation = "preview"

    invoke_request = ToolInvokeRequest(
        operation=operation,
        payload=arguments,
        context=context,
    )

    try:
        response = _dispatcher.invoke(tool, invoke_request)
    except Exception as exc:
        logger.error("MCP tools/call failed for %s: %s", tool_name, exc)
        return _rpc_result(
            request_id,
            CallToolResult(
                content=[McpErrorContent(text=f"Tool execution error: {exc}")],
                is_error=True,
            ).model_dump(by_alias=True),
        )

    if response.success:
        result_data = response.result if hasattr(response, "result") and response.result else {}
        content_text = json.dumps(
            {"tool_name": tool_name, "status": response.status, "data": result_data},
            ensure_ascii=False,
        )
        return _rpc_result(
            request_id,
            CallToolResult(
                content=[McpTextContent(text=content_text)],
                is_error=False,
            ).model_dump(by_alias=True),
        )
    else:
        error_parts = [f"Tool {tool_name} failed: {response.status}"]
        if response.message:
            error_parts.append(response.message)
        return _rpc_result(
            request_id,
            CallToolResult(
                content=[McpErrorContent(text="; ".join(error_parts))],
                is_error=True,
            ).model_dump(by_alias=True),
        )


METHOD_HANDLERS = {
    MCP_METHOD_INITIALIZE: _handle_initialize,
    MCP_METHOD_PING: _handle_ping,
    MCP_METHOD_RESOURCES_LIST: _handle_resources_list,
    MCP_METHOD_RESOURCES_READ: _handle_resources_read,
    MCP_METHOD_PROMPTS_LIST: _handle_prompts_list,
    MCP_METHOD_PROMPTS_GET: _handle_prompts_get,
    MCP_METHOD_TOOLS_LIST: _handle_tools_list,
    MCP_METHOD_TOOLS_CALL: _handle_tools_call,
}


@mcp_lifecycle_router.post("/mcp")
async def mcp_jsonrpc_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _rpc_error(ERROR_PARSE, "Failed to parse JSON-RPC body")

    try:
        rpc_request = JSONRPCRequest.model_validate(body)
    except Exception:
        return _rpc_error(ERROR_INVALID_REQUEST, "Invalid JSON-RPC 2.0 request structure")

    method = rpc_request.method
    handler = METHOD_HANDLERS.get(method)
    if handler is None:
        return _rpc_error(ERROR_METHOD_NOT_FOUND, f"Method not found: {method}", req_id=rpc_request.id)

    try:
        return handler(rpc_request.params, rpc_request.id)
    except Exception as exc:
        logger.exception("Unhandled error in MCP method %s", method)
        return _rpc_error(ERROR_INTERNAL, f"Internal error: {exc}")


@mcp_lifecycle_router.get("/mcp/initialize")
async def mcp_initialize_get():
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": _build_server_capabilities().model_dump(by_alias=True),
        "serverInfo": _build_server_info(),
        "instructions": "Use POST /mcp with JSON-RPC 2.0 for full MCP protocol.",
    }