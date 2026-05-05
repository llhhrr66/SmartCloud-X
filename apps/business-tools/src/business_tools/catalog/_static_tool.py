from __future__ import annotations

from typing import Any, Callable

from business_tools.idempotency import get_idempotency_store
from business_tools.query_cache import get_query_cache_store
from business_tools.interfaces import (
    BusinessTool,
    ToolDefinition,
    ToolExecutionResult,
    ToolInvocationRequest,
    build_tool_user_action_hint,
    is_missing_tool_value,
)

from ._compensation import _build_compensation
from ._session_context_patch import _build_session_context_patch


ResultBuilder = Callable[[ToolInvocationRequest], tuple[str, dict[str, Any], list[str]]]


class StaticBusinessTool(BusinessTool):
    """Catalog-driven tool that delegates to preview/execute builder callables.

    The class enforces the cross-cutting policies — payload validation,
    auth-required short-circuiting, confirmation gating, idempotency, and
    query-result caching — so that domain builders can stay focused on the
    business behaviour for each tool.
    """

    def __init__(
        self,
        definition: ToolDefinition,
        preview_builder: ResultBuilder,
        execute_builder: ResultBuilder | None = None,
    ) -> None:
        self.definition = definition
        self._preview_builder = preview_builder
        self._execute_builder = execute_builder or preview_builder

    def invoke(self, request: ToolInvocationRequest) -> ToolExecutionResult:
        audit_tags = [self.definition.capability, request.operation, self.definition.mode]
        if self.definition.high_risk:
            audit_tags.append("high-risk")

        required_fields = self.definition.operation_required_fields.get(request.operation, [])
        missing_payload = [
            field
            for field in required_fields
            if is_missing_tool_value(request.payload.get(field))
        ]
        if missing_payload:
            return ToolExecutionResult(
                tool_name=self.definition.name,
                operation=request.operation,
                status="invalid-payload",
                summary=f"{self.definition.name} 缺少必要字段：{', '.join(missing_payload)}。",
                result={
                    "missing_fields": missing_payload,
                    "required_fields": required_fields,
                },
                citations=[],
                audit_tags=[*audit_tags, "invalid-payload"],
                session_context_patch={},
                success=False,
                code=4001001,
                message="invalid tool payload",
                provider=self.definition.provider,
                error_detail={"missing_fields": missing_payload},
                idempotency_key=request.context.idempotency_key,
                user_action_hint=build_tool_user_action_hint(
                    self.definition,
                    status="invalid-payload",
                    missing_payload_fields=missing_payload,
                    missing_payload_hints={
                        field: self.definition.input_field_hints[field]
                        for field in missing_payload
                        if field in self.definition.input_field_hints
                    },
                ),
            )

        builder = self._preview_builder if request.operation == "preview" else self._execute_builder

        # ── PRE_TOOL_USE hook (business-tools layer) ──
        try:
            from business_tools.hooks import HookEvent, dispatch_hook
            pre_decision = dispatch_hook(HookEvent.PRE_TOOL_USE, self.definition.name, request.payload)
            if pre_decision.action == "block":
                return ToolExecutionResult(
                    tool_name=self.definition.name,
                    operation=request.operation,
                    status="hook-blocked",
                    summary=f"工具 {self.definition.name} 被钩子拦截：{pre_decision.message}",
                    result={},
                    citations=[],
                    audit_tags=[*audit_tags, "hook-blocked"],
                    session_context_patch={},
                    success=False,
                    code=4990001,
                    message=f"hook blocked: {pre_decision.message}",
                    provider=self.definition.provider,
                    idempotency_key=request.context.idempotency_key,
                )
            if pre_decision.action == "warn":
                import logging
                logging.getLogger(__name__).info(
                    "PRE hook warning for %s: %s", self.definition.name, pre_decision.message,
                )
            if pre_decision.modified_payload is not None:
                # Patch the request payload with the modified one
                request = ToolInvocationRequest(
                    tool_name=request.tool_name,
                    operation=request.operation,
                    payload=pre_decision.modified_payload,
                    context=request.context,
                )
        except ImportError:
            pass  # hooks module not available — skip

        summary, payload, citations = builder(request)
        compensation = _build_compensation(self.definition, request, payload)
        session_context_patch = _build_session_context_patch(self.definition, request, payload)
        missing_auth = (
            request.context.missing_auth(self.definition.auth_requirements)
            if request.operation == "execute"
            else []
        )

        if missing_auth:
            payload = {
                **payload,
                "missing_context": missing_auth,
                "auth_requirements": self.definition.auth_requirements.model_dump(),
            }
            return ToolExecutionResult(
                tool_name=self.definition.name,
                operation=request.operation,
                status="auth-required",
                summary=f"{summary}；执行前需补充鉴权上下文。",
                result=payload,
                citations=citations,
                audit_tags=audit_tags,
                session_context_patch=session_context_patch,
                success=False,
                code=4030001,
                message="auth context missing",
                provider=self.definition.provider,
                cache_ttl_seconds=self.definition.cache_ttl_seconds if self.definition.mode == "query" else None,
                error_detail={"missing_context": missing_auth},
                idempotency_key=request.context.idempotency_key,
                user_action_hint=build_tool_user_action_hint(
                    self.definition,
                    status="auth-required",
                    missing_auth_context=missing_auth,
                    required_permissions=list(self.definition.auth_requirements.required_permissions),
                    requires_account_context=self.definition.auth_requirements.require_account_id,
                ),
            )

        if (
            request.operation == "execute"
            and self.definition.auth_requirements.confirmation_required
            and not request.payload.get("_confirmed")
        ):
            payload = {
                **payload,
                "confirmation_required": True,
                "confirmation_hint": "set payload._confirmed=true after explicit user confirmation",
            }
            return ToolExecutionResult(
                tool_name=self.definition.name,
                operation=request.operation,
                status="confirmation-required",
                summary=f"{summary}；该工具属于写操作，需先完成显式确认。",
                result=payload,
                citations=citations,
                audit_tags=audit_tags,
                session_context_patch=session_context_patch,
                success=False,
                code=4090002,
                message="confirmation required",
                provider=self.definition.provider,
                error_detail={"reason": "confirmation_required"},
                idempotency_key=request.context.idempotency_key,
                user_action_hint=build_tool_user_action_hint(
                    self.definition,
                    status="confirmation-required",
                    confirmation_required=self.definition.auth_requirements.confirmation_required,
                ),
            )

        if request.operation == "execute" and self.definition.mode == "query":
            cached = get_query_cache_store().get(
                self.definition.name,
                request.operation,
                request.payload,
                request.context,
            )
            if cached is not None:
                return cached

        if request.operation == "execute" and self.definition.mode == "write" and request.context.idempotency_key:
            replayed, conflict = get_idempotency_store().get(
                self.definition.name,
                request.context.idempotency_key,
                request.payload,
                request.context,
            )
            if conflict:
                return ToolExecutionResult(
                    tool_name=self.definition.name,
                    operation=request.operation,
                    status="idempotency-conflict",
                    summary=f"{summary}；幂等键已被其他写入请求占用。",
                    result={"idempotency_key": request.context.idempotency_key},
                    citations=citations,
                    audit_tags=[*audit_tags, "idempotency-conflict"],
                    session_context_patch={},
                    success=False,
                    code=4090001,
                    message="idempotency conflict",
                    provider=self.definition.provider,
                    error_detail={"reason": "idempotency_conflict"},
                    idempotency_key=request.context.idempotency_key,
                )
            if replayed is not None:
                return replayed

        preview_confirmation_hint = (
            build_tool_user_action_hint(
                self.definition,
                status="confirmation-required",
                confirmation_required=self.definition.auth_requirements.confirmation_required,
            )
            if (
                request.operation == "preview"
                and self.definition.mode == "write"
                and self.definition.auth_requirements.confirmation_required
            )
            else None
        )
        status = "preview-ready" if request.operation == "preview" else "completed"
        result = ToolExecutionResult(
            tool_name=self.definition.name,
            operation=request.operation,
            status=status,
            summary=summary,
            result=payload,
            citations=citations,
            audit_tags=audit_tags,
            session_context_patch=session_context_patch,
            success=True,
            code=0,
            message="ok",
            provider=self.definition.provider,
            cache_ttl_seconds=self.definition.cache_ttl_seconds if self.definition.mode == "query" else None,
            compensation=compensation,
            idempotency_key=request.context.idempotency_key,
            user_action_hint=preview_confirmation_hint,
        )

        # ── POST_TOOL_USE hook (business-tools layer) ──
        try:
            from business_tools.hooks import HookEvent, dispatch_hook
            result_payload = result.result if result.result else {}
            post_decision = dispatch_hook(HookEvent.POST_TOOL_USE, self.definition.name, result_payload)
            if post_decision.action == "block":
                import logging
                logging.getLogger(__name__).warning(
                    "POST hook blocked result for %s: %s", self.definition.name, post_decision.message,
                )
                return ToolExecutionResult(
                    tool_name=self.definition.name,
                    operation=request.operation,
                    status="hook-blocked-post",
                    summary=f"工具 {self.definition.name} 结果被钩子拦截：{post_decision.message}",
                    result={},
                    citations=citations,
                    audit_tags=[*audit_tags, "hook-blocked-post"],
                    session_context_patch=session_context_patch,
                    success=False,
                    code=4990002,
                    message=f"post-hook blocked: {post_decision.message}",
                    provider=self.definition.provider,
                    idempotency_key=request.context.idempotency_key,
                )
            if post_decision.action == "warn":
                import logging
                logging.getLogger(__name__).info(
                    "POST hook warning for %s: %s", self.definition.name, post_decision.message,
                )
        except ImportError:
            pass  # hooks module not available — skip
        if request.operation == "execute" and self.definition.mode == "write" and request.context.idempotency_key:
            return get_idempotency_store().save(
                self.definition.name,
                request.context.idempotency_key,
                request.payload,
                request.context,
                self.definition.idempotency_window_seconds,
                result,
            )
        if request.operation == "execute" and self.definition.mode == "query":
            return get_query_cache_store().save(
                self.definition.name,
                request.operation,
                request.payload,
                request.context,
                self.definition.cache_ttl_seconds,
                result,
            )
        return result
