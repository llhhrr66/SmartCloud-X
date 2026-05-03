from __future__ import annotations

from app.models.orchestration import AgentName, ToolInvocation


_AGENT_DISPLAY_NAMES: dict[AgentName, str] = {
    "product_tech_agent": "技术支持",
    "finance_order_agent": "账单专员",
    "icp_service_agent": "ICP备案专员",
    "ops_marketing_agent": "营销专员",
    "deep_research_agent": "市场研究专员",
}

_AGENT_CAPABILITY_LINES: dict[AgentName, str] = {
    "product_tech_agent": "我可以帮你排查故障、推荐实例规格、查看服务状态，也能给出部署和排障建议。",
    "finance_order_agent": "我可以帮你查询账单、订单、退款、发票和工单进度。",
    "icp_service_agent": "我可以帮你检查备案材料、核验主体信息、提交备案申请和跟踪进度。",
    "ops_marketing_agent": "我可以帮你策划营销活动、生成文案、制作海报和生成推广链接。",
    "deep_research_agent": "我可以帮你做行业调研、竞品对比、整理参考资料和导出研究报告。",
}

_GREETING_TOKENS = (
    "你好",
    "您好",
    "hello",
    "hi",
    "hey",
    "哈喽",
    "嗨",
    "在吗",
)


def _display_name(agent: AgentName) -> str:
    return _AGENT_DISPLAY_NAMES.get(agent, agent)


def _is_generic_greeting(user_query: str) -> bool:
    normalized = "".join(str(user_query or "").strip().lower().split())
    if not normalized:
        return False
    return normalized in _GREETING_TOKENS


def _agent_idle_answer(agent: AgentName, user_query: str) -> str:
    name = _display_name(agent)
    capability = _AGENT_CAPABILITY_LINES.get(agent, "我可以帮你处理当前场景下的问题。")
    if _is_generic_greeting(user_query):
        return f"你好，我是{name}。{capability}"
    return f"我是{name}。{capability} 你可以直接告诉我你的具体需求。"


def render_baseline_final_answer(
    agent: AgentName,
    user_query: str,
    tool_calls: list[ToolInvocation],
    status: str,
    next_agent: str | None,
) -> str | None:
    """Compose a deterministic baseline answer string from tool-call payloads.

    The agent runtime calls the configured ``AgentAnswerGenerator`` first; this
    function provides the structured fallback that maps each tool's payload to
    a Chinese-language confirmation message. Lives here to keep
    ``agent_runtime.py`` focused on orchestration flow.
    """
    if status == "failed":
        return f"{agent} 当前处理失败，请稍后重试。"
    if status == "need_user_input":
        if tool_calls:
            latest = tool_calls[-1]
            needs_confirmation = (
                latest.user_action_hint is not None
                and latest.user_action_hint.action == "user-confirmation"
            ) or latest.status == "preview-ready"
            base = latest.summary or f"{agent} 需要更多信息后才能继续处理。"
            if needs_confirmation:
                return f"{base}请确认后继续执行。"
            return base
        return f"{agent} 需要更多信息后才能继续处理。"
    final_tool_call = next((tool for tool in reversed(tool_calls) if tool.success), None)
    if final_tool_call is None:
        if status == "handoff" and next_agent:
            return f"{_display_name(agent)} 已完成当前阶段，准备交接给 {_display_name(next_agent)}。"
        return _agent_idle_answer(agent, user_query)
    payload = final_tool_call.payload
    rendered = _render_for_tool(final_tool_call.tool_name, payload, final_tool_call)
    if rendered is not None:
        return rendered
    if status == "handoff" and next_agent:
        return f"{_display_name(agent)} 已完成当前阶段，准备交接给 {_display_name(next_agent)}。"
    return final_tool_call.summary or _agent_idle_answer(agent, user_query)


def _render_for_tool(
    tool_name: str,
    payload: dict,
    final_tool_call: ToolInvocation,
) -> str | None:
    if tool_name == "billing.query_statement":
        billing_cycle = payload.get("billing_cycle") or payload.get("cycle") or payload.get("range")
        total_amount = payload.get("total_amount")
        currency = payload.get("currency") or "CNY"
        if total_amount is not None and billing_cycle:
            return f"账单周期 {billing_cycle} 的费用为 {total_amount} {currency}。"
        if billing_cycle:
            return f"账单周期 {billing_cycle} 的账单结果已返回，请查看上方结果摘要。"
        return "账单查询结果已返回，请查看上方结果摘要。"
    if tool_name == "order.query_order":
        order_no = payload.get("order_no") or payload.get("order_id")
        order_status = payload.get("order_status") or payload.get("status")
        refund_no = payload.get("refund_no")
        refund_status = payload.get("refund_status")
        if refund_no and refund_status:
            return f"退款申请 {refund_no} 进度 {refund_status}，关联订单 {order_no or '当前订单'}。"
        if order_no and order_status:
            return f"订单 {order_no} 当前状态 {order_status}。"
        if order_no:
            return f"订单 {order_no} 的状态已返回，请查看上方结果摘要。"
        return final_tool_call.summary or "订单状态已返回，请查看上方结果摘要。"
    if tool_name == "invoice.query_invoice":
        invoice_no = payload.get("invoice_no") or payload.get("invoice_id")
        invoice_status = payload.get("invoice_status") or payload.get("status")
        if invoice_no and invoice_status:
            return f"发票申请 {invoice_no} 当前状态 {invoice_status}。"
        if invoice_no:
            return f"发票申请 {invoice_no} 的状态已返回，请查看上方结果摘要。"
        return "发票状态已返回，请查看上方结果摘要。"
    if tool_name == "billing.query_instance_cost":
        instance_id = payload.get("instance_id") or "当前实例"
        billing_cycle = payload.get("billing_cycle") or payload.get("range")
        total_amount = payload.get("total_amount")
        currency = payload.get("currency") or "CNY"
        if total_amount is not None and billing_cycle:
            return f"实例 {instance_id} 在 {billing_cycle} 的费用为 {total_amount} {currency}。"
        if total_amount is not None:
            return f"实例 {instance_id} 当前查询到的费用为 {total_amount} {currency}。"
        return f"实例 {instance_id} 的费用结果已返回，请查看上方结果摘要。"
    if tool_name == "finance.refund_preview":
        order_id = payload.get("order_id") or "当前订单"
        return f"已完成 {order_id} 的退款预检，请确认后继续。"
    if tool_name == "icp.prepare_filing":
        company_name = payload.get("company_name") or "当前主体"
        return f"已为 {company_name} 准备 ICP 备案材料清单。"
    if tool_name == "icp.verify_subject":
        subject_name = payload.get("subject_name") or payload.get("company_name") or "当前主体"
        verification_status = payload.get("verification_status") or ("verified" if payload.get("verified") else None)
        if verification_status:
            return f"{subject_name} 主体实名认证已完成，当前状态 {verification_status}。"
        return f"已完成 {subject_name} 的备案实名认证核验。"
    if tool_name == "icp.submit_application":
        application_no = payload.get("application_no") or payload.get("application_id")
        if application_no:
            return f"备案申请 {application_no} 已提交，请留意后续审核进度。"
        domain = payload.get("domain")
        if domain:
            return f"备案申请 {domain} 已提交，请留意后续审核进度。"
        return "备案申请已提交，请留意后续审核进度。"
    if tool_name == "ticket.create":
        ticket_no = payload.get("ticket_no") or payload.get("ticket_id")
        queue = payload.get("queue")
        if ticket_no and queue:
            return f"工单 {ticket_no} 已创建，已进入 {queue} 队列。"
        if ticket_no:
            return f"工单 {ticket_no} 已创建。"
        return "已生成工单创建结果。"
    if tool_name == "research.export_report":
        export_format = str(payload.get("format") or "markdown").strip().upper()
        download_path = payload.get("download_path")
        if isinstance(download_path, str) and download_path.strip():
            return f"已导出 {export_format} 报告，下载路径 {download_path.strip()}"
        return f"已导出 {export_format} 报告。"
    if tool_name == "marketing.generate_copy":
        headline = payload.get("headline")
        body = payload.get("body")
        if isinstance(headline, str) and headline.strip():
            return f"已生成营销文案：{headline.strip()}"
        if isinstance(body, str) and body.strip():
            lead_sentence = body.strip().split("。", 1)[0].strip()
            if lead_sentence:
                return f"已生成营销文案：{lead_sentence}。"
        return "已生成营销文案。"
    if tool_name == "marketing.generate_promotion_link":
        short_url = payload.get("short_url") or payload.get("short_url_preview") or payload.get("promotion_link")
        if short_url:
            return f"已生成推广链接 {short_url}"
        return "已生成推广链接。"
    if tool_name == "marketing.generate_poster":
        poster_asset_id = payload.get("poster_asset_id")
        if poster_asset_id:
            return f"已生成海报资产 {poster_asset_id}"
        return "已生成营销海报资产。"
    if tool_name in {"support.recommend_instance", "product.recommend_instance"}:
        recommended_instance_summary = payload.get("recommended_instance_summary")
        if isinstance(recommended_instance_summary, str) and recommended_instance_summary.strip():
            rationale = payload.get("rationale")
            if isinstance(rationale, list):
                first_reason = next(
                    (
                        str(item).strip()
                        for item in rationale
                        if isinstance(item, str) and item.strip()
                    ),
                    None,
                )
            else:
                first_reason = None
            summary = f"推荐实例：{recommended_instance_summary.strip()}。"
            if first_reason:
                return f"{summary}{first_reason}"
            return summary
        workload_label = payload.get("workload") or "当前业务"
        if (
            payload.get("recommended_instance_type")
            and payload.get("gpu_model")
            and payload.get("gpu_count")
            and payload.get("vcpu")
            and payload.get("memory_gb")
        ):
            return (
                f"建议先使用 {payload.get('recommended_instance_type')} "
                f"（{payload.get('gpu_model')} x{payload.get('gpu_count')}，"
                f"{payload.get('vcpu')} vCPU / {payload.get('memory_gb')}GB）"
                f"承载 {workload_label} 场景。"
            )
        return None
    if tool_name == "support.query_service_status":
        resource_label = payload.get("instance_id") or payload.get("service_name")
        summary = payload.get("summary")
        incident_code = payload.get("incident_code")
        if incident_code:
            return f"{resource_label} 状态检查结果：{summary} 关联事件 {incident_code}。"
        return f"{resource_label} 状态检查结果：{summary}"
    if tool_name == "support.handoff_brief":
        queue = payload.get("queue")
        severity = payload.get("severity")
        summary = payload.get("summary") or "已生成转人工交接摘要。"
        if queue and severity:
            return f"{summary} 建议分配到 {queue} 队列，优先级 {severity}。"
        return str(summary)
    if tool_name == "billing.create_invoice":
        invoice_no = payload.get("invoice_no") or payload.get("invoice_id")
        invoice_status = payload.get("invoice_status") or payload.get("status")
        if invoice_status == "submitted" and invoice_no:
            return f"开票申请 {invoice_no} 已提交，请留意后续处理进度。"
        if invoice_status == "submitted":
            return "开票申请已提交，请留意后续处理进度。"
        if invoice_no:
            return f"已创建开票申请 {invoice_no}。"
        return "已创建开票申请。"
    return None
