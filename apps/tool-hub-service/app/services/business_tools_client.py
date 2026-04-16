from __future__ import annotations

import time

import httpx

from app.core.business_tools_sdk import (
    BusinessTool,
    CompensationExecutionRequest,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolInvocationRequest,
    ToolMode,
    ToolPreflightResult,
    ToolUserActionHint,
    build_catalog,
    execute_compensation,
    filter_tool_definitions,
    preflight_tool_invocation,
)
from app.core.config import Settings, get_settings
from app.models.tools import (
    CompensationCallRequest,
    CompensationCallResponse,
    ToolCallError,
    ToolCallRequest,
    ToolCallResponse,
)


class _DefinitionOnlyTool:
    def __init__(self, definition: ToolDefinition) -> None:
        self.definition = definition


class BusinessToolsClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._catalog = build_catalog()

    def invoke_call(self, tool: BusinessTool, request: ToolCallRequest) -> ToolCallResponse:
        try:
            definition = self.describe_tool(request.tool_name) or tool.definition
        except (httpx.HTTPError, ValueError):
            definition = tool.definition
        effective_tool = _DefinitionOnlyTool(definition)
        attempts = 0
        max_attempts = 1 + (self.settings.tool_retry_attempts if definition.idempotent else 0)
        last_response: ToolCallResponse | None = None

        while attempts < max_attempts:
            attempts += 1
            attempt_started = time.perf_counter()
            try:
                response = (
                    self._invoke_via_http(effective_tool, request)
                    if self.settings.business_tools_transport == "http"
                    else self._invoke_locally(tool, request)
                )
            except httpx.TimeoutException as exc:
                response = ToolCallResponse(
                    success=False,
                    code=5003002,
                    message="downstream timeout",
                    status="timeout",
                    summary="downstream timeout",
                    result={},
                    data={},
                    citations=[],
                    audit_tags=[],
                    tool_call_id=request.tool_call_id,
                    latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                    provider=definition.provider,
                    error=ToolCallError(
                        retryable=True,
                        provider=definition.provider,
                        details={"exception": exc.__class__.__name__},
                    ),
                    idempotency_key=request.idempotency_key,
                    attempts=attempts,
                )
            except httpx.HTTPError as exc:
                response = ToolCallResponse(
                    success=False,
                    code=5003001,
                    message="downstream http error",
                    status="failed",
                    summary="downstream http error",
                    result={},
                    data={},
                    citations=[],
                    audit_tags=[],
                    tool_call_id=request.tool_call_id,
                    latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                    provider=definition.provider,
                    error=ToolCallError(
                        retryable=False,
                        provider=definition.provider,
                        details={"exception": exc.__class__.__name__},
                    ),
                    idempotency_key=request.idempotency_key,
                    attempts=attempts,
                )
            response.attempts = attempts
            last_response = response
            if response.success:
                return response
            if not response.error or not response.error.retryable or attempts >= max_attempts:
                return response
        return last_response or ToolCallResponse(
            success=False,
            code=5003000,
            message="business tool invocation failed",
            status="failed",
            summary="business tool invocation failed",
            result={},
            data={},
            citations=[],
            audit_tags=[],
            tool_call_id=request.tool_call_id,
            latency_ms=0,
            error=ToolCallError(retryable=False, provider=definition.provider, details={}),
            attempts=attempts,
        )

    def invoke_tool(
        self,
        definition: ToolDefinition,
        request: ToolInvocationRequest,
    ) -> ToolExecutionResult:
        if self.settings.business_tools_transport != "http":
            tool = self._catalog.get(definition.name)
            if tool is None:
                raise ValueError(f"Unknown tool: {definition.name}")
            return tool.invoke(request)
        try:
            return self._invoke_tool_via_http(definition, request)
        except (httpx.HTTPError, ValueError):
            tool = self._catalog.get(definition.name)
            if tool is None:
                raise
            return tool.invoke(request)

    def list_tools(
        self,
        *,
        capability: str | None = None,
        mode: ToolMode | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[ToolDefinition]:
        if self.settings.business_tools_transport != "http":
            return filter_tool_definitions(
                (tool.definition for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])),
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )
        try:
            with httpx.Client(
                base_url=self.settings.business_tools_base_url,
                timeout=self.settings.request_timeout_ms / 1000,
            ) as client:
                params = {
                    key: value
                    for key, value in {
                        "capability": capability,
                        "mode": mode,
                        "tag": tag,
                        "query": query,
                    }.items()
                    if value not in {None, ""}
                }
                response = client.get(
                    f"{self.settings.business_tools_internal_api_prefix}/tools",
                    headers=self._discovery_headers(),
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return filter_tool_definitions(
                (tool.definition for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])),
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )
        raw_tools = payload.get("tools", payload.get("data", [])) if isinstance(payload, dict) else []
        return [ToolDefinition.model_validate(raw_tool) for raw_tool in raw_tools]

    def describe_tool(self, tool_name: str) -> ToolDefinition | None:
        if self.settings.business_tools_transport != "http":
            tool = self._catalog.get(tool_name)
            return tool.definition.model_copy(deep=True) if tool else None
        try:
            with httpx.Client(
                base_url=self.settings.business_tools_base_url,
                timeout=self.settings.request_timeout_ms / 1000,
            ) as client:
                response = client.get(
                    f"{self.settings.business_tools_internal_api_prefix}/tools/{tool_name}",
                    headers=self._discovery_headers(),
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            tool = self._catalog.get(tool_name)
            return tool.definition.model_copy(deep=True) if tool else None
        if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
            payload = payload["data"]
        return ToolDefinition.model_validate(payload)

    def preflight_call(self, tool_name: str, request: ToolCallRequest) -> ToolPreflightResult:
        try:
            definition = self.describe_tool(tool_name)
        except (httpx.HTTPError, ValueError):
            tool = self._catalog.get(tool_name)
            definition = tool.definition.model_copy(deep=True) if tool else None
        if definition is None:
            return ToolPreflightResult(
                tool_name=tool_name,
                operation=request.operation,
                status="missing-tool",
                ready=False,
                available=False,
            )
        invocation = ToolInvocationRequest(
            tool_name=tool_name,
            operation=request.operation,
            payload=request.payload,
            context=ToolExecutionContext(
                request_id=request.tool_call_id,
                trace_id=request.trace_id,
                conversation_id=request.conversation_id,
                message_id=request.message_id,
                tenant_id=request.user_context.tenant_id,
                user_id=request.user_context.user_id,
                account_id=request.user_context.account_id,
                roles=request.user_context.roles,
                permissions=request.user_context.permissions,
                locale=request.user_context.locale,
                operator_type=request.operator.type,
                operator_id=request.operator.id,
                idempotency_key=request.idempotency_key,
            ),
        )
        if self.settings.business_tools_transport != "http":
            return preflight_tool_invocation(definition, invocation)
        try:
            with httpx.Client(
                base_url=self.settings.business_tools_base_url,
                timeout=self.settings.request_timeout_ms / 1000,
            ) as client:
                response = client.post(
                    f"{self.settings.business_tools_internal_api_prefix}/preflight/{tool_name}",
                    json={
                        "operator": request.operator.model_dump(),
                        "subject": request.user_context.model_dump(),
                        "payload": request.payload,
                        "operation": request.operation,
                    },
                    headers=self._tool_execution_headers(request),
                )
                response.raise_for_status()
                payload = response.json()
            return ToolPreflightResult.model_validate(payload)
        except (httpx.HTTPError, ValueError):
            return preflight_tool_invocation(definition, invocation)

    def _invoke_locally(self, tool: BusinessTool, request: ToolCallRequest) -> ToolCallResponse:
        started = time.perf_counter()
        result = tool.invoke(
            ToolInvocationRequest(
                tool_name=request.tool_name,
                operation=request.operation,
                payload=request.payload,
                context=ToolExecutionContext(
                    request_id=request.tool_call_id,
                    trace_id=request.trace_id,
                    conversation_id=request.conversation_id,
                    message_id=request.message_id,
                    tenant_id=request.user_context.tenant_id,
                    user_id=request.user_context.user_id,
                    account_id=request.user_context.account_id,
                    roles=request.user_context.roles,
                    permissions=request.user_context.permissions,
                    locale=request.user_context.locale,
                    operator_type=request.operator.type,
                    operator_id=request.operator.id,
                    idempotency_key=request.idempotency_key,
                ),
            )
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = None
        if not result.success:
            error = ToolCallError(
                retryable=result.retryable,
                provider=result.provider,
                details=result.error_detail,
            )
        return ToolCallResponse(
            success=result.success,
            code=result.code,
            message=result.message,
            status=result.status,
            summary=result.summary,
            result=result.result,
            data=result.result,
            citations=result.citations,
            audit_tags=result.audit_tags,
            session_context_patch=result.session_context_patch,
            tool_call_id=request.tool_call_id,
            latency_ms=latency_ms,
            provider=result.provider,
            error=error,
            compensation=result.compensation,
            idempotency_key=result.idempotency_key,
            user_action_hint=result.user_action_hint,
        )

    def _invoke_via_http(self, tool: BusinessTool, request: ToolCallRequest) -> ToolCallResponse:
        started = time.perf_counter()
        with httpx.Client(
            base_url=self.settings.business_tools_base_url,
            timeout=tool.definition.timeout_ms / 1000,
        ) as client:
            response = client.post(
                f"{self.settings.business_tools_internal_api_prefix}/execute/{request.tool_name}",
                json={
                    "operator": request.operator.model_dump(),
                    "subject": request.user_context.model_dump(),
                    "payload": request.payload,
                    "operation": request.operation,
                },
                headers=self._tool_execution_headers(request),
            )
            response.raise_for_status()
            payload = response.json()
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = None
        if not payload["success"]:
            error = ToolCallError(
                retryable=bool(payload.get("retryable", False)),
                provider=payload.get("provider", tool.definition.provider),
                details=payload.get("error_detail", {}),
            )
        result_payload = self._tool_result(payload)
        return ToolCallResponse(
            success=payload["success"],
            code=payload["code"],
            message=self._tool_message(payload),
            status=payload.get("status", self._status_from_execute_payload(payload, request.operation)),
            summary=payload.get("summary", self._tool_message(payload)),
            result=result_payload,
            data=result_payload,
            citations=payload.get("citations", []),
            audit_tags=payload.get("audit_tags", []),
            session_context_patch=payload.get("session_context_patch", {}),
            tool_call_id=request.tool_call_id,
            latency_ms=latency_ms,
            provider=payload.get("provider", tool.definition.provider),
            error=error,
            compensation=payload.get("compensation"),
            idempotency_key=payload.get("idempotency_key"),
            user_action_hint=self._tool_user_action_hint(payload),
        )

    def _invoke_tool_via_http(
        self,
        definition: ToolDefinition,
        request: ToolInvocationRequest,
    ) -> ToolExecutionResult:
        with httpx.Client(
            base_url=self.settings.business_tools_base_url,
            timeout=definition.timeout_ms / 1000,
        ) as client:
            response = client.post(
                f"{self.settings.business_tools_internal_api_prefix}/execute/{definition.name}",
                json={
                    "operator": {
                        "type": request.context.operator_type or "agent",
                        "id": request.context.operator_id or self.settings.app_name,
                    },
                    "subject": {
                        "user_id": request.context.user_id,
                        "account_id": request.context.account_id,
                        "tenant_id": request.context.tenant_id,
                        "roles": request.context.roles,
                        "permissions": request.context.permissions,
                        "locale": request.context.locale,
                    },
                    "payload": request.payload,
                    "operation": request.operation,
                },
                headers=self._tool_invoke_headers(request),
            )
            response.raise_for_status()
            payload = response.json()
        return ToolExecutionResult(
            tool_name=payload.get("tool_name", definition.name),
            operation=payload.get("operation", request.operation),
            status=payload.get("status", self._status_from_execute_payload(payload, request.operation)),
            summary=payload.get("summary", self._tool_message(payload)),
            result=self._tool_result(payload),
            citations=payload.get("citations", []),
            audit_tags=payload.get("audit_tags", []),
            session_context_patch=payload.get("session_context_patch", {}),
            success=bool(payload.get("success", True)),
            code=payload.get("code", 0),
            message=self._tool_message(payload),
            retryable=bool(payload.get("retryable", False)),
            provider=payload.get("provider", definition.provider),
            cache_ttl_seconds=payload.get("cache_ttl_seconds"),
            error_detail=payload.get("error_detail", {}),
            compensation=payload.get("compensation"),
            idempotency_key=payload.get("idempotency_key"),
            user_action_hint=self._tool_user_action_hint(payload),
        )

    def invoke_compensation(self, request: CompensationCallRequest) -> CompensationCallResponse:
        attempt_started = time.perf_counter()
        try:
            response = (
                self._invoke_compensation_via_http(request)
                if self.settings.business_tools_transport == "http"
                else self._invoke_compensation_locally(request)
            )
        except httpx.TimeoutException as exc:
            response = CompensationCallResponse(
                success=False,
                code=5003002,
                message="downstream timeout",
                data={},
                compensation_id=request.compensation_id,
                action_name=request.action_name,
                latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                provider="business-tools",
                error=ToolCallError(
                    retryable=True,
                    provider="business-tools",
                    details={"exception": exc.__class__.__name__},
                ),
                idempotency_key=request.idempotency_key,
                attempts=1,
            )
        except httpx.HTTPError as exc:
            response = CompensationCallResponse(
                success=False,
                code=5003001,
                message="downstream http error",
                data={},
                compensation_id=request.compensation_id,
                action_name=request.action_name,
                latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                provider="business-tools",
                error=ToolCallError(
                    retryable=False,
                    provider="business-tools",
                    details={"exception": exc.__class__.__name__},
                ),
                idempotency_key=request.idempotency_key,
                attempts=1,
            )
        response.attempts = 1
        return response

    def _invoke_compensation_locally(self, request: CompensationCallRequest) -> CompensationCallResponse:
        started = time.perf_counter()
        result = execute_compensation(
            CompensationExecutionRequest(
                action_name=request.action_name,
                payload=request.payload,
                context=ToolExecutionContext(
                    request_id=request.compensation_id,
                    trace_id=request.trace_id,
                    conversation_id=request.conversation_id,
                    operator_type=request.operator.type,
                    operator_id=request.operator.id,
                    idempotency_key=request.idempotency_key,
                ),
            )
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = None
        if not result.success:
            error = ToolCallError(
                retryable=result.retryable,
                provider=result.provider,
                details=result.error_detail,
            )
        return CompensationCallResponse(
            success=result.success,
            code=result.code,
            message=result.summary,
            data=result.result,
            compensation_id=request.compensation_id,
            action_name=request.action_name,
            latency_ms=latency_ms,
            provider=result.provider,
            error=error,
            idempotency_key=result.idempotency_key,
        )

    def _invoke_compensation_via_http(self, request: CompensationCallRequest) -> CompensationCallResponse:
        started = time.perf_counter()
        with httpx.Client(
            base_url=self.settings.business_tools_base_url,
            timeout=self.settings.request_timeout_ms / 1000,
        ) as client:
            response = client.post(
                f"{self.settings.business_tools_internal_api_prefix}/compensations/execute",
                json={
                    "compensation_id": request.compensation_id,
                    "conversation_id": request.conversation_id,
                    "action_name": request.action_name,
                    "operator": request.operator.model_dump(),
                    "payload": request.payload,
                },
                headers=self._compensation_headers(request),
            )
            response.raise_for_status()
            payload = response.json()
        latency_ms = int((time.perf_counter() - started) * 1000)
        error = None
        if not payload["success"]:
            error = ToolCallError(
                retryable=bool(payload.get("retryable", False)),
                provider=payload.get("provider", "business-tools"),
                details=payload.get("error_detail", {}),
            )
        return CompensationCallResponse(
            success=payload["success"],
            code=payload["code"],
            message=payload["message"],
            data=payload.get("data", {}),
            compensation_id=payload.get("compensation_id", request.compensation_id),
            action_name=payload.get("action_name", request.action_name),
            latency_ms=payload.get("latency_ms", latency_ms),
            provider=payload.get("provider", "business-tools"),
            error=error,
            idempotency_key=payload.get("idempotency_key"),
        )

    def _tool_execution_headers(self, request: ToolCallRequest) -> dict[str, str]:
        return {
            self.settings.request_id_header: request.tool_call_id,
            self.settings.trace_id_header: request.trace_id,
            self.settings.conversation_id_header: request.conversation_id,
            self.settings.message_id_header: request.message_id or request.tool_call_id,
            self.settings.tenant_id_header: request.user_context.tenant_id,
            self.settings.caller_service_header: self.settings.app_name,
            self.settings.tool_call_id_header: request.tool_call_id,
            self.settings.idempotency_key_header: request.idempotency_key or f"tool-{request.tool_call_id}",
        }

    def _tool_invoke_headers(self, request: ToolInvocationRequest) -> dict[str, str]:
        request_id = request.context.request_id or f"invoke-{request.tool_name}"
        trace_id = request.context.trace_id or request_id
        conversation_id = request.context.conversation_id or "unknown"
        message_id = request.context.message_id or request_id
        return {
            self.settings.request_id_header: request_id,
            self.settings.trace_id_header: trace_id,
            self.settings.conversation_id_header: conversation_id,
            self.settings.message_id_header: message_id,
            self.settings.tenant_id_header: request.context.tenant_id,
            self.settings.caller_service_header: self.settings.app_name,
            self.settings.tool_call_id_header: request_id,
            self.settings.idempotency_key_header: request.context.idempotency_key or f"tool-{request_id}",
        }

    def _discovery_headers(self) -> dict[str, str]:
        return {
            self.settings.caller_service_header: self.settings.app_name,
        }

    def _compensation_headers(self, request: CompensationCallRequest) -> dict[str, str]:
        return {
            self.settings.request_id_header: request.compensation_id,
            self.settings.trace_id_header: request.trace_id,
            self.settings.conversation_id_header: request.conversation_id,
            self.settings.caller_service_header: self.settings.app_name,
            self.settings.idempotency_key_header: request.idempotency_key or f"comp-{request.compensation_id}",
        }

    @staticmethod
    def _tool_message(payload: dict[str, object]) -> str:
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
        summary = payload.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        return "ok"

    @staticmethod
    def _tool_result(payload: dict[str, object]) -> dict[str, object]:
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _status_from_execute_payload(payload: dict[str, object], operation: str) -> str:
        if payload.get("success"):
            return "preview-ready" if operation == "preview" else "completed"
        return {
            4001001: "invalid-payload",
            4030001: "auth-required",
            4040001: "missing-tool",
            4090001: "idempotency-conflict",
            4090002: "confirmation-required",
        }.get(payload.get("code"), "failed")

    @staticmethod
    def _tool_user_action_hint(payload: dict[str, object]) -> ToolUserActionHint | None:
        raw_hint = payload.get("user_action_hint")
        if not isinstance(raw_hint, dict):
            return None
        try:
            return ToolUserActionHint.model_validate(raw_hint)
        except Exception:
            return None
