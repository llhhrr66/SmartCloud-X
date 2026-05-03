from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from business_tools.db import query_all, query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import (
    _normalize_string_list,
    _query_payload,
    _slugify_token,
    _with_result,
)
from .._static_tool import StaticBusinessTool


# ----------------------------------------------------------------------
# product.catalog_lookup
# ----------------------------------------------------------------------


def _product_catalog_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = _query_payload(request)

    rows = query_all(
        "SELECT DISTINCT product_family FROM product_catalog WHERE status = 'active' ORDER BY product_family"
    )
    if rows:
        families = [r["product_family"] for r in rows]
        return _with_result(
            "已整理产品族和部署选型建议。",
            {"matched_query": query, "product_families": families, "next_step": "结合 RAG 文档补充规格建议"},
            "db://product-catalog/families",
        )

    families = []
    return _with_result(
        "已整理产品族和部署选型建议。",
        {"matched_query": query, "product_families": families, "next_step": "暂无产品数据，请联系运营补充"},
        "baseline://product-catalog",
    )


# ----------------------------------------------------------------------
# product.recommend_instance
# ----------------------------------------------------------------------


def _product_recommend_instance_profile(request: ToolInvocationRequest) -> dict[str, Any]:
    query = _query_payload(request)
    lowered_query = query.lower()

    workload = str(request.payload.get("workload") or "").strip().lower()
    if not workload:
        if any(token in query for token in ("训练", "微调")) or "train" in lowered_query:
            workload = "training"
        elif any(token in query for token in ("推理", "部署", "上线")) or "inference" in lowered_query:
            workload = "inference"
        else:
            workload = "general"

    model_family = str(request.payload.get("model_family") or "").strip().lower()
    if not model_family:
        if any(token in query for token in ("多模态", "文生图", "图文")):
            model_family = "multimodal"
        elif any(token in query for token in ("视觉", "视频")):
            model_family = "vision"
        elif any(token in query for token in ("大模型", "llm", "qwen", "llama", "deepseek")):
            model_family = "llm"
        else:
            model_family = "general"

    budget_level = str(request.payload.get("budget_level") or "").strip().lower()
    if not budget_level:
        if any(token in query for token in ("低预算", "成本", "便宜", "测试", "demo", "poc")):
            budget_level = "cost_optimized"
        elif any(token in query for token in ("高性能", "生产", "企业级", "高并发", "低延迟")):
            budget_level = "performance"
        else:
            budget_level = "balanced"

    # Try to find matching instance specs from DB
    if workload == "training" or budget_level == "performance":
        spec_rows = query_all(
            "SELECT s.instance_type, s.instance_family, s.gpu_model, s.gpu_count, s.vcpu, s.memory_gb, "
            "s.network_gbps, p.price_per_unit, p.currency "
            "FROM product_instance_specs s LEFT JOIN product_pricing p ON s.instance_type = p.instance_type AND p.status = 'active' "
            "WHERE s.status = 'active' AND s.gpu_count >= 4 ORDER BY s.gpu_count DESC, s.vcpu DESC LIMIT 3"
        )
    elif budget_level == "cost_optimized":
        spec_rows = query_all(
            "SELECT s.instance_type, s.instance_family, s.gpu_model, s.gpu_count, s.vcpu, s.memory_gb, "
            "s.network_gbps, p.price_per_unit, p.currency "
            "FROM product_instance_specs s LEFT JOIN product_pricing p ON s.instance_type = p.instance_type AND p.status = 'active' "
            "WHERE s.status = 'active' AND s.gpu_count = 1 ORDER BY p.price_per_unit ASC LIMIT 3"
        )
    else:
        spec_rows = query_all(
            "SELECT s.instance_type, s.instance_family, s.gpu_model, s.gpu_count, s.vcpu, s.memory_gb, "
            "s.network_gbps, p.price_per_unit, p.currency "
            "FROM product_instance_specs s LEFT JOIN product_pricing p ON s.instance_type = p.instance_type AND p.status = 'active' "
            "WHERE s.status = 'active' AND s.gpu_count BETWEEN 2 AND 4 ORDER BY s.gpu_count, s.vcpu LIMIT 3"
        )

    if spec_rows:
        primary = spec_rows[0]
        monthly_cost = float(primary.get("price_per_unit") or 0) * 730 if primary.get("price_per_unit") else 0
        alternatives = []
        for alt in spec_rows[1:]:
            alt_cost = float(alt.get("price_per_unit") or 0) * 730 if alt.get("price_per_unit") else 0
            alternatives.append({
                "instance_type": alt["instance_type"],
                "gpu_model": alt.get("gpu_model", ""),
                "scenario": f"{alt.get('gpu_count', 0)}x {alt.get('gpu_model', 'GPU')}",
                "estimated_monthly_cost_cny": round(alt_cost, 2) if alt_cost else None,
            })

        rationale = []
        if workload == "training":
            rationale.append(f"适合大模型训练/微调，{primary.get('gpu_count', 0)}x {primary.get('gpu_model', 'GPU')} 提供充足算力。")
        elif workload == "inference":
            rationale.append(f"适合推理部署场景，{primary.get('gpu_count', 0)}x {primary.get('gpu_model', 'GPU')} 平衡吞吐与成本。")
        else:
            rationale.append(f"推荐规格适合通用场景，{primary.get('gpu_count', 0)}x {primary.get('gpu_model', 'GPU')} 配置均衡。")
        rationale.append(f"vCPU {primary.get('vcpu', 0)} / 内存 {primary.get('memory_gb', 0)}GB 满足大多数工作负载。")
        if primary.get("network_gbps"):
            rationale.append(f"网络带宽 {primary['network_gbps']}Gbps 支撑高速数据传输。")

        recommendation = {
            "recommended_instance_family": primary.get("instance_family", ""),
            "recommended_instance_type": primary["instance_type"],
            "gpu_model": primary.get("gpu_model", ""),
            "gpu_count": primary.get("gpu_count", 0),
            "vcpu": primary.get("vcpu", 0),
            "memory_gb": primary.get("memory_gb", 0),
            "network_gbps": primary.get("network_gbps", 0),
            "estimated_monthly_cost_cny": round(monthly_cost, 2) if monthly_cost else None,
            "rationale": rationale,
            "alternatives": alternatives,
        }
    else:
        # Fallback baseline — try any available specs from DB
        any_specs = query_all(
            "SELECT s.instance_type, s.instance_family, s.gpu_model, s.gpu_count, s.vcpu, s.memory_gb, "
            "s.network_gbps, p.price_per_unit, p.currency "
            "FROM product_instance_specs s LEFT JOIN product_pricing p ON s.instance_type = p.instance_type AND p.status = 'active' "
            "WHERE s.status = 'active' ORDER BY s.gpu_count DESC LIMIT 3"
        )
        if any_specs:
            primary = any_specs[0]
            monthly_cost = float(primary.get("price_per_unit") or 0) * 730 if primary.get("price_per_unit") else 0
            alternatives = []
            for alt in any_specs[1:]:
                alt_cost = float(alt.get("price_per_unit") or 0) * 730 if alt.get("price_per_unit") else 0
                alternatives.append({
                    "instance_type": alt["instance_type"],
                    "gpu_model": alt.get("gpu_model", ""),
                    "scenario": f"{alt.get('gpu_count', 0)}x {alt.get('gpu_model', 'GPU')}",
                    "estimated_monthly_cost_cny": round(alt_cost, 2) if alt_cost else None,
                })
            rationale = [f"推荐 {primary.get('gpu_count', 0)}x {primary.get('gpu_model', 'GPU')} 规格。"]
            recommendation = {
                "recommended_instance_family": primary.get("instance_family", ""),
                "recommended_instance_type": primary["instance_type"],
                "gpu_model": primary.get("gpu_model", ""),
                "gpu_count": primary.get("gpu_count", 0),
                "vcpu": primary.get("vcpu", 0),
                "memory_gb": primary.get("memory_gb", 0),
                "network_gbps": primary.get("network_gbps", 0),
                "estimated_monthly_cost_cny": round(monthly_cost, 2) if monthly_cost else None,
                "rationale": rationale,
                "alternatives": alternatives,
            }
        else:
            # No DB data at all — return empty baseline
            recommendation = {
                "recommended_instance_family": "",
                "recommended_instance_type": "",
                "gpu_model": "",
                "gpu_count": 0,
                "vcpu": 0,
                "memory_gb": 0,
                "network_gbps": 0,
                "estimated_monthly_cost_cny": None,
                "rationale": ["暂无可用规格数据，请联系技术支持获取推荐。"],
                "alternatives": [],
            }

    return {
        "query": query,
        "workload": workload,
        "model_family": model_family,
        "budget_level": budget_level,
        **recommendation,
    }


def _product_recommend_instance_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    recommendation = _product_recommend_instance_profile(request)
    return _with_result(
        "已生成云主机规格推荐草稿。",
        {
            **recommendation,
            "preview_notice": "正式执行会返回推荐理由、备选机型与基线成本估算。",
        },
        "baseline://product-instance-recommendation",
    )


def _product_recommend_instance_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    recommendation = _product_recommend_instance_profile(request)
    itype = recommendation.get("recommended_instance_type", "")
    citation = "db://product-instance-specs/" + itype if itype else "baseline://product-instance-recommendation"
    return _with_result("已生成云主机规格建议。", recommendation, citation)


# ----------------------------------------------------------------------
# support.playbook_search / support.query_service_status / support.handoff_brief
# ----------------------------------------------------------------------


def _support_playbook_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = _query_payload(request)

    # Try to find relevant product catalog entries for playbook context
    rows = query_all(
        "SELECT name, category FROM product_catalog WHERE status = 'active' AND "
        "(name LIKE CONCAT('%', :q, '%') OR category LIKE CONCAT('%', :q, '%')) LIMIT 3",
        {"q": query[:50]},
    )
    if rows:
        playbooks = [
            {"title": f"《{r['name']}》技术文档与排查指南", "confidence": 0.85, "category": r.get("category")}
            for r in rows
        ]
        return _with_result(
            "已生成可继续检索的技术支持 SOP 候选。",
            {"matched_query": query, "playbooks": playbooks},
            "db://product-catalog/search",
        )

    playbooks = [
        {"title": "GPU 驱动与 CUDA 环境检查", "confidence": 0.83},
        {"title": "实例网络与安全组排查", "confidence": 0.77},
    ]
    if "部署" not in query and "故障" not in query:
        playbooks = [{"title": "云产品咨询话术模板", "confidence": 0.68}]
    return _with_result(
        "已生成可继续检索的技术支持 SOP 候选。",
        {"matched_query": query, "playbooks": playbooks},
        "baseline://support-playbook",
    )


def _infer_region_from_instance_id(instance_id: str | None) -> str:
    normalized = str(instance_id or "").strip().lower()
    if "cn-sh2" in normalized or "shanghai" in normalized:
        return ""
    if "cn-bj1" in normalized or "beijing" in normalized:
        return "cn-beijing-1"
    if "cn-gz1" in normalized or "guangzhou" in normalized:
        return "cn-guangzhou-1"
    return ""


def _support_query_service_status_profile(request: ToolInvocationRequest) -> dict[str, Any]:
    query = str(request.payload.get("user_query") or _query_payload(request) or "待补充服务状态问题")
    lowered_query = query.lower()
    instance_id = str(request.payload.get("instance_id") or "").strip() or None
    region = str(request.payload.get("region") or "").strip() or _infer_region_from_instance_id(instance_id)

    raw_service = str(request.payload.get("service") or "").strip()
    if "网络" in query:
        service_name = "实例网络连通性"
        service_code = "instance-network"
    elif any(token in query for token in ("存储", "磁盘", "云盘")):
        service_name = "块存储服务"
        service_code = "block-storage"
    elif instance_id and instance_id.startswith("gpu-"):
        service_name = "GPU 实例服务"
        service_code = "gpu-instance"
    elif any(token in lowered_query for token in ("gpu", "cuda", "显卡")):
        service_name = "GPU 实例服务"
        service_code = "gpu-instance"
    elif instance_id and instance_id.startswith(("ecs-", "vm-", "instance-", "i-")):
        service_name = "云服务器实例"
        service_code = "cloud-server"
    elif raw_service:
        service_name = raw_service
        service_code = _slugify_token(raw_service, fallback="cloud-service")
    else:
        service_name = "云服务运行状态"
        service_code = "cloud-service"

    symptoms: list[str] = []
    if any(token in query for token in ("不可用", "中断", "宕机")):
        symptoms.append("用户反馈服务不可用或已中断。")
    if any(token in query for token in ("故障", "异常")):
        symptoms.append("用户反馈实例或服务出现异常。")
    if any(token in query for token in ("网络", "丢包", "超时", "连接")):
        symptoms.append("观测到网络连通性或时延相关诉求。")
    if any(token in query for token in ("延迟", "抖动", "慢")):
        symptoms.append("存在性能波动或访问延迟升高风险。")
    if not symptoms:
        symptoms.append("基线巡检未收到明确故障关键词。")

    if any(token in query for token in ("不可用", "中断", "宕机")):
        status = "outage"
        severity = "sev1"
        recommended_action = "建议立即转人工并核对影响时间、实例编号和最近变更记录。"
    elif any(token in query for token in ("故障", "异常", "告警", "延迟", "抖动", "超时")):
        status = "degraded"
        severity = "sev2"
        recommended_action = "建议先核对网络/安全组/驱动，再视影响范围升级人工支持。"
    else:
        status = "healthy"
        severity = "info"
        recommended_action = "当前未发现明显异常，可继续观察并补充具体实例或时间窗。"

    region_token = region.upper().replace("-", "")
    service_token = _slugify_token(service_code, fallback="service").upper().replace("-", "")
    incident_code = None
    if status != "healthy":
        incident_code = f"INC-{region_token}-{service_token[:10]}-042"

    impact_scope = "single-instance" if instance_id else "regional"
    if status == "healthy":
        summary = f"{service_name} 在 {region} 当前未发现显著异常。"
    elif instance_id:
        summary = f"{instance_id} 所属{service_name}在 {region} 当前为 {status}，建议尽快处理。"
    else:
        summary = f"{service_name} 在 {region} 当前为 {status}，建议确认受影响资源范围。"

    return {
        "instance_id": instance_id,
        "service_name": service_name,
        "region": region,
        "status": status,
        "severity": severity,
        "incident_code": incident_code,
        "impact_scope": impact_scope,
        "symptoms": symptoms,
        "summary": summary,
        "recommended_action": recommended_action,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "escalation_recommended": status != "healthy",
    }


def _support_query_service_status_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    profile = _support_query_service_status_profile(request)
    return _with_result(
        "已生成服务状态巡检草稿。",
        {
            **profile,
            "preview_notice": "正式执行会返回基线状态摘要、建议动作和可能的事件编号。",
        },
        "baseline://support-service-status",
    )


def _support_query_service_status_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    profile = _support_query_service_status_profile(request)
    instance_id = profile.get("instance_id")
    user_id = request.context.user_id

    # Try to find matching open tickets from DB
    if instance_id:
        row = query_one(
            "SELECT ticket_no, status, severity, incident_code, subject, description, assigned_team "
            "FROM support_tickets WHERE instance_id = :iid AND status IN ('open', 'processing') "
            "ORDER BY updated_at DESC LIMIT 1",
            {"iid": instance_id},
        )
    elif user_id:
        row = query_one(
            "SELECT ticket_no, status, severity, incident_code, subject, description, assigned_team "
            "FROM support_tickets WHERE user_id = :uid AND status IN ('open', 'processing') "
            "ORDER BY updated_at DESC LIMIT 1",
            {"uid": user_id},
        )
    else:
        row = None

    if row:
        if row.get("severity"):
            profile["severity"] = row["severity"]
        if row.get("incident_code"):
            profile["incident_code"] = row["incident_code"]
        if row.get("assigned_team"):
            profile["assigned_team"] = row["assigned_team"]
        profile["related_ticket_no"] = row["ticket_no"]
        if row["status"] in ("open", "processing"):
            profile["status"] = "degraded" if profile["status"] == "healthy" else profile["status"]
        return _with_result(
            "已返回服务状态数据。",
            profile,
            "db://support-tickets/" + row["ticket_no"],
        )

    return _with_result(
        "已返回服务状态基线信息。",
        profile,
        "baseline://support-service-status",
    )


def _support_handoff_brief_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = str(request.payload.get("user_query") or _query_payload(request) or "待补充用户诉求")
    scene = str(request.payload.get("scene") or "customer_service").strip() or "customer_service"
    urgency = str(request.payload.get("urgency") or "medium").strip().lower() or "medium"
    conversation_summary = str(request.payload.get("conversation_summary") or "").strip()
    open_ticket_id = str(request.payload.get("open_ticket_id") or "").strip() or None
    related_resources = _normalize_string_list(request.payload.get("related_resources"))
    service_status = str(request.payload.get("service_status") or "").strip() or None
    incident_code = str(request.payload.get("incident_code") or "").strip() or None
    diagnostic_summary = str(request.payload.get("status_summary") or "").strip() or None
    recommended_action = str(request.payload.get("recommended_action") or "").strip() or None

    queue_mapping = {
        "billing": "billing-ops",
        "technical_support": "technical-support-l2",
        "icp": "icp-service-desk",
        "marketing": "marketing-ops",
        "research": "solution-architecture",
        "customer_service": "customer-success",
    }
    queue = queue_mapping.get(scene, "customer-success")

    lowered_query = query.lower()
    if any(token in query for token in ("投诉", "升级")):
        reason = "complaint_or_escalation"
    elif any(token in query for token in ("异常", "故障", "不可用", "中断")):
        reason = "service_exception"
    elif "退款" in query:
        reason = "refund_follow_up"
    elif "备案" in query:
        reason = "icp_manual_review"
    else:
        reason = "user_requested_handoff"

    severity = urgency
    if severity not in {"low", "medium", "high"}:
        severity = "medium"
    if reason in {"complaint_or_escalation", "service_exception"} or any(
        token in lowered_query for token in ("urgent", "p0", "sev1")
    ):
        severity = "high"

    operator_notes: list[str] = []
    if scene == "billing":
        operator_notes.extend(
            [
                "优先核对账单、退款或发票关联记录，确认是否存在金额或状态异常。",
                "如用户已提供订单号/发票号，请在人工接入时复核对应凭证。",
            ]
        )
    elif scene == "technical_support":
        operator_notes.extend(
            [
                "优先确认实例、网络、安全组或 GPU 驱动是否存在服务异常。",
                "接入后先确认影响范围、开始时间以及是否需要升级值班支持。",
            ]
        )
    elif scene == "icp":
        operator_notes.extend(
            [
                "优先核对备案主体、联系人与材料缺口，必要时走人工复审。",
                "如涉及实名核验失败，请确认主体证件号和联系方式是否一致。",
            ]
        )
    elif scene == "marketing":
        operator_notes.extend(
            [
                "确认活动有效期、投放渠道与素材约束，再安排人工运营跟进。",
                "如用户涉及定制诉求，请保留当前 campaign / 海报 / 文案上下文。",
            ]
        )
    elif scene == "research":
        operator_notes.extend(
            [
                "确认调研目标、交付时间和期望输出格式，再分配到方案或架构团队。",
                "必要时回看已有参考资料和报告导出记录，避免重复劳动。",
            ]
        )
    else:
        operator_notes.extend(
            [
                "先复述用户当前诉求与紧急程度，再确认需转接的具体业务团队。",
                "如已有上下文摘要或工单编号，请一并同步给人工坐席。",
            ]
        )

    if diagnostic_summary:
        operator_notes.append(f"当前基线状态检查：{diagnostic_summary}")
    elif service_status:
        operator_notes.append(f"当前基线状态：{service_status}。")
    if incident_code:
        operator_notes.append(f"关联事件编号：{incident_code}。")
    if recommended_action:
        operator_notes.append(f"建议优先动作：{recommended_action}")

    summary_parts = [f"用户请求人工介入：{query}"]
    if conversation_summary:
        summary_parts.append(f"历史摘要：{conversation_summary}")
    if related_resources:
        summary_parts.append(f"关联资源：{'、'.join(related_resources[:5])}")
    if open_ticket_id:
        summary_parts.append(f"已有工单：{open_ticket_id}")
    if diagnostic_summary:
        summary_parts.append(f"状态检查：{diagnostic_summary}")
    if incident_code:
        summary_parts.append(f"事件编号：{incident_code}")
    summary = "；".join(summary_parts)

    result_data: dict[str, Any] = {
        "queue": queue,
        "severity": severity,
        "reason": reason,
        "summary": summary,
        "conversation_summary": conversation_summary or None,
        "related_resources": related_resources,
        "open_ticket_id": open_ticket_id,
        "service_status": service_status,
        "incident_code": incident_code,
        "status_summary": diagnostic_summary,
        "recommended_action": recommended_action,
        "operator_notes": operator_notes,
    }

    # Try to enrich from DB: look up related open ticket
    user_id = request.context.user_id
    ticket_row = None
    if open_ticket_id:
        ticket_row = query_one(
            "SELECT ticket_no, status, severity, subject, incident_code, assigned_team "
            "FROM support_tickets WHERE ticket_no = :tno LIMIT 1",
            {"tno": open_ticket_id},
        )
    elif user_id:
        ticket_row = query_one(
            "SELECT ticket_no, status, severity, subject, incident_code, assigned_team "
            "FROM support_tickets WHERE user_id = :uid AND status IN ('open', 'processing') "
            "ORDER BY updated_at DESC LIMIT 1",
            {"uid": user_id},
        )
    if ticket_row:
        result_data["open_ticket_id"] = ticket_row["ticket_no"]
        result_data["ticket_subject"] = ticket_row.get("subject")
        if ticket_row.get("assigned_team"):
            result_data["assigned_team"] = ticket_row["assigned_team"]
        if ticket_row.get("incident_code") and not incident_code:
            result_data["incident_code"] = ticket_row["incident_code"]
        return _with_result(
            "已生成转人工交接摘要。",
            result_data,
            "db://support-tickets/" + ticket_row["ticket_no"],
        )

    return _with_result(
        "已生成转人工交接摘要。",
        result_data,
        "baseline://support-handoff-brief",
    )


# ----------------------------------------------------------------------
# Registry entries
# ----------------------------------------------------------------------


def build_tools() -> list[StaticBusinessTool]:
    return [
        _tool(
            name="product.catalog_lookup",
            capability="product-tech",
            description="Look up cloud product families and baseline sizing hints.",
            tags=["product", "catalog", "tech"],
            input_schema_hint={"user_query": "string"},
            output_schema_hint={"product_families": "string[]"},
            session_context_output_keys=["active_products"],
            cache_ttl_seconds=60,
            preview_builder=_product_catalog_builder,
        ),
        _tool(
            name="product.recommend_instance",
            capability="product-tech",
            description="Recommend baseline GPU instance sizing for deployment or training workloads.",
            tags=["product", "recommendation", "gpu", "tech"],
            input_schema_hint={
                "user_query": "string",
                "workload": "training|inference|general?",
                "model_family": "llm|multimodal|vision|general?",
                "budget_level": "cost_optimized|balanced|performance?",
            },
            output_schema_hint={
                "workload": "string",
                "model_family": "string",
                "budget_level": "string",
                "recommended_instance_family": "string",
                "recommended_instance_type": "string",
                "gpu_model": "string",
                "gpu_count": "integer",
                "vcpu": "integer",
                "memory_gb": "integer",
                "network_gbps": "integer",
                "estimated_monthly_cost_cny": "number",
                "rationale": "string[]",
                "alternatives": "object[]",
            },
            session_context_bindings={
                "workload": ["attributes.recommended_workload"],
                "model_family": ["attributes.recommended_model_family"],
                "budget_level": ["attributes.recommended_budget_level"],
            },
            session_context_output_keys=[
                "active_products",
                "attributes.recommended_workload",
                "attributes.recommended_model_family",
                "attributes.recommended_budget_level",
                "attributes.recommended_instance_family",
                "attributes.recommended_instance_type",
                "attributes.recommended_gpu_model",
                "attributes.recommended_gpu_count",
                "attributes.recommended_vcpu",
                "attributes.recommended_memory_gb",
                "attributes.recommended_network_gbps",
                "attributes.recommended_instance_summary",
            ],
            cache_ttl_seconds=90,
            preview_builder=_product_recommend_instance_preview,
            execute_builder=_product_recommend_instance_execute,
        ),
        _tool(
            name="support.playbook_search",
            capability="product-tech",
            description="Return troubleshooting or deployment SOP candidates.",
            tags=["support", "playbook", "knowledge"],
            input_schema_hint={"user_query": "string", "scene": "string?"},
            output_schema_hint={"playbooks": "object[]"},
            session_context_output_keys=["attributes.playbook_titles"],
            cache_ttl_seconds=60,
            preview_builder=_support_playbook_builder,
        ),
        _tool(
            name="support.query_service_status",
            capability="product-tech",
            description="Check baseline service or instance health status for technical-support flows.",
            tags=["support", "status", "incident", "tech"],
            input_schema_hint={
                "user_query": "string",
                "instance_id": "string?",
                "service": "string?",
                "region": "string?",
            },
            output_schema_hint={
                "instance_id": "string?",
                "service_name": "string",
                "region": "string",
                "status": "healthy|degraded|outage",
                "severity": "info|sev2|sev1",
                "incident_code": "string?",
                "impact_scope": "string",
                "symptoms": "string[]",
                "summary": "string",
                "recommended_action": "string",
                "checked_at": "string",
                "escalation_recommended": "boolean",
            },
            session_context_bindings={
                "instance_id": [
                    "attributes.instance_id",
                    "attributes.primary_instance_id",
                    "attributes.service_affected_instance_id",
                ],
                "service": [
                    "attributes.instance_product",
                    "attributes.service_name",
                ],
                "region": ["attributes.service_region"],
            },
            session_context_output_keys=[
                "active_products",
                "attributes.service_status",
                "attributes.service_severity",
                "attributes.service_incident_code",
                "attributes.service_status_summary",
                "attributes.service_recommended_action",
                "attributes.service_region",
                "attributes.service_name",
                "attributes.service_health_checked_at",
                "attributes.service_affected_instance_id",
                "attributes.service_escalation_recommended",
            ],
            cache_ttl_seconds=15,
            preview_builder=_support_query_service_status_preview,
            execute_builder=_support_query_service_status_execute,
        ),
        _tool(
            name="support.handoff_brief",
            capability="customer-service",
            description="Prepare a structured human-operator handoff brief for escalations.",
            tags=["support", "handoff", "human"],
            input_schema_hint={
                "user_query": "string",
                "scene": "customer_service|billing|technical_support|icp|marketing|research?",
                "urgency": "low|medium|high?",
                "reason": "string?",
                "conversation_summary": "string?",
                "related_resources": "string[]?",
                "open_ticket_id": "string?",
                "service_status": "string?",
                "incident_code": "string?",
                "status_summary": "string?",
                "recommended_action": "string?",
            },
            output_schema_hint={
                "queue": "string",
                "severity": "string",
                "reason": "string",
                "summary": "string",
                "conversation_summary": "string?",
                "related_resources": "string[]",
                "open_ticket_id": "string?",
                "service_status": "string?",
                "incident_code": "string?",
                "status_summary": "string?",
                "recommended_action": "string?",
                "operator_notes": "string[]",
            },
            session_context_bindings={
                "conversation_summary": ["history_summary"],
                "related_resources": ["active_products"],
                "open_ticket_id": ["open_ticket_id"],
                "service_status": ["attributes.service_status"],
                "incident_code": ["attributes.service_incident_code"],
                "status_summary": ["attributes.service_status_summary"],
                "recommended_action": ["attributes.service_recommended_action"],
            },
            session_context_output_keys=[
                "attributes.human_handoff_queue",
                "attributes.human_handoff_severity",
                "attributes.human_handoff_summary",
                "attributes.human_handoff_reason",
                "attributes.human_handoff_related_resources",
                "attributes.human_handoff_existing_ticket_no",
                "attributes.human_handoff_service_status",
                "attributes.human_handoff_incident_code",
                "attributes.human_handoff_recommended_action",
                "attributes.human_handoff_operator_notes",
            ],
            cache_ttl_seconds=30,
            preview_builder=_support_handoff_brief_builder,
        ),
    ]
