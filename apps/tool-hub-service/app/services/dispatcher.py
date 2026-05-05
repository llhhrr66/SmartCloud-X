from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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

        # ── PRE_TOOL_USE hook ──
        from app.services.hooks import HookEvent, dispatch_hook
        from app.core.config import get_settings

        settings = get_settings()
        if settings.tool_hooks_enabled:
            pre_decision = dispatch_hook(
                HookEvent.PRE_TOOL_USE,
                definition.name,
                request.payload,
            )
            if pre_decision.action == "block":
                return ToolInvokeResponse(
                    tool_name=definition.name,
                    operation=request.operation,
                    status="hook-blocked",
                    summary=f"工具 {definition.name} 被钩子拦截：{pre_decision.message}",
                    result={},
                    citations=[],
                    audit_tags=["hook-blocked"],
                    session_context_patch={},
                    success=False,
                    code=4990001,
                    message=f"hook blocked: {pre_decision.message}",
                    provider=definition.provider,
                    downstream_target=definition.downstream_target,
                    auth_requirements=definition.auth_requirements,
                )
            if pre_decision.action == "warn":
                logger.info("PRE hook warning for %s: %s", definition.name, pre_decision.message)
            # Apply modified payload if hook altered it
            if pre_decision.modified_payload is not None:
                request = request.model_copy(update={"payload": pre_decision.modified_payload})

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

        response = ToolInvokeResponse(
            **result.model_dump(),
            downstream_target=definition.downstream_target,
            auth_requirements=definition.auth_requirements,
        )

        # ── POST_TOOL_USE hook ──
        if settings.tool_hooks_enabled:
            result_payload = result.result if result.result else {}
            post_decision = dispatch_hook(
                HookEvent.POST_TOOL_USE,
                definition.name,
                result_payload,
            )
            if post_decision.action == "block":
                logger.warning("POST hook blocked result for %s: %s", definition.name, post_decision.message)
                return ToolInvokeResponse(
                    tool_name=definition.name,
                    operation=request.operation,
                    status="hook-blocked-post",
                    summary=f"工具 {definition.name} 结果被钩子拦截：{post_decision.message}",
                    result={},
                    citations=result.citations,
                    audit_tags=[*result.audit_tags, "hook-blocked-post"],
                    session_context_patch=result.session_context_patch,
                    success=False,
                    code=4990002,
                    message=f"post-hook blocked: {post_decision.message}",
                    provider=definition.provider,
                    downstream_target=definition.downstream_target,
                    auth_requirements=definition.auth_requirements,
                )
            if post_decision.action == "warn":
                logger.info("POST hook warning for %s: %s", definition.name, post_decision.message)

        return response
