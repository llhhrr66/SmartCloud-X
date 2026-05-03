from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from app.api.common import canonical_error, canonical_success, paginated_data
from app.services.auth import GatewaySubject, require_user_subject
from app.services.http import build_fallback_idempotency_key
from app.services.request_context import get_request_identity


router = APIRouter(prefix="/api/v1", tags=["business"])


async def _execute_business_tool(
    request: Request,
    subject: GatewaySubject,
    *,
    tool_name: str,
    payload: dict,
    operation: str = "execute",
) -> dict:
    services = request.app.state.gateway_services
    idempotency_key = request.headers.get(services.settings.idempotency_key_header) or build_fallback_idempotency_key(request)
    effective_account_id = subject.account_id or subject.subject_id
    return await services.http.request_json(
        "business-tools-service",
        "POST",
        f"/internal/v1/execute/{tool_name}",
        headers={
            "Content-Type": "application/json",
            services.settings.caller_service_header: "gateway-service",
            services.settings.request_id_header: request.state.request_id,
            services.settings.trace_id_header: request.state.trace_id,
            services.settings.tenant_id_header: subject.tenant_id or "default",
            services.settings.idempotency_key_header: idempotency_key,
        },
        content=(
            json.dumps(
                {
                    "subject": {
                        "user_id": subject.subject_id,
                        "tenant_id": subject.tenant_id,
                        "account_id": effective_account_id,
                        "roles": subject.roles,
                        "permissions": subject.permissions,
                    },
                    "operator": {"type": "system", "id": "gateway-service"},
                    "payload": payload,
                    "operation": operation,
                }
            ).encode("utf-8")
        ),
        request_identity=get_request_identity(request),
    )


def _tool_result_data(tool_payload: dict) -> dict:
    return (
        tool_payload.get("result")
        if isinstance(tool_payload.get("result"), dict)
        else tool_payload.get("data", {})
    )


def _billing_summary_payload(tool_payload: dict) -> dict:
    result = _tool_result_data(tool_payload)
    items = result.get("items") or []
    total_amount = float(result.get("total_amount") or 0)
    top_products = []
    for item in items:
        amount = float(item.get("amount") or 0)
        top_products.append(
            {
                "product_type": item.get("product") or "Unknown",
                "amount": f"{amount:.2f}",
                "ratio": round(amount / total_amount, 2) if total_amount else 0,
            }
        )
    top_instances = [
        {
            "instance_id": item.get("instance_id"),
            "instance_name": item.get("instance_id"),
            "amount": f"{float(item.get('amount') or 0):.2f}",
        }
        for item in result.get("top_instances") or []
    ]
    return {
        "total_amount": f"{total_amount:.2f}",
        "currency": result.get("currency") or "CNY",
        "range": result.get("range") or "this_month",
        "top_products": top_products,
        "top_instances": top_instances,
    }


def _cache_order_snapshot(request: Request, subject: GatewaySubject, result: dict) -> dict:
    return request.app.state.gateway_services.store.upsert_order_snapshot(
        subject.tenant_id,
        subject.subject_id,
        order_no=str(result.get("order_no") or ""),
        order_status=str(result.get("order_status") or "unknown"),
        paid_amount=f"{float(result.get('paid_amount') or 0):.2f}",
        currency=str(result.get("currency") or "CNY"),
        refund_no=result.get("refund_no"),
        refund_status=str(result.get("refund_status") or "not_requested"),
        invoice_status=str(result.get("invoice_status") or "unknown"),
        product_type=str(result.get("product_name") or result.get("product_type") or ""),
    )


def _cache_ticket_snapshot(request: Request, subject: GatewaySubject, result: dict) -> dict:
    return request.app.state.gateway_services.store.upsert_ticket_snapshot(
        subject.tenant_id,
        subject.subject_id,
        ticket_no=str(result.get("ticket_no") or ""),
        subject=str(result.get("subject") or "工单"),
        status=str(result.get("status") or "processing"),
        latest_action=result.get("latest_action"),
    )


def _cache_icp_application_snapshot(request: Request, subject: GatewaySubject, result: dict) -> dict:
    return request.app.state.gateway_services.store.upsert_icp_application_snapshot(
        subject.tenant_id,
        subject.subject_id,
        application_no=str(result.get("application_no") or ""),
        status=str(result.get("status") or "submitted"),
        current_step=str(result.get("current_step") or "provider_review"),
        latest_action=result.get("latest_action"),
        domain=result.get("domain"),
    )


@router.get("/billing/summary")
async def billing_summary(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await _execute_business_tool(
        request,
        subject,
        tool_name="billing.query_statement",
        payload={"range": request.query_params.get("range", "this_month")},
    )
    return canonical_success(_billing_summary_payload(payload), request.state.request_id)


@router.get("/billing/details")
async def billing_details(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await _execute_business_tool(
        request,
        subject,
        tool_name="billing.query_statement",
        payload={"range": request.query_params.get("range", "this_month")},
    )
    result = _tool_result_data(payload)
    items = [
        {
            "statement_no": (result.get("statement_nos") or [result.get("billing_cycle", "")])[0],
            "billing_cycle": result.get("billing_cycle") or "",
            "product_type": item.get("product") or item.get("product_type", ""),
            "instance_id": item.get("instance_id"),
            "instance_name": item.get("instance_id"),
            "amount": f"{float(item.get('amount') or 0):.2f}",
            "status": item.get("status") or result.get("status", "unknown"),
        }
        for item in result.get("top_instances") or result.get("items") or []
    ]
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    return canonical_success(paginated_data(items, page=page, page_size=page_size), request.state.request_id)


@router.get("/billing/invoices")
async def billing_invoices(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    store = request.app.state.gateway_services.store
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    return canonical_success(
        paginated_data(store.list_invoices(subject.tenant_id, subject.subject_id), page=page, page_size=page_size),
        request.state.request_id,
    )


@router.get("/orders")
async def list_orders(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    store = request.app.state.gateway_services.store
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    return canonical_success(
        paginated_data(store.list_orders(subject.tenant_id, subject.subject_id), page=page, page_size=page_size),
        request.state.request_id,
    )


@router.get("/orders/{order_no}")
async def get_order(request: Request, order_no: str, subject: GatewaySubject = Depends(require_user_subject)):
    detail = request.app.state.gateway_services.store.order_detail(subject.tenant_id, subject.subject_id, order_no)
    if detail is None:
        tool_result = await _execute_business_tool(
            request,
            subject,
            tool_name="order.query_order",
            payload={"order_no": order_no},
        )
        result = _tool_result_data(tool_result)
        if not result.get("order_no"):
            return canonical_error(
                request_id=request.state.request_id,
                status_code=404,
                code=4040001,
                message="order not found",
            )
        _cache_order_snapshot(request, subject, result)
        detail = request.app.state.gateway_services.store.order_detail(subject.tenant_id, subject.subject_id, order_no)
    return canonical_success(detail, request.state.request_id)


@router.post("/orders/{order_no}/refunds")
async def create_refund(request: Request, order_no: str, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="order.create_refund",
        payload={
            "order_no": order_no,
            "reason": payload.get("reason"),
            "amount": payload.get("amount"),
            "attachments": [item.get("file_id") for item in payload.get("attachments") or []],
        },
    )
    result = _tool_result_data(tool_result)
    _cache_order_snapshot(request, subject, {**result, "order_no": order_no})
    refund = request.app.state.gateway_services.store.add_refund(
        subject.tenant_id,
        subject.subject_id,
        order_no=order_no,
        refund_no=result.get("refund_no") or f"refund_{order_no}",
        amount=str(payload.get("amount")),
        currency=str(result.get("currency") or "CNY"),
        status=result.get("status") or "processing",
        reason=str(payload.get("reason") or ""),
    )
    return canonical_success(refund, request.state.request_id)


@router.get("/refunds")
async def list_refunds(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    store = request.app.state.gateway_services.store
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    return canonical_success(
        paginated_data(store.list_refunds(subject.tenant_id, subject.subject_id), page=page, page_size=page_size),
        request.state.request_id,
    )


@router.get("/refunds/{refund_no}")
async def get_refund(request: Request, refund_no: str, subject: GatewaySubject = Depends(require_user_subject)):
    refunds = request.app.state.gateway_services.store.list_refunds(subject.tenant_id, subject.subject_id)
    refund = next((item for item in refunds if item["refund_no"] == refund_no), None)
    if refund is None:
        tool_result = await _execute_business_tool(
            request,
            subject,
            tool_name="order.query_order",
            payload={"refund_no": refund_no},
        )
        result = _tool_result_data(tool_result)
        if not result.get("refund_no"):
            return canonical_error(
                request_id=request.state.request_id,
                status_code=404,
                code=4040001,
                message="refund not found",
            )
        if result.get("order_no"):
            _cache_order_snapshot(request, subject, result)
        refund = {
            "refund_no": str(result.get("refund_no")),
            "order_no": str(result.get("order_no") or ""),
            "status": str(result.get("refund_status") or "processing"),
            "requested_amount": f"{float(result.get('paid_amount') or 0):.2f}",
            "currency": str(result.get("currency") or "CNY"),
            "created_at": request.app.state.gateway_services.store.workspace_updated_at(subject.tenant_id, subject.subject_id),
            "timeline": [],
        }
    return canonical_success(refund, request.state.request_id)


@router.get("/tickets")
async def list_tickets(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    store = request.app.state.gateway_services.store
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    return canonical_success(
        paginated_data(store.list_tickets(subject.tenant_id, subject.subject_id), page=page, page_size=page_size),
        request.state.request_id,
    )


@router.post("/tickets")
async def create_ticket(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="ticket.create",
        payload={
            "subject": payload.get("subject"),
            "content": payload.get("content"),
            "priority": payload.get("priority"),
            "category": payload.get("category"),
            "attachments": [item.get("file_id") for item in payload.get("attachments") or []],
        },
    )
    result = _tool_result_data(tool_result)
    ticket = request.app.state.gateway_services.store.add_ticket(
        subject.tenant_id,
        subject.subject_id,
        ticket_no=result.get("ticket_no") or f"tk_{subject.subject_id}",
        subject=str(payload.get("subject") or ""),
        content=str(payload.get("content") or ""),
        category=str(payload.get("category") or "general"),
        priority=str(payload.get("priority") or "medium"),
        status=result.get("status") or "processing",
        sla_minutes=result.get("sla_minutes"),
    )
    return canonical_success(ticket, request.state.request_id)


@router.get("/tickets/{ticket_no}")
async def ticket_detail(request: Request, ticket_no: str, subject: GatewaySubject = Depends(require_user_subject)):
    detail = request.app.state.gateway_services.store.ticket_detail(subject.tenant_id, subject.subject_id, ticket_no)
    if detail is None:
        tool_result = await _execute_business_tool(
            request,
            subject,
            tool_name="ticket.query_ticket",
            payload={"ticket_no": ticket_no},
        )
        result = _tool_result_data(tool_result)
        if not result.get("ticket_no"):
            return canonical_error(
                request_id=request.state.request_id,
                status_code=404,
                code=4040001,
                message="ticket not found",
            )
        _cache_ticket_snapshot(request, subject, result)
        detail = request.app.state.gateway_services.store.ticket_detail(subject.tenant_id, subject.subject_id, ticket_no)
    return canonical_success(detail, request.state.request_id)


@router.post("/tickets/{ticket_no}/replies")
async def reply_ticket(request: Request, ticket_no: str, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="ticket.reply",
        payload={
            "ticket_no": ticket_no,
            "content": payload.get("content"),
            "attachments": [item.get("file_id") for item in payload.get("attachments") or []],
        },
    )
    result = _tool_result_data(tool_result)
    reply = request.app.state.gateway_services.store.add_ticket_reply(
        subject.tenant_id,
        subject.subject_id,
        ticket_no=ticket_no,
        reply_no=result.get("reply_no") or f"reply_{ticket_no}_001",
        content=str(payload.get("content") or ""),
    )
    return canonical_success(reply, request.state.request_id)


@router.post("/icp/materials/check")
async def icp_materials_check(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="icp.material_check",
        payload={
            "subject_type": payload.get("subject_type"),
            "materials": payload.get("materials") or [],
        },
    )
    result = _tool_result_data(tool_result)
    issues = [
        {"field": "materials", "severity": "error", "message": item}
        for item in result.get("issues") or []
    ]
    return canonical_success(
        {
            "passed": result.get("passed", not issues),
            "issues": issues,
            "required_materials": result.get("required_materials") or [],
        },
        request.state.request_id,
    )


@router.get("/icp/applications")
async def list_icp_applications(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    store = request.app.state.gateway_services.store
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    return canonical_success(
        paginated_data(
            store.list_icp_applications(subject.tenant_id, subject.subject_id),
            page=page,
            page_size=page_size,
        ),
        request.state.request_id,
    )


@router.post("/icp/applications")
async def create_icp_application(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    contacts = payload.get("contacts") or []
    materials = payload.get("materials") or []
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="icp.submit_application",
        payload={
            "subject_type": payload.get("subject_type"),
            "domain": payload.get("domain"),
            "website_name": payload.get("website_name"),
            "contacts": {"contact_name": contacts[0]} if contacts else {},
            "materials": materials,
        },
    )
    result = _tool_result_data(tool_result)
    record = request.app.state.gateway_services.store.add_icp_application(
        subject.tenant_id,
        subject.subject_id,
        application_no=result.get("application_no") or f"icp_{subject.subject_id}",
        domain=str(payload.get("domain") or ""),
        website_name=str(payload.get("website_name") or ""),
        subject_type=str(payload.get("subject_type") or "enterprise"),
        contacts=list(contacts),
        materials=list(materials),
        status=result.get("status") or "submitted",
        current_step=result.get("current_step") or "provider_review",
    )
    return canonical_success(record, request.state.request_id)


@router.get("/icp/applications/{application_no}")
async def get_icp_application(request: Request, application_no: str, subject: GatewaySubject = Depends(require_user_subject)):
    record = request.app.state.gateway_services.store.get_icp_application(subject.tenant_id, subject.subject_id, application_no)
    if record is None:
        tool_result = await _execute_business_tool(
            request,
            subject,
            tool_name="icp.query_application",
            payload={"application_no": application_no},
        )
        result = _tool_result_data(tool_result)
        if not result.get("application_no"):
            return canonical_error(
                request_id=request.state.request_id,
                status_code=404,
                code=4040001,
                message="icp application not found",
            )
        record = _cache_icp_application_snapshot(request, subject, result)
    return canonical_success(record, request.state.request_id)


@router.post("/files/upload-policy")
async def file_upload_policy(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    policy = request.app.state.gateway_services.store.create_upload_policy(
        subject.tenant_id,
        subject.subject_id,
        file_name=str(payload.get("file_name") or ""),
        size=int(payload.get("size") or 0),
        mime_type=str(payload.get("mime_type") or "application/octet-stream"),
        biz_type=str(payload.get("biz_type") or "chat_attachment"),
    )
    return canonical_success(policy, request.state.request_id)


@router.post("/files/complete")
async def file_complete(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    payload = await request.json()
    record = request.app.state.gateway_services.store.complete_upload(
        subject.tenant_id,
        subject.subject_id,
        file_id=str(payload.get("file_id") or ""),
        object_key=str(payload.get("object_key") or ""),
        size=int(payload.get("size") or 0),
    )
    return canonical_success(record, request.state.request_id)


@router.get("/files/{file_id}")
async def file_detail(request: Request, file_id: str, subject: GatewaySubject = Depends(require_user_subject)):
    record = request.app.state.gateway_services.store.get_file(subject.tenant_id, subject.subject_id, file_id)
    if record is None:
        return canonical_error(
            request_id=request.state.request_id,
            status_code=404,
            code=4040001,
            message="file not found",
        )
    return canonical_success(record, request.state.request_id)


@router.delete("/files/{file_id}")
async def delete_file(request: Request, file_id: str, subject: GatewaySubject = Depends(require_user_subject)):
    request.app.state.gateway_services.store.delete_file(subject.tenant_id, subject.subject_id, file_id)
    return canonical_success({"success": True}, request.state.request_id)


@router.get("/products")
async def list_products(request: Request, subject: GatewaySubject = Depends(require_user_subject)):
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="product.catalog_lookup",
        payload={"user_query": request.query_params.get("query", "")},
    )
    result = _tool_result_data(tool_result)
    families = result.get("product_families") or []
    page = int(request.query_params.get("page", "1"))
    page_size = int(request.query_params.get("page_size", "20"))
    items = [{"product_family": f} for f in families]
    return canonical_success(paginated_data(items, page=page, page_size=page_size), request.state.request_id)


@router.get("/products/{product_id}/pricing")
async def product_pricing(request: Request, product_id: str, subject: GatewaySubject = Depends(require_user_subject)):
    tool_result = await _execute_business_tool(
        request,
        subject,
        tool_name="product.recommend_instance",
        payload={"user_query": product_id},
    )
    result = _tool_result_data(tool_result)
    return canonical_success(
        {
            "product_id": product_id,
            "recommended_instance_type": result.get("recommended_instance_type"),
            "recommended_instance_family": result.get("recommended_instance_family"),
            "gpu_model": result.get("gpu_model"),
            "gpu_count": result.get("gpu_count"),
            "vcpu": result.get("vcpu"),
            "memory_gb": result.get("memory_gb"),
            "network_gbps": result.get("network_gbps"),
            "estimated_monthly_cost_cny": result.get("estimated_monthly_cost_cny"),
            "alternatives": result.get("alternatives") or [],
        },
        request.state.request_id,
    )


@router.get("/citations/{citation_id}")
async def citation_detail(request: Request, citation_id: str, subject: GatewaySubject = Depends(require_user_subject)):
    citation = request.app.state.gateway_services.store.get_citation(subject.tenant_id, subject.subject_id, citation_id)
    if citation is None:
        return canonical_error(
            request_id=request.state.request_id,
            status_code=404,
            code=4040001,
            message="citation not found",
        )
    return canonical_success(citation, request.state.request_id)
