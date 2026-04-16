from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

from app.core.business_tools_sdk import (
    BusinessTool,
    ToolDefinition,
    ToolExecutionResult,
    ToolInvocationRequest,
    is_missing_tool_value,
)
from app.models.tools import ToolInvokeRequest, ToolInvokeResponse


@dataclass
class ToolInvocationError(Exception):
    status_code: int
    code: str
    message: str
    details: dict | None = None


ToolExecutor = Callable[[ToolDefinition, ToolInvocationRequest], ToolExecutionResult]


class ToolDispatcher:
    def invoke(
        self,
        tool: BusinessTool | ToolDefinition,
        request: ToolInvokeRequest,
        executor: ToolExecutor | None = None,
    ) -> ToolInvokeResponse:
        definition = tool.definition if hasattr(tool, "definition") else tool

        if request.operation not in definition.supported_operations:
            raise ToolInvocationError(
                status_code=422,
                code="ORCH_TOOL_OPERATION_INVALID",
                message=f"Unsupported operation '{request.operation}' for tool '{definition.name}'.",
                details={"supported_operations": definition.supported_operations},
            )

        required_fields = definition.operation_required_fields.get(request.operation, [])
        missing_payload = [
            field
            for field in required_fields
            if is_missing_tool_value(request.payload.get(field))
        ]
        if missing_payload:
            raise ToolInvocationError(
                status_code=422,
                code="ORCH_TOOL_PAYLOAD_INVALID",
                message=f"Missing required payload field(s) for '{definition.name}'.",
                details={"missing_fields": missing_payload},
            )

        missing_auth = (
            request.context.missing_auth(definition.auth_requirements)
            if request.operation == "execute"
            else []
        )
        if missing_auth:
            raise ToolInvocationError(
                status_code=403,
                code="ORCH_TOOL_AUTH_REQUIRED",
                message=f"Tool '{definition.name}' requires authenticated execution context.",
                details={"missing_context": missing_auth},
            )

        invocation = ToolInvocationRequest(
            tool_name=definition.name,
            operation=request.operation,
            payload=request.payload,
            context=request.context,
        )
        if executor is not None:
            result = executor(definition, invocation)
        elif hasattr(tool, "invoke"):
            result = tool.invoke(invocation)
        else:
            raise ValueError(f"Tool '{definition.name}' requires an execution adapter.")
        return ToolInvokeResponse(
            **result.model_dump(),
            downstream_target=definition.downstream_target,
            auth_requirements=definition.auth_requirements,
        )
