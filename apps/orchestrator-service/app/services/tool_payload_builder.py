from __future__ import annotations

from app.core.business_tools_sdk import ToolDefinition
from app.models.orchestration import RouteRequest
from app.services.tool_context import hydrate_payload_from_session_context

from .route_text_signals import RouteTextSignals


def _confirmed_tool_names(request: RouteRequest) -> set[str]:
    confirmed_tool_names = set(request.session_context.confirmed_tool_names)
    extra_confirmed = request.session_context.attributes.get("confirmed_tool_names", [])
    if isinstance(extra_confirmed, str):
        extra_confirmed = [extra_confirmed]
    confirmed_tool_names.update(extra_confirmed)
    return confirmed_tool_names


def _billing_range_payload(text: str, attributes: dict) -> dict[str, object]:
    if any(token in text for token in ("本月", "这个月")):
        return {"range": "this_month"}
    if any(token in text for token in ("上月", "上个月", "上期")):
        return {"range": "last_month"}
    if any(token in text for token in ("最近三个月", "近三个月", "过去三个月")):
        return {"range": "last_3_months"}
    if attributes.get("billing_range"):
        return {"range": attributes["billing_range"]}
    if attributes.get("billing_cycle"):
        return {"billing_cycle": attributes["billing_cycle"]}
    return {}


def _instance_cost_payload(text: str, attributes: dict) -> dict[str, object]:
    payload: dict[str, object] = {}
    if any(token in text for token in ("本月", "这个月")):
        payload["range"] = "this_month"
    elif any(token in text for token in ("上月", "上个月", "上期")):
        payload["range"] = "last_month"
    elif any(token in text for token in ("最近三个月", "近三个月", "过去三个月")):
        payload["range"] = "last_3_months"
    elif attributes.get("instance_billing_cycle"):
        payload["billing_cycle"] = attributes["instance_billing_cycle"]
    elif attributes.get("billing_cycle"):
        payload["billing_cycle"] = attributes["billing_cycle"]
    return payload


def _channel_from_text(text: str) -> str:
    if "微信" in text:
        return "wechat"
    if "邮件" in text:
        return "email"
    if "短信" in text:
        return "sms"
    return "web"


def _marketing_copy_tone(text: str) -> str:
    if "限时" in text or "冲量" in text:
        return "urgent"
    if "轻松" in text or "亲和" in text:
        return "friendly"
    return "professional"


def _poster_size(text: str) -> str:
    if "方图" in text or "方版" in text:
        return "square"
    if "横版" in text:
        return "landscape"
    return "portrait"


def _product_workload(text: str) -> str:
    if any(token in text for token in ("训练", "微调")):
        return "training"
    if any(token in text for token in ("推理", "部署", "上线")):
        return "inference"
    return "general"


def _product_model_family(text: str) -> str | None:
    if any(token in text for token in ("多模态", "文生图", "图文")):
        return "multimodal"
    if any(token in text for token in ("视觉", "视频")):
        return "vision"
    if any(token in text for token in ("大模型", "llm", "qwen", "llama", "deepseek")):
        return "llm"
    return None


def _product_budget_level(text: str) -> str:
    if any(token in text for token in ("低预算", "成本", "便宜", "测试", "demo", "poc")):
        return "cost_optimized"
    if any(token in text for token in ("高性能", "生产", "企业级", "高并发", "低延迟")):
        return "performance"
    return "balanced"


class ToolPayloadBuilder:
    """Builds tool invocation payloads from a route request.

    All methods are static — payload construction is a pure function of the
    request and the active text signals. The builder is split out to keep
    `router.py` focused on planning and selection logic.
    """

    @staticmethod
    def build(
        tool_name: str,
        request: RouteRequest,
        text: str,
        definition: ToolDefinition | None,
    ) -> dict[str, object]:
        raw_query = request.user_query
        attributes = request.session_context.attributes
        base_payload: dict[str, object] = {
            "user_query": request.user_query,
            "conversation_id": request.conversation_id,
        }
        if request.user_profile.account_id:
            base_payload["account_id"] = request.user_profile.account_id
        if request.user_profile.user_id:
            base_payload["user_id"] = request.user_profile.user_id

        if tool_name == "billing.query_statement":
            base_payload.update(_billing_range_payload(text, attributes))
        elif tool_name == "billing.query_instance_cost":
            extracted_instance_id = RouteTextSignals.extract_identifier(raw_query, "instance_id")
            if extracted_instance_id is not None:
                base_payload["instance_id"] = extracted_instance_id
            base_payload.update(_instance_cost_payload(text, attributes))
        elif tool_name == "order.query_order":
            extracted_order_no = RouteTextSignals.extract_identifier(raw_query, "order_no")
            extracted_refund_no = RouteTextSignals.extract_identifier(raw_query, "refund_no")
            if extracted_order_no is not None:
                base_payload["order_no"] = extracted_order_no
            if extracted_refund_no is not None:
                base_payload["refund_no"] = extracted_refund_no
        elif tool_name == "billing.create_invoice":
            extracted_invoice_no = RouteTextSignals.extract_identifier(raw_query, "invoice_no")
            if extracted_invoice_no is not None:
                base_payload["invoice_no"] = extracted_invoice_no
        elif tool_name == "invoice.query_invoice":
            extracted_invoice_no = RouteTextSignals.extract_identifier(raw_query, "invoice_no")
            if extracted_invoice_no is not None:
                base_payload["invoice_no"] = extracted_invoice_no
        elif tool_name == "order.create_refund":
            extracted_order_no = RouteTextSignals.extract_identifier(raw_query, "order_no")
            if extracted_order_no is not None:
                base_payload["order_no"] = extracted_order_no
        elif tool_name == "ticket.create":
            effective_scene = RouteTextSignals.effective_scene_for_payload(request, text)
            ticket_waits_for_context = (
                RouteTextSignals.human_handoff_requested(text)
                or (
                    effective_scene == "technical_support"
                    and RouteTextSignals.service_status_requested(text)
                )
            )
            base_payload.update(
                {
                    "scene": effective_scene,
                    "priority": "high" if "紧急" in text else "medium",
                    "category": effective_scene,
                }
            )
            if not ticket_waits_for_context:
                base_payload["subject"] = request.user_query
                base_payload["content"] = request.user_query
        elif tool_name == "ticket.reply":
            extracted_ticket_no = RouteTextSignals.extract_identifier(raw_query, "ticket_no")
            if extracted_ticket_no is not None:
                base_payload["ticket_no"] = extracted_ticket_no
            base_payload["content"] = request.user_query
        elif tool_name == "ticket.query_ticket":
            extracted_ticket_no = RouteTextSignals.extract_identifier(raw_query, "ticket_no")
            if extracted_ticket_no is not None:
                base_payload["ticket_no"] = extracted_ticket_no
        elif tool_name == "support.handoff_brief":
            effective_scene = RouteTextSignals.effective_scene_for_payload(request, text)
            base_payload.update(
                {
                    "scene": effective_scene,
                    "urgency": RouteTextSignals.determine_urgency(text),
                    "reason": RouteTextSignals.human_handoff_reason(text, effective_scene),
                    "related_resources": RouteTextSignals.handoff_related_resources(request),
                }
            )
            if request.session_context.history_summary:
                base_payload["conversation_summary"] = request.session_context.history_summary
            if request.session_context.open_ticket_id:
                base_payload["open_ticket_id"] = request.session_context.open_ticket_id
        elif tool_name == "support.query_service_status":
            extracted_instance_id = RouteTextSignals.extract_identifier(raw_query, "instance_id")
            if extracted_instance_id is not None:
                base_payload["instance_id"] = extracted_instance_id
            if "网络" in text:
                base_payload["service"] = "实例网络连通性"
            elif any(token in text for token in ("存储", "磁盘", "云盘")):
                base_payload["service"] = "块存储服务"
            elif "gpu" in text or "显卡" in request.user_query:
                base_payload["service"] = "GPU 实例服务"
        elif tool_name == "icp.verify_subject":
            if "个人" in text:
                base_payload["subject_type"] = "personal"
            elif any(token in text for token in ("企业", "公司")):
                base_payload["subject_type"] = "enterprise"
            extracted_certificate_no = RouteTextSignals.extract_certificate_no(raw_query)
            extracted_phone = RouteTextSignals.extract_phone(raw_query)
            if extracted_certificate_no is not None:
                base_payload["certificate_no"] = extracted_certificate_no
            if extracted_phone is not None:
                base_payload["contact_phone"] = extracted_phone
        elif tool_name == "icp.query_application":
            extracted_application_no = RouteTextSignals.extract_identifier(raw_query, "application_no")
            if extracted_application_no is not None:
                base_payload["application_no"] = extracted_application_no
        elif tool_name == "marketing.campaign_lookup":
            base_payload["product"] = "GPU" if "gpu" in text else "云服务"
        elif tool_name == "marketing.poster_brief":
            base_payload["theme"] = request.user_query
            base_payload["cta"] = "立即咨询"
        elif tool_name == "marketing.generate_copy":
            base_payload["channel"] = _channel_from_text(text)
            base_payload["tone"] = _marketing_copy_tone(text)
        elif tool_name == "marketing.generate_promotion_link":
            base_payload["channel"] = _channel_from_text(text)
        elif tool_name == "marketing.generate_poster":
            base_payload["size"] = _poster_size(text)
            base_payload["channel"] = _channel_from_text(text)
        elif tool_name == "product.recommend_instance":
            base_payload["workload"] = _product_workload(text)
            model_family = _product_model_family(text)
            if model_family is not None:
                base_payload["model_family"] = model_family
            base_payload["budget_level"] = _product_budget_level(text)
        elif tool_name == "research.generate_report":
            base_payload["topic"] = request.user_query
        elif tool_name == "research.reference_search":
            base_payload["topic"] = request.user_query
            base_payload["limit"] = 5
        elif tool_name == "research.export_report":
            base_payload["format"] = "pdf" if "pdf" in text else "markdown"

        base_payload = hydrate_payload_from_session_context(
            base_payload,
            definition,
            request.session_context,
        )
        if tool_name in _confirmed_tool_names(request):
            base_payload["_confirmed"] = True
        return {key: value for key, value in base_payload.items() if value is not None and value != ""}
