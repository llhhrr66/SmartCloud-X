from __future__ import annotations

from app.models.orchestration import AgentName, RouteRequest, SceneName

from .agent_registry import (
    AGENT_KEYWORDS,
    CERTIFICATE_NO_PATTERN,
    HIGH_URGENCY_KEYWORDS,
    HUMAN_HANDOFF_KEYWORDS,
    IDENTIFIER_PATTERNS,
    PHONE_PATTERN,
    primary_agent_to_scene,
)


class RouteTextSignals:
    """Stateless text classifiers and identifier extractors used by the router.

    Every method is pure and operates on a query string (or RouteRequest) and
    returns a primitive. Keeping these together makes the router class easier
    to read and the heuristics easier to test in isolation.
    """

    # ------------------------------------------------------------------
    # Boolean classifiers
    # ------------------------------------------------------------------

    @staticmethod
    def human_handoff_requested(text: str) -> bool:
        return any(token in text for token in HUMAN_HANDOFF_KEYWORDS)

    @staticmethod
    def ticket_requested(text: str) -> bool:
        return any(token in text for token in ("工单", "售后", "ticket", "服务单"))

    @staticmethod
    def service_status_requested(text: str) -> bool:
        return any(
            token in text
            for token in ("状态", "健康", "异常", "故障", "不可用", "中断", "告警", "延迟", "抖动", "超时")
        ) and any(
            token in text
            for token in ("实例", "服务", "节点", "网络", "gpu", "云服务器", "ecs")
        )

    @staticmethod
    def product_sizing_requested(text: str) -> bool:
        return any(
            token in text
            for token in ("推荐", "规格", "选型", "大模型", "推理", "训练", "算力", "机型", "主机", "通用", "套餐", "配置")
        ) or (
            "gpu" in text
            and any(token in text for token in ("部署", "规格", "推荐", "大模型", "算力", "训练", "推理"))
        ) or (
            "gpu" in text
            and "实例" in text
            and any(token in text for token in ("文案", "海报", "推广", "宣传", "活动", "优惠", "促销", "链接"))
        )

    @classmethod
    def human_handoff_prefers_brief_only(cls, text: str) -> bool:
        if not cls.human_handoff_requested(text):
            return False
        operational_tokens = (
            "查",
            "查询",
            "核对",
            "确认",
            "开票",
            "退款",
            "创建",
            "回复",
            "提交",
            "生成",
            "推荐",
            "导出",
            "工单",
        )
        return not any(token in text for token in operational_tokens)

    @staticmethod
    def determine_urgency(text: str) -> str:
        if any(token in text for token in HIGH_URGENCY_KEYWORDS):
            return "high"
        if any(token in text for token in ("尽快", "今天", "马上")):
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # Tool list helpers
    # ------------------------------------------------------------------

    @staticmethod
    def promote_tool(tool_names: list[str], tool_name: str) -> list[str]:
        if tool_name not in tool_names:
            return tool_names
        return [tool_name, *[value for value in tool_names if value != tool_name]]

    @classmethod
    def append_handoff_brief(cls, tool_names: list[str], *, text: str) -> list[str]:
        if cls.human_handoff_requested(text) and "support.handoff_brief" not in tool_names:
            tool_names.append("support.handoff_brief")
        return tool_names

    # ------------------------------------------------------------------
    # Identifier extraction
    # ------------------------------------------------------------------

    @staticmethod
    def extract_identifier(query: str, identifier_type: str) -> str | None:
        pattern = IDENTIFIER_PATTERNS.get(identifier_type)
        if pattern is None:
            return None
        match = pattern.search(query)
        if match is None:
            return None
        return match.group(1)

    @staticmethod
    def extract_certificate_no(query: str) -> str | None:
        match = CERTIFICATE_NO_PATTERN.search(query)
        if match is None:
            return None
        return match.group(1).upper()

    @staticmethod
    def extract_phone(query: str) -> str | None:
        match = PHONE_PATTERN.search(query)
        if match is None:
            return None
        return match.group(1)

    # ------------------------------------------------------------------
    # Handoff context helpers
    # ------------------------------------------------------------------

    @staticmethod
    def handoff_related_resources(request: RouteRequest) -> list[str]:
        attributes = request.session_context.attributes
        related: list[str] = []
        for value in request.session_context.active_products:
            normalized = str(value).strip()
            if normalized and normalized not in related:
                related.append(normalized)
        for key in (
            "primary_instance_id",
            "instance_id",
            "order_no",
            "refund_no",
            "invoice_no",
            "application_no",
            "domain",
            "recommended_instance_type",
            "recommended_instance_summary",
        ):
            value = attributes.get(key)
            normalized = str(value).strip() if value is not None else ""
            if normalized and normalized not in related:
                related.append(normalized)
        if request.session_context.open_ticket_id:
            normalized_ticket = str(request.session_context.open_ticket_id).strip()
            if normalized_ticket and normalized_ticket not in related:
                related.append(normalized_ticket)
        return related[:6]

    @staticmethod
    def human_handoff_reason(text: str, scene: SceneName) -> str:
        if any(token in text for token in ("投诉", "升级")):
            return "complaint_or_escalation"
        if any(token in text for token in ("异常", "故障", "不可用", "中断")):
            return "service_exception"
        if scene == "billing":
            return "billing_manual_follow_up"
        if scene == "icp":
            return "icp_manual_review"
        if scene == "marketing":
            return "marketing_manual_follow_up"
        if scene == "research":
            return "research_manual_follow_up"
        return "user_requested_handoff"

    @staticmethod
    def effective_scene_for_payload(request: RouteRequest, text: str) -> SceneName:
        if request.scene != "customer_service":
            return request.scene
        if any(token in text for token in ("账单", "订单", "退款", "发票", "工单", "费用")):
            return "billing"
        if any(token in text for token in ("备案", "实名", "合规", "icp")):
            return "icp"
        if any(token in text for token in ("营销", "活动", "海报", "推广", "优惠", "促销", "文案")):
            return "marketing"
        if any(token in text for token in ("研究", "调研", "报告", "对比", "选型")):
            return "research"
        return "technical_support"

    @staticmethod
    def infer_scene(primary: AgentName, requested_scene: SceneName) -> SceneName:
        if requested_scene != "customer_service":
            return requested_scene
        return primary_agent_to_scene(primary)


def build_signals(text: str) -> list:
    """Build IntentSignal scores per keyword group.

    Imported here (rather than at module load) to avoid circular dependencies
    between the router and shared models.
    """
    from app.models.orchestration import IntentSignal

    signals: list[IntentSignal] = []
    for agent, keywords in AGENT_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword in text]
        signals.append(
            IntentSignal(
                label=agent,
                score=len(matched),
                matched_keywords=matched,
            )
        )
    return signals
