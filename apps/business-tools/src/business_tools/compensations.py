from __future__ import annotations

from typing import Callable

from business_tools.interfaces import CompensationExecutionRequest, CompensationExecutionResult


CompensationHandler = Callable[[CompensationExecutionRequest], CompensationExecutionResult]


def build_compensation_registry() -> dict[str, CompensationHandler]:
    return {
        "cancel_invoice_request": _cancel_invoice_request,
        "cancel_refund_request": _cancel_refund_request,
        "close_ticket": _close_ticket,
        "retract_ticket_reply": _retract_ticket_reply,
        "withdraw_icp_application": _withdraw_icp_application,
        "deactivate_promotion_link": _deactivate_promotion_link,
        "delete_poster_asset": _delete_poster_asset,
    }


def execute_compensation(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    handler = build_compensation_registry().get(request.action_name)
    if handler is None:
        return CompensationExecutionResult(
            action_name=request.action_name,
            status="missing-compensation",
            summary=f"未注册的补偿动作：{request.action_name}",
            success=False,
            code=4040001,
            message="compensation action not found",
            error_detail={"action_name": request.action_name},
            idempotency_key=request.context.idempotency_key,
        )
    return handler(request)


def _success(
    request: CompensationExecutionRequest,
    summary: str,
    result: dict[str, object],
) -> CompensationExecutionResult:
    return CompensationExecutionResult(
        action_name=request.action_name,
        status="completed",
        summary=summary,
        result=result,
        success=True,
        code=0,
        message="ok",
        provider="business-tools",
        idempotency_key=request.context.idempotency_key,
    )


def _validation_error(
    request: CompensationExecutionRequest,
    *required_fields: str,
) -> CompensationExecutionResult:
    missing_fields = [
        field
        for field in required_fields
        if request.payload.get(field) is None or request.payload.get(field) == ""
    ]
    if not missing_fields:
        raise ValueError("validation_error helper should only be used when required fields are missing")
    return CompensationExecutionResult(
        action_name=request.action_name,
        status="invalid-payload",
        summary=f"补偿动作 {request.action_name} 缺少必要字段。",
        success=False,
        code=4001001,
        message="invalid compensation payload",
        provider="business-tools",
        error_detail={"missing_fields": missing_fields},
        idempotency_key=request.context.idempotency_key,
    )


def _cancel_invoice_request(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("invoice_no"):
        return _validation_error(request, "invoice_no")
    return _success(
        request,
        "已撤销开票申请基线记录。",
        {
            "invoice_no": request.payload.get("invoice_no"),
            "statement_nos": request.payload.get("statement_nos", []),
            "status": "cancelled",
        },
    )


def _cancel_refund_request(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("refund_no"):
        return _validation_error(request, "refund_no")
    return _success(
        request,
        "已撤销退款申请基线记录。",
        {
            "refund_no": request.payload.get("refund_no"),
            "order_no": request.payload.get("order_no"),
            "status": "cancelled",
        },
    )


def _close_ticket(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("ticket_no"):
        return _validation_error(request, "ticket_no")
    return _success(
        request,
        "已关闭工单并写入撤销说明。",
        {
            "ticket_no": request.payload.get("ticket_no"),
            "subject": request.payload.get("subject"),
            "status": "closed",
        },
    )


def _retract_ticket_reply(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("ticket_no") or not request.payload.get("reply_no"):
        return _validation_error(request, "ticket_no", "reply_no")
    return _success(
        request,
        "已撤回最近一次工单回复。",
        {
            "ticket_no": request.payload.get("ticket_no"),
            "reply_no": request.payload.get("reply_no"),
            "status": "retracted",
        },
    )


def _withdraw_icp_application(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("application_no"):
        return _validation_error(request, "application_no")
    return _success(
        request,
        "已撤回备案申请基线记录。",
        {
            "application_no": request.payload.get("application_no"),
            "domain": request.payload.get("domain"),
            "status": "withdrawn",
        },
    )


def _deactivate_promotion_link(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("promotion_link_id"):
        return _validation_error(request, "promotion_link_id")
    return _success(
        request,
        "已停用推广链接基线记录。",
        {
            "promotion_link_id": request.payload.get("promotion_link_id"),
            "short_url": request.payload.get("short_url"),
            "status": "disabled",
        },
    )


def _delete_poster_asset(request: CompensationExecutionRequest) -> CompensationExecutionResult:
    if not request.payload.get("poster_asset_id"):
        return _validation_error(request, "poster_asset_id")
    return _success(
        request,
        "已删除海报资产基线记录。",
        {
            "poster_asset_id": request.payload.get("poster_asset_id"),
            "preview_url": request.payload.get("preview_url"),
            "download_path": request.payload.get("download_path"),
            "status": "deleted",
        },
    )
