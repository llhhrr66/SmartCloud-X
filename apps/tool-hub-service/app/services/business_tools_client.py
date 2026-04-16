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
    ensure_local_runtime,
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
        except (httpx.HTTPError, ValueError, BusinessToolsDiscoveryUnavailableError):
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
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if self._allow_local_degraded_fallback():
                    response = self._mark_local_fallback(
                        self._invoke_locally(tool, request),
                        fallback_tag="degraded-http-connect-fallback",
                    )
                else:
                    response = ToolCallResponse(
                        success=False,
                        code=5003001,
                        message="downstream connection failed",
                        status="failed",
                        summary="downstream connection failed",
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
            ensure_local_runtime(
                activation_mode=self._local_runtime_activation_mode(),
                settings=self.settings,
            )
            tool = self._catalog.get(definition.name)
            if tool is None:
                raise ValueError(f"Unknown tool: {definition.name}")
            return tool.invoke(request)
        try:
            return self._invoke_tool_via_http(definition, request)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if not self._allow_local_degraded_fallback():
                raise
            tool = self._catalog.get(definition.name)
            if tool is None:
                raise
            result = tool.invoke(request)
            return result.model_copy(
                deep=True,
                update={
                    "audit_tags": list(dict.fromkeys([*result.audit_tags, "degraded-http-connect-fallback"])),
                },
            )

    def list_tools(
        self,
        *,
        capability: str | None = None,
        mode: ToolMode | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[ToolDefinition]:
        if self.settings.business_tools_transport != "http":
            return self._local_tool_definitions(
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )
        try:
            return self._discover_tools(
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )
        except BusinessToolsDiscoveryUnavailableError:
            return self._local_tool_definitions(
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )

    def describe_tool(self, tool_name: str) -> ToolDefinition | None:
        if self.settings.business_tools_transport != "http":
            tool = self._catalog.get(tool_name)
            return tool.definition.model_copy(deep=True) if tool else None
        try:
            return self._discover_tool(tool_name)
        except BusinessToolsDiscoveryUnavailableError:
            tool = self._catalog.get(tool_name)
            return tool.definition.model_copy(deep=True) if tool else None

    def dependency_readiness(self) -> dict[str, object]:
        if self.settings.business_tools_transport != "http":
            return {
                "ready": True,
                "status": "ready",
                "mode": "transport-local",
                "service": "business-tools-service",
                "notReadyComponents": [],
            }
        try:
            with httpx.Client(
                base_url=self.settings.business_tools_base_url,
                timeout=self._dependency_probe_timeout_seconds(),
            ) as client:
                response = client.get(
                    "/readyz",
                    headers={self.settings.caller_service_header: self.settings.app_name},
                )
        except httpx.HTTPError as exc:
            return {
                "ready": False,
                "status": "unreachable",
                "mode": "http",
                "service": "business-tools-service",
                "error": exc.__class__.__name__,
            }

        payload = self._dependency_probe_payload(response)
        status = str(payload.get("status") or ("ready" if response.status_code < 400 else "not_ready"))
        raw_components = payload.get("not_ready_components")
        not_ready_components = (
            [str(component) for component in raw_components]
            if isinstance(raw_components, list)
            else []
        )
        return {
            "ready": response.status_code < 400 and status == "ready",
            "status": status,
            "mode": "http",
            "service": str(payload.get("service") or "business-tools-service"),
            "httpStatus": response.status_code,
            "notReadyComponents": not_ready_components,
        }

    def preflight_call(self, tool_name: str, request: ToolCallRequest) -> ToolPreflightResult:
        local_tool = self._catalog.get(tool_name)
        local_definition = local_tool.definition.model_copy(deep=True) if local_tool is not None else None
        try:
            definition = self.describe_tool(tool_name)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if self._allow_local_degraded_fallback() and local_definition is not None:
                definition = local_definition
            else:
                return self._unavailable_preflight(tool_name, request.operation, local_definition)
        except (httpx.TimeoutException, httpx.HTTPError, ValueError):
            return self._unavailable_preflight(tool_name, request.operation, local_definition)
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
            ensure_local_runtime(
                activation_mode=self._local_runtime_activation_mode(),
                settings=self.settings,
            )
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
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if self._allow_local_degraded_fallback():
                return preflight_tool_invocation(definition, invocation)
            return self._unavailable_preflight(tool_name, request.operation, definition)
        except (httpx.TimeoutException, httpx.HTTPError, ValueError):
            return self._unavailable_preflight(tool_name, request.operation, definition)

    def _invoke_locally(self, tool: BusinessTool, request: ToolCallRequest) -> ToolCallResponse:
        ensure_local_runtime(
            activation_mode=self._local_runtime_activation_mode(),
            settings=self.settings,
        )
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
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if self._allow_local_degraded_fallback():
                response = self._invoke_compensation_locally(request)
            else:
                response = CompensationCallResponse(
                    success=False,
                    code=5003001,
                    message="downstream connection failed",
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
        ensure_local_runtime(
            activation_mode=self._local_runtime_activation_mode(),
            settings=self.settings,
        )
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

    def _allow_local_degraded_fallback(self) -> bool:
        return self.settings.app_env in {"local", "dev", "test"}

    def discover_tools(
        self,
        *,
        capability: str | None = None,
        mode: ToolMode | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[ToolDefinition]:
        if self.settings.business_tools_transport != "http":
            return self._local_tool_definitions(
                capability=capability,
                mode=mode,
                tag=tag,
                query=query,
            )
        return self._discover_tools(
            capability=capability,
            mode=mode,
            tag=tag,
            query=query,
        )

    def discover_tool(self, tool_name: str) -> ToolDefinition | None:
        if self.settings.business_tools_transport != "http":
            tool = self._catalog.get(tool_name)
            return tool.definition.model_copy(deep=True) if tool else None
        return self._discover_tool(tool_name)

    def _discover_tools(
        self,
        *,
        capability: str | None = None,
        mode: ToolMode | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[ToolDefinition]:
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
        except httpx.HTTPError as exc:
            raise BusinessToolsDiscoveryUnavailableError(
                "business-tools discovery is unavailable while HTTP transport is enabled."
            ) from exc
        raw_tools = payload.get("tools", payload.get("data", [])) if isinstance(payload, dict) else []
        definitions: list[ToolDefinition] = []
        try:
            for raw_tool in raw_tools:
                definitions.append(ToolDefinition.model_validate(raw_tool))
        except Exception as exc:
            raise BusinessToolsDiscoveryUnavailableError(
                "business-tools discovery returned invalid tool metadata while HTTP transport is enabled."
            ) from exc
        return definitions

    def _discover_tool(self, tool_name: str) -> ToolDefinition | None:
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
        except httpx.HTTPError as exc:
            raise BusinessToolsDiscoveryUnavailableError(
                "business-tools discovery is unavailable while HTTP transport is enabled."
            ) from exc
        if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
            payload = payload["data"]
        try:
            return ToolDefinition.model_validate(payload)
        except Exception as exc:
            raise BusinessToolsDiscoveryUnavailableError(
                "business-tools discovery returned invalid tool metadata while HTTP transport is enabled."
            ) from exc

    def _local_tool_definitions(
        self,
        *,
        capability: str | None = None,
        mode: ToolMode | None = None,
        tag: str | None = None,
        query: str | None = None,
    ) -> list[ToolDefinition]:
        return filter_tool_definitions(
            (tool.definition for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])),
            capability=capability,
            mode=mode,
            tag=tag,
            query=query,
        )

    def _local_runtime_activation_mode(self) -> Literal["transport-local", "degraded-fallback"]:
        return "transport-local" if self.settings.business_tools_transport != "http" else "degraded-fallback"

    def _dependency_probe_timeout_seconds(self) -> float:
        return max(min(self.settings.request_timeout_ms, 2_000), 500) / 1000

    @staticmethod
    def _dependency_probe_payload(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _unavailable_preflight(
        tool_name: str,
        operation: str,
        definition: ToolDefinition | None,
    ) -> ToolPreflightResult:
        if definition is None:
            return ToolPreflightResult(
                tool_name=tool_name,
                operation=operation,
                status="missing-tool",
                ready=False,
                available=False,
            )
        return ToolPreflightResult(
            tool_name=tool_name,
            operation=operation,
            status="ready",
            ready=False,
            available=False,
            high_risk=definition.high_risk,
            tool_mode=definition.mode,
            timeout_ms=definition.timeout_ms,
            idempotent=definition.idempotent,
            cache_ttl_seconds=definition.cache_ttl_seconds,
            required_permissions=list(definition.auth_requirements.required_permissions),
            requires_account_context=definition.auth_requirements.require_account_id,
            confirmation_required=definition.auth_requirements.confirmation_required,
        )

    @staticmethod
    def _mark_local_fallback(
        response: ToolCallResponse,
        *,
        fallback_tag: str,
    ) -> ToolCallResponse:
        return response.model_copy(
            deep=True,
            update={
                "audit_tags": list(dict.fromkeys([*response.audit_tags, fallback_tag])),
            },
        )

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


class BusinessToolsDiscoveryUnavailableError(RuntimeError):
    pass
