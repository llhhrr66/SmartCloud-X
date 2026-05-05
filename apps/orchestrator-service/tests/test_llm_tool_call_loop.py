from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from app.core.business_tools_sdk import ToolDefinition
from app.models.common import TraceContext
from app.models.orchestration import (
    MessageRequest,
    SessionContext,
    ToolInvocation,
    ToolPlanItem,
    UserProfile,
)
from app.services.llm_tool_call_loop import (
    LLMToolCallLoop,
    _preflight_blocked_invocation,
    _serialize_tool_result,
)


# ------------------------------------------------------------------
# Fakes / helpers
# ------------------------------------------------------------------


class _FakeToolCallFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str) -> None:
        self.id = id
        self.type = "function"
        self.function = _FakeToolCallFunction(name, arguments)


class _FakeMessage:
    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[_FakeToolCall] | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeCompletion:
    def __init__(self, choices: list[_FakeChoice]) -> None:
        self.choices = choices


class _FakeAnswerGenerator:
    """Records calls and returns canned completions."""

    def __init__(self, responses: list[_FakeCompletion | None]) -> None:
        self._responses = list(responses)
        self._call_index = 0
        self.calls: list[dict[str, Any]] = []

    def create_with_tools(
        self,
        *,
        agent: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        compacted_history: str | None = None,
    ) -> _FakeCompletion | None:
        self.calls.append({"agent": agent, "messages": messages, "tools": tools})
        if self._call_index >= len(self._responses):
            return None
        resp = self._responses[self._call_index]
        self._call_index += 1
        return resp


class _FakeBusinessTool:
    """Mimics the BusinessTool Protocol with a .definition attribute."""

    def __init__(self, definition: ToolDefinition) -> None:
        self.definition = definition

    def invoke(self, request):
        return MagicMock()


class _FakeToolHubClient:
    def __init__(self, invocation_results: list[ToolInvocation] | None = None) -> None:
        self._invocation_results = list(invocation_results or [])
        self._result_index = 0
        self.preflight_calls: list[dict[str, Any]] = []
        self.invoke_calls: list[dict[str, Any]] = []

    @property
    def settings(self):
        return _FakeSettings()

    def preflight(self, plan_item, user_profile, trace, *, operator_id, message_id):
        self.preflight_calls.append({
            "plan_item": plan_item,
            "operator_id": operator_id,
        })
        result = MagicMock()
        result.ready = True
        result.status = "ready"
        result.missing_payload_fields = []
        result.missing_auth_context = []
        result.missing_payload_hints = {}
        return result

    def invoke_plan(self, plan_items, user_profile, trace, *, operator_id, message_id):
        self.invoke_calls.append({
            "plan_items": plan_items,
            "operator_id": operator_id,
        })
        results = []
        for _ in plan_items:
            if self._result_index < len(self._invocation_results):
                results.append(self._invocation_results[self._result_index])
                self._result_index += 1
            else:
                results.append(ToolInvocation(
                    tool_name="fallback",
                    tool_call_id="tc-fb",
                    operation="execute",
                    status="completed",
                    success=True,
                    summary="默认结果。",
                ))
        return results


class _FakeSettings:
    tool_call_enabled = True
    max_tool_call_rounds = 5
    llm_api_key = "test-key"
    llm_model = "test-model"
    llm_base_url = "http://localhost:1234"
    llm_timeout_seconds = 20
    # Compaction settings
    compact_enabled = False
    compact_strategy = "full"
    micro_compact_enabled = False


def _sample_catalog() -> dict[str, _FakeBusinessTool]:
    return {
        "product.catalog_lookup": _FakeBusinessTool(ToolDefinition(
            name="product.catalog_lookup",
            capability="product",
            description="查询云产品目录。",
            input_schema={
                "type": "object",
                "properties": {"category": {"type": "string"}},
            },
            input_field_hints={"category": "产品分类"},
            operation_required_fields={"execute": ["category"]},
        )),
        "product.recommend_instance": _FakeBusinessTool(ToolDefinition(
            name="product.recommend_instance",
            capability="product",
            description="推荐GPU实例规格。",
            input_schema={
                "type": "object",
                "properties": {"workload_type": {"type": "string"}},
            },
        )),
        "billing.query_statement": _FakeBusinessTool(ToolDefinition(
            name="billing.query_statement",
            capability="billing",
            description="查询账单。",
            high_risk=True,
            input_schema={
                "type": "object",
                "properties": {"billing_cycle": {"type": "string"}},
            },
            input_field_hints={"billing_cycle": "账期"},
        )),
    }


def _make_request() -> MessageRequest:
    return MessageRequest(
        user_query="有哪些GPU实例？",
        user_profile=UserProfile(),
        session_context=SessionContext(),
    )


# ------------------------------------------------------------------
# Tests: LLM returns no tool calls (simple answer)
# ------------------------------------------------------------------


def test_loop_returns_empty_when_llm_has_no_tool_calls() -> None:
    generator = _FakeAnswerGenerator([
        _FakeCompletion([_FakeChoice(_FakeMessage(content="我们提供 A100 和 H100 两种 GPU 实例。"))]),
    ])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=_FakeToolHubClient(),
        catalog=_sample_catalog(),
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="有哪些GPU实例？",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert tool_calls == []
    assert llm_answer == "我们提供 A100 和 H100 两种 GPU 实例。"


# ------------------------------------------------------------------
# Tests: LLM returns tool calls, then answer
# ------------------------------------------------------------------


def test_loop_executes_tool_calls_and_returns_answer() -> None:
    tc = _FakeToolCall(
        id="tc-1",
        name="product.catalog_lookup",
        arguments='{"category": "GPU"}',
    )
    invocation = ToolInvocation(
        tool_name="product.catalog_lookup",
        tool_call_id="tc-1",
        operation="execute",
        status="completed",
        payload={"category": "GPU"},
        success=True,
        summary="找到3款GPU实例。",
        result={"items": [{"name": "A100"}, {"name": "H100"}]},
    )
    generator = _FakeAnswerGenerator([
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(content="我们提供 A100、H100 等GPU实例。"))]),
    ])
    hub = _FakeToolHubClient(invocation_results=[invocation])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=hub,
        catalog=_sample_catalog(),
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="有哪些GPU实例？",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "product.catalog_lookup"
    assert tool_calls[0].success is True
    assert llm_answer == "我们提供 A100、H100 等GPU实例。"


# ------------------------------------------------------------------
# Tests: LLM returns tool calls across multiple rounds
# ------------------------------------------------------------------


def test_loop_handles_multiple_rounds() -> None:
    tc1 = _FakeToolCall(id="tc-1", name="product.catalog_lookup", arguments='{"category": "GPU"}')
    tc2 = _FakeToolCall(id="tc-2", name="product.catalog_lookup", arguments='{"category": "ECS"}')
    inv1 = ToolInvocation(
        tool_name="product.catalog_lookup",
        tool_call_id="tc-1",
        operation="execute",
        status="completed",
        payload={"category": "GPU"},
        success=True,
        summary="GPU产品列表。",
    )
    inv2 = ToolInvocation(
        tool_name="product.catalog_lookup",
        tool_call_id="tc-2",
        operation="execute",
        status="completed",
        payload={"category": "ECS"},
        success=True,
        summary="ECS产品列表。",
    )
    generator = _FakeAnswerGenerator([
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc1]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc2]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(content="已查询GPU和ECS产品。"))]),
    ])
    hub = _FakeToolHubClient(invocation_results=[inv1, inv2])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=hub,
        catalog=_sample_catalog(),
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="GPU和ECS都有哪些？",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert len(tool_calls) == 2
    assert llm_answer == "已查询GPU和ECS产品。"


# ------------------------------------------------------------------
# Tests: max rounds guard
# ------------------------------------------------------------------


def test_loop_stops_after_max_rounds() -> None:
    tc = _FakeToolCall(id="tc-loop", name="product.catalog_lookup", arguments='{"category": "GPU"}')
    inv = ToolInvocation(
        tool_name="product.catalog_lookup",
        tool_call_id="tc-loop",
        operation="execute",
        status="completed",
        payload={"category": "GPU"},
        success=True,
        summary="GPU列表。",
    )
    generator = _FakeAnswerGenerator([
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc]))]),
    ])
    hub = _FakeToolHubClient(invocation_results=[inv, inv, inv])

    class _MaxRounds2(_FakeSettings):
        max_tool_call_rounds = 2

    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=hub,
        catalog=_sample_catalog(),
        settings=_MaxRounds2(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="GPU？",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert len(tool_calls) == 2
    assert llm_answer is None


# ------------------------------------------------------------------
# Tests: LLM call failure
# ------------------------------------------------------------------


def test_loop_returns_early_when_llm_call_fails() -> None:
    generator = _FakeAnswerGenerator([None])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=_FakeToolHubClient(),
        catalog=_sample_catalog(),
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="你好",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert tool_calls == []
    assert llm_answer is None


# ------------------------------------------------------------------
# Tests: no tools available for agent
# ------------------------------------------------------------------


def test_loop_returns_early_when_no_tools_available() -> None:
    generator = _FakeAnswerGenerator([])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=_FakeToolHubClient(),
        catalog={},  # empty catalog
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="你好",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert tool_calls == []
    assert llm_answer is None
    assert len(generator.calls) == 0  # catalog empty → no definitions → no LLM call


# ------------------------------------------------------------------
# Tests: high-risk tool uses preview mode
# ------------------------------------------------------------------


def test_high_risk_tool_uses_preview_operation() -> None:
    tc = _FakeToolCall(id="tc-hr", name="billing.query_statement", arguments='{"billing_cycle": "2026-04"}')
    inv = ToolInvocation(
        tool_name="billing.query_statement",
        tool_call_id="tc-hr",
        operation="preview",
        status="completed",
        payload={"billing_cycle": "2026-04"},
        success=True,
        summary="账单预览。",
    )
    generator = _FakeAnswerGenerator([
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(content="账单已预览。"))]),
    ])
    hub = _FakeToolHubClient(invocation_results=[inv])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=hub,
        catalog=_sample_catalog(),
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="finance_order_agent",
        user_query="查看上个月账单",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert len(tool_calls) == 1
    assert tool_calls[0].operation == "preview"


# ------------------------------------------------------------------
# Tests: preflight blocked
# ------------------------------------------------------------------


def test_preflight_blocked_returns_failed_invocation() -> None:
    plan_item = ToolPlanItem(
        tool_call_id="tc-blk",
        tool_name="product.catalog_lookup",
        assigned_agent="product_tech_agent",
        operation="execute",
        reason="test",
        payload={"category": "GPU"},
    )
    preflight = MagicMock()
    preflight.status = "auth-required"
    preflight.ready = False
    preflight.missing_payload_fields = []
    preflight.missing_auth_context = ["user_id"]
    preflight.missing_payload_hints = {}
    invocation = _preflight_blocked_invocation(plan_item, preflight, "product_tech_agent")
    assert invocation.success is False
    assert invocation.status == "auth-required"
    assert "catalog_lookup" in invocation.summary


# ------------------------------------------------------------------
# Tests: _serialize_tool_result
# ------------------------------------------------------------------


def test_serialize_tool_result_success() -> None:
    inv = ToolInvocation(
        tool_name="product.catalog_lookup",
        tool_call_id="tc-s",
        operation="execute",
        status="completed",
        payload={"items": [1, 2, 3]},
        success=True,
        summary="找到3款产品。",
    )
    result_str = _serialize_tool_result(inv)
    parsed = json.loads(result_str)
    assert parsed["success"] is True
    assert parsed["tool_name"] == "product.catalog_lookup"
    assert parsed["data"] == {"items": [1, 2, 3]}


def test_serialize_tool_result_failure_with_action_hint() -> None:
    from app.core.business_tools_sdk import ToolUserActionHint

    inv = ToolInvocation(
        tool_name="billing.create_invoice",
        tool_call_id="tc-f",
        operation="execute",
        status="auth-required",
        payload={},
        success=False,
        summary="需要鉴权。",
        user_action_hint=ToolUserActionHint(
            action="collect-auth-context",
            message="请先完成鉴权。",
        ),
    )
    result_str = _serialize_tool_result(inv)
    parsed = json.loads(result_str)
    assert parsed["success"] is False
    assert parsed["action_required"] == "collect-auth-context"
    assert parsed["message"] == "请先完成鉴权。"


# ------------------------------------------------------------------
# Tests: JSON decode error on arguments
# ------------------------------------------------------------------


def test_loop_handles_malformed_tool_arguments() -> None:
    tc = _FakeToolCall(id="tc-bad", name="product.catalog_lookup", arguments="not-json")
    inv = ToolInvocation(
        tool_name="product.catalog_lookup",
        tool_call_id="tc-bad",
        operation="execute",
        status="completed",
        payload={},
        success=True,
        summary="默认结果。",
    )
    generator = _FakeAnswerGenerator([
        _FakeCompletion([_FakeChoice(_FakeMessage(tool_calls=[tc]))]),
        _FakeCompletion([_FakeChoice(_FakeMessage(content="处理完成。"))]),
    ])
    hub = _FakeToolHubClient(invocation_results=[inv])
    loop = LLMToolCallLoop(
        answer_generator=generator,
        tool_hub_client=hub,
        catalog=_sample_catalog(),
        settings=_FakeSettings(),
    )
    tool_calls, llm_answer = loop.run(
        agent="product_tech_agent",
        user_query="产品？",
        request=_make_request(),
        working_context=SessionContext(),
    )
    assert len(tool_calls) == 1
    assert tool_calls[0].payload == {}  # empty dict from json decode failure
