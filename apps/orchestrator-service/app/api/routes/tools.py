from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.models.common import ApiEnvelope
from app.tools.definitions import knowledge_tools, marketing_tools, research_tools
from app.tools.permissions import check_permission, PermissionMode
from app.tools.registry import ToolDefinition, get_tool_registry

router = APIRouter(tags=["tools"])

# ——————————————————————————————————————
# bootstrap — register all tool definitions on import
# ——————————————————————————————————————

_registry = get_tool_registry()

_registry._tools.clear()
for tool_list in (knowledge_tools, marketing_tools, research_tools):
    for tool in tool_list:
        _registry.register(tool)


# ——————————————————————————————————————
# helper — extract role from request
# ——————————————————————————————————————

def _extract_role(request: Request) -> str:
    return request.headers.get("X-Role", "admin")


def _extract_user_context(request: Request) -> dict[str, Any]:
    return {
        "tenant_id": request.headers.get("X-Tenant-Id", "default"),
        "user_id": request.headers.get("X-User-Id", "unknown"),
    }


# ——————————————————————————————————————
# /api/v1/tools/list
# ——————————————————————————————————————


class ToolListItem(BaseModel):
    name: str
    description: str
    is_readonly: bool
    allowed_roles: list[str] = Field(default_factory=list)
    input_schema_fields: list[str] = Field(default_factory=list)


@router.get("/tools/list")
def list_tools(
    request: Request,
) -> ApiEnvelope[list[ToolListItem]]:
    role = _extract_role(request)
    user_context = _extract_user_context(request)

    tools = _registry.get_tools_for_role(role, user_context)

    items: list[ToolListItem] = []
    for t in tools:
        fields = list(t.input_schema.model_fields.keys()) if t.input_schema else []
        items.append(
            ToolListItem(
                name=t.name,
                description=t.description,
                is_readonly=t.is_readonly,
                allowed_roles=t.allowed_roles,
                input_schema_fields=fields,
            )
        )

    return ApiEnvelope(success=True, data=items)


# ——————————————————————————————————————
# /api/v1/tools/execute
# ——————————————————————————————————————


class ToolExecuteRequest(BaseModel):
    tool_name: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class ToolExecuteResponse(BaseModel):
    tool_name: str
    result: Any = None
    permission_mode: str = "auto"
    error: str | None = None


@router.post("/tools/execute")
def execute_tool(
    body: ToolExecuteRequest,
    request: Request,
) -> ApiEnvelope[ToolExecuteResponse]:
    role = _extract_role(request)
    user_context = _extract_user_context(request)

    tool = _registry.get_tool(body.tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool: {body.tool_name}")

    # three-layer filter
    available = _registry.get_tools_for_role(role, user_context)
    if tool not in available:
        raise HTTPException(status_code=403, detail=f"tool '{body.tool_name}' not allowed for role={role}")

    # permission check
    perm = check_permission(tool.name, tool.is_readonly, role, user_context)
    if perm.mode == PermissionMode.DENY:
        raise HTTPException(status_code=403, detail=perm.reason)

    # validate input
    try:
        validated_input = tool.input_schema.model_validate(body.inputs)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"input validation failed: {exc}")

    # execute
    try:
        if tool.execute_func:
            result = tool.execute_func(validated_input, user_context)
        else:
            result = {"status": "acknowledged", "inputs": validated_input.model_dump()}
    except Exception as exc:
        return ApiEnvelope(
            success=True,
            data=ToolExecuteResponse(
                tool_name=tool.name,
                error=str(exc),
                permission_mode=perm.mode.value,
            ),
        )

    return ApiEnvelope(
        success=True,
        data=ToolExecuteResponse(
            tool_name=tool.name,
            result=result,
            permission_mode=perm.mode.value,
        ),
    )
