from __future__ import annotations

from typing import Any

from business_tools.db import query_all, query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import _current_billing_cycle, _query_payload, _with_result
from .._static_tool import StaticBusinessTool

# Re-use the modern product-catalog builder to keep the legacy alias aligned
# with the canonical implementation.
from .product import _product_catalog_builder


def _legacy_order_status_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_id = request.payload.get("order_id") or "order-preview"
    refund_id = request.payload.get("refund_id")

    # Try DB first
    if order_id and order_id != "order-preview":
        row = query_one(
            "SELECT order_no, status, product_name, paid_amount, currency FROM billing_orders "
            "WHERE order_no = :ono LIMIT 1",
            {"ono": order_id},
        )
        if row:
            result: dict[str, Any] = {
                "order_id": row["order_no"],
                "refund_id": refund_id,
                "status": row["status"],
                "product_name": row.get("product_name"),
                "paid_amount": float(row.get("paid_amount", 0)) if row.get("paid_amount") else None,
                "currency": row.get("currency", "CNY"),
                "invoice_status": "waiting-confirmation",
            }
            # Check for related refund
            if refund_id:
                refund_row = query_one(
                    "SELECT refund_no, status FROM billing_refunds WHERE refund_no = :rno LIMIT 1",
                    {"rno": refund_id},
                )
                if refund_row:
                    result["refund_id"] = refund_row["refund_no"]
                    result["refund_status"] = refund_row["status"]
            return _with_result("已返回订单/退款状态数据。", result, "db://billing-orders/" + order_id)

    # Fallback
    return _with_result(
        "已整理订单/退款状态查询结果。",
        {
            "order_id": order_id,
            "refund_id": refund_id,
            "status": "processing" if refund_id else "paid",
            "invoice_status": "waiting-confirmation",
        },
        "baseline://orders-status",
    )


def _legacy_billing_summary_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    month = str(request.payload.get("month", _current_billing_cycle("this_month")))
    return _with_result(
        "已准备历史账单汇总查询。",
        {
            "account_id": request.context.account_id or request.payload.get("account_id"),
            "month": month,
            "billing_cycle": month,
            "statement_nos": [f"stmt_{month.replace('-', '_')}_001"],
            "preview_notice": "正式执行会返回该月账单汇总基线数据。",
        },
        "baseline://billing-summary-legacy",
    )


def _legacy_billing_summary_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    month = str(request.payload.get("month", _current_billing_cycle("this_month")))
    account_id = request.context.account_id or request.payload.get("account_id")

    # Try DB first
    row = query_one(
        "SELECT billing_cycle, total_amount, currency, statement_no, items_json "
        "FROM billing_statements "
        "WHERE billing_cycle = :cycle AND account_id = :aid LIMIT 1",
        {"cycle": month, "aid": account_id},
    )
    if row:
        import json
        items = row.get("items_json")
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except (json.JSONDecodeError, TypeError):
                items = []
        return _with_result(
            "已返回历史账单汇总数据。",
            {
                "billing_cycle": row["billing_cycle"],
                "month": row["billing_cycle"],
                "total_amount": float(row["total_amount"]) if row.get("total_amount") else 0,
                "currency": row.get("currency", "CNY"),
                "statement_nos": [row["statement_no"]],
                "items": items or [],
            },
            "db://billing-statements/" + row["statement_no"],
        )

    # Fallback — try any statement for this cycle
    fallback_rows = query_all(
        "SELECT total_amount, currency, items_json FROM billing_statements "
        "WHERE billing_cycle = :cycle LIMIT 3",
        {"cycle": month},
    )
    if fallback_rows:
        total_amount = round(sum(float(r["total_amount"]) for r in fallback_rows), 2)
        items = []
        top_row = fallback_rows[0]
        if top_row.get("items_json"):
            try:
                items = json.loads(top_row["items_json"]) if isinstance(top_row["items_json"], str) else top_row["items_json"]
            except (json.JSONDecodeError, TypeError):
                items = []
        if not items:
            items = [
                {"product": "云服务", "amount": round(total_amount * 0.60, 2)},
                {"product": "对象存储", "amount": round(total_amount * 0.22, 2)},
                {"product": "公网带宽", "amount": round(total_amount * 0.18, 2)},
            ]
        return _with_result(
            "已返回历史账单汇总数据（按周期聚合）。",
            {
                "billing_cycle": month,
                "month": month,
                "total_amount": total_amount,
                "currency": fallback_rows[0].get("currency", "CNY"),
                "statement_nos": [f"stmt_{month.replace('-', '_')}_001"],
                "items": items,
            },
            "db://billing-statements/cycle/" + month,
        )

    # No data at all
    return _with_result(
        "已返回历史账单汇总基线数据。",
        {
            "billing_cycle": month,
            "month": month,
            "total_amount": 0,
            "currency": "CNY",
            "statement_nos": [],
            "items": [],
        },
        "baseline://billing-summary-legacy",
    )


def _legacy_icp_checklist_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    entity_type = request.payload.get("entity_type", "企业")
    subject_name = request.payload.get("subject_name")

    # Try to look up existing application for materials context
    row = None
    if subject_name:
        row = query_one(
            "SELECT materials_json, status FROM icp_applications "
            "WHERE subject_name = :sname LIMIT 1",
            {"sname": subject_name},
        )
    if row:
        import json
        db_materials = row.get("materials_json")
        if isinstance(db_materials, str):
            try:
                db_materials = json.loads(db_materials)
            except (json.JSONDecodeError, TypeError):
                db_materials = []
        if isinstance(db_materials, list) and db_materials:
            return _with_result(
                "已生成备案材料清单。",
                {
                    "entity_type": entity_type,
                    "province": request.payload.get("province", "待补充"),
                    "checklist": [str(m) for m in db_materials],
                },
                "db://icp-applications",
            )

    return _with_result(
        "已生成备案材料清单。",
        {
            "entity_type": entity_type,
            "province": request.payload.get("province", "待补充"),
            "checklist": ["营业执照", "负责人身份证", "域名证书", "网站负责人核验材料"],
        },
        "baseline://icp-checklist",
    )


def _legacy_icp_status_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    application_id = request.payload.get("application_id", "icp-preview")

    # Try DB first
    if application_id and application_id != "icp-preview":
        row = query_one(
            "SELECT application_no, status, domain, site_name, reject_reason FROM icp_applications "
            "WHERE application_no = :ano LIMIT 1",
            {"ano": application_id},
        )
        if row:
            action_map = {
                "submitted": "服务商正在审核主体资质",
                "verified": "服务商初审通过，等待管局审核",
                "approved": "备案已通过",
                "rejected": f"备案被驳回：{row.get('reject_reason', '原因未知')}",
            }
            return _with_result(
                "已返回备案状态数据。",
                {
                    "application_id": row["application_no"],
                    "status": row["status"],
                    "latest_action": action_map.get(row["status"], "状态更新中"),
                    "domain": row.get("domain"),
                    "site_name": row.get("site_name"),
                },
                "db://icp-applications/" + row["application_no"],
            )

    # Fallback
    return _with_result(
        "已生成备案状态查询结果。",
        {
            "application_id": application_id,
            "status": "materials-review",
            "latest_action": "等待补充网站负责人联系方式",
        },
        "baseline://icp-status",
    )


def _legacy_research_outline_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"
    return _with_result(
        "已生成研究提纲。",
        {
            "topic": topic,
            "outline": [
                "业务背景与目标",
                "候选方案对比",
                "成本与风险评估",
                "推荐路线与下一步行动",
            ],
        },
        "baseline://research-outline",
    )


def build_tools() -> list[StaticBusinessTool]:
    return [
        _tool(
            name="product_catalog.lookup",
            capability="product-tech",
            description="Legacy alias for product catalog lookup.",
            tags=["legacy", "product", "catalog"],
            input_schema_hint={"user_query": "string"},
            output_schema_hint={"product_families": "string[]"},
            cache_ttl_seconds=60,
            preview_builder=_product_catalog_builder,
        ),
        _tool(
            name="billing.summary",
            capability="finance-order",
            description="Legacy alias for billing query statement.",
            tags=["legacy", "billing"],
            input_schema_hint={"month": "string?", "account_id": "string?"},
            input_field_hints={"month": "需要确认账单月份，例如 2026-04。"},
            output_schema_hint={"billing_cycle": "string", "total_amount": "number", "statement_nos": "string[]"},
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                require_account_id=True,
                required_permissions=["user:billing.read"],
            ),
            operation_required_fields={"execute": ["month"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=30,
            preview_builder=_legacy_billing_summary_preview,
            execute_builder=_legacy_billing_summary_execute,
        ),
        _tool(
            name="orders.status_lookup",
            capability="finance-order",
            description="Legacy order/refund status lookup tool.",
            tags=["legacy", "orders", "refund"],
            input_schema_hint={"order_id": "string?", "refund_id": "string?"},
            output_schema_hint={"status": "string", "invoice_status": "string"},
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:order.read"],
            ),
            cache_ttl_seconds=60,
            preview_builder=_legacy_order_status_builder,
            execute_builder=_legacy_order_status_builder,
        ),
        _tool(
            name="icp.checklist",
            capability="icp-service",
            description="Legacy ICP checklist helper.",
            tags=["legacy", "icp", "checklist"],
            input_schema_hint={"entity_type": "string?", "province": "string?"},
            output_schema_hint={"checklist": "string[]"},
            cache_ttl_seconds=60,
            preview_builder=_legacy_icp_checklist_builder,
        ),
        _tool(
            name="icp.status_lookup",
            capability="icp-service",
            description="Legacy ICP status lookup helper.",
            tags=["legacy", "icp", "status"],
            input_schema_hint={"application_id": "string"},
            input_field_hints={"application_id": "需要确认备案申请号。"},
            output_schema_hint={"status": "string", "latest_action": "string"},
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:icp.read"],
            ),
            operation_required_fields={"execute": ["application_id"]},
            cache_ttl_seconds=60,
            preview_builder=_legacy_icp_status_builder,
            execute_builder=_legacy_icp_status_builder,
        ),
        _tool(
            name="research.outline",
            capability="deep-research",
            description="Legacy research outline helper.",
            tags=["legacy", "research", "outline"],
            input_schema_hint={"topic": "string"},
            input_field_hints={"topic": "需要确认调研主题。"},
            output_schema_hint={"outline": "string[]"},
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            cache_ttl_seconds=300,
            preview_builder=_legacy_research_outline_builder,
            execute_builder=_legacy_research_outline_builder,
        ),
    ]
