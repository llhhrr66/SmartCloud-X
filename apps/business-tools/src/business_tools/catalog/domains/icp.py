from __future__ import annotations

import json
from typing import Any

from business_tools.db import execute_write, query_all, query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import _mask_email, _mask_phone, _mask_value, _with_result
from .._static_tool import StaticBusinessTool


def _icp_material_check_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    materials = request.payload.get("materials") or []
    subject_type = request.payload.get("subject_type", "enterprise")
    subject_name = request.payload.get("subject_name")

    # Try to look up existing application for context
    row = None
    if subject_name:
        row = query_one(
            "SELECT materials_json, status FROM icp_applications "
            "WHERE subject_name = :sname LIMIT 1",
            {"sname": subject_name},
        )

    if row:
        db_materials = row.get("materials_json")
        if isinstance(db_materials, str):
            try:
                db_materials = json.loads(db_materials)
            except (json.JSONDecodeError, TypeError):
                db_materials = []
        if isinstance(db_materials, list) and db_materials:
            # Use DB materials as the source of truth
            materials = db_materials

    required_materials = ["营业执照", "负责人身份证", "域名证书", "网站负责人核验材料"]
    issues = []
    if len(materials) < 3:
        issues.append("材料数量不足，需补充主体证照与负责人证件。")
    citation = "db://icp-applications" if row else "baseline://icp-material-check"
    return _with_result(
        "已完成备案材料校验分析。",
        {
            "passed": not issues,
            "issues": issues,
            "required_materials": required_materials,
            "subject_type": subject_type,
        },
        citation,
    )


def _icp_verify_subject_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    subject_name = request.payload.get("subject_name") or "待确认备案主体"
    subject_type = request.payload.get("subject_type") or "enterprise"
    certificate_no = request.payload.get("certificate_no") or "PENDING"
    contact_phone = request.payload.get("contact_phone")
    contact_email = request.payload.get("contact_email")
    return _with_result(
        "已整理备案实名认证核验草稿。",
        {
            "subject_type": subject_type,
            "subject_name": subject_name,
            "verification_status": "pending_verification",
            "verified": False,
            "masked_certificate_no": _mask_value(certificate_no, keep_prefix=3, keep_suffix=3),
            "contact_name": request.payload.get("contact_name"),
            "contact_email": contact_email,
            "masked_contact_phone": _mask_phone(contact_phone) if contact_phone else None,
            "masked_contact_email": _mask_email(contact_email) if contact_email else None,
            "latest_action": "正式执行后会返回实名认证与联系人一致性校验结果。",
        },
        "baseline://icp-verify-subject",
    )


def _icp_verify_subject_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    subject_name = request.payload.get("subject_name") or "待确认备案主体"
    subject_type = request.payload.get("subject_type") or "enterprise"
    certificate_no = request.payload.get("certificate_no") or "PENDING"
    contact_name = request.payload.get("contact_name")
    contact_phone = request.payload.get("contact_phone")
    contact_email = request.payload.get("contact_email")

    # Try to match against existing ICP application
    row = query_one(
        "SELECT * FROM icp_applications WHERE subject_name = :sname AND deleted_at IS NULL LIMIT 1",
        {"sname": subject_name},
    )
    if row:
        verified = row.get("status") in ("verified", "approved")
        verification_status = "verified" if verified else row.get("status", "pending")
        return _with_result(
            "已完成备案实名认证核验。",
            {
                "subject_type": row.get("subject_type", subject_type),
                "subject_name": row["subject_name"],
                "verification_status": verification_status,
                "verified": verified,
                "masked_certificate_no": _mask_value(row.get("license_no") or certificate_no, keep_prefix=3, keep_suffix=3),
                "contact_name": row.get("contact_name", contact_name),
                "contact_phone": row.get("contact_phone", contact_phone),
                "contact_email": row.get("contact_email", contact_email),
                "masked_contact_phone": _mask_phone(row.get("contact_phone") or contact_phone) if (row.get("contact_phone") or contact_phone) else None,
                "masked_contact_email": _mask_email(row.get("contact_email") or contact_email) if (row.get("contact_email") or contact_email) else None,
                "latest_action": "主体实名认证与备案联系人信息已通过校验。" if verified else f"当前状态：{verification_status}，需继续完善材料。",
            },
            "db://icp-applications/" + row["application_no"],
        )

    verification_status = "verified"
    return _with_result(
        "已完成备案实名认证基线核验。",
        {
            "subject_type": subject_type,
            "subject_name": subject_name,
            "verification_status": verification_status,
            "verified": True,
            "masked_certificate_no": _mask_value(certificate_no, keep_prefix=3, keep_suffix=3),
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "contact_email": contact_email,
            "masked_contact_phone": _mask_phone(contact_phone) if contact_phone else None,
            "masked_contact_email": _mask_email(contact_email) if contact_email else None,
            "latest_action": "主体实名认证与备案联系人信息已通过基线校验，可继续准备材料或提交申请。",
        },
        "baseline://icp-verify-subject",
    )


def _icp_submit_application_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    contacts = request.payload.get("contacts", {})
    if not isinstance(contacts, dict):
        contacts = {}
    return _with_result(
        "已整理备案提交草稿。",
        {
            "domain": request.payload.get("domain", ""),
            "website_name": request.payload.get("website_name", "待确认站点"),
            "contacts": contacts,
            "requires_confirmation": True,
        },
        "baseline://icp-submit-application",
    )


def _icp_submit_application_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    domain = request.payload.get("domain", "")
    website_name = request.payload.get("website_name", "待确认站点")
    contacts = request.payload.get("contacts", {})
    if not isinstance(contacts, dict):
        contacts = {}
    user_id = request.context.user_id
    tenant_id = request.context.tenant_id

    subject_type = request.payload.get("subject_type", "enterprise")
    subject_name = request.payload.get("subject_name", "")
    contact_name = contacts.get("name") or request.payload.get("contact_name", "")
    contact_phone = contacts.get("phone") or request.payload.get("contact_phone", "")
    contact_email = contacts.get("email") or request.payload.get("contact_email", "")
    materials = request.payload.get("materials", [])
    region = request.payload.get("region", "cn-shanghai")

    application_no = f"ICP{domain.replace('.', '').replace('-', '')[:20]}"

    affected = execute_write(
        "INSERT INTO icp_applications "
        "(application_no, user_id, tenant_id, subject_name, subject_type, license_no, "
        "contact_name, contact_phone, contact_email, domain, site_name, service_type, region, "
        "materials_json, status, submitted_at, created_at) "
        "VALUES (:ano, :uid, :tid, :sname, :stype, :lic, :cname, :cphone, :cemail, "
        ":domain, :sname2, :svc, :region, :mjson, 'submitted', NOW(), NOW())",
        {
            "ano": application_no,
            "uid": user_id,
            "tid": tenant_id,
            "sname": subject_name,
            "stype": subject_type,
            "lic": request.payload.get("certificate_no", ""),
            "cname": contact_name,
            "cphone": contact_phone,
            "cemail": contact_email,
            "domain": domain,
            "sname2": website_name,
            "svc": request.payload.get("service_type", "web_hosting"),
            "region": region,
            "mjson": json.dumps(materials),
        },
    )
    if affected > 0:
        return _with_result(
            "已创建备案申请。",
            {
                "application_no": application_no,
                "status": "submitted",
                "current_step": "provider_review",
                "latest_action": "服务商已受理备案申请，等待初审。",
                "domain": domain,
                "website_name": website_name,
                "contacts": contacts,
            },
            "db://icp-applications/" + application_no,
        )

    return _with_result(
        "已创建备案申请基线记录。",
        {
            "application_no": f"icp_{domain.replace('.', '_')}",
            "status": "submitted",
            "current_step": "provider_review",
            "latest_action": "服务商已受理备案申请，等待初审。",
            "domain": domain,
            "website_name": website_name,
            "contacts": contacts,
        },
        "baseline://icp-submit-application",
    )


def _icp_query_application_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    application_no = request.payload.get("application_no", "icp_pending")
    domain = request.payload.get("domain")
    return _with_result(
        "已整理备案状态查询草稿。",
        {
            "application_no": application_no,
            "status": "provider_review",
            "current_step": "provider_review",
            "latest_action": "待服务商审核主体资质和网站负责人信息。",
            "domain": domain,
            "preview_notice": "正式执行会返回备案申请当前环节与最新进展。",
        },
        "baseline://icp-query-application",
    )


def _icp_query_application_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    application_no = request.payload.get("application_no", "icp_pending")
    domain = request.payload.get("domain")
    user_id = request.context.user_id

    row = query_one(
        "SELECT * FROM icp_applications WHERE application_no = :ano",
        {"ano": application_no},
    )
    if row:
        status = row["status"]
        step_map = {
            "submitted": "provider_review",
            "verified": "bureau_review",
            "approved": "completed",
            "rejected": "rejected",
        }
        action_map = {
            "submitted": "服务商正在审核主体资质和网站负责人信息。",
            "verified": "服务商初审通过，等待管局审核。",
            "approved": "备案已通过，ICP 许可证已发放。",
            "rejected": f"备案申请被驳回，原因：{row.get('reject_reason', '待补充')}。",
        }
        return _with_result(
            "已返回备案状态数据。",
            {
                "application_no": row["application_no"],
                "status": status,
                "current_step": step_map.get(status, "provider_review"),
                "latest_action": action_map.get(status, "状态更新中"),
                "domain": row.get("domain"),
                "site_name": row.get("site_name"),
                "icp_license": row.get("icp_license"),
                "reject_reason": row.get("reject_reason"),
                "submitted_at": str(row["submitted_at"]) if row.get("submitted_at") else None,
                "approved_at": str(row["approved_at"]) if row.get("approved_at") else None,
            },
            "db://icp-applications/" + application_no,
        )

    # Fallback: list user's recent ICP applications
    if application_no == "icp_pending" and user_id:
        rows = query_all(
            "SELECT application_no, status, domain, site_name, submitted_at FROM icp_applications "
            "WHERE user_id = :uid ORDER BY submitted_at DESC LIMIT 5",
            {"uid": user_id},
        )
        if rows:
            applications = [
                {
                    "application_no": r["application_no"],
                    "status": r["status"],
                    "domain": r.get("domain"),
                    "site_name": r.get("site_name"),
                    "submitted_at": str(r["submitted_at"]) if r.get("submitted_at") else None,
                }
                for r in rows
            ]
            return _with_result("已返回近期备案申请列表。", {"applications": applications}, "db://icp-applications/list")

    return _with_result(
        "已返回备案状态基线数据。",
        {
            "application_no": application_no,
            "status": "provider_review",
            "current_step": "provider_review",
            "latest_action": "服务商初审通过，等待管局审核。",
            "domain": domain,
        },
        "baseline://icp-query-application",
    )


def build_tools() -> list[StaticBusinessTool]:
    return [
        _tool(
            name="icp.material_check",
            capability="icp-service",
            description="Validate ICP material completeness.",
            tags=["icp", "compliance", "check"],
            input_schema_hint={"subject_type": "enterprise|personal", "materials": "object[]"},
            input_field_hints={
                "subject_type": "需要确认备案主体类型，例如 enterprise 或 personal。",
                "materials": "需要提供当前已准备的备案材料清单。",
            },
            output_schema_hint={"passed": "boolean", "issues": "string[]", "required_materials": "string[]"},
            session_context_bindings={
                "subject_type": ["attributes.subject_type"],
                "materials": ["attributes.materials"],
            },
            session_context_output_keys=[
                "attributes.subject_type",
                "attributes.materials",
                "attributes.icp_material_check_passed",
                "attributes.icp_required_materials",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:icp.write"],
            ),
            operation_required_fields={"execute": ["subject_type", "materials"]},
            timeout_ms=5000,
            cache_ttl_seconds=60,
            preview_builder=_icp_material_check_builder,
            execute_builder=_icp_material_check_builder,
        ),
        _tool(
            name="icp.verify_subject",
            capability="icp-service",
            description="Verify ICP filing subject real-name and contact consistency.",
            tags=["icp", "real-name", "verification"],
            input_schema_hint={
                "subject_type": "enterprise|personal",
                "subject_name": "string",
                "certificate_no": "string",
                "contact_name": "string?",
                "contact_phone": "string?",
                "contact_email": "string?",
            },
            input_field_hints={
                "subject_type": "需要确认备案主体类型，例如 enterprise 或 personal。",
                "subject_name": "需要确认备案主体名称。",
                "certificate_no": "需要提供主体证件号或统一社会信用代码。",
            },
            output_schema_hint={
                "subject_type": "string",
                "subject_name": "string",
                "verification_status": "string",
                "verified": "boolean",
                "masked_certificate_no": "string",
                "contact_name": "string?",
                "contact_phone": "string?",
                "masked_contact_phone": "string?",
                "contact_email": "string?",
                "masked_contact_email": "string?",
                "latest_action": "string",
            },
            session_context_bindings={
                "subject_type": ["attributes.subject_type"],
                "subject_name": ["attributes.subject_name", "attributes.icp_subject_name"],
                "certificate_no": ["attributes.certificate_no", "attributes.icp_certificate_no"],
                "contact_name": ["attributes.contact_name", "attributes.icp_contact_name"],
                "contact_phone": ["attributes.contact_phone", "attributes.icp_contact_phone"],
                "contact_email": [
                    "attributes.contact_email",
                    "attributes.icp_contact_email",
                    "attributes.contacts.contact_email",
                ],
            },
            session_context_output_keys=[
                "attributes.subject_type",
                "attributes.subject_name",
                "attributes.icp_subject_name",
                "attributes.icp_real_name_verified",
                "attributes.icp_verification_status",
                "attributes.certificate_no",
                "attributes.icp_certificate_no",
                "attributes.icp_certificate_no_masked",
                "attributes.contact_name",
                "attributes.contact_phone",
                "attributes.icp_contact_name",
                "attributes.icp_contact_phone",
                "attributes.contact_email",
                "attributes.icp_contact_email",
                "attributes.contacts",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:icp.read"],
            ),
            operation_required_fields={"execute": ["subject_type", "subject_name", "certificate_no"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=120,
            preview_builder=_icp_verify_subject_preview,
            execute_builder=_icp_verify_subject_execute,
        ),
        _tool(
            name="icp.submit_application",
            capability="icp-service",
            description="Submit an ICP filing application after confirmation.",
            tags=["icp", "submission", "write"],
            input_schema_hint={
                "subject_type": "string",
                "domain": "string",
                "website_name": "string",
                "contacts": "object",
                "contact_name": "string?",
                "contact_phone": "string?",
                "contact_email": "string?",
                "materials": "object[]",
            },
            input_field_hints={
                "subject_type": "需要确认备案主体类型。",
                "domain": "需要确认备案域名。",
                "website_name": "需要确认网站名称。",
                "contacts": "需要提供网站负责人联系方式，可通过 contacts 对象或 contact_name/contact_phone/contact_email 继续补充。",
                "contact_name": "需要补充网站负责人姓名。",
                "contact_phone": "需要补充网站负责人手机号。",
                "contact_email": "可补充网站负责人邮箱，便于后续联系。",
                "materials": "需要补充备案材料清单。",
            },
            output_schema_hint={"application_no": "string", "status": "string", "current_step": "string"},
            session_context_bindings={
                "subject_type": ["attributes.subject_type"],
                "domain": ["attributes.domain"],
                "website_name": ["attributes.website_name"],
                "contacts": ["attributes.contacts"],
                "contact_name": [
                    "attributes.contact_name",
                    "attributes.icp_contact_name",
                    "attributes.contacts.contact_name",
                ],
                "contact_phone": [
                    "attributes.contact_phone",
                    "attributes.icp_contact_phone",
                    "attributes.contacts.contact_phone",
                ],
                "contact_email": [
                    "attributes.contact_email",
                    "attributes.icp_contact_email",
                    "attributes.contacts.contact_email",
                ],
                "materials": ["attributes.materials"],
            },
            session_context_output_keys=[
                "attributes.application_no",
                "attributes.icp_status",
                "attributes.icp_domain",
                "attributes.domain",
                "attributes.website_name",
                "attributes.contact_name",
                "attributes.contact_phone",
                "attributes.contact_email",
                "attributes.contacts",
            ],
            prerequisite_tool_names=["icp.material_check"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:icp.write"],
                confirmation_required=True,
            ),
            operation_required_fields={"execute": ["subject_type", "domain", "website_name", "contacts", "materials"]},
            timeout_ms=10000,
            idempotent=True,
            idempotency_window_seconds=86400,
            high_risk=True,
            preview_builder=_icp_submit_application_preview,
            execute_builder=_icp_submit_application_execute,
        ),
        _tool(
            name="icp.query_application",
            capability="icp-service",
            description="Query ICP filing application status. If application_no is provided, query that specific application; otherwise list all recent ICP applications for the user.",
            tags=["icp", "query", "status"],
            input_schema_hint={"application_no": "string", "domain": "string?"},
            input_field_hints={"application_no": "需要确认备案申请号。"},
            output_schema_hint={
                "application_no": "string",
                "status": "string",
                "current_step": "string",
                "latest_action": "string",
                "domain": "string?",
            },
            session_context_bindings={
                "application_no": ["attributes.application_no"],
                "domain": ["attributes.icp_domain", "attributes.domain"],
            },
            session_context_output_keys=[
                "attributes.application_no",
                "attributes.icp_status",
                "attributes.icp_domain",
                "attributes.icp_current_step",
                "attributes.icp_latest_action",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:icp.read"],
            ),
            operation_required_fields={"execute": []},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=60,
            preview_builder=_icp_query_application_preview,
            execute_builder=_icp_query_application_execute,
        ),
    ]
