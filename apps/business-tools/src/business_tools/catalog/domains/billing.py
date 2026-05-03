from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from business_tools.db import execute_write, query_all, query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import _current_billing_cycle, _with_result
from .._static_tool import StaticBusinessTool


# ----------------------------------------------------------------------
# Billing query / instance cost
# ----------------------------------------------------------------------


def _billing_query_statement_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    range_name = str(request.payload.get("range", "this_month"))
    billing_cycle = _current_billing_cycle(range_name)
    account_id = request.context.account_id or request.payload.get("account_id")

    # Try DB to get real statement info for preview
    row = query_one(
        "SELECT billing_cycle, statement_no FROM billing_statements "
        "WHERE billing_cycle = :cycle AND account_id = :aid LIMIT 1",
        {"cycle": billing_cycle, "aid": account_id},
    )
    if row:
        return _with_result(
            "已准备账单查询计划。",
            {
                "account_id": account_id,
                "range": range_name,
                "billing_cycle": row["billing_cycle"],
                "statement_nos": [row["statement_no"]],
                "preview_notice": "正式执行会返回账单汇总与明细数据。",
            },
            "db://billing-statements/" + row["statement_no"],
        )

    return _with_result(
        "已准备账单查询计划。",
        {
            "account_id": account_id,
            "range": range_name,
            "billing_cycle": billing_cycle,
            "statement_nos": [f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"],
            "preview_notice": "正式执行会返回账单汇总与明细基线数据。",
        },
        "baseline://billing-query-statement",
    )


def _billing_query_statement_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    range_name = str(request.payload.get("range", "this_month"))
    billing_cycle = _current_billing_cycle(range_name)
    account_id = request.context.account_id or request.payload.get("account_id")

    row = query_one(
        "SELECT * FROM billing_statements WHERE billing_cycle = :cycle AND account_id = :aid LIMIT 1",
        {"cycle": billing_cycle, "aid": account_id},
    )
    if row:
        items = json.loads(row.get("items_json") or "[]")
        top_instances = json.loads(row.get("top_instances_json") or "[]")
        return _with_result(
            "已返回账单汇总数据。",
            {
                "billing_cycle": row["billing_cycle"],
                "range": row.get("range_name") or range_name,
                "total_amount": float(row["total_amount"]),
                "currency": row.get("currency", "CNY"),
                "statement_nos": [row["statement_no"]],
                "items": items,
                "top_instances": top_instances,
            },
            "db://billing-statements/" + row["statement_no"],
        )

    # fallback baseline — query DB for aggregate amounts when no specific statement match
    stmt_rows = query_all(
        "SELECT billing_cycle, total_amount, statement_no FROM billing_statements "
        "WHERE billing_cycle = :cycle ORDER BY total_amount DESC LIMIT 5",
        {"cycle": billing_cycle},
    )
    if stmt_rows:
        total_amount = round(sum(float(r["total_amount"]) for r in stmt_rows), 2)
        statement_nos = [r["statement_no"] for r in stmt_rows]
        # Build items from top statement's items_json
        top_row = query_one(
            "SELECT items_json FROM billing_statements WHERE statement_no = :sno LIMIT 1",
            {"sno": statement_nos[0]},
        )
        items = []
        if top_row and top_row.get("items_json"):
            try:
                items = json.loads(top_row["items_json"])
            except (json.JSONDecodeError, TypeError):
                items = []
        if not items:
            items = [
                {"product": "云服务", "amount": round(total_amount * 0.60, 2)},
                {"product": "对象存储", "amount": round(total_amount * 0.22, 2)},
                {"product": "公网带宽", "amount": round(total_amount * 0.18, 2)},
            ]
        # Build top_instances from billing_orders for this cycle
        order_rows = query_all(
            "SELECT instance_name, paid_amount FROM billing_orders "
            "WHERE status = 'paid' ORDER BY paid_amount DESC LIMIT 3",
            {},
        )
        top_instances = [
            {"instance_id": r["instance_name"], "amount": float(r["paid_amount"])}
            for r in order_rows
        ] if order_rows else []
        return _with_result(
            "已返回账单汇总数据（按账单周期聚合）。",
            {
                "billing_cycle": billing_cycle,
                "range": range_name,
                "total_amount": total_amount,
                "currency": "CNY",
                "statement_nos": statement_nos,
                "items": items,
                "top_instances": top_instances,
            },
            "db://billing-statements/cycle/" + billing_cycle,
        )

    return _with_result(
        "已返回账单汇总基线数据。",
        {
            "billing_cycle": billing_cycle,
            "range": range_name,
            "total_amount": 0,
            "currency": "CNY",
            "statement_nos": [],
            "items": [],
            "top_instances": [],
        },
        "baseline://billing-query-statement",
    )


def _billing_query_instance_cost_profile(request: ToolInvocationRequest) -> dict[str, Any]:
    instance_id = str(request.payload.get("instance_id") or "inst_pending").strip()
    range_name = str(request.payload.get("range", "this_month"))
    billing_cycle = str(request.payload.get("billing_cycle") or _current_billing_cycle(range_name))

    row = query_one(
        "SELECT * FROM billing_orders WHERE instance_name = :iid AND status = 'paid' LIMIT 1",
        {"iid": instance_id},
    )
    if row:
        paid = float(row["paid_amount"])
        compute_amount = round(paid * 0.82, 2)
        storage_amount = round(paid * 0.12, 2)
        network_amount = round(paid - compute_amount - storage_amount, 2)
        statement_no = f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"
        return {
            "instance_id": instance_id,
            "instance_name": row.get("instance_name", instance_id),
            "product": row.get("product_name", ""),
            "billing_cycle": billing_cycle,
            "range": range_name,
            "statement_no": statement_no,
            "currency": row.get("currency", "CNY"),
            "total_amount": paid,
            "daily_average_amount": round(paid / 30, 2),
            "compute_amount": compute_amount,
            "storage_amount": storage_amount,
            "network_amount": network_amount,
            "region": row.get("region", ""),
        }

    # fallback baseline — try broader DB lookup by instance_id pattern
    broader = query_all(
        "SELECT instance_name, product_name, paid_amount, currency, region FROM billing_orders "
        "WHERE status = 'paid' ORDER BY created_at DESC LIMIT 5",
        {},
    )
    if broader:
        match = next((r for r in broader if instance_id in (r.get("instance_name") or "")), broader[0])
        paid = float(match["paid_amount"])
        compute_amount = round(paid * 0.82, 2)
        storage_amount = round(paid * 0.12, 2)
        network_amount = round(paid - compute_amount - storage_amount, 2)
        statement_no = f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"
        return {
            "instance_id": instance_id,
            "instance_name": match.get("instance_name", instance_id),
            "product": match.get("product_name", ""),
            "billing_cycle": billing_cycle,
            "range": range_name,
            "statement_no": statement_no,
            "currency": match.get("currency", "CNY"),
            "total_amount": paid,
            "daily_average_amount": round(paid / 30, 2),
            "compute_amount": compute_amount,
            "storage_amount": storage_amount,
            "network_amount": network_amount,
            "region": match.get("region", ""),
        }

    # minimal baseline — no DB data available
    statement_no = f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"
    return {
        "instance_id": instance_id,
        "instance_name": instance_id,
        "product": "",
        "billing_cycle": billing_cycle,
        "range": range_name,
        "statement_no": statement_no,
        "currency": "CNY",
        "total_amount": 0,
        "daily_average_amount": 0,
        "compute_amount": 0,
        "storage_amount": 0,
        "network_amount": 0,
        "region": "",
    }


def _billing_query_instance_cost_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    profile = _billing_query_instance_cost_profile(request)
    return _with_result(
        "已整理实例费用查询草稿。",
        {**profile, "preview_notice": "正式执行会返回该实例的费用拆分和账期基线数据。"},
        "baseline://billing-query-instance-cost",
    )


def _billing_query_instance_cost_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    profile = _billing_query_instance_cost_profile(request)
    citation = "baseline://billing-query-instance-cost"
    row = query_one(
        "SELECT order_no FROM billing_orders WHERE instance_name = :iid AND status = 'paid' LIMIT 1",
        {"iid": str(request.payload.get("instance_id") or "inst_pending").strip()},
    )
    if row:
        citation = "db://billing-orders/" + row["order_no"]
    return _with_result("已返回实例费用数据。" if row else "已返回实例费用基线数据。", profile, citation)


# ----------------------------------------------------------------------
# Order / refund
# ----------------------------------------------------------------------


def _order_query_order_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_no = request.payload.get("order_no") or request.payload.get("order_id") or ""
    refund_no = request.payload.get("refund_no") or request.payload.get("refund_id")

    # Try DB to get real order data for preview
    if order_no:
        row = query_one(
            "SELECT order_no, status, paid_amount, currency FROM billing_orders WHERE order_no = :ono LIMIT 1",
            {"ono": order_no},
        )
        if row:
            return _with_result(
                "已整理订单状态查询草稿。",
                {
                    "order_no": row["order_no"],
                    "refund_no": refund_no,
                    "order_status": row["status"],
                    "refund_status": "processing" if refund_no else "not_requested",
                    "invoice_status": "submitted",
                    "paid_amount": float(row["paid_amount"]),
                    "currency": row.get("currency", "CNY"),
                    "preview_notice": "正式执行会返回订单、退款与发票状态数据。",
                },
                "db://billing-orders/" + row["order_no"],
            )

    return _with_result(
        "已整理订单状态查询草稿。",
        {
            "order_no": order_no,
            "refund_no": refund_no,
            "order_status": "paid",
            "refund_status": "processing" if refund_no else "not_requested",
            "invoice_status": "submitted",
            "paid_amount": 0,
            "currency": "CNY",
            "preview_notice": "正式执行会返回订单、退款与发票状态基线数据。",
        },
        "baseline://orders-status",
    )


def _order_query_order_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_no = request.payload.get("order_no") or request.payload.get("order_id") or "ord_pending"
    refund_no_input = request.payload.get("refund_no") or request.payload.get("refund_id")
    user_id = request.context.user_id

    # Try to look up the order from DB
    row = query_one(
        "SELECT * FROM billing_orders WHERE order_no = :ono",
        {"ono": order_no},
    )
    if row:
        result: dict[str, Any] = {
            "order_no": row["order_no"],
            "order_status": row["status"],
            "product_name": row.get("product_name"),
            "instance_type": row.get("instance_type"),
            "instance_name": row.get("instance_name"),
            "paid_amount": float(row["paid_amount"]),
            "currency": row.get("currency", "CNY"),
            "created_at": str(row["created_at"]) if row.get("created_at") else None,
            "paid_at": str(row["paid_at"]) if row.get("paid_at") else None,
        }
        # Check refund status
        refund_row = query_one(
            "SELECT * FROM billing_refunds WHERE order_no = :ono LIMIT 1",
            {"ono": order_no},
        )
        if refund_row:
            result["refund_no"] = refund_row["refund_no"]
            result["refund_status"] = refund_row["status"]
            result["refund_amount"] = float(refund_row.get("requested_amount") or 0)
        else:
            result["refund_no"] = refund_no_input
            result["refund_status"] = "not_requested"
        # Check invoice status
        invoice_row = query_one(
            "SELECT invoice_no, status FROM billing_invoices WHERE user_id = :uid AND status != 'cancelled' LIMIT 1",
            {"uid": user_id},
        )
        if invoice_row:
            result["invoice_no"] = invoice_row["invoice_no"]
            result["invoice_status"] = invoice_row["status"]
        else:
            result["invoice_status"] = "not_requested"
        return _with_result("已返回订单状态数据。", result, "db://billing-orders/" + order_no)

    # Fallback: list recent orders for the user if no specific order_no match
    if order_no == "ord_pending" and user_id:
        rows = query_all(
            "SELECT order_no, status, product_name, paid_amount, currency, created_at FROM billing_orders WHERE user_id = :uid ORDER BY created_at DESC LIMIT 5",
            {"uid": user_id},
        )
        if rows:
            orders = [
                {
                    "order_no": r["order_no"],
                    "order_status": r["status"],
                    "product_name": r.get("product_name"),
                    "paid_amount": float(r["paid_amount"]),
                    "currency": r.get("currency", "CNY"),
                    "created_at": str(r["created_at"]) if r.get("created_at") else None,
                }
                for r in rows
            ]
            return _with_result("已返回近期订单列表。", {"orders": orders}, "db://billing-orders/list")

    # DB miss fallback
    return _with_result(
        "已返回订单状态基线数据。",
        {
            "order_no": order_no,
            "order_status": "refunding" if refund_no_input else "paid",
            "refund_no": refund_no_input,
            "refund_status": "processing" if refund_no_input else "not_requested",
            "invoice_status": "not_requested",
            "paid_amount": 0,
            "currency": "CNY",
        },
        "baseline://orders-status",
    )


def _order_create_refund_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    return _with_result(
        "已整理退款申请草稿。",
        {
            "order_no": request.payload.get("order_no", "order_pending"),
            "reason": request.payload.get("reason", "待补充"),
            "amount": request.payload.get("amount", 0),
            "requires_confirmation": True,
        },
        "baseline://order-create-refund",
    )


def _order_create_refund_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_no = request.payload.get("order_no", "order_pending")
    reason = request.payload.get("reason", "待补充")
    amount = request.payload.get("amount", 0)
    user_id = request.context.user_id
    tenant_id = request.context.tenant_id

    refund_no = f"REF{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    affected = execute_write(
        "INSERT INTO billing_refunds (refund_no, order_no, user_id, tenant_id, requested_amount, currency, reason, status, created_at) "
        "VALUES (:rno, :ono, :uid, :tid, :amt, 'CNY', :reason, 'requested', NOW())",
        {"rno": refund_no, "ono": order_no, "uid": user_id, "tid": tenant_id, "amt": amount, "reason": reason},
    )
    if affected > 0:
        return _with_result(
            "已创建退款申请。",
            {"order_no": order_no, "refund_no": refund_no, "status": "requested", "requested_amount": amount, "reason": reason},
            "db://billing-refunds/" + refund_no,
        )

    return _with_result(
        "已创建退款申请基线记录。",
        {
            "order_no": order_no,
            "refund_no": f"refund_{order_no}",
            "status": "requested",
            "requested_amount": amount,
            "reason": reason,
        },
        "baseline://order-create-refund",
    )


# ----------------------------------------------------------------------
# Invoice
# ----------------------------------------------------------------------


def _billing_create_invoice_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    statement_nos = request.payload.get("statement_nos") or []

    # Try DB to estimate amount from real statements
    estimated_amount = 0.0
    if statement_nos:
        placeholders = ", ".join(f":s{i}" for i in range(len(statement_nos)))
        params = {f"s{i}": s for i, s in enumerate(statement_nos)}
        stmt_rows = query_all(
            f"SELECT total_amount FROM billing_statements WHERE statement_no IN ({placeholders})",
            params,
        )
        if stmt_rows:
            estimated_amount = sum(float(r["total_amount"]) for r in stmt_rows)

    return _with_result(
        "已整理开票申请草稿。",
        {
            "statement_nos": statement_nos,
            "invoice_type": request.payload.get("invoice_type", "vat_special"),
            "title": request.payload.get("title", "待确认抬头"),
            "estimated_amount": round(estimated_amount, 2),
            "requires_confirmation": True,
        },
        "baseline://billing-create-invoice",
    )


def _billing_create_invoice_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    statement_nos = request.payload.get("statement_nos") or []
    invoice_type = request.payload.get("invoice_type", "vat_special")
    title = request.payload.get("title", "待确认抬头")
    tax_no = request.payload.get("tax_no")
    email = request.payload.get("email")
    user_id = request.context.user_id
    tenant_id = request.context.tenant_id

    # Calculate amount from statements
    amount = 0.0
    if statement_nos:
        placeholders = ", ".join(f":s{i}" for i in range(len(statement_nos)))
        params = {f"s{i}": s for i, s in enumerate(statement_nos)}
        stmt_rows = query_all(
            f"SELECT total_amount FROM billing_statements WHERE statement_no IN ({placeholders})",
            params,
        )
        if stmt_rows:
            amount = sum(float(r["total_amount"]) for r in stmt_rows)
    if amount == 0.0:
        amount = 0.0

    invoice_no = f"INV{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    affected = execute_write(
        "INSERT INTO billing_invoices (invoice_no, user_id, tenant_id, invoice_type, title, tax_no, amount, currency, statement_nos, status, email, created_at) "
        "VALUES (:ino, :uid, :tid, :itype, :title, :taxno, :amt, 'CNY', :snos, 'submitted', :email, NOW())",
        {
            "ino": invoice_no,
            "uid": user_id,
            "tid": tenant_id,
            "itype": invoice_type,
            "title": title,
            "taxno": tax_no,
            "amt": amount,
            "snos": json.dumps(statement_nos),
            "email": email,
        },
    )
    if affected > 0:
        return _with_result(
            "已创建开票申请。",
            {
                "invoice_no": invoice_no,
                "status": "submitted",
                "amount": amount,
                "title": title,
                "invoice_type": invoice_type,
                "statement_nos": statement_nos,
            },
            "db://billing-invoices/" + invoice_no,
        )

    return _with_result(
        "已创建开票申请基线记录。",
        {
            "invoice_no": invoice_no,
            "status": "submitted",
            "amount": amount,
            "title": title,
            "invoice_type": invoice_type,
            "statement_nos": statement_nos,
        },
        "baseline://billing-create-invoice",
    )


def _invoice_query_invoice_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    invoice_no = request.payload.get("invoice_no") or "inv_pending"
    statement_nos = request.payload.get("statement_nos") or []

    # Try DB for real invoice data in preview
    if invoice_no and invoice_no != "inv_pending":
        row = query_one(
            "SELECT invoice_no, status, amount, title, statement_nos FROM billing_invoices WHERE invoice_no = :ino LIMIT 1",
            {"ino": invoice_no},
        )
        if row:
            snos = json.loads(row.get("statement_nos") or "[]")
            return _with_result(
                "已整理发票状态查询草稿。",
                {
                    "invoice_no": row["invoice_no"],
                    "status": row["status"],
                    "amount": float(row["amount"]),
                    "title": row.get("title", ""),
                    "statement_nos": snos,
                    "preview_notice": "正式执行会返回发票申请状态数据。",
                },
                "db://billing-invoices/" + row["invoice_no"],
            )

    return _with_result(
        "已整理发票状态查询草稿。",
        {
            "invoice_no": invoice_no,
            "status": "",
            "amount": 0,
            "title": request.payload.get("title", ""),
            "statement_nos": statement_nos,
            "preview_notice": "正式执行会返回发票申请状态基线数据。",
        },
        "baseline://invoice-query-status",
    )


def _invoice_query_invoice_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    invoice_no = request.payload.get("invoice_no") or "inv_pending"

    row = query_one(
        "SELECT * FROM billing_invoices WHERE invoice_no = :ino",
        {"ino": invoice_no},
    )
    if row:
        snos = json.loads(row.get("statement_nos") or "[]")
        return _with_result(
            "已返回发票状态数据。",
            {
                "invoice_no": row["invoice_no"],
                "status": row["status"],
                "amount": float(row["amount"]),
                "title": row.get("title", ""),
                "invoice_type": row.get("invoice_type", ""),
                "tax_no": row.get("tax_no"),
                "statement_nos": snos,
                "email": row.get("email"),
                "created_at": str(row["created_at"]) if row.get("created_at") else None,
            },
            "db://billing-invoices/" + invoice_no,
        )

    # Fallback baseline
    statement_nos = request.payload.get("statement_nos") or []
    return _with_result(
        "已返回发票状态基线数据。",
        {
            "invoice_no": invoice_no,
            "status": "",
            "amount": 0,
            "title": request.payload.get("title", ""),
            "statement_nos": statement_nos,
        },
        "baseline://invoice-query-status",
    )


# ----------------------------------------------------------------------
# Registry entries
# ----------------------------------------------------------------------


def build_tools() -> list[StaticBusinessTool]:
    return [
        _tool(
            name="billing.query_statement",
            capability="finance-order",
            description="Prepare or execute monthly billing summary lookup.",
            tags=["billing", "finance"],
            input_schema_hint={"range": "this_month|last_month|last_3_months|custom", "start_date": "string?", "end_date": "string?"},
            input_field_hints={"range": "需要确认账单范围，例如本月、上月或最近三个月。"},
            output_schema_hint={
                "billing_cycle": "string",
                "total_amount": "number",
                "currency": "string",
                "statement_nos": "string[]",
                "items": "object[]",
                "top_instances": "object[]",
            },
            session_context_bindings={
                "range": ["attributes.billing_range"],
                "start_date": ["attributes.billing_start_date"],
                "end_date": ["attributes.billing_end_date"],
            },
            session_context_output_keys=[
                "active_products",
                "attributes.statement_nos",
                "attributes.statement_no",
                "attributes.billing_range",
                "attributes.billing_start_date",
                "attributes.billing_end_date",
                "attributes.billing_cycle",
                "attributes.currency",
                "attributes.latest_billing_total",
                "attributes.top_instances",
                "attributes.primary_instance_id",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                require_account_id=True,
                required_permissions=["user:billing.read"],
            ),
            operation_required_fields={"execute": ["range"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=30,
            preview_builder=_billing_query_statement_preview,
            execute_builder=_billing_query_statement_execute,
        ),
        _tool(
            name="billing.query_instance_cost",
            capability="finance-order",
            description="Query billing breakdown for a specific cloud instance.",
            tags=["billing", "instance", "cost", "query"],
            input_schema_hint={
                "instance_id": "string",
                "range": "this_month|last_month|last_3_months|custom?",
                "billing_cycle": "string?",
            },
            input_field_hints={"instance_id": "需要确认实例 ID，例如 gpu-cn-sh2-01 或 ecs-cn-sh2-07。"},
            output_schema_hint={
                "instance_id": "string",
                "instance_name": "string",
                "product": "string",
                "billing_cycle": "string",
                "range": "string",
                "statement_no": "string",
                "currency": "string",
                "total_amount": "number",
                "daily_average_amount": "number",
                "compute_amount": "number",
                "storage_amount": "number",
                "network_amount": "number",
                "region": "string",
            },
            session_context_bindings={
                "instance_id": ["attributes.instance_id", "attributes.primary_instance_id"],
                "range": ["attributes.instance_range", "attributes.billing_range"],
            },
            session_context_output_keys=[
                "active_products",
                "attributes.instance_id",
                "attributes.primary_instance_id",
                "attributes.instance_name",
                "attributes.instance_product",
                "attributes.instance_billing_cycle",
                "attributes.instance_statement_no",
                "attributes.instance_range",
                "attributes.last_instance_cost_total",
                "attributes.currency",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                require_account_id=True,
                required_permissions=["user:billing.read"],
            ),
            operation_required_fields={"preview": ["instance_id"], "execute": ["instance_id"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=30,
            preview_builder=_billing_query_instance_cost_preview,
            execute_builder=_billing_query_instance_cost_execute,
        ),
        _tool(
            name="order.query_order",
            capability="finance-order",
            description="Query order payment and refund status. If order_no is provided, query that specific order; otherwise list all recent orders for the user.",
            tags=["order", "refund", "query"],
            input_schema_hint={"order_no": "string", "refund_no": "string?"},
            input_field_hints={"order_no": "需要确认订单号。"},
            output_schema_hint={
                "order_no": "string",
                "order_status": "string",
                "refund_no": "string?",
                "refund_status": "string",
                "invoice_status": "string",
                "paid_amount": "number",
                "currency": "string",
            },
            session_context_bindings={
                "order_no": ["attributes.order_no", "attributes.refund_order_no"],
                "refund_no": ["attributes.refund_no"],
            },
            session_context_output_keys=[
                "attributes.order_no",
                "attributes.order_status",
                "attributes.refund_no",
                "attributes.refund_status",
                "attributes.invoice_status",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:order.read"],
            ),
            operation_required_fields={"execute": []},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=45,
            preview_builder=_order_query_order_preview,
            execute_builder=_order_query_order_execute,
        ),
        _tool(
            name="billing.create_invoice",
            capability="finance-order",
            description="Create an invoice request after explicit confirmation.",
            tags=["billing", "invoice", "write"],
            input_schema_hint={"statement_nos": "string[]", "invoice_type": "string", "title": "string", "tax_no": "string?", "email": "string?"},
            input_field_hints={
                "statement_nos": "需要确认要开票的账单编号，可先完成账单查询后选择。",
                "invoice_type": "需要确认发票类型，例如 vat_special 或 vat_normal。",
                "title": "需要确认发票抬头。",
            },
            output_schema_hint={"invoice_no": "string", "status": "string", "amount": "number"},
            session_context_bindings={
                "statement_nos": ["attributes.statement_nos", "attributes.statement_no"],
                "invoice_type": ["attributes.invoice_type"],
                "title": ["attributes.invoice_title"],
            },
            session_context_output_keys=[
                "attributes.invoice_no",
                "attributes.invoice_status",
                "attributes.last_invoice_amount",
            ],
            prerequisite_tool_names=["billing.query_statement"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:billing.read"],
                confirmation_required=True,
            ),
            operation_required_fields={"execute": ["statement_nos", "invoice_type", "title"]},
            timeout_ms=10000,
            idempotent=True,
            idempotency_window_seconds=86400,
            high_risk=True,
            preview_builder=_billing_create_invoice_preview,
            execute_builder=_billing_create_invoice_execute,
        ),
        _tool(
            name="invoice.query_invoice",
            capability="finance-order",
            description="Query invoice request status by invoice number.",
            tags=["billing", "invoice", "query"],
            input_schema_hint={
                "invoice_no": "string",
                "title": "string?",
                "statement_nos": "string[]?",
            },
            input_field_hints={"invoice_no": "需要确认发票申请单号。"},
            output_schema_hint={
                "invoice_no": "string",
                "status": "string",
                "amount": "number",
                "title": "string",
                "statement_nos": "string[]",
            },
            session_context_bindings={
                "invoice_no": ["attributes.invoice_no"],
                "title": ["attributes.invoice_title"],
                "statement_nos": ["attributes.statement_nos", "attributes.statement_no"],
            },
            session_context_output_keys=[
                "attributes.invoice_no",
                "attributes.invoice_status",
                "attributes.last_invoice_amount",
                "attributes.invoice_title",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:billing.read"],
            ),
            operation_required_fields={"execute": ["invoice_no"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=45,
            preview_builder=_invoice_query_invoice_preview,
            execute_builder=_invoice_query_invoice_execute,
        ),
        _tool(
            name="order.create_refund",
            capability="finance-order",
            description="Create a refund request after confirmation.",
            tags=["order", "refund", "write"],
            input_schema_hint={"order_no": "string", "reason": "string", "amount": "number", "attachments": "string[]?"},
            input_field_hints={
                "order_no": "需要确认订单号。",
                "reason": "需要确认退款原因。",
                "amount": "需要确认退款金额。",
            },
            output_schema_hint={"refund_no": "string", "status": "string", "requested_amount": "number"},
            session_context_bindings={
                "order_no": ["attributes.order_no"],
                "reason": ["attributes.refund_reason"],
                "amount": ["attributes.refund_amount"],
            },
            session_context_output_keys=[
                "attributes.refund_no",
                "attributes.refund_status",
                "attributes.refund_order_no",
            ],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:order.read"],
                confirmation_required=True,
            ),
            operation_required_fields={"execute": ["order_no", "reason", "amount"]},
            timeout_ms=10000,
            idempotent=True,
            idempotency_window_seconds=86400,
            high_risk=True,
            preview_builder=_order_create_refund_preview,
            execute_builder=_order_create_refund_execute,
        ),
    ]
