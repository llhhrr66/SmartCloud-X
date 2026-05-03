from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from business_tools.db import execute_write, query_all, query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import _normalize_string_list, _query_payload, _slugify_token, _with_result
from .._static_tool import StaticBusinessTool


def _ticket_create_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    scene = str(request.payload.get("scene") or request.payload.get("category") or "customer_service").strip() or "customer_service"
    category = str(request.payload.get("category") or scene or "general").strip() or "general"
    queue = str(request.payload.get("queue") or "").strip() or None
    service_status = str(request.payload.get("service_status") or "").strip() or None
    incident_code = str(request.payload.get("incident_code") or "").strip() or None
    status_summary = str(request.payload.get("status_summary") or "").strip() or None
    recommended_action = str(request.payload.get("recommended_action") or "").strip() or None
    related_resources = _normalize_string_list(request.payload.get("related_resources"))
    operator_notes = _normalize_string_list(request.payload.get("operator_notes"))
    priority = str(request.payload.get("priority") or "").strip().lower() or "medium"
    if priority not in {"low", "medium", "high"}:
        priority = "high" if service_status in {"degraded", "outage"} else "medium"

    subject = str(request.payload.get("subject") or "").strip()
    if not subject:
        resource_label = related_resources[0] if related_resources else None
        if resource_label and incident_code:
            subject = f"{resource_label} 异常工单 {incident_code}"
        elif resource_label and service_status:
            subject = f"{resource_label} {service_status} 工单"
        elif status_summary:
            subject = status_summary
        else:
            subject = _query_payload(request) or "待补充工单主题"

    content_lines: list[str] = []
    raw_content = str(request.payload.get("content") or "").strip()
    if raw_content:
        content_lines.append(raw_content)
    elif status_summary:
        content_lines.append(status_summary)
    else:
        content_lines.append(_query_payload(request) or "待补充工单内容")
    if incident_code:
        content_lines.append(f"关联事件：{incident_code}")
    if queue:
        content_lines.append(f"建议队列：{queue}")
    if related_resources:
        content_lines.append(f"关联资源：{', '.join(related_resources)}")
    if recommended_action:
        content_lines.append(f"建议动作：{recommended_action}")
    if operator_notes:
        content_lines.append(f"值守提示：{'；'.join(operator_notes)}")

    # On execute, try to write to DB
    if request.operation == "execute":
        user_id = request.context.user_id
        tenant_id = request.context.tenant_id
        ticket_no = f"TK{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        instance_id = related_resources[0] if related_resources else None
        region = request.payload.get("region", "")

        affected = execute_write(
            "INSERT INTO support_tickets "
            "(ticket_no, user_id, tenant_id, subject, scene, severity, status, instance_id, region, "
            "incident_code, description, created_at, updated_at) "
            "VALUES (:tno, :uid, :tid, :subj, :scene, :sev, 'open', :iid, :region, "
            ":icode, :descr, NOW(), NOW())",
            {
                "tno": ticket_no,
                "uid": user_id,
                "tid": tenant_id,
                "subj": subject,
                "scene": scene,
                "sev": priority,
                "iid": instance_id,
                "region": region,
                "icode": incident_code,
                "descr": "\n".join(content_lines),
            },
        )
        if affected > 0:
            return _with_result(
                "已创建工单。",
                {
                    "ticket_no": ticket_no,
                    "status": "open",
                    "sla_minutes": 0,
                    "subject": subject,
                    "content": "\n".join(content_lines),
                    "priority": priority,
                    "category": category,
                    "scene": scene,
                    "queue": queue,
                    "incident_code": incident_code,
                    "service_status": service_status,
                    "related_resources": related_resources,
                },
                "db://support-tickets/" + ticket_no,
            )

    return _with_result(
        "已生成工单创建结果。",
        {
            "ticket_no": f"tk_{_slugify_token(category, fallback='general')}_001",
            "status": "open" if request.operation == "execute" else "draft",
            "sla_minutes": 30,
            "subject": subject,
            "content": "\n".join(content_lines),
            "priority": priority,
            "category": category,
            "scene": scene,
            "queue": queue,
            "incident_code": incident_code,
            "service_status": service_status,
            "related_resources": related_resources,
        },
        "baseline://ticket-create",
    )


def _ticket_reply_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    ticket_no = request.payload.get("ticket_no", "tk_pending")
    content = str(request.payload.get("content") or "").strip()

    if request.operation == "execute" and content:
        user_id = request.context.user_id

        reply_id = f"RPY{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        affected = execute_write(
            "INSERT INTO support_ticket_replies (reply_id, ticket_no, user_id, role, content, created_at) "
            "VALUES (:rid, :tno, :uid, 'user', :content, NOW())",
            {"rid": reply_id, "tno": ticket_no, "uid": user_id, "content": content},
        )
        if affected > 0:
            return _with_result(
                "已回复工单。",
                {"ticket_no": ticket_no, "reply_id": reply_id, "status": "sent"},
                "db://support-ticket-replies/" + reply_id,
            )

    return _with_result(
        "已生成工单回复结果。",
        {
            "ticket_no": ticket_no,
            "reply_no": f"reply_{ticket_no}_001",
            "status": "sent" if request.operation == "execute" else "draft",
        },
        "baseline://ticket-reply",
    )


def _ticket_query_ticket_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    ticket_no = request.payload.get("ticket_no", "tk_pending")
    subject = request.payload.get("subject") or "待确认工单主题"
    return _with_result(
        "已整理工单状态查询草稿。",
        {
            "ticket_no": ticket_no,
            "status": "processing",
            "subject": subject,
            "latest_action": "工单已进入服务台队列，正式查询后返回最新跟进。",
            "reply_no": request.payload.get("reply_no"),
            "preview_notice": "正式执行会返回工单状态和最近处理进展。",
        },
        "baseline://ticket-query-status",
    )


def _ticket_query_ticket_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    ticket_no = request.payload.get("ticket_no", "tk_pending")
    user_id = request.context.user_id

    row = query_one(
        "SELECT * FROM support_tickets WHERE ticket_no = :tno",
        {"tno": ticket_no},
    )
    if row:
        result: dict[str, Any] = {
            "ticket_no": row["ticket_no"],
            "status": row["status"],
            "subject": row.get("subject", ""),
            "scene": row.get("scene"),
            "severity": row.get("severity"),
            "instance_id": row.get("instance_id"),
            "region": row.get("region"),
            "incident_code": row.get("incident_code"),
            "assigned_team": row.get("assigned_team"),
            "created_at": str(row["created_at"]) if row.get("created_at") else None,
            "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
            "resolved_at": str(row["resolved_at"]) if row.get("resolved_at") else None,
        }

        if row.get("resolution"):
            result["resolution"] = row["resolution"]
            result["latest_action"] = row["resolution"]
        else:
            result["latest_action"] = "技术同学已接单，正在排查实例与网络侧异常。"

        # Get latest reply
        reply_row = query_one(
            "SELECT reply_id, role, content, created_at FROM support_ticket_replies "
            "WHERE ticket_no = :tno ORDER BY created_at DESC LIMIT 1",
            {"tno": ticket_no},
        )
        if reply_row:
            result["latest_reply"] = {
                "reply_id": reply_row["reply_id"],
                "role": reply_row["role"],
                "content": reply_row["content"],
                "created_at": str(reply_row["created_at"]),
            }

        return _with_result("已返回工单状态数据。", result, "db://support-tickets/" + ticket_no)

    # Fallback: list user's recent tickets
    if ticket_no == "tk_pending" and user_id:
        rows = query_all(
            "SELECT ticket_no, status, subject, severity, scene, created_at FROM support_tickets "
            "WHERE user_id = :uid ORDER BY created_at DESC LIMIT 5",
            {"uid": user_id},
        )
        if rows:
            tickets = [
                {
                    "ticket_no": r["ticket_no"],
                    "status": r["status"],
                    "subject": r.get("subject"),
                    "severity": r.get("severity"),
                    "scene": r.get("scene"),
                    "created_at": str(r["created_at"]) if r.get("created_at") else None,
                }
                for r in rows
            ]
            return _with_result("已返回近期工单列表。", {"tickets": tickets}, "db://support-tickets/list")

    subject = request.payload.get("subject") or "待确认工单主题"
    return _with_result(
        "已返回工单状态基线数据。",
        {
            "ticket_no": ticket_no,
            "status": "processing",
            "subject": subject,
            "latest_action": "技术同学已接单，正在排查实例与网络侧异常。",
            "reply_no": request.payload.get("reply_no"),
        },
        "baseline://ticket-query-status",
    )


def build_tools() -> list[StaticBusinessTool]:
    return [
        _tool(
            name="ticket.create",
            capability="finance-order",
            description="Create a support ticket with optional handoff and incident context.",
            tags=["ticket", "support", "write"],
            input_schema_hint={
                "subject": "string",
                "content": "string",
                "priority": "string?",
                "category": "string?",
                "scene": "string?",
                "queue": "string?",
                "incident_code": "string?",
                "service_status": "string?",
                "status_summary": "string?",
                "recommended_action": "string?",
                "related_resources": "string[]?",
                "operator_notes": "string[]?",
                "attachments": "string[]?",
            },
            input_field_hints={
                "subject": "需要确认工单主题。",
                "content": "需要补充工单描述或排障内容。",
            },
            output_schema_hint={
                "ticket_no": "string",
                "status": "string",
                "sla_minutes": "number",
                "subject": "string",
                "content": "string",
                "priority": "string",
                "category": "string",
                "scene": "string",
                "queue": "string?",
                "incident_code": "string?",
                "service_status": "string?",
                "related_resources": "string[]",
            },
            session_context_bindings={
                "subject": [
                    "attributes.human_handoff_summary",
                    "attributes.service_status_summary",
                    "attributes.ticket_subject",
                ],
                "content": [
                    "attributes.human_handoff_summary",
                    "history_summary",
                    "attributes.service_status_summary",
                ],
                "priority": ["attributes.human_handoff_severity", "attributes.ticket_priority"],
                "queue": ["attributes.human_handoff_queue", "attributes.ticket_queue"],
                "incident_code": ["attributes.human_handoff_incident_code", "attributes.service_incident_code"],
                "service_status": ["attributes.human_handoff_service_status", "attributes.service_status"],
                "status_summary": ["attributes.service_status_summary"],
                "recommended_action": [
                    "attributes.human_handoff_recommended_action",
                    "attributes.service_recommended_action",
                ],
                "related_resources": [
                    "attributes.human_handoff_related_resources",
                    "active_products",
                ],
                "operator_notes": ["attributes.human_handoff_operator_notes"],
            },
            session_context_output_keys=[
                "open_ticket_id",
                "attributes.ticket_status",
                "attributes.ticket_subject",
                "attributes.ticket_priority",
                "attributes.ticket_category",
                "attributes.ticket_queue",
                "attributes.ticket_incident_code",
                "attributes.ticket_related_resources",
            ],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:ticket.write"],
            ),
            operation_required_fields={"execute": ["subject", "content"]},
            timeout_ms=10000,
            idempotent=True,
            preview_builder=_ticket_create_builder,
            execute_builder=_ticket_create_builder,
        ),
        _tool(
            name="ticket.reply",
            capability="finance-order",
            description="Reply to an existing support ticket.",
            tags=["ticket", "reply", "write"],
            input_schema_hint={"ticket_no": "string", "content": "string", "attachments": "string[]?"},
            input_field_hints={
                "ticket_no": "需要确认要回复的工单编号。",
                "content": "需要补充回复内容。",
            },
            output_schema_hint={"reply_no": "string", "status": "string"},
            session_context_bindings={"ticket_no": ["open_ticket_id"]},
            session_context_output_keys=[
                "open_ticket_id",
                "attributes.last_ticket_reply_no",
                "attributes.ticket_status",
            ],
            prerequisite_tool_names=["ticket.create"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:ticket.write"],
            ),
            operation_required_fields={"execute": ["ticket_no", "content"]},
            timeout_ms=10000,
            idempotent=True,
            preview_builder=_ticket_reply_builder,
            execute_builder=_ticket_reply_builder,
        ),
        _tool(
            name="ticket.query_ticket",
            capability="finance-order",
            description="Query support ticket status and the latest progress. If ticket_no is provided, query that specific ticket; otherwise list all recent tickets for the user.",
            tags=["ticket", "query", "status"],
            input_schema_hint={"ticket_no": "string", "subject": "string?", "reply_no": "string?"},
            input_field_hints={"ticket_no": "需要确认工单编号。"},
            output_schema_hint={
                "ticket_no": "string",
                "status": "string",
                "subject": "string",
                "latest_action": "string",
                "reply_no": "string?",
            },
            session_context_bindings={
                "ticket_no": ["open_ticket_id"],
                "subject": ["attributes.ticket_subject"],
                "reply_no": ["attributes.last_ticket_reply_no"],
            },
            session_context_output_keys=[
                "open_ticket_id",
                "attributes.ticket_status",
                "attributes.ticket_subject",
                "attributes.last_ticket_reply_no",
                "attributes.ticket_latest_action",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:ticket.read"],
            ),
            operation_required_fields={"execute": []},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=45,
            preview_builder=_ticket_query_ticket_preview,
            execute_builder=_ticket_query_ticket_execute,
        ),
    ]
