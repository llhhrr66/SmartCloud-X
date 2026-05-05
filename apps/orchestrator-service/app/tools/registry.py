from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

# ——————————————————————————————————————
# Layer 1: global disallow list
# ——————————————————————————————————————
ALL_AGENT_DISALLOWED_TOOLS: set[str] = {
    "delete_database",
    "drop_table",
    "truncate_table",
    "execute_raw_sql",
    "shutdown_server",
    "revoke_all_permissions",
}

# ——————————————————————————————————————
# Layer 2: per-role tool whitelist
# ——————————————————————————————————————
ROLE_TOOL_WHITELIST: dict[str, set[str]] = {
    "admin": set(),  # empty = unrestricted
    "research": {
        "search_documents",
        "list_knowledge_bases",
        "analyze",
        "search",
    },
    "marketing": {
        "generate_poster",
        "create_campaign",
        "generate_copy",
        "search_documents",
        "list_knowledge_bases",
    },
}


class ToolDefinition(BaseModel):
    """Declarative tool definition — register once, filter by role."""

    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel] | None = None
    is_readonly: bool = True
    allowed_roles: list[str] = ["admin"]
    execute_func: Callable[..., Any] | None = None

    model_config = {"arbitrary_types_allowed": True}


class ToolRegistry:
    """Central registry with three-layer permission filtering."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # -- registration --------------------------------------------------

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get_all_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    # -- three-layer filtering -----------------------------------------

    def _layer1_global_deny(self, tools: list[ToolDefinition]) -> list[ToolDefinition]:
        return [t for t in tools if t.name not in ALL_AGENT_DISALLOWED_TOOLS]

    def _layer2_role_filter(self, tools: list[ToolDefinition], role: str) -> list[ToolDefinition]:
        allowed = ROLE_TOOL_WHITELIST.get(role)
        if allowed is None or len(allowed) == 0:
            return tools
        return [t for t in tools if t.name in allowed]

    def _layer3_runtime_check(
        self,
        tools: list[ToolDefinition],
        user_context: dict[str, Any],
        permission_checker: Callable[..., bool] | None = None,
    ) -> list[ToolDefinition]:
        if permission_checker is None:
            return tools
        return [t for t in tools if permission_checker(t, user_context)]

    # -- public API ----------------------------------------------------

    def get_tools_for_role(
        self,
        role: str,
        user_context: dict[str, Any] | None = None,
        permission_checker: Callable[..., bool] | None = None,
    ) -> list[ToolDefinition]:
        tools = self.get_all_tools()
        tools = self._layer1_global_deny(tools)
        tools = self._layer2_role_filter(tools, role)
        if user_context and permission_checker:
            tools = self._layer3_runtime_check(tools, user_context, permission_checker)
        return tools

    def filter_tools(
        self,
        deny_list: set[str] | None = None,
        allow_list: set[str] | None = None,
    ) -> list[ToolDefinition]:
        tools = self.get_all_tools()
        deny = deny_list or set()
        if allow_list is not None:
            tools = [t for t in tools if t.name in allow_list]
        tools = [t for t in tools if t.name not in deny]
        return tools


# ——————————————————————————————————————
# singleton
# ——————————————————————————————————————
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
