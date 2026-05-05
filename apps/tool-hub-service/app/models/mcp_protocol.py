from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ── JSON-RPC 2.0 envelope ──

class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] | None = None
    id: str | int | None = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    result: Any | None = None
    error: JSONRPCError | None = None


# ── Capabilities ──

class ClientCapabilities(BaseModel):
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None


class ServerCapabilities(BaseModel):
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None


# ── Implementation info ──

class ImplementationInfo(BaseModel):
    name: str
    version: str


# ── Initialize ──

class InitializeRequestParams(BaseModel):
    protocol_version: str = Field(alias="protocolVersion")
    capabilities: ClientCapabilities = Field(default_factory=ClientCapabilities)
    client_info: ImplementationInfo = Field(alias="clientInfo")

    model_config = {"populate_by_name": True}


class InitializeResponseResult(BaseModel):
    protocol_version: str = Field(alias="protocolVersion")
    capabilities: ServerCapabilities = Field(default_factory=ServerCapabilities)
    server_info: ImplementationInfo = Field(alias="serverInfo")
    instructions: str | None = None

    model_config = {"populate_by_name": True}


# ── Resources ──

class ResourceItem(BaseModel):
    uri: str
    name: str
    description: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    size: int | None = None

    model_config = {"populate_by_name": True}


class TextResourceContents(BaseModel):
    uri: str
    mime_type: str | None = Field(default=None, alias="mimeType")
    text: str

    model_config = {"populate_by_name": True}


class BlobResourceContents(BaseModel):
    uri: str
    mime_type: str | None = Field(default=None, alias="mimeType")
    blob: str

    model_config = {"populate_by_name": True}


class ListResourcesResult(BaseModel):
    resources: list[ResourceItem] = Field(default_factory=list)


class ReadResourceResult(BaseModel):
    contents: list[TextResourceContents | BlobResourceContents] = Field(default_factory=list)


# ── Prompts ──

class PromptArgument(BaseModel):
    name: str
    description: str | None = None
    required: bool = False


class PromptItem(BaseModel):
    name: str
    description: str | None = None
    arguments: list[PromptArgument] = Field(default_factory=list)


class ListPromptsResult(BaseModel):
    prompts: list[PromptItem] = Field(default_factory=list)


class PromptMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: Any


class GetPromptResult(BaseModel):
    description: str | None = None
    messages: list[PromptMessage] = Field(default_factory=list)


# ── Notifications ──

class NotificationParams(BaseModel):
    level: Literal["debug", "info", "warning", "error"] | None = None
    data: dict[str, Any] | None = None


# ── Method names as constants ──

MCP_METHOD_INITIALIZE = "initialize"
MCP_METHOD_INITIALIZED = "notifications/initialized"
MCP_METHOD_RESOURCES_LIST = "resources/list"
MCP_METHOD_RESOURCES_READ = "resources/read"
MCP_METHOD_RESOURCES_TEMPLATES_LIST = "resources/templates/list"
MCP_METHOD_PROMPTS_LIST = "prompts/list"
MCP_METHOD_PROMPTS_GET = "prompts/get"
MCP_METHOD_PING = "ping"

MCP_METHOD_TOOLS_LIST = "tools/list"
MCP_METHOD_TOOLS_CALL = "tools/call"

PROTOCOL_VERSION = "2024-11-05"

# MCP standard error codes
ERROR_PARSE = -32700
ERROR_INVALID_REQUEST = -32600
ERROR_METHOD_NOT_FOUND = -32601
ERROR_INVALID_PARAMS = -32602
ERROR_INTERNAL = -32603


# ── Tools ──

class McpToolSchema(BaseModel):
    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class McpToolItem(BaseModel):
    name: str
    description: str | None = None
    input_schema: McpToolSchema = Field(alias="inputSchema", default_factory=McpToolSchema)

    model_config = {"populate_by_name": True}


class ListToolsResult(BaseModel):
    tools: list[McpToolItem] = Field(default_factory=list)


class McpTextContent(BaseModel):
    type: str = "text"
    text: str


class McpErrorContent(BaseModel):
    type: str = "text"
    text: str


class CallToolResult(BaseModel):
    content: list[McpTextContent | McpErrorContent] = Field(default_factory=list)
    is_error: bool = Field(default=False, alias="isError")

    model_config = {"populate_by_name": True}