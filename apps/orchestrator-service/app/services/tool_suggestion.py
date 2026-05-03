from __future__ import annotations

from app.models.orchestration import AgentName, RouteRequest

from .agent_registry import allowed_tools_for
from .route_text_signals import RouteTextSignals


class ToolSuggestionEngine:
    """Per-agent tool suggestion heuristics.

    Each method returns a list of tool names that a given agent should attempt
    to invoke for the current request. Suggestions are derived from text
    signals only — selection, payload binding, and dependency ordering happen
    later in the pipeline.
    """

    @staticmethod
    def suggest(
        agent: AgentName,
        request: RouteRequest,
        text: str,
        tool_candidates: list[str],
    ) -> list[str]:
        if tool_candidates:
            allowed_tools = set(allowed_tools_for(agent))
            return [tool_name for tool_name in tool_candidates if tool_name in allowed_tools]
        if RouteTextSignals.human_handoff_prefers_brief_only(text):
            return ["support.handoff_brief"]
        if agent == "finance_order_agent":
            return ToolSuggestionEngine._suggest_finance_order(text)
        if agent == "icp_service_agent":
            return ToolSuggestionEngine._suggest_icp_service(text)
        if agent == "ops_marketing_agent":
            return ToolSuggestionEngine._suggest_ops_marketing(request, text)
        if agent == "deep_research_agent":
            return ToolSuggestionEngine._suggest_deep_research(request, text)
        if agent == "product_tech_agent":
            return ToolSuggestionEngine._suggest_product_tech(text)
        return allowed_tools_for(agent)

    @staticmethod
    def _suggest_finance_order(text: str) -> list[str]:
        tools: list[str] = []
        instance_cost_requested = (
            any(
                token in text
                for token in ("实例费用", "实例花费", "实例消费", "机器费用", "主机费用", "节点费用", "实例账单", "花了多少钱", "多少钱", "收费", "价格")
            )
            or ("实例" in text and any(token in text for token in ("费用", "花费", "成本", "消费", "账单")))
            or (any(token in text for token in ("费用", "花费", "成本", "消费", "账单", "多少钱", "花了")) and any(
                token in text for token in ("机器", "主机", "节点", "这台", "那台", "服务器")
            ))
            or (
                RouteTextSignals.extract_identifier(text, "instance_id") is not None
                and any(token in text for token in ("费用", "花费", "成本", "消费", "账单", "多少钱", "花了", "收费", "价格"))
            )
        )
        general_billing_requested = any(token in text for token in ("账单", "扣费")) or (
            any(token in text for token in ("消费", "费用")) and not instance_cost_requested
        )
        if general_billing_requested:
            tools.append("billing.query_statement")
        if instance_cost_requested:
            tools.append("billing.query_instance_cost")
        order_status_requested = any(
            token in text for token in ("订单状态", "订单详情", "订单信息", "订单进度", "订单", "我的订单", "最近订单", "所有订单")
        )
        refund_status_requested = "退款" in text and any(
            token in text for token in ("状态", "进度", "详情", "查询")
        )
        invoice_status_requested = any(
            token in text for token in ("发票状态", "开票状态", "发票进度", "开票进度", "发票详情")
        )
        ticket_status_requested = "工单" in text and any(
            token in text for token in ("状态", "进度", "详情", "查询", "跟进", "处理到哪", "查看", "看", "我的", "列表", "有哪些", "最新")
        )
        if order_status_requested or refund_status_requested:
            tools.append("order.query_order")
        if invoice_status_requested:
            tools.append("invoice.query_invoice")
        if any(token in text for token in ("发票", "开票")) and not invoice_status_requested:
            tools.append("billing.create_invoice")
        if any(token in text for token in ("退款", "退费")) and not refund_status_requested:
            tools.append("order.create_refund")
        if any(token in text for token in ("工单", "售后")):
            if ticket_status_requested:
                tools.append("ticket.query_ticket")
            else:
                tools.append("ticket.reply" if "回复" in text else "ticket.create")
        tools = RouteTextSignals.append_handoff_brief(
            tools or allowed_tools_for("finance_order_agent")[:2],
            text=text,
        )
        if "ticket.create" in tools and "support.handoff_brief" in tools:
            tools = RouteTextSignals.promote_tool(tools, "support.handoff_brief")
        return tools

    @staticmethod
    def _suggest_icp_service(text: str) -> list[str]:
        tools: list[str] = []
        verification_requested = any(token in text for token in ("实名", "实名认证", "核身", "主体核验"))
        materials_requested = any(token in text for token in ("材料", "资料", "清单"))
        submit_requested = any(token in text for token in ("提交", "申请", "上线"))
        icp_status_requested = ("备案" in text or "icp" in text) and any(
            token in text for token in ("状态", "进度", "详情", "查询", "审核", "结果")
        )
        if verification_requested:
            tools.append("icp.verify_subject")
        if materials_requested or (submit_requested and not icp_status_requested) or (("备案" in text or "icp" in text) and not verification_requested and not icp_status_requested and not submit_requested):
            tools.append("icp.material_check")
        if icp_status_requested:
            tools.append("icp.query_application")
        if submit_requested and not icp_status_requested:
            tools.append("icp.submit_application")
        return RouteTextSignals.append_handoff_brief(
            tools or allowed_tools_for("icp_service_agent"),
            text=text,
        )

    @staticmethod
    def _suggest_ops_marketing(request: RouteRequest, text: str) -> list[str]:
        human_handoff_requested = RouteTextSignals.human_handoff_requested(text)
        generic_greeting = (
            len(text) <= 20
            and not any(
                token in text
                for token in (
                    "活动", "优惠", "促销", "推广", "海报", "poster", "视觉", "版式",
                    "文案", "宣传语", "广告语", "slogan", "标题", "卖点",
                    "推广链接", "短链", "utm", "落地页", "链接",
                    "营销", "转化", "渠道", "素材", "品牌",
                    "产品", "服务器", "算力", "推荐", "选型",
                )
            )
        )
        if generic_greeting:
            return ["support.handoff_brief"] if human_handoff_requested else []

        tools: list[str] = []
        poster_requested = any(token in text for token in ("海报", "poster", "视觉", "版式"))
        if any(token in text for token in ("活动", "优惠", "促销", "推广")):
            tools.append("marketing.campaign_lookup")
        if poster_requested:
            tools.append("marketing.poster_brief")
        if any(token in text for token in ("文案", "宣传语", "广告语", "slogan", "标题", "卖点")):
            if (
                "marketing.campaign_lookup" not in tools
                and not request.session_context.attributes.get("last_campaign_name")
            ):
                tools.append("marketing.campaign_lookup")
            tools.append("marketing.generate_copy")
        if any(token in text for token in ("推广链接", "短链", "utm", "落地页", "链接")):
            if (
                "marketing.campaign_lookup" not in tools
                and not request.session_context.attributes.get("last_campaign_name")
            ):
                tools.append("marketing.campaign_lookup")
            tools.append("marketing.generate_promotion_link")
        if poster_requested:
            tools.append("marketing.generate_poster")
        if not tools:
            return ["support.handoff_brief"] if human_handoff_requested else []
        return RouteTextSignals.append_handoff_brief(tools, text=text)

    @staticmethod
    def _suggest_deep_research(request: RouteRequest, text: str) -> list[str]:
        export_requested = any(token in text for token in ("导出", "markdown", "pdf", "下载"))
        has_existing_report = bool(
            request.session_context.attributes.get("research_topic")
            or request.session_context.attributes.get("report_outline")
        )
        if export_requested and has_existing_report:
            tools: list[str] = []
            if not request.session_context.attributes.get("reference_titles"):
                tools.append("research.reference_search")
            tools.append("research.export_report")
            return RouteTextSignals.append_handoff_brief(tools, text=text)
        tools = ["research.generate_report"]
        if any(token in text for token in ("研究", "调研", "对比", "报告", "参考")):
            tools.append("research.reference_search")
        if export_requested:
            if "research.reference_search" not in tools:
                tools.append("research.reference_search")
            tools.append("research.export_report")
        return RouteTextSignals.append_handoff_brief(tools, text=text)

    @staticmethod
    def _suggest_product_tech(text: str) -> list[str]:
        ticket_requested = RouteTextSignals.ticket_requested(text)
        service_status_requested = RouteTextSignals.service_status_requested(text)
        product_sizing_requested = RouteTextSignals.product_sizing_requested(text)
        human_handoff_requested = RouteTextSignals.human_handoff_requested(text)

        # 纯问候/闲聊，不触发任何工具调用
        generic_greeting = (
            len(text) <= 20
            and not any(
                token in text
                for token in (
                    "查", "产品", "规格", "推荐", "gpu", "部署", "故障",
                    "异常", "配置", "技术", "费用", "账单", "工单", "备案",
                    "活动", "调研", "怎么", "如何", "多少", "什么",
                    "服务器", "实例", "主机", "云", "机型", "套餐", "算力",
                    "选型", "ecs", "通用", "订单", "退款", "发票",
                )
            )
        )
        if generic_greeting:
            return ["support.handoff_brief"] if human_handoff_requested else []

        product_catalog_requested = (
            any(token in text for token in ("产品", "规格", "选型", "推荐", "大模型", "算力"))
            or ("部署" in text and not service_status_requested)
            or ("gpu" in text and product_sizing_requested)
        ) and not (service_status_requested or ticket_requested or human_handoff_requested)
        tools = ["product.catalog_lookup"] if product_catalog_requested else []
        if product_sizing_requested:
            tools.append("product.recommend_instance")
        if service_status_requested:
            tools.append("support.query_service_status")
        if ticket_requested and service_status_requested and "support.handoff_brief" not in tools:
            tools.append("support.handoff_brief")
        if (
            any(token in text for token in ("技术", "配置", "排查", "最佳实践", "教程", "sop"))
            or (
                any(token in text for token in ("故障", "异常"))
                and any(token in text for token in ("排查", "修复", "恢复", "怎么办", "怎么处理"))
            )
            or (
                "部署" in text
                and any(token in text for token in ("方案", "实践", "步骤", "排查"))
            )
        ):
            tools.append("support.playbook_search")
        fallback_tools = (
            ["support.query_service_status"]
            if service_status_requested
            else (["support.playbook_search"] if not human_handoff_requested else ["support.handoff_brief"])
        )
        if tools:
            tools = RouteTextSignals.append_handoff_brief(tools, text=text)
        return tools or fallback_tools
