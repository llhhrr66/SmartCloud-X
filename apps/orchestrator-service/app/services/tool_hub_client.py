from __future__ import annotations

from collections.abc import Iterable
import time

import httpx

from app.core.business_tools_sdk import (
    CompensationExecutionRequest,
    ToolDefinition,
    ToolPreflightResult,
    ToolExecutionContext,
    ToolInvocationRequest,
    ToolUserActionHint,
    build_catalog,
    execute_compensation,
    preflight_tool_invocation,
)
from app.core.config import get_settings
from app.models.common import TraceContext
from app.models.orchestration import (
    CompensationExecutionRecord,
    SagaCompensationStep,
    ToolInvocation,
    ToolPlanItem,
    UserProfile,
)


class ToolHubClient:
    """Adapter for tool-hub contracts.

    Defaults to local business-tool execution and can switch to HTTP mode when
    the tool-hub service is running.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._catalog = build_catalog()

    def invoke_plan(
        self,
        tool_plan: Iterable[ToolPlanItem],
        user_profile: UserProfile,
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator",
        message_id: str | None = None,
    ) -> list[ToolInvocation]:
        if self.settings.tool_hub_transport == "http":
            return list(self._invoke_via_http(tool_plan, user_profile, trace, operator_id, message_id))
        return list(self._invoke_locally(tool_plan, user_profile, trace, operator_id, message_id))

    def preflight(
        self,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator",
        message_id: str | None = None,
    ) -> ToolPreflightResult:
        try:
            if self.settings.tool_hub_transport == "http":
                return self._preflight_via_http(item, user_profile, trace, operator_id, message_id)
            return self._preflight_locally(item, user_profile, trace, operator_id, message_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return ToolPreflightResult(
                    tool_name=item.tool_name,
                    operation=item.operation,
                    status="missing-tool",
                    ready=False,
                    available=False,
                )
            return ToolPreflightResult(tool_name=item.tool_name, operation=item.operation)
        except httpx.HTTPError:
            return ToolPreflightResult(tool_name=item.tool_name, operation=item.operation)

    def list_tool_definitions(self) -> list[ToolDefinition]:
        if self.settings.tool_hub_transport != "http":
            return [
                tool.definition.model_copy(deep=True)
                for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])
            ]
        try:
            with httpx.Client(
                base_url=self.settings.tool_hub_base_url,
                timeout=self.settings.request_timeout_ms / 1000,
            ) as client:
                response = client.get(
                    f"{self.settings.tool_hub_internal_api_prefix}/tools",
                    headers={
                        self.settings.caller_service_header: self.settings.app_name,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError:
            return [
                tool.definition.model_copy(deep=True)
                for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])
            ]

        raw_tools = payload.get("data", payload.get("tools", [])) if isinstance(payload, dict) else []
        definitions: list[ToolDefinition] = []
        for raw_tool in raw_tools:
            try:
                definitions.append(ToolDefinition.model_validate(raw_tool))
            except Exception:
                continue
        if definitions:
            return definitions
        return [
            tool.definition.model_copy(deep=True)
            for _, tool in sorted(self._catalog.items(), key=lambda item: item[0])
        ]

    def _invoke_locally(
        self,
        tool_plan: Iterable[ToolPlanItem],
        user_profile: UserProfile,
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator",
        message_id: str | None = None,
    ) -> Iterable[ToolInvocation]:
        for item in tool_plan:
            tool = self._catalog.get(item.tool_name)
            if tool is None:
                yield ToolInvocation(
                    tool_name=item.tool_name,
                    tool_call_id=item.tool_call_id,
                    operation=item.operation,
                    status="missing-tool",
                    payload=item.payload,
                    summary="Tool not registered in local business-tools catalog.",
                    auth_required=item.auth_required,
                    success=False,
                    code=4040001,
                )
                continue
            idempotency_key = self._build_idempotency_key(item, trace)
            local_context = self._build_context(item, user_profile, trace, operator_id, idempotency_key, message_id)
            result = tool.invoke(
                ToolInvocationRequest(
                    tool_name=item.tool_name,
                    operation=item.operation,
                    payload=item.payload,
                    context=local_context,
                )
            )
            yield ToolInvocation(
                tool_name=item.tool_name,
                tool_call_id=item.tool_call_id,
                operation=item.operation,
                status=result.status,
                payload=result.result,
                summary=result.summary,
                citations=result.citations,
                auth_required=item.auth_required,
                success=result.success,
                code=result.code,
                retryable=result.retryable,
                compensation=result.compensation,
                provider=result.provider,
                audit_tags=result.audit_tags,
                error_detail=result.error_detail,
                idempotency_key=result.idempotency_key,
                session_context_patch=result.session_context_patch,
                user_action_hint=result.user_action_hint,
            )

    def _invoke_via_http(
        self,
        tool_plan: Iterable[ToolPlanItem],
        user_profile: UserProfile,
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator",
        message_id: str | None = None,
    ) -> Iterable[ToolInvocation]:
        with httpx.Client(base_url=self.settings.tool_hub_base_url, timeout=self.settings.request_timeout_ms / 1000) as client:
            for item in tool_plan:
                started = time.perf_counter()
                idempotency_key = self._build_idempotency_key(item, trace)
                try:
                    response = self._request_tool_call(
                        client=client,
                        item=item,
                        user_profile=user_profile,
                        trace=trace,
                        operator_id=operator_id,
                        idempotency_key=idempotency_key,
                        message_id=message_id,
                    )
                    response.raise_for_status()
                    payload = response.json()
                except httpx.TimeoutException as exc:
                    yield self._http_error_invocation(
                        item=item,
                        trace=trace,
                        idempotency_key=idempotency_key,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        summary="tool-hub request timed out",
                        code=5003002,
                        retryable=True,
                        error_detail={"exception": exc.__class__.__name__},
                    )
                    continue
                except httpx.HTTPStatusError as exc:
                    detail = self._http_error_detail(exc.response)
                    yield self._http_error_invocation(
                        item=item,
                        trace=trace,
                        idempotency_key=idempotency_key,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        summary=str(detail.get("message") or "tool-hub returned an error response"),
                        code=exc.response.status_code,
                        retryable=exc.response.status_code >= 500,
                        error_detail=detail,
                    )
                    continue
                except httpx.HTTPError as exc:
                    yield self._http_error_invocation(
                        item=item,
                        trace=trace,
                        idempotency_key=idempotency_key,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        summary="tool-hub request failed",
                        code=5003001,
                        retryable=False,
                        error_detail={"exception": exc.__class__.__name__},
                    )
                    continue
                yield ToolInvocation(
                    tool_name=item.tool_name,
                    tool_call_id=item.tool_call_id,
                    operation=item.operation,
                    status=self._status_from_http_payload(payload),
                    payload=self._result_from_http_payload(payload),
                    summary=self._summary_from_http_payload(payload),
                    citations=self._citations_from_http_payload(payload),
                    auth_required=item.auth_required,
                    success=payload.get("success"),
                    code=payload.get("code"),
                    retryable=(
                        bool(payload.get("error", {}).get("retryable", False))
                        if isinstance(payload.get("error"), dict)
                        else False
                    ),
                    latency_ms=payload.get("latency_ms"),
                    compensation=payload.get("compensation"),
                    provider=payload.get("provider", "tool-hub-service"),
                    audit_tags=payload.get("audit_tags", []),
                    error_detail=(
                        payload.get("error", {}).get("details", {})
                        if isinstance(payload.get("error"), dict)
                        else {}
                    ),
                    idempotency_key=payload.get("idempotency_key"),
                    session_context_patch=payload.get("session_context_patch", {}),
                    user_action_hint=self._user_action_hint_from_http_payload(payload),
                )

    def _preflight_locally(
        self,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator",
        message_id: str | None = None,
    ) -> ToolPreflightResult:
        tool = self._catalog.get(item.tool_name)
        if tool is None:
            return ToolPreflightResult(
                tool_name=item.tool_name,
                operation=item.operation,
                status="missing-tool",
                ready=False,
                available=False,
            )
        idempotency_key = self._build_idempotency_key(item, trace)
        context = self._build_context(item, user_profile, trace, operator_id, idempotency_key, message_id)
        return preflight_tool_invocation(
            tool.definition,
            ToolInvocationRequest(
                tool_name=item.tool_name,
                operation=item.operation,
                payload=item.payload,
                context=context,
            ),
        )

    def _preflight_via_http(
        self,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator",
        message_id: str | None = None,
    ) -> ToolPreflightResult:
        with httpx.Client(base_url=self.settings.tool_hub_base_url, timeout=self.settings.request_timeout_ms / 1000) as client:
            idempotency_key = self._build_idempotency_key(item, trace)
            response = self._request_tool_preflight(
                client=client,
                item=item,
                user_profile=user_profile,
                trace=trace,
                operator_id=operator_id,
                idempotency_key=idempotency_key,
                message_id=message_id,
            )
            response.raise_for_status()
            payload = response.json()
        return ToolPreflightResult.model_validate(payload)

    def _build_context(
        self,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None,
        operator_id: str,
        idempotency_key: str,
        message_id: str | None,
    ) -> ToolExecutionContext:
        return ToolExecutionContext(
            request_id=item.tool_call_id,
            trace_id=trace.trace_id if trace else None,
            conversation_id=trace.conversation_id if trace else None,
            message_id=message_id,
            user_id=user_profile.user_id,
            account_id=user_profile.account_id,
            roles=user_profile.roles,
            permissions=user_profile.permissions,
            tenant_id=user_profile.tenant_id,
            locale=user_profile.locale,
            operator_id=operator_id,
            operator_type="agent",
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _build_idempotency_key(item: ToolPlanItem, trace: TraceContext | None = None) -> str:
        conversation_id = (
            trace.conversation_id
            if trace and trace.conversation_id
            else str(item.payload.get("conversation_id", "unknown"))
        )
        return f"tool-{conversation_id}-{item.tool_call_id}"

    def _request_tool_call(
        self,
        client: httpx.Client,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None,
        operator_id: str,
        idempotency_key: str,
        message_id: str | None,
    ) -> httpx.Response:
        return client.post(
            f"{self.settings.tool_hub_internal_api_prefix}/tools/call",
            json=self._tool_call_body(item, user_profile, trace, operator_id, idempotency_key, message_id),
            headers=self._tool_call_headers(item, user_profile, trace, idempotency_key, message_id),
        )

    def _request_tool_preflight(
        self,
        client: httpx.Client,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None,
        operator_id: str,
        idempotency_key: str,
        message_id: str | None,
    ) -> httpx.Response:
        return client.post(
            f"{self.settings.tool_hub_internal_api_prefix}/tools/preflight",
            json=self._tool_call_body(item, user_profile, trace, operator_id, idempotency_key, message_id),
            headers=self._tool_call_headers(item, user_profile, trace, idempotency_key, message_id),
        )

    def _tool_call_body(
        self,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None,
        operator_id: str,
        idempotency_key: str,
        message_id: str | None,
    ) -> dict[str, object]:
        return {
            "trace_id": trace.trace_id if trace and trace.trace_id else (trace.request_id if trace else item.tool_call_id),
            "conversation_id": trace.conversation_id if trace and trace.conversation_id else "unknown",
            "message_id": message_id,
            "tool_call_id": item.tool_call_id,
            "tool_name": item.tool_name,
            "operator": {"type": "agent", "id": operator_id},
            "user_context": {
                "user_id": user_profile.user_id,
                "account_id": user_profile.account_id,
                "permissions": user_profile.permissions,
                "roles": user_profile.roles,
                "tenant_id": user_profile.tenant_id,
                "locale": user_profile.locale,
            },
            "payload": item.payload,
            "idempotency_key": idempotency_key,
            "operation": item.operation,
        }

    def _tool_call_headers(
        self,
        item: ToolPlanItem,
        user_profile: UserProfile,
        trace: TraceContext | None,
        idempotency_key: str,
        message_id: str | None,
    ) -> dict[str, str]:
        return {
            self.settings.request_id_header: trace.request_id if trace and trace.request_id else item.tool_call_id,
            self.settings.trace_id_header: trace.trace_id if trace and trace.trace_id else item.tool_call_id,
            self.settings.conversation_id_header: trace.conversation_id if trace and trace.conversation_id else "unknown",
            self.settings.message_id_header: message_id or item.tool_call_id,
            self.settings.tenant_id_header: user_profile.tenant_id,
            self.settings.caller_service_header: self.settings.app_name,
            self.settings.tool_call_id_header: item.tool_call_id,
            self.settings.idempotency_key_header: idempotency_key,
        }

    @staticmethod
    def _http_error_detail(response: httpx.Response) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            return {"status_code": response.status_code}
        if not isinstance(payload, dict):
            return {"status_code": response.status_code}
        detail = payload.get("detail")
        if isinstance(detail, dict):
            return {
                "status_code": response.status_code,
                "error_code": detail.get("code"),
                "message": detail.get("message"),
                "details": detail.get("details"),
            }
        return {"status_code": response.status_code}

    @staticmethod
    def _status_from_http_payload(payload: dict[str, object]) -> str:
        status = payload.get("status")
        if isinstance(status, str) and status:
            return status
        if payload.get("success"):
            return "completed"
        return {
            4001001: "invalid-payload",
            4030001: "auth-required",
            4040001: "missing-tool",
            4090001: "idempotency-conflict",
            4090002: "confirmation-required",
            5003002: "failed",
        }.get(payload.get("code"), "failed")

    @staticmethod
    def _summary_from_http_payload(payload: dict[str, object]) -> str | None:
        summary = payload.get("summary")
        if isinstance(summary, str) and summary:
            return summary
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
        return None

    @staticmethod
    def _result_from_http_payload(payload: dict[str, object]) -> dict[str, object]:
        result = payload.get("result")
        if isinstance(result, dict):
            return result
        data = payload.get("data")
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _citations_from_http_payload(payload: dict[str, object]) -> list[str]:
        citations = payload.get("citations")
        if not isinstance(citations, list):
            return []
        return [str(citation) for citation in citations if str(citation).strip()]

    @staticmethod
    def _user_action_hint_from_http_payload(payload: dict[str, object]) -> ToolUserActionHint | None:
        raw_hint = payload.get("user_action_hint")
        if not isinstance(raw_hint, dict):
            return None
        try:
            return ToolUserActionHint.model_validate(raw_hint)
        except Exception:
            return None

    def execute_compensations(
        self,
        compensation_steps: Iterable[SagaCompensationStep],
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator-service",
    ) -> list[CompensationExecutionRecord]:
        if self.settings.tool_hub_transport == "http":
            return list(self._execute_compensations_via_http(compensation_steps, trace, operator_id))
        return list(self._execute_compensations_locally(compensation_steps, trace, operator_id))

    def _execute_compensations_locally(
        self,
        compensation_steps: Iterable[SagaCompensationStep],
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator-service",
    ) -> Iterable[CompensationExecutionRecord]:
        for step in compensation_steps:
            started = time.perf_counter()
            idempotency_key = self._compensation_idempotency_key(step, trace)
            result = execute_compensation(
                CompensationExecutionRequest(
                    action_name=step.compensation.action_name,
                    payload=step.compensation.payload,
                    context=ToolExecutionContext(
                        request_id=step.step_id,
                        trace_id=trace.trace_id if trace else None,
                        conversation_id=trace.conversation_id if trace else step.saga_id.replace("saga-", "", 1),
                        operator_type="system",
                        operator_id=operator_id,
                        idempotency_key=idempotency_key,
                    ),
                )
            )
            yield CompensationExecutionRecord(
                step_id=step.step_id,
                tool_name=step.tool_name,
                action_name=step.compensation.action_name,
                status="completed" if result.success else "failed",
                success=result.success,
                message=result.summary,
                data=result.result,
                provider=result.provider,
                code=result.code,
                retryable=result.retryable,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error_detail=result.error_detail,
                idempotency_key=result.idempotency_key,
            )

    def _execute_compensations_via_http(
        self,
        compensation_steps: Iterable[SagaCompensationStep],
        trace: TraceContext | None = None,
        operator_id: str = "orchestrator-service",
    ) -> Iterable[CompensationExecutionRecord]:
        with httpx.Client(base_url=self.settings.tool_hub_base_url, timeout=self.settings.request_timeout_ms / 1000) as client:
            for step in compensation_steps:
                started = time.perf_counter()
                idempotency_key = self._compensation_idempotency_key(step, trace)
                try:
                    response = client.post(
                        f"{self.settings.tool_hub_internal_api_prefix}/tool-compensations/call",
                        json={
                            "trace_id": trace.trace_id if trace and trace.trace_id else step.step_id,
                            "conversation_id": trace.conversation_id if trace and trace.conversation_id else step.saga_id.replace("saga-", "", 1),
                            "compensation_id": step.step_id,
                            "action_name": step.compensation.action_name,
                            "operator": {"type": "system", "id": operator_id},
                            "payload": step.compensation.payload,
                            "idempotency_key": idempotency_key,
                        },
                        headers={
                            self.settings.request_id_header: trace.request_id if trace and trace.request_id else step.step_id,
                            self.settings.trace_id_header: trace.trace_id if trace and trace.trace_id else step.step_id,
                            self.settings.conversation_id_header: trace.conversation_id if trace and trace.conversation_id else step.saga_id.replace("saga-", "", 1),
                            self.settings.caller_service_header: self.settings.app_name,
                            self.settings.idempotency_key_header: idempotency_key,
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                except httpx.TimeoutException as exc:
                    yield CompensationExecutionRecord(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        action_name=step.compensation.action_name,
                        status="failed",
                        success=False,
                        message="tool-hub compensation request timed out",
                        provider="tool-hub-service",
                        code=5003002,
                        retryable=True,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error_detail={"exception": exc.__class__.__name__},
                        idempotency_key=idempotency_key,
                    )
                    continue
                except httpx.HTTPStatusError as exc:
                    detail = self._http_error_detail(exc.response)
                    yield CompensationExecutionRecord(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        action_name=step.compensation.action_name,
                        status="failed",
                        success=False,
                        message=str(detail.get("message") or "tool-hub returned an error response"),
                        provider="tool-hub-service",
                        code=exc.response.status_code,
                        retryable=exc.response.status_code >= 500,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error_detail=detail,
                        idempotency_key=idempotency_key,
                    )
                    continue
                except httpx.HTTPError as exc:
                    yield CompensationExecutionRecord(
                        step_id=step.step_id,
                        tool_name=step.tool_name,
                        action_name=step.compensation.action_name,
                        status="failed",
                        success=False,
                        message="tool-hub compensation request failed",
                        provider="tool-hub-service",
                        code=5003001,
                        retryable=False,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error_detail={"exception": exc.__class__.__name__},
                        idempotency_key=idempotency_key,
                    )
                    continue
                error_detail = payload.get("error", {}).get("details", {}) if isinstance(payload.get("error"), dict) else {}
                yield CompensationExecutionRecord(
                    step_id=step.step_id,
                    tool_name=step.tool_name,
                    action_name=payload.get("action_name", step.compensation.action_name),
                    status="completed" if payload.get("success") else "failed",
                    success=bool(payload.get("success")),
                    message=str(payload.get("message", "ok")),
                    data=payload.get("data", {}),
                    provider=payload.get("provider", "tool-hub-service"),
                    code=payload.get("code"),
                    retryable=bool(payload.get("error", {}).get("retryable", False)) if isinstance(payload.get("error"), dict) else False,
                    latency_ms=payload.get("latency_ms"),
                    error_detail=error_detail,
                    idempotency_key=payload.get("idempotency_key"),
                )

    @staticmethod
    def _compensation_idempotency_key(
        step: SagaCompensationStep,
        trace: TraceContext | None = None,
    ) -> str:
        conversation_id = (
            trace.conversation_id
            if trace and trace.conversation_id
            else step.saga_id.replace("saga-", "", 1)
        )
        return f"comp-{conversation_id}-{step.step_id}"

    @staticmethod
    def _http_error_invocation(
        *,
        item: ToolPlanItem,
        trace: TraceContext | None,
        idempotency_key: str,
        latency_ms: int,
        summary: str,
        code: int,
        retryable: bool,
        error_detail: dict[str, object],
    ) -> ToolInvocation:
        return ToolInvocation(
            tool_name=item.tool_name,
            tool_call_id=item.tool_call_id,
            operation=item.operation,
            status="failed",
            payload={"conversation_id": trace.conversation_id} if trace and trace.conversation_id else {},
            summary=summary,
            auth_required=item.auth_required,
            success=False,
            code=code,
            retryable=retryable,
            latency_ms=latency_ms,
            provider="tool-hub-service",
            error_detail=error_detail,
            idempotency_key=idempotency_key,
        )
