from app.models.common import TraceContext
from app.models.orchestration import MessageRequest, RouteRequest, UserProfile
from app.services.agent_config_store import AgentConfigStore
from app.services.agent_runtime import AgentRuntime
from app.services.router import AgentRouter


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _SlowToolHubClient:
    def __init__(self, clock: _FakeClock) -> None:
        from app.services.tool_hub_client import ToolHubClient

        self._clock = clock
        self._client = ToolHubClient()

    def preflight(self, *args, **kwargs):
        self._clock.advance(0.6)
        return self._client.preflight(*args, **kwargs)

    def invoke_plan(self, *args, **kwargs):
        self._clock.advance(0.6)
        return self._client.invoke_plan(*args, **kwargs)



def test_runtime_executes_query_tool_and_returns_summary() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我查下这个月账单",
            conversation_id="conv-runtime",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我查下这个月账单",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        ),
        TraceContext(requestId="req-1", conversationId="conv-runtime", traceId="trace-1"),
    )

    assert executions
    assert executions[0].tool_calls
    assert executions[0].tool_calls[0].status == "completed"
    assert "账单周期" in (executions[0].final_answer or "")



def test_runtime_executes_order_status_query_from_session_context() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我查下退款进度",
            conversation_id="conv-order-runtime",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:order.read"]),
            session_context={
                "attributes": {
                    "refund_order_no": "ord_20260416_001",
                    "refund_no": "refund_ord_20260416_001",
                }
            },
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我查下退款进度",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:order.read"]),
            session_context={
                "attributes": {
                    "refund_order_no": "ord_20260416_001",
                    "refund_no": "refund_ord_20260416_001",
                }
            },
        ),
        TraceContext(
            requestId="req-order-runtime",
            conversationId="conv-order-runtime",
            traceId="trace-order-runtime",
        ),
    )

    assert executions[0].status == "success"
    assert executions[0].tool_calls[0].tool_name == "order.query_order"
    assert "退款申请 refund_ord_20260416_001 进度 processing" in (executions[0].final_answer or "")



def test_runtime_executes_invoice_status_query_from_session_context() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我查下发票状态",
            conversation_id="conv-invoice-runtime",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:billing.read"]),
            session_context={"attributes": {"invoice_no": "inv_001_20260416"}},
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我查下发票状态",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:billing.read"]),
            session_context={"attributes": {"invoice_no": "inv_001_20260416"}},
        ),
        TraceContext(
            requestId="req-invoice-runtime",
            conversationId="conv-invoice-runtime",
            traceId="trace-invoice-runtime",
        ),
    )

    assert executions[0].status == "success"
    assert executions[0].tool_calls[0].tool_name == "invoice.query_invoice"
    assert "发票申请 inv_001_20260416 当前状态 processing" in (executions[0].final_answer or "")


def test_runtime_executes_icp_subject_verification_from_session_context() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="请帮我核验备案实名认证",
            conversation_id="conv-icp-verify-runtime",
            scene="icp",
            user_profile=UserProfile(user_id="u-1", permissions=["user:icp.read"]),
            session_context={
                "attributes": {
                    "subject_type": "enterprise",
                    "subject_name": "上海示例科技有限公司",
                    "certificate_no": "91310000MA1CTEST88",
                    "contact_name": "张三",
                    "contact_phone": "13800138000",
                }
            },
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="请帮我核验备案实名认证",
            scene="icp",
            user_profile=UserProfile(user_id="u-1", permissions=["user:icp.read"]),
            session_context={
                "attributes": {
                    "subject_type": "enterprise",
                    "subject_name": "上海示例科技有限公司",
                    "certificate_no": "91310000MA1CTEST88",
                    "contact_name": "张三",
                    "contact_phone": "13800138000",
                }
            },
        ),
        TraceContext(
            requestId="req-icp-verify-runtime",
            conversationId="conv-icp-verify-runtime",
            traceId="trace-icp-verify-runtime",
        ),
    )

    assert executions[0].status == "success"
    assert executions[0].tool_calls[0].tool_name == "icp.verify_subject"
    assert "上海示例科技有限公司" in (executions[0].final_answer or "")


def test_runtime_marks_confirmation_as_need_user_input() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我开票",
            conversation_id="conv-confirm",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:billing.read"]),
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我开票",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:billing.read"]),
        ),
        TraceContext(requestId="req-2", conversationId="conv-confirm", traceId="trace-2"),
    )
    assert executions[0].status == "need_user_input"
    assert executions[0].action_required == "clarify-tool-input"
    assert executions[0].tool_calls[0].status == "clarification-required"
    assert "missing_tool_input" in executions[0].risk_flags


def test_runtime_marks_ready_high_risk_write_as_confirmation_required() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我开票",
            conversation_id="conv-confirm-ready",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
            session_context={
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                }
            },
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我开票",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
            session_context={
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                }
            },
        ),
        TraceContext(requestId="req-2b", conversationId="conv-confirm-ready", traceId="trace-2b"),
    )
    assert executions[0].status == "need_user_input"
    assert executions[0].action_required == "user-confirmation"
    assert executions[0].tool_calls[0].status == "preview-ready"
    assert executions[0].tool_calls[0].user_action_hint is not None
    assert executions[0].tool_calls[0].user_action_hint.action == "user-confirmation"
    assert "confirmation_required" in executions[0].risk_flags


def test_runtime_executes_confirmed_write_tool() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我开票",
            conversation_id="conv-confirmed-write",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
            session_context={
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我开票",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
            session_context={
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "statement_nos": ["stmt_2026_04_001"],
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        ),
        TraceContext(requestId="req-4", conversationId="conv-confirmed-write", traceId="trace-4"),
    )
    assert executions[0].status == "success"
    assert executions[0].tool_calls[0].compensation is not None
    assert "已提交" in (executions[0].final_answer or "")


def test_runtime_hydrates_ticket_reply_from_session_context_binding() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="请帮我回复工单，告诉客户问题已恢复",
            conversation_id="conv-ticket-reply",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:ticket.write"]),
            session_context={
                "open_ticket_id": "tk_billing_001",
            },
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="请帮我回复工单，告诉客户问题已恢复",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", permissions=["user:ticket.write"]),
            session_context={
                "open_ticket_id": "tk_billing_001",
            },
        ),
        TraceContext(
            requestId="req-ticket-reply",
            conversationId="conv-ticket-reply",
            traceId="trace-ticket-reply",
        ),
    )
    assert executions[0].status == "success"
    assert executions[0].tool_calls[0].tool_name == "ticket.reply"
    assert executions[0].tool_calls[0].payload["ticket_no"] == "tk_billing_001"



def test_runtime_executes_marketing_poster_generation_chain() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我生成 GPU 活动海报",
            conversation_id="conv-marketing-poster-runtime",
            scene="marketing",
            user_profile=UserProfile(
                user_id="u-1",
                permissions=["user:marketing.read", "user:marketing.write"],
            ),
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我生成 GPU 活动海报",
            scene="marketing",
            user_profile=UserProfile(
                user_id="u-1",
                permissions=["user:marketing.read", "user:marketing.write"],
            ),
        ),
        TraceContext(
            requestId="req-marketing-poster-runtime",
            conversationId="conv-marketing-poster-runtime",
            traceId="trace-marketing-poster-runtime",
        ),
    )
    assert executions[0].status == "success"
    assert [tool_call.tool_name for tool_call in executions[0].tool_calls] == [
        "marketing.campaign_lookup",
        "marketing.poster_brief",
        "marketing.generate_poster",
    ]
    assert executions[0].tool_calls[-1].payload["poster_asset_id"].startswith("poster_")
    assert "海报资产" in (executions[0].final_answer or "")


def test_runtime_marks_human_handoff_status() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="服务异常我要转人工",
            conversation_id="conv-human",
            scene="technical_support",
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(user_query="服务异常我要转人工", scene="technical_support"),
        TraceContext(requestId="req-3", conversationId="conv-human", traceId="trace-3"),
    )
    assert executions[0].status == "handoff"
    assert "human_handoff_requested" in executions[0].risk_flags


def test_runtime_stops_after_first_blocking_agent_result() -> None:
    router = AgentRouter()
    route = router.route(
        RouteRequest(
            user_query="帮我申请发票并推荐活动",
            conversation_id="conv-blocking",
            scene="billing",
            user_profile=UserProfile(user_id="u-1"),
        )
    )
    runtime = AgentRuntime()
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我申请发票并推荐活动",
            scene="billing",
            user_profile=UserProfile(user_id="u-1"),
        ),
        TraceContext(requestId="req-5", conversationId="conv-blocking", traceId="trace-5"),
    )
    assert len(route.tasks) > 1
    assert len(executions) == 1
    assert executions[0].status == "need_user_input"


def test_runtime_fails_agent_when_execution_exceeds_configured_timeout() -> None:
    agent_config_store = AgentConfigStore()
    agent_config_store.upsert(
        agent_name="finance_order_agent",
        agent_code="finance_order",
        values={"timeout_seconds": 1},
    )
    router = AgentRouter(agent_config_store=agent_config_store)
    route = router.route(
        RouteRequest(
            user_query="帮我查下这个月账单",
            conversation_id="conv-timeout-runtime",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        )
    )
    clock = _FakeClock()
    runtime = AgentRuntime(
        tool_hub_client=_SlowToolHubClient(clock),
        agent_config_store=agent_config_store,
        clock=clock,
    )
    executions = runtime.execute(
        route,
        MessageRequest(
            user_query="帮我查下这个月账单",
            scene="billing",
            user_profile=UserProfile(user_id="u-1", account_id="acct-1", permissions=["user:billing.read"]),
        ),
        TraceContext(
            requestId="req-timeout-runtime",
            conversationId="conv-timeout-runtime",
            traceId="trace-timeout-runtime",
        ),
    )

    assert executions[0].status == "failed"
    assert executions[0].tool_calls[0].status == "completed"
    assert executions[0].next_agent is None
    assert "agent_timeout" in executions[0].risk_flags
    assert "agent_timeout" in executions[0].trace_tags
    assert "1 秒" in (executions[0].final_answer or "")
