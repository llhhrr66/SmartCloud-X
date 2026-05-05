from __future__ import annotations

import re
from collections import OrderedDict
from typing import Literal

from app.models.orchestration import AgentName, SceneName


AGENT_KEYWORDS: OrderedDict[str, tuple[str, ...]] = OrderedDict(
    [
        ("finance_order_agent", ("账单", "订单", "退款", "发票", "扣费", "工单", "费用", "消费", "花了", "多少钱", "收费", "价格", "多少钱")),
        ("icp_service_agent", ("备案", "实名", "合规", "icp", "核验")),
        ("ops_marketing_agent", ("营销", "活动", "海报", "推广", "优惠", "促销", "文案")),
        ("deep_research_agent", ("调研", "研究", "对比", "报告", "选型", "方案评估")),
        ("product_tech_agent", ("gpu", "云服务器", "ecs", "部署", "技术", "配置", "故障", "产品", "服务器", "算力", "规格", "主机", "机型", "套餐", "云产品")),
    ]
)

HUMAN_HANDOFF_KEYWORDS: tuple[str, ...] = ("人工", "转人工", "投诉", "升级", "紧急", "电话联系")
HIGH_URGENCY_KEYWORDS: tuple[str, ...] = ("紧急", "故障", "投诉", "服务异常")
RETRIEVAL_KEYWORDS: tuple[str, ...] = ("文档", "教程", "faq", "方案", "how", "最佳实践", "排查", "研究", "对比")

SCENE_TO_AGENT: dict[SceneName, AgentName] = {
    "billing": "finance_order_agent",
    "technical_support": "product_tech_agent",
    "icp": "icp_service_agent",
    "marketing": "ops_marketing_agent",
    "research": "deep_research_agent",
    "customer_service": "product_tech_agent",
}

AGENT_REGISTRY: dict[AgentName, dict[str, object]] = {
    "product_tech_agent": {
        "code": "product_tech",
        "display_name": "Product_Tech_Agent",
        "description": "处理产品咨询、云服务器、GPU、部署与技术排障。",
        "supported_scenes": ["customer_service", "technical_support", "research"],
        "allowed_tools": {
            "product.catalog_lookup": "allow",
            "product.recommend_instance": "allow",
            "support.playbook_search": "allow",
            "support.query_service_status": "allow",
            "support.handoff_brief": "allow",
        },
        "fallback_agent": "orchestrator",
    },
    "finance_order_agent": {
        "code": "finance_order",
        "display_name": "Finance_Order_Agent",
        "description": "处理账单、订单、发票、退款和工单相关问题。",
        "supported_scenes": ["billing", "customer_service"],
        "allowed_tools": {
            "billing.query_statement": "allow",
            "billing.query_instance_cost": "allow",
            "order.query_order": "allow",
            "billing.create_invoice": "ask",
            "invoice.query_invoice": "allow",
            "order.create_refund": "ask",
            "ticket.create": "ask",
            "ticket.reply": "ask",
            "ticket.query_ticket": "allow",
            "support.handoff_brief": "allow",
        },
        "fallback_agent": "orchestrator",
    },
    "icp_service_agent": {
        "code": "icp_service",
        "display_name": "ICP_Service_Agent",
        "description": "处理备案材料检查、流程说明与备案申请。",
        "supported_scenes": ["icp", "customer_service"],
        "allowed_tools": {
            "icp.material_check": "allow",
            "icp.verify_subject": "allow",
            "icp.submit_application": "ask",
            "icp.query_application": "allow",
            "support.handoff_brief": "allow",
        },
        "fallback_agent": "orchestrator",
    },
    "ops_marketing_agent": {
        "code": "ops_marketing",
        "display_name": "Ops_Marketing_Agent",
        "description": "处理活动营销、海报 brief 与推广建议。",
        "supported_scenes": ["marketing", "customer_service"],
        "allowed_tools": {
            "marketing.campaign_lookup": "allow",
            "marketing.poster_brief": "allow",
            "marketing.generate_copy": "ask",
            "marketing.generate_promotion_link": "ask",
            "marketing.generate_poster": "ask",
            "support.handoff_brief": "allow",
        },
        "fallback_agent": "orchestrator",
    },
    "deep_research_agent": {
        "code": "deep_research",
        "display_name": "Deep_Research_Agent",
        "description": "处理技术选型、行业调研与报告生成。",
        "supported_scenes": ["research", "technical_support"],
        "allowed_tools": {
            "research.generate_report": "ask",
            "research.reference_search": "allow",
            "research.export_report": "ask",
            "support.handoff_brief": "allow",
        },
        "fallback_agent": "orchestrator",
    },
}

IDENTIFIER_PATTERNS: dict[str, re.Pattern[str]] = {
    "order_no": re.compile(r"\b(ord[-_][a-z0-9._-]+)\b", re.IGNORECASE),
    "refund_no": re.compile(r"\b(refund[-_][a-z0-9._-]+)\b", re.IGNORECASE),
    "invoice_no": re.compile(r"\b(inv[-_][a-z0-9._-]+)\b", re.IGNORECASE),
    "ticket_no": re.compile(r"\b(tk[-_][a-z0-9._-]+)\b", re.IGNORECASE),
    "application_no": re.compile(r"\b(icp[-_][a-z0-9._-]+)\b", re.IGNORECASE),
    "instance_id": re.compile(r"\b((?:gpu|ecs|vm|instance|i)-[a-z0-9._-]+)\b", re.IGNORECASE),
}

CERTIFICATE_NO_PATTERN: re.Pattern[str] = re.compile(r"\b([0-9A-Z]{15,18})\b", re.IGNORECASE)
PHONE_PATTERN: re.Pattern[str] = re.compile(r"(?<!\d)(1\d{10})(?!\d)")

_AGENT_STEP_OBJECTIVES: dict[AgentName, str] = {
    "product_tech_agent": "评估产品选型、部署方案与技术排障建议。",
    "finance_order_agent": "核对账单、订单、退款、发票或工单处理状态。",
    "icp_service_agent": "核对备案材料、流程或状态，并指出缺口。",
    "ops_marketing_agent": "整理活动、营销文案和海报 brief 候选。",
    "deep_research_agent": "组织调研提纲、参考资料与报告结构。",
}

_PRIMARY_AGENT_TO_SCENE: dict[AgentName, SceneName] = {
    "product_tech_agent": "technical_support",
    "finance_order_agent": "billing",
    "icp_service_agent": "icp",
    "ops_marketing_agent": "marketing",
    "deep_research_agent": "research",
}


def allowed_tools_for(agent: AgentName) -> list[str]:
    """Return the list of tool names an agent may use.

    Backward-compatible: handles both new dict format (allow/ask/deny)
    and legacy list format (all treated as allow).
    """
    raw = AGENT_REGISTRY[agent]["allowed_tools"]
    if isinstance(raw, dict):
        return [name for name, perm in raw.items() if perm != "deny"]
    # Legacy list format — all treated as allow
    return list(raw)


ToolPermission = Literal["allow", "ask", "deny"]


def tool_permission_for(agent: AgentName, tool_name: str) -> ToolPermission:
    """Return the permission level for a specific agent+tool combination.

    - "allow": tool may be called without confirmation
    - "ask":   tool requires user confirmation (preview unless _confirmed)
    - "deny":  tool is not available to this agent
    """
    raw = AGENT_REGISTRY[agent]["allowed_tools"]
    if isinstance(raw, dict):
        return raw.get(tool_name, "deny")  # type: ignore[return-value]
    # Legacy list format — present = allow, absent = deny
    if tool_name in raw:
        return "allow"
    return "deny"


def agent_code_for(agent: AgentName) -> str:
    return str(AGENT_REGISTRY[agent]["code"])


def step_objective(agent: AgentName, primary: bool) -> str:
    prefix = "主处理" if primary else "补充处理"
    return f"{prefix}：{_AGENT_STEP_OBJECTIVES[agent]}"


def resolve_agent_name(agent_code: str) -> AgentName:
    normalized = agent_code.strip()
    for agent_name, meta in AGENT_REGISTRY.items():
        if normalized in {agent_name, str(meta["code"])}:
            return agent_name
    raise ValueError(f"Unknown agent code: {agent_code}")


def primary_agent_to_scene(primary: AgentName) -> SceneName:
    return _PRIMARY_AGENT_TO_SCENE.get(primary, "customer_service")
