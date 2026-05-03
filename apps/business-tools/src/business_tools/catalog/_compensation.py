from __future__ import annotations

from typing import Any

from business_tools.interfaces import (
    ToolCompensationAction,
    ToolDefinition,
    ToolInvocationRequest,
)


def _build_compensation(
    definition: ToolDefinition,
    request: ToolInvocationRequest,
    payload: dict[str, Any],
) -> ToolCompensationAction | None:
    if request.operation != "execute" or definition.mode != "write":
        return None

    if definition.name == "billing.create_invoice":
        return ToolCompensationAction(
            action_name="cancel_invoice_request",
            description="撤销尚未生效的开票申请草稿或提交记录。",
            payload={
                "invoice_no": payload.get("invoice_no"),
                "statement_nos": request.payload.get("statement_nos", []),
            },
        )
    if definition.name == "order.create_refund":
        return ToolCompensationAction(
            action_name="cancel_refund_request",
            description="撤销退款申请并恢复后续人工审核流程。",
            payload={
                "refund_no": payload.get("refund_no"),
                "order_no": request.payload.get("order_no"),
            },
        )
    if definition.name == "ticket.create":
        return ToolCompensationAction(
            action_name="close_ticket",
            description="关闭当前创建的工单并写入撤销说明。",
            payload={
                "ticket_no": payload.get("ticket_no"),
                "subject": payload.get("subject"),
            },
        )
    if definition.name == "ticket.reply":
        return ToolCompensationAction(
            action_name="retract_ticket_reply",
            description="撤回最近一次工单回复。",
            payload={
                "ticket_no": payload.get("ticket_no"),
                "reply_no": payload.get("reply_no"),
            },
        )
    if definition.name == "icp.submit_application":
        return ToolCompensationAction(
            action_name="withdraw_icp_application",
            description="撤回备案申请草稿或待审核记录。",
            payload={
                "application_no": payload.get("application_no"),
                "domain": request.payload.get("domain"),
            },
        )
    if definition.name == "marketing.generate_promotion_link":
        return ToolCompensationAction(
            action_name="deactivate_promotion_link",
            description="停用刚创建的推广链接并保留追踪信息。",
            payload={
                "promotion_link_id": payload.get("promotion_link_id"),
                "short_url": payload.get("short_url"),
            },
        )
    if definition.name == "marketing.generate_poster":
        return ToolCompensationAction(
            action_name="delete_poster_asset",
            description="删除刚生成的海报资产并撤回预览链接。",
            payload={
                "poster_asset_id": payload.get("poster_asset_id"),
                "preview_url": payload.get("preview_url"),
                "download_path": payload.get("download_path"),
            },
        )
    return None
