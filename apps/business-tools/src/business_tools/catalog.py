from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from business_tools.idempotency import get_idempotency_store
from business_tools.query_cache import get_query_cache_store
from business_tools.interfaces import (
    BusinessTool,
    ToolAuthRequirements,
    ToolCompensationAction,
    ToolDefinition,
    ToolExecutionResult,
    ToolInvocationRequest,
    ToolMode,
    ToolOperation,
    build_tool_user_action_hint,
    is_missing_tool_value,
)


ResultBuilder = Callable[[ToolInvocationRequest], tuple[str, dict[str, Any], list[str]]]


class StaticBusinessTool(BusinessTool):
    def __init__(
        self,
        definition: ToolDefinition,
        preview_builder: ResultBuilder,
        execute_builder: ResultBuilder | None = None,
    ) -> None:
        self.definition = definition
        self._preview_builder = preview_builder
        self._execute_builder = execute_builder or preview_builder

    def invoke(self, request: ToolInvocationRequest) -> ToolExecutionResult:
        audit_tags = [self.definition.capability, request.operation, self.definition.mode]
        if self.definition.high_risk:
            audit_tags.append("high-risk")

        required_fields = self.definition.operation_required_fields.get(request.operation, [])
        missing_payload = [
            field
            for field in required_fields
            if is_missing_tool_value(request.payload.get(field))
        ]
        if missing_payload:
            return ToolExecutionResult(
                tool_name=self.definition.name,
                operation=request.operation,
                status="invalid-payload",
                summary=f"{self.definition.name} 缺少必要字段：{', '.join(missing_payload)}。",
                result={
                    "missing_fields": missing_payload,
                    "required_fields": required_fields,
                },
                citations=[],
                audit_tags=[*audit_tags, "invalid-payload"],
                session_context_patch={},
                success=False,
                code=4001001,
                message="invalid tool payload",
                provider=self.definition.provider,
                error_detail={"missing_fields": missing_payload},
                idempotency_key=request.context.idempotency_key,
                user_action_hint=build_tool_user_action_hint(
                    self.definition,
                    status="invalid-payload",
                    missing_payload_fields=missing_payload,
                    missing_payload_hints={
                        field: self.definition.input_field_hints[field]
                        for field in missing_payload
                        if field in self.definition.input_field_hints
                    },
                ),
            )

        builder = self._preview_builder if request.operation == "preview" else self._execute_builder
        summary, payload, citations = builder(request)
        compensation = _build_compensation(self.definition, request, payload)
        session_context_patch = _build_session_context_patch(self.definition, request, payload)
        missing_auth = (
            request.context.missing_auth(self.definition.auth_requirements)
            if request.operation == "execute"
            else []
        )

        if missing_auth:
            payload = {
                **payload,
                "missing_context": missing_auth,
                "auth_requirements": self.definition.auth_requirements.model_dump(),
            }
            return ToolExecutionResult(
                tool_name=self.definition.name,
                operation=request.operation,
                status="auth-required",
                summary=f"{summary}；执行前需补充鉴权上下文。",
                result=payload,
                citations=citations,
                audit_tags=audit_tags,
                session_context_patch=session_context_patch,
                success=False,
                code=4030001,
                message="auth context missing",
                provider=self.definition.provider,
                cache_ttl_seconds=self.definition.cache_ttl_seconds if self.definition.mode == "query" else None,
                error_detail={"missing_context": missing_auth},
                idempotency_key=request.context.idempotency_key,
                user_action_hint=build_tool_user_action_hint(
                    self.definition,
                    status="auth-required",
                    missing_auth_context=missing_auth,
                    required_permissions=list(self.definition.auth_requirements.required_permissions),
                    requires_account_context=self.definition.auth_requirements.require_account_id,
                ),
            )

        if (
            request.operation == "execute"
            and self.definition.auth_requirements.confirmation_required
            and not request.payload.get("_confirmed")
        ):
            payload = {
                **payload,
                "confirmation_required": True,
                "confirmation_hint": "set payload._confirmed=true after explicit user confirmation",
            }
            return ToolExecutionResult(
                tool_name=self.definition.name,
                operation=request.operation,
                status="confirmation-required",
                summary=f"{summary}；该工具属于写操作，需先完成显式确认。",
                result=payload,
                citations=citations,
                audit_tags=audit_tags,
                session_context_patch=session_context_patch,
                success=False,
                code=4090002,
                message="confirmation required",
                provider=self.definition.provider,
                error_detail={"reason": "confirmation_required"},
                idempotency_key=request.context.idempotency_key,
                user_action_hint=build_tool_user_action_hint(
                    self.definition,
                    status="confirmation-required",
                    confirmation_required=self.definition.auth_requirements.confirmation_required,
                ),
            )

        if request.operation == "execute" and self.definition.mode == "query":
            cached = get_query_cache_store().get(
                self.definition.name,
                request.operation,
                request.payload,
                request.context,
            )
            if cached is not None:
                return cached

        if request.operation == "execute" and self.definition.mode == "write" and request.context.idempotency_key:
            replayed, conflict = get_idempotency_store().get(
                self.definition.name,
                request.context.idempotency_key,
                request.payload,
                request.context,
            )
            if conflict:
                return ToolExecutionResult(
                    tool_name=self.definition.name,
                    operation=request.operation,
                    status="idempotency-conflict",
                    summary=f"{summary}；幂等键已被其他写入请求占用。",
                    result={"idempotency_key": request.context.idempotency_key},
                    citations=citations,
                    audit_tags=[*audit_tags, "idempotency-conflict"],
                    session_context_patch={},
                    success=False,
                    code=4090001,
                    message="idempotency conflict",
                    provider=self.definition.provider,
                    error_detail={"reason": "idempotency_conflict"},
                    idempotency_key=request.context.idempotency_key,
                )
            if replayed is not None:
                return replayed

        preview_confirmation_hint = (
            build_tool_user_action_hint(
                self.definition,
                status="confirmation-required",
                confirmation_required=self.definition.auth_requirements.confirmation_required,
            )
            if (
                request.operation == "preview"
                and self.definition.mode == "write"
                and self.definition.auth_requirements.confirmation_required
            )
            else None
        )
        status = "preview-ready" if request.operation == "preview" else "completed"
        result = ToolExecutionResult(
            tool_name=self.definition.name,
            operation=request.operation,
            status=status,
            summary=summary,
            result=payload,
            citations=citations,
            audit_tags=audit_tags,
            session_context_patch=session_context_patch,
            success=True,
            code=0,
            message="ok",
            provider=self.definition.provider,
            cache_ttl_seconds=self.definition.cache_ttl_seconds if self.definition.mode == "query" else None,
            compensation=compensation,
            idempotency_key=request.context.idempotency_key,
            user_action_hint=preview_confirmation_hint,
        )
        if request.operation == "execute" and self.definition.mode == "write" and request.context.idempotency_key:
            return get_idempotency_store().save(
                self.definition.name,
                request.context.idempotency_key,
                request.payload,
                request.context,
                self.definition.idempotency_window_seconds,
                result,
            )
        if request.operation == "execute" and self.definition.mode == "query":
            return get_query_cache_store().save(
                self.definition.name,
                request.operation,
                request.payload,
                request.context,
                self.definition.cache_ttl_seconds,
                result,
            )
        return result


def _query_payload(request: ToolInvocationRequest) -> str:
    return str(
        request.payload.get("user_query")
        or request.payload.get("topic")
        or request.payload.get("theme")
        or request.payload.get("product_summary")
        or request.payload.get("product")
        or request.payload.get("subject")
        or ""
    )


def _with_result(
    summary: str,
    result: dict[str, Any],
    *citations: str,
) -> tuple[str, dict[str, Any], list[str]]:
    return summary, result, list(citations)


def _list_strings(values: list[Any]) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        return _list_strings(value)
    return []


def _slugify_token(value: Any, *, fallback: str) -> str:
    normalized = "".join(
        character.lower()
        if character.isalnum()
        else "-"
        for character in str(value or "").strip()
    )
    collapsed = "-".join(part for part in normalized.split("-") if part)
    return collapsed[:48] or fallback


def _mask_value(value: Any, *, keep_prefix: int = 2, keep_suffix: int = 2) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= keep_prefix + keep_suffix:
        return "*" * len(raw)
    middle_length = max(len(raw) - keep_prefix - keep_suffix, 1)
    return f"{raw[:keep_prefix]}{'*' * middle_length}{raw[-keep_suffix:]}"


def _mask_phone(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) < 7:
        return _mask_value(raw, keep_prefix=1, keep_suffix=1)
    return f"{raw[:3]}****{raw[-4:]}"


def _mask_email(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw or "@" not in raw:
        return _mask_value(raw, keep_prefix=1, keep_suffix=1)
    local, domain = raw.split("@", 1)
    masked_local = _mask_value(local, keep_prefix=1, keep_suffix=1) if local else "*"
    return f"{masked_local}@{domain}"


def _build_session_context_patch(
    definition: ToolDefinition,
    request: ToolInvocationRequest,
    payload: dict[str, Any],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    attributes: dict[str, Any] = {}
    active_products: list[str] = []

    if definition.name in {"billing.query_statement", "billing.summary"}:
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        active_products = _list_strings(
            [item.get("product") for item in items if isinstance(item, dict)]
        )
        top_instances = (
            payload.get("top_instances", [])
            if isinstance(payload.get("top_instances"), list)
            else []
        )
        primary_instance_id = next(
            (
                item.get("instance_id")
                for item in top_instances
                if isinstance(item, dict) and item.get("instance_id")
            ),
            None,
        )
        statement_nos = _normalize_string_list(payload.get("statement_nos"))
        if not statement_nos and payload.get("billing_cycle"):
            billing_cycle = str(payload["billing_cycle"]).replace("-", "_").replace("~", "_")
            statement_nos = [f"stmt_{billing_cycle}_001"]
        attributes.update(
            {
                "statement_nos": statement_nos,
                "statement_no": (statement_nos or [None])[0],
                "billing_range": request.payload.get("range"),
                "billing_start_date": request.payload.get("start_date"),
                "billing_end_date": request.payload.get("end_date"),
                "billing_cycle": payload.get("billing_cycle"),
                "currency": payload.get("currency"),
                "latest_billing_total": payload.get("total_amount"),
                "top_instances": top_instances,
                "primary_instance_id": primary_instance_id,
            }
        )
    elif definition.name == "billing.query_instance_cost":
        instance_id = payload.get("instance_id") or request.payload.get("instance_id")
        product = payload.get("product")
        active_products = _list_strings([product])
        attributes.update(
            {
                "instance_id": instance_id,
                "primary_instance_id": instance_id,
                "instance_name": payload.get("instance_name"),
                "instance_product": product,
                "instance_billing_cycle": payload.get("billing_cycle"),
                "instance_statement_no": payload.get("statement_no"),
                "instance_range": request.payload.get("range"),
                "last_instance_cost_total": payload.get("total_amount"),
                "currency": payload.get("currency"),
            }
        )
    elif definition.name == "order.query_order":
        attributes.update(
            {
                "order_no": payload.get("order_no") or request.payload.get("order_no"),
                "order_status": payload.get("order_status"),
                "refund_no": payload.get("refund_no") or request.payload.get("refund_no"),
                "refund_status": payload.get("refund_status"),
                "invoice_status": payload.get("invoice_status"),
            }
        )
    elif definition.name == "billing.create_invoice":
        attributes.update(
            {
                "invoice_no": payload.get("invoice_no"),
                "invoice_status": payload.get("status"),
                "last_invoice_amount": payload.get("amount"),
                "invoice_title": request.payload.get("title"),
                "invoice_type": request.payload.get("invoice_type"),
                "statement_nos": _normalize_string_list(request.payload.get("statement_nos")),
            }
        )
    elif definition.name == "invoice.query_invoice":
        attributes.update(
            {
                "invoice_no": payload.get("invoice_no") or request.payload.get("invoice_no"),
                "invoice_status": payload.get("status"),
                "last_invoice_amount": payload.get("amount"),
                "invoice_title": payload.get("title") or request.payload.get("title"),
            }
        )
    elif definition.name == "order.create_refund":
        attributes.update(
            {
                "refund_no": payload.get("refund_no"),
                "refund_status": payload.get("status"),
                "refund_order_no": request.payload.get("order_no"),
                "order_no": request.payload.get("order_no"),
                "refund_reason": request.payload.get("reason"),
                "refund_amount": request.payload.get("amount"),
            }
        )
    elif definition.name == "ticket.create":
        patch["open_ticket_id"] = payload.get("ticket_no")
        attributes.update(
            {
                "ticket_status": payload.get("status"),
                "ticket_subject": payload.get("subject"),
                "ticket_priority": payload.get("priority"),
                "ticket_category": payload.get("category"),
                "ticket_queue": payload.get("queue"),
                "ticket_incident_code": payload.get("incident_code"),
                "ticket_related_resources": payload.get("related_resources", []),
            }
        )
    elif definition.name == "ticket.reply":
        patch["open_ticket_id"] = payload.get("ticket_no") or request.payload.get("ticket_no")
        attributes.update(
            {
                "last_ticket_reply_no": payload.get("reply_no"),
                "ticket_status": payload.get("status"),
            }
        )
    elif definition.name == "ticket.query_ticket":
        patch["open_ticket_id"] = payload.get("ticket_no") or request.payload.get("ticket_no")
        attributes.update(
            {
                "ticket_status": payload.get("status"),
                "ticket_subject": payload.get("subject") or request.payload.get("subject"),
                "last_ticket_reply_no": payload.get("reply_no"),
                "ticket_latest_action": payload.get("latest_action"),
            }
        )
    elif definition.name == "icp.material_check":
        attributes.update(
            {
                "subject_type": request.payload.get("subject_type"),
                "materials": request.payload.get("materials", []),
                "icp_material_check_passed": payload.get("passed"),
                "icp_required_materials": payload.get("required_materials", []),
            }
        )
    elif definition.name == "icp.verify_subject":
        contacts: dict[str, Any] = {}
        if payload.get("contact_name"):
            contacts["contact_name"] = payload.get("contact_name")
        if payload.get("contact_phone"):
            contacts["contact_phone"] = payload.get("contact_phone")
        if payload.get("contact_email"):
            contacts["contact_email"] = payload.get("contact_email")
        attributes.update(
            {
                "subject_type": payload.get("subject_type") or request.payload.get("subject_type"),
                "subject_name": payload.get("subject_name") or request.payload.get("subject_name"),
                "icp_subject_name": payload.get("subject_name") or request.payload.get("subject_name"),
                "icp_real_name_verified": payload.get("verified"),
                "icp_verification_status": payload.get("verification_status"),
                "certificate_no": request.payload.get("certificate_no"),
                "icp_certificate_no": request.payload.get("certificate_no"),
                "icp_certificate_no_masked": payload.get("masked_certificate_no"),
                "contact_name": payload.get("contact_name") or request.payload.get("contact_name"),
                "contact_phone": payload.get("contact_phone") or request.payload.get("contact_phone"),
                "icp_contact_name": payload.get("contact_name") or request.payload.get("contact_name"),
                "icp_contact_phone": payload.get("contact_phone") or request.payload.get("contact_phone"),
                "contact_email": payload.get("contact_email") or request.payload.get("contact_email"),
                "icp_contact_email": payload.get("contact_email") or request.payload.get("contact_email"),
                "contacts": contacts,
            }
        )
    elif definition.name == "icp.submit_application":
        attributes.update(
            {
                "application_no": payload.get("application_no"),
                "icp_status": payload.get("status"),
                "icp_current_step": payload.get("current_step"),
                "icp_latest_action": payload.get("latest_action"),
                "icp_domain": request.payload.get("domain"),
                "domain": request.payload.get("domain"),
                "website_name": request.payload.get("website_name"),
                "contacts": request.payload.get("contacts"),
                "contact_name": (
                    request.payload.get("contacts", {}).get("contact_name")
                    if isinstance(request.payload.get("contacts"), dict)
                    else request.payload.get("contact_name")
                ),
                "contact_phone": (
                    request.payload.get("contacts", {}).get("contact_phone")
                    if isinstance(request.payload.get("contacts"), dict)
                    else request.payload.get("contact_phone")
                ),
                "contact_email": (
                    request.payload.get("contacts", {}).get("contact_email")
                    if isinstance(request.payload.get("contacts"), dict)
                    else request.payload.get("contact_email")
                ),
            }
        )
    elif definition.name == "icp.query_application":
        attributes.update(
            {
                "application_no": payload.get("application_no") or request.payload.get("application_no"),
                "icp_status": payload.get("status"),
                "icp_current_step": payload.get("current_step"),
                "icp_latest_action": payload.get("latest_action"),
                "icp_domain": payload.get("domain") or request.payload.get("domain"),
            }
        )
    elif definition.name == "marketing.campaign_lookup":
        active_products = _list_strings(
            [request.payload.get("product")]
            + [
                campaign.get("name")
                for campaign in payload.get("campaigns", [])
                if isinstance(campaign, dict)
            ]
        )
        first_campaign = next(
            (
                campaign.get("name")
                for campaign in payload.get("campaigns", [])
                if isinstance(campaign, dict) and campaign.get("name")
            ),
            None,
        )
        attributes["last_campaign_name"] = first_campaign
        attributes["last_marketing_product_summary"] = (
            payload.get("product_summary")
            or payload.get("matched_product")
            or request.payload.get("product_summary")
            or request.payload.get("product")
        )
    elif definition.name == "marketing.poster_brief":
        attributes.update(
            {
                "poster_theme": payload.get("theme") or request.payload.get("theme"),
                "poster_cta": payload.get("cta"),
                "last_marketing_product_summary": (
                    payload.get("product_summary")
                    or request.payload.get("product_summary")
                ),
            }
        )
    elif definition.name == "marketing.generate_copy":
        attributes.update(
            {
                "last_marketing_copy_headline": payload.get("headline"),
                "last_marketing_copy_body": payload.get("body"),
                "last_marketing_copy_campaign_name": payload.get("campaign_name"),
                "last_marketing_copy_channel": payload.get("channel"),
                "last_marketing_copy_cta": payload.get("cta"),
                "last_marketing_product_summary": (
                    payload.get("product_summary")
                    or request.payload.get("product_summary")
                    or payload.get("product")
                    or request.payload.get("product")
                ),
            }
        )
    elif definition.name == "marketing.generate_promotion_link":
        attributes.update(
            {
                "last_promotion_link_id": payload.get("promotion_link_id"),
                "last_promotion_link": payload.get("short_url"),
                "promotion_channel": payload.get("channel"),
            }
        )
    elif definition.name == "marketing.generate_poster":
        attributes.update(
            {
                "poster_asset_id": payload.get("poster_asset_id"),
                "poster_preview_url": payload.get("preview_url"),
                "poster_download_path": payload.get("download_path"),
                "poster_headline": payload.get("headline"),
                "poster_size": payload.get("size"),
                "poster_theme": payload.get("theme") or request.payload.get("theme"),
                "last_campaign_name": payload.get("campaign_name") or request.payload.get("campaign_name"),
                "last_marketing_product_summary": (
                    payload.get("product_summary")
                    or request.payload.get("product_summary")
                ),
            }
        )
    elif definition.name in {"research.generate_report", "research.outline"}:
        attributes.update(
            {
                "research_topic": payload.get("topic") or request.payload.get("topic"),
                "report_outline": payload.get("outline", []),
            }
        )
    elif definition.name == "research.reference_search":
        attributes["reference_titles"] = [
            item.get("title")
            for item in payload.get("references", [])
            if isinstance(item, dict) and item.get("title")
        ]
    elif definition.name == "research.export_report":
        attributes.update(
            {
                "last_report_export_id": payload.get("artifact_id"),
                "last_report_export_path": payload.get("download_path"),
                "last_report_export_format": payload.get("format"),
            }
        )
    elif definition.name == "product.catalog_lookup":
        active_products = _list_strings(payload.get("product_families", []))
    elif definition.name == "product.recommend_instance":
        active_products = _list_strings(
            [
                "GPU 实例",
                payload.get("recommended_instance_family"),
                payload.get("recommended_instance_type"),
            ]
        )
        attributes.update(
            {
                "recommended_workload": payload.get("workload"),
                "recommended_model_family": payload.get("model_family"),
                "recommended_budget_level": payload.get("budget_level"),
                "recommended_instance_family": payload.get("recommended_instance_family"),
                "recommended_instance_type": payload.get("recommended_instance_type"),
                "recommended_gpu_model": payload.get("gpu_model"),
                "recommended_gpu_count": payload.get("gpu_count"),
                "recommended_vcpu": payload.get("vcpu"),
                "recommended_memory_gb": payload.get("memory_gb"),
                "recommended_network_gbps": payload.get("network_gbps"),
                "recommended_instance_summary": (
                    f"{payload.get('recommended_instance_type')} / "
                    f"{payload.get('gpu_model')} x{payload.get('gpu_count')}"
                )
                if payload.get("recommended_instance_type") and payload.get("gpu_model")
                else None,
            }
        )
    elif definition.name == "support.playbook_search":
        attributes["playbook_titles"] = [
            item.get("title")
            for item in payload.get("playbooks", [])
            if isinstance(item, dict) and item.get("title")
        ]
    elif definition.name == "support.query_service_status":
        service_name = payload.get("service_name") or request.payload.get("service")
        active_products = _list_strings([service_name])
        attributes.update(
            {
                "service_status": payload.get("status"),
                "service_severity": payload.get("severity"),
                "service_incident_code": payload.get("incident_code"),
                "service_status_summary": payload.get("summary"),
                "service_recommended_action": payload.get("recommended_action"),
                "service_region": payload.get("region"),
                "service_name": service_name,
                "service_health_checked_at": payload.get("checked_at"),
                "service_affected_instance_id": payload.get("instance_id") or request.payload.get("instance_id"),
                "service_escalation_recommended": payload.get("escalation_recommended"),
            }
        )
    elif definition.name == "support.handoff_brief":
        attributes.update(
            {
                "human_handoff_queue": payload.get("queue"),
                "human_handoff_severity": payload.get("severity"),
                "human_handoff_summary": payload.get("summary"),
                "human_handoff_reason": payload.get("reason"),
                "human_handoff_related_resources": payload.get("related_resources", []),
                "human_handoff_existing_ticket_no": payload.get("open_ticket_id"),
                "human_handoff_service_status": payload.get("service_status"),
                "human_handoff_incident_code": payload.get("incident_code"),
                "human_handoff_recommended_action": payload.get("recommended_action"),
                "human_handoff_operator_notes": payload.get("operator_notes", []),
            }
        )

    if active_products:
        patch["active_products"] = active_products

    if attributes:
        patch["attributes"] = {
            key: value
            for key, value in attributes.items()
            if value is not None and value != "" and value != [] and value != {}
        }

    return patch


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


def _current_billing_cycle(range_name: str) -> str:
    mapping = {
        "this_month": "2026-04",
        "last_month": "2026-03",
        "last_3_months": "2026-02~2026-04",
        "custom": "custom-range",
    }
    return mapping.get(range_name, "2026-04")


def _product_catalog_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = _query_payload(request)
    families = ["通用云服务器", "GPU 实例", "高可用网络方案"]
    if "gpu" not in query.lower() and "大模型" not in query:
        families = ["通用云服务器", "对象存储", "容器服务"]
    return _with_result(
        "已整理产品族和部署选型建议。",
        {"matched_query": query, "product_families": families, "next_step": "结合 RAG 文档补充规格建议"},
        "baseline://product-catalog",
    )


def _support_playbook_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = _query_payload(request)
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
        return "cn-shanghai-2"
    if "cn-bj1" in normalized or "beijing" in normalized:
        return "cn-beijing-1"
    if "cn-gz1" in normalized or "guangzhou" in normalized:
        return "cn-guangzhou-1"
    return "cn-shanghai-2"


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
        "checked_at": "2026-04-16T00:00:00+08:00",
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

    return _with_result(
        "已生成转人工交接摘要。",
        {
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
        },
        "baseline://support-handoff-brief",
    )


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

    if workload == "training" or budget_level == "performance":
        recommendation = {
            "recommended_instance_family": "GPU-GN8",
            "recommended_instance_type": "gn8.8xlarge",
            "gpu_model": "NVIDIA H100",
            "gpu_count": 8,
            "vcpu": 128,
            "memory_gb": 1024,
            "network_gbps": 200,
            "estimated_monthly_cost_cny": 198000,
            "rationale": [
                "适合 70B 级大模型训练、微调或长上下文实验。",
                "预留 NVLink / 高速网络带宽，便于分布式训练和参数同步。",
                "显存、CPU 与内存余量更适合生产级吞吐与扩容。",
            ],
            "alternatives": [
                {"instance_type": "gn8.4xlarge", "gpu_model": "NVIDIA H100", "scenario": "中等规模微调"},
                {"instance_type": "gi4.4xlarge", "gpu_model": "NVIDIA L40S", "scenario": "推理优先的中大型部署"},
            ],
        }
    elif budget_level == "cost_optimized":
        recommendation = {
            "recommended_instance_family": "GPU-GN6i",
            "recommended_instance_type": "gn6i.xlarge",
            "gpu_model": "NVIDIA A10",
            "gpu_count": 1,
            "vcpu": 16,
            "memory_gb": 64,
            "network_gbps": 25,
            "estimated_monthly_cost_cny": 18000,
            "rationale": [
                "适合 PoC、低成本验证和中小模型推理。",
                "单卡规格更容易控制预算并快速上线测试环境。",
                "可以先完成业务验证，再平滑升级到更高阶 GPU 机型。",
            ],
            "alternatives": [
                {"instance_type": "gn6i.2xlarge", "gpu_model": "NVIDIA A10", "scenario": "略高吞吐的推理场景"},
                {"instance_type": "gi4.2xlarge", "gpu_model": "NVIDIA L40S", "scenario": "量产前的性能升级"},
            ],
        }
    else:
        recommendation = {
            "recommended_instance_family": "GPU-GI4",
            "recommended_instance_type": "gi4.2xlarge",
            "gpu_model": "NVIDIA L40S",
            "gpu_count": 2,
            "vcpu": 32,
            "memory_gb": 128,
            "network_gbps": 50,
            "estimated_monthly_cost_cny": 42000,
            "rationale": [
                "适合 7B-70B 量化模型推理和大模型部署。",
                "双卡 L40S 在吞吐、显存与成本之间更均衡。",
                "便于后续挂接对象存储、负载均衡和弹性扩容。",
            ],
            "alternatives": [
                {"instance_type": "gn6i.2xlarge", "gpu_model": "NVIDIA A10", "scenario": "预算敏感推理"},
                {"instance_type": "gn8.4xlarge", "gpu_model": "NVIDIA H100", "scenario": "更高吞吐和训练预留"},
            ],
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
    return _with_result(
        "已生成云主机规格建议。",
        recommendation,
        "baseline://product-instance-recommendation",
    )


def _billing_query_statement_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    range_name = str(request.payload.get("range", "this_month"))
    billing_cycle = _current_billing_cycle(range_name)
    return _with_result(
        "已准备账单查询计划。",
        {
            "account_id": request.context.account_id or request.payload.get("account_id"),
            "range": range_name,
            "billing_cycle": billing_cycle,
            "statement_nos": [f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"],
            "preview_notice": "正式执行会返回账单汇总与明细样例。",
        },
        "baseline://billing-query-statement",
    )


def _billing_query_statement_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    range_name = str(request.payload.get("range", "this_month"))
    total_amount = {
        "this_month": 1288.32,
        "last_month": 1199.50,
        "last_3_months": 3688.18,
        "custom": 952.80,
    }.get(range_name, 1288.32)
    billing_cycle = _current_billing_cycle(range_name)
    return _with_result(
        "已返回账单汇总基线数据。",
        {
            "billing_cycle": billing_cycle,
            "range": range_name,
            "total_amount": total_amount,
            "currency": "CNY",
            "statement_nos": [f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"],
            "items": [
                {"product": "GPU 实例", "amount": round(total_amount * 0.69, 2)},
                {"product": "对象存储", "amount": round(total_amount * 0.16, 2)},
                {"product": "公网带宽", "amount": round(total_amount * 0.15, 2)},
            ],
            "top_instances": [
                {"instance_id": "gpu-cn-sh2-01", "amount": round(total_amount * 0.32, 2)},
                {"instance_id": "gpu-cn-sh2-02", "amount": round(total_amount * 0.24, 2)},
                {"instance_id": "ecs-cn-sh2-07", "amount": round(total_amount * 0.13, 2)},
            ],
        },
        "baseline://billing-query-statement",
    )


def _billing_query_instance_cost_profile(request: ToolInvocationRequest) -> dict[str, Any]:
    instance_id = str(request.payload.get("instance_id") or "inst_pending").strip()
    range_name = str(request.payload.get("range", "this_month"))
    billing_cycle = str(request.payload.get("billing_cycle") or _current_billing_cycle(range_name))
    if instance_id.startswith("gpu-"):
        product = "GPU 实例"
        instance_name = "智能算力实例"
        region = "cn-shanghai-2"
        total_amount = 412.68 if billing_cycle == "2026-04" else 386.40
    elif instance_id.startswith("ecs-"):
        product = "通用云服务器"
        instance_name = "通用计算实例"
        region = "cn-shanghai-2"
        total_amount = 168.42 if billing_cycle == "2026-04" else 154.76
    else:
        product = "云主机实例"
        instance_name = "云主机实例"
        region = "cn-hangzhou-1"
        total_amount = 238.60 if billing_cycle == "2026-04" else 224.30

    compute_amount = round(total_amount * 0.82, 2)
    storage_amount = round(total_amount * 0.12, 2)
    network_amount = round(total_amount - compute_amount - storage_amount, 2)
    statement_no = f"stmt_{billing_cycle.replace('-', '_').replace('~', '_')}_001"

    return {
        "instance_id": instance_id,
        "instance_name": instance_name,
        "product": product,
        "billing_cycle": billing_cycle,
        "range": range_name,
        "statement_no": statement_no,
        "currency": "CNY",
        "total_amount": total_amount,
        "daily_average_amount": round(total_amount / 30, 2),
        "compute_amount": compute_amount,
        "storage_amount": storage_amount,
        "network_amount": network_amount,
        "region": region,
    }


def _billing_query_instance_cost_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    profile = _billing_query_instance_cost_profile(request)
    return _with_result(
        "已整理实例费用查询草稿。",
        {
            **profile,
            "preview_notice": "正式执行会返回该实例的费用拆分和账期基线数据。",
        },
        "baseline://billing-query-instance-cost",
    )


def _billing_query_instance_cost_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    profile = _billing_query_instance_cost_profile(request)
    return _with_result(
        "已返回实例费用基线数据。",
        profile,
        "baseline://billing-query-instance-cost",
    )


def _order_query_order_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_no = request.payload.get("order_no") or request.payload.get("order_id") or "ord_pending"
    refund_no = request.payload.get("refund_no") or request.payload.get("refund_id")
    return _with_result(
        "已整理订单状态查询草稿。",
        {
            "order_no": order_no,
            "refund_no": refund_no,
            "order_status": "paid",
            "refund_status": "processing" if refund_no else "not_requested",
            "invoice_status": "submitted",
            "paid_amount": 1288.32,
            "currency": "CNY",
            "preview_notice": "正式执行会返回订单、退款与发票状态基线数据。",
        },
        "baseline://orders-status",
    )


def _order_query_order_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_no = request.payload.get("order_no") or request.payload.get("order_id") or "ord_pending"
    refund_no = request.payload.get("refund_no") or request.payload.get("refund_id")
    return _with_result(
        "已返回订单状态基线数据。",
        {
            "order_no": order_no,
            "order_status": "refunding" if refund_no else "paid",
            "refund_no": refund_no,
            "refund_status": "processing" if refund_no else "not_requested",
            "invoice_status": "submitted",
            "paid_amount": 1288.32,
            "currency": "CNY",
        },
        "baseline://orders-status",
    )


def _billing_create_invoice_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    statement_nos = request.payload.get("statement_nos") or ["stmt_2026_04_001"]
    return _with_result(
        "已整理开票申请草稿。",
        {
            "statement_nos": statement_nos,
            "invoice_type": request.payload.get("invoice_type", "vat_special"),
            "title": request.payload.get("title", "待确认抬头"),
            "estimated_amount": len(statement_nos) * 1288.32,
            "requires_confirmation": True,
        },
        "baseline://billing-create-invoice",
    )


def _billing_create_invoice_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    statement_nos = request.payload.get("statement_nos") or ["stmt_2026_04_001"]
    return _with_result(
        "已创建开票申请基线记录。",
        {
            "invoice_no": f"inv_{len(statement_nos):03d}_20260416",
            "status": "submitted",
            "amount": round(len(statement_nos) * 1288.32, 2),
            "title": request.payload.get("title", "待确认抬头"),
            "invoice_type": request.payload.get("invoice_type", "vat_special"),
            "statement_nos": statement_nos,
        },
        "baseline://billing-create-invoice",
    )


def _invoice_query_invoice_preview(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    invoice_no = request.payload.get("invoice_no") or "inv_pending"
    statement_nos = request.payload.get("statement_nos") or ["stmt_2026_04_001"]
    return _with_result(
        "已整理发票状态查询草稿。",
        {
            "invoice_no": invoice_no,
            "status": "processing",
            "amount": round(len(statement_nos) * 1288.32, 2),
            "title": request.payload.get("title", "待确认抬头"),
            "statement_nos": statement_nos,
            "preview_notice": "正式执行会返回发票申请状态基线数据。",
        },
        "baseline://invoice-query-status",
    )


def _invoice_query_invoice_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    invoice_no = request.payload.get("invoice_no") or "inv_pending"
    statement_nos = request.payload.get("statement_nos") or ["stmt_2026_04_001"]
    return _with_result(
        "已返回发票状态基线数据。",
        {
            "invoice_no": invoice_no,
            "status": "processing",
            "amount": round(len(statement_nos) * 1288.32, 2),
            "title": request.payload.get("title", "待确认抬头"),
            "statement_nos": statement_nos,
        },
        "baseline://invoice-query-status",
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
    return _with_result(
        "已创建退款申请基线记录。",
        {
            "order_no": order_no,
            "refund_no": f"refund_{order_no}",
            "status": "requested",
            "requested_amount": request.payload.get("amount", 0),
            "reason": request.payload.get("reason", "待补充"),
        },
        "baseline://order-create-refund",
    )


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


def _icp_material_check_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    materials = request.payload.get("materials") or []
    required_materials = ["营业执照", "负责人身份证", "域名证书", "网站负责人核验材料"]
    issues = []
    if len(materials) < 3:
        issues.append("材料数量不足，需补充主体证照与负责人证件。")
    return _with_result(
        "已完成备案材料校验基线分析。",
        {
            "passed": not issues,
            "issues": issues,
            "required_materials": required_materials,
            "subject_type": request.payload.get("subject_type", "enterprise"),
        },
        "baseline://icp-material-check",
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
            "domain": request.payload.get("domain", "pending.example.com"),
            "website_name": request.payload.get("website_name", "待确认站点"),
            "contacts": contacts,
            "requires_confirmation": True,
        },
        "baseline://icp-submit-application",
    )


def _icp_submit_application_execute(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    domain = request.payload.get("domain", "pending.example.com")
    contacts = request.payload.get("contacts", {})
    if not isinstance(contacts, dict):
        contacts = {}
    return _with_result(
        "已创建备案申请基线记录。",
        {
            "application_no": f"icp_{domain.replace('.', '_')}",
            "status": "submitted",
            "current_step": "provider_review",
            "latest_action": "服务商已受理备案申请，等待初审。",
            "domain": domain,
            "website_name": request.payload.get("website_name"),
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


def _campaign_lookup_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = _query_payload(request)
    product, product_summary = _marketing_product_context(request)
    effective_query = product_summary or product or query
    lowered_query = effective_query.lower()
    gpu_context = any(
        token in lowered_query
        for token in ("gpu", "l40s", "h100", "a10", "gi4", "gn6", "gn8", "算力", "大模型")
    ) or "大模型" in effective_query
    campaigns = [
        {
            "name": "GPU 新客满减",
            "segment": product_summary or "AI/大模型",
            "priority": "high",
        },
        {
            "name": "大模型部署代金券",
            "segment": product or "GPU 实例",
            "priority": "medium",
        },
    ]
    if not gpu_context:
        campaigns = [{"name": "春季通用云上云活动", "segment": "SMB", "priority": "medium"}]
    return _with_result(
        "已整理营销活动候选。",
        {
            "matched_query": query,
            "matched_product": product,
            "product_summary": product_summary or None,
            "campaigns": campaigns,
        },
        "baseline://marketing-campaign",
    )


def _poster_brief_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    product, product_summary = _marketing_product_context(request)
    theme = (
        request.payload.get("theme")
        or product_summary
        or _query_payload(request)
        or "云服务推广"
    )
    copy_points = ["高性能算力", "7x24 智能服务", "快速部署"]
    if product_summary:
        copy_points = [
            f"推荐机型：{product_summary}",
            "AI/大模型场景可快速上线",
            "弹性扩容与专家顾问协同跟进",
        ]
    return _with_result(
        "已生成海报 brief。",
        {
            "theme": theme,
            "product": product,
            "product_summary": product_summary or None,
            "cta": request.payload.get("cta", "立即咨询"),
            "visual_style": "科技蓝 + 工业风",
            "copy_points": copy_points,
        },
        "baseline://marketing-poster",
    )


def _marketing_copy_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    campaign_name = request.payload.get("campaign_name") or "待确认活动"
    product, product_summary = _marketing_product_context(request)
    display_product = product_summary or product
    channel = str(request.payload.get("channel", "web"))
    tone = str(request.payload.get("tone", "professional"))
    cta = str(request.payload.get("cta") or ("立即咨询" if channel == "web" else "联系专属顾问"))
    lead = {
        "professional": "为企业上云准备的稳健方案",
        "urgent": "限时窗口期内的优惠机会",
        "friendly": "轻量起步、快速见效的上云选择",
    }.get(tone, "为企业上云准备的稳健方案")
    bullets = [
        "高性能算力与弹性规格可按需扩容",
        "部署快，支持 AI/业务上云场景",
        "专属顾问和智能服务协同跟进",
    ]
    if product_summary:
        bullets = [
            f"{product_summary} 适合 AI/大模型场景快速上线",
            "规格清晰，可衔接营销落地页或销售跟进",
            "智能服务与专属顾问协同推进转化",
        ]
    return _with_result(
        "已生成营销文案草稿。",
        {
            "campaign_name": campaign_name,
            "product": product,
            "product_summary": product_summary or None,
            "channel": channel,
            "tone": tone,
            "headline": f"{campaign_name} | {display_product} 专属优惠",
            "body": (
                f"{lead}。围绕 {display_product} 提供高性能算力、弹性部署能力与 7x24 智能服务支持，"
                "适合需要稳定交付和快速上线的业务团队。"
            ),
            "bullets": bullets,
            "cta": cta,
        },
        "baseline://marketing-copy",
    )


def _marketing_poster_preview_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    _, product_summary = _marketing_product_context(request)
    theme = str(request.payload.get("theme") or _query_payload(request) or "云服务推广海报")
    campaign_name = str(request.payload.get("campaign_name") or "待确认活动")
    headline = str(request.payload.get("headline") or f"{campaign_name} | {product_summary or theme}")
    size = str(request.payload.get("size") or "portrait")
    channel = str(request.payload.get("channel") or "web")
    return _with_result(
        "已整理海报生成草稿。",
        {
            "theme": theme,
            "campaign_name": campaign_name,
            "headline": headline,
            "product_summary": product_summary or None,
            "cta": request.payload.get("cta", "立即咨询"),
            "size": size,
            "channel": channel,
            "visual_style": request.payload.get("visual_style", "科技蓝 + 工业风"),
            "preview_url": f"https://cdn.smartcloud.example/posters/preview/{_slugify_token(theme, fallback='poster')}-{size}.png",
            "render_status": "draft",
        },
        "baseline://marketing-poster-asset",
    )


def _marketing_poster_execute_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    _, product_summary = _marketing_product_context(request)
    theme = str(request.payload.get("theme") or _query_payload(request) or "云服务推广海报")
    campaign_name = str(request.payload.get("campaign_name") or "待确认活动")
    headline = str(request.payload.get("headline") or f"{campaign_name} | {product_summary or theme}")
    size = str(request.payload.get("size") or "portrait")
    channel = str(request.payload.get("channel") or "web")
    theme_slug = _slugify_token(theme, fallback="poster")
    campaign_slug = _slugify_token(campaign_name, fallback="campaign")
    return _with_result(
        "已生成营销海报资产。",
        {
            "poster_asset_id": f"poster_{campaign_slug}_{size}",
            "theme": theme,
            "campaign_name": campaign_name,
            "headline": headline,
            "product_summary": product_summary or None,
            "cta": request.payload.get("cta", "立即咨询"),
            "size": size,
            "channel": channel,
            "preview_url": f"https://cdn.smartcloud.example/posters/{campaign_slug}/{theme_slug}-{size}-preview.png",
            "download_path": f"/artifacts/posters/{campaign_slug}-{size}.png",
            "render_status": "generated",
        },
        "baseline://marketing-poster-asset",
    )


def _promotion_link_preview_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    campaign_name = request.payload.get("campaign_name") or "待确认活动"
    channel = request.payload.get("channel", "web")
    campaign_slug = _slugify_token(campaign_name, fallback="campaign")
    return _with_result(
        "已整理推广链接草稿。",
        {
            "campaign_name": campaign_name,
            "channel": channel,
            "landing_page": request.payload.get("landing_page", "https://smartcloud.example.com/campaigns"),
            "short_url_preview": f"https://scx.example/p/{campaign_slug}-{channel}",
            "utm_campaign": campaign_slug,
            "utm_source": channel,
        },
        "baseline://marketing-promotion-link",
    )


def _marketing_product_context(request: ToolInvocationRequest) -> tuple[str, str]:
    raw_product = request.payload.get("product")
    if isinstance(raw_product, list):
        product = next((str(item).strip() for item in raw_product if str(item).strip()), "")
    else:
        product = str(raw_product or "").strip()

    product_summary = str(request.payload.get("product_summary") or "").strip()
    if not product and product_summary:
        product = product_summary
    if not product:
        product = "SmartCloud 云服务"
    return product, product_summary


def _promotion_link_execute_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    campaign_name = request.payload.get("campaign_name") or "待确认活动"
    channel = str(request.payload.get("channel", "web"))
    campaign_slug = _slugify_token(campaign_name, fallback="campaign")
    return _with_result(
        "已生成推广链接。",
        {
            "promotion_link_id": f"promo_{campaign_slug}_{channel}",
            "campaign_name": campaign_name,
            "channel": channel,
            "landing_page": request.payload.get("landing_page", "https://smartcloud.example.com/campaigns"),
            "short_url": f"https://scx.example/p/{campaign_slug}-{channel}",
            "utm_campaign": campaign_slug,
            "utm_source": channel,
            "status": "active",
        },
        "baseline://marketing-promotion-link",
    )


def _research_generate_report_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"
    return _with_result(
        "已生成调研报告基线结构。",
        {
            "topic": topic,
            "executive_summary": "建议优先采用稳定可观测的多 Agent + Tool Hub 组合架构。",
            "outline": [
                "业务背景与目标",
                "候选方案对比",
                "成本与风险评估",
                "推荐路线与下一步行动",
            ],
        },
        "baseline://research-generate-report",
    )


def _research_reference_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"
    return _with_result(
        "已收集调研参考源。",
        {
            "topic": topic,
            "references": [
                {"title": "LangGraph overview", "type": "official-doc"},
                {"title": "AWS Saga orchestration pattern", "type": "architecture"},
                {"title": "Phoenix observability docs", "type": "observability"},
            ],
        },
        "baseline://research-references",
    )


def _research_export_report_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    topic = request.payload.get("topic") or _query_payload(request) or "待补充研究主题"
    export_format = str(request.payload.get("format", "markdown")).lower()
    if export_format not in {"markdown", "pdf"}:
        export_format = "markdown"
    topic_slug = _slugify_token(topic, fallback="research-report")
    outline = _normalize_string_list(request.payload.get("outline")) or [
        "业务背景与目标",
        "候选方案对比",
        "成本与风险评估",
        "推荐路线与下一步行动",
    ]
    reference_titles = _normalize_string_list(request.payload.get("reference_titles"))
    content_preview = "\n".join(
        [
            f"# {topic}",
            "",
            "## 摘要",
            "建议优先采用稳定可观测的多 Agent + Tool Hub 组合架构。",
            "",
            "## 目录",
            *[f"- {item}" for item in outline[:4]],
        ]
    )
    if reference_titles:
        content_preview = "\n".join(
            [
                content_preview,
                "",
                "## 参考资料",
                *[f"- {title}" for title in reference_titles[:3]],
            ]
        )
    extension = "md" if export_format == "markdown" else "pdf"
    return _with_result(
        "已导出调研报告基线文件。",
        {
            "artifact_id": f"research_{topic_slug}_{export_format}",
            "topic": topic,
            "format": export_format,
            "download_path": f"/artifacts/research/{topic_slug}.{extension}",
            "content_preview": content_preview,
            "line_count": len(content_preview.splitlines()),
        },
        "baseline://research-export-report",
    )


def _legacy_order_status_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    order_id = request.payload.get("order_id") or "order-preview"
    refund_id = request.payload.get("refund_id")
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
    total_amount = {
        "2026-04": 1288.32,
        "2026-03": 1199.50,
        "2026-02": 1200.36,
    }.get(month, 952.80)
    return _with_result(
        "已返回历史账单汇总基线数据。",
        {
            "billing_cycle": month,
            "month": month,
            "total_amount": total_amount,
            "currency": "CNY",
            "statement_nos": [f"stmt_{month.replace('-', '_')}_001"],
            "items": [
                {"product": "云服务器", "amount": round(total_amount * 0.62, 2)},
                {"product": "对象存储", "amount": round(total_amount * 0.18, 2)},
                {"product": "公网带宽", "amount": round(total_amount * 0.20, 2)},
            ],
        },
        "baseline://billing-summary-legacy",
    )


def _legacy_icp_checklist_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    entity_type = request.payload.get("entity_type", "企业")
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


def _dedupe_ordered_strings(values: list[str]) -> list[str]:
    ordered: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return ordered


def _schema_property_from_hint(hint: Any) -> dict[str, Any]:
    if isinstance(hint, dict):
        return dict(hint)

    normalized = str(hint or "string").strip()
    optional = normalized.endswith("?")
    if optional:
        normalized = normalized[:-1]

    if normalized.endswith("[]"):
        items_schema = _schema_property_from_hint(normalized[:-2] or "string")
        items_schema.pop("nullable", None)
        schema: dict[str, Any] = {"type": "array", "items": items_schema}
    elif "|" in normalized:
        schema = {
            "type": "string",
            "enum": [part for part in normalized.split("|") if part],
        }
    else:
        schema = {
            "string": {"type": "string"},
            "integer": {"type": "integer"},
            "number": {"type": "number"},
            "boolean": {"type": "boolean"},
            "object": {"type": "object"},
        }.get(normalized, {"type": "string"})

    if optional:
        schema["nullable"] = True
    return schema


def _schema_from_hint(
    properties_hint: dict[str, Any],
    *,
    required_fields: list[str] | None = None,
    field_hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for field_name, hint in properties_hint.items():
        property_schema = _schema_property_from_hint(hint)
        if field_hints and field_name in field_hints:
            property_schema.setdefault("description", field_hints[field_name])
        properties[field_name] = property_schema

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required_fields:
        schema["required"] = required_fields
    return schema


def _tool(
    *,
    name: str,
    capability: str,
    description: str,
    tags: list[str],
    input_schema_hint: dict[str, Any],
    input_field_hints: dict[str, str] | None = None,
    output_schema_hint: dict[str, Any],
    session_context_bindings: dict[str, list[str]] | None = None,
    session_context_output_keys: list[str] | None = None,
    prerequisite_tool_names: list[str] | None = None,
    mode: ToolMode = "query",
    auth_requirements: ToolAuthRequirements | None = None,
    operation_required_fields: dict[ToolOperation, list[str]] | None = None,
    timeout_ms: int = 5000,
    idempotent: bool = True,
    idempotency_window_seconds: int | None = None,
    high_risk: bool = False,
    cache_ttl_seconds: int | None = None,
    preview_builder: ResultBuilder,
    execute_builder: ResultBuilder | None = None,
) -> StaticBusinessTool:
    ordered_required_fields = _dedupe_ordered_strings(
        [
            field
            for fields in (operation_required_fields or {}).values()
            for field in fields
        ]
    )
    effective_field_hints = input_field_hints or {}
    return StaticBusinessTool(
        ToolDefinition(
            name=name,
            capability=capability,
            description=description,
            tags=tags,
            input_schema=_schema_from_hint(
                input_schema_hint,
                required_fields=ordered_required_fields,
                field_hints=effective_field_hints,
            ),
            input_schema_hint=input_schema_hint,
            input_field_hints=effective_field_hints,
            output_schema=_schema_from_hint(output_schema_hint),
            output_schema_hint=output_schema_hint,
            session_context_bindings=session_context_bindings or {},
            session_context_output_keys=session_context_output_keys or [],
            prerequisite_tool_names=prerequisite_tool_names or [],
            mode=mode,
            auth_requirements=auth_requirements or ToolAuthRequirements(),
            operation_required_fields=operation_required_fields or {},
            timeout_ms=timeout_ms,
            idempotent=idempotent,
            idempotency_window_seconds=idempotency_window_seconds,
            high_risk=high_risk,
            cache_ttl_seconds=cache_ttl_seconds,
        ),
        preview_builder=preview_builder,
        execute_builder=execute_builder,
    )


def build_catalog() -> dict[str, BusinessTool]:
    tools = [
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
        _tool(
            name="billing.query_statement",
            capability="finance-order",
            description="Prepare or execute monthly billing summary lookup.",
            tags=["billing", "finance"],
            input_schema_hint={"range": "this_month|last_month|last_3_months|custom", "start_date": "string?", "end_date": "string?"},
            input_field_hints={
                "range": "需要确认账单范围，例如本月、上月或最近三个月。",
            },
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
            input_field_hints={
                "instance_id": "需要确认实例 ID，例如 gpu-cn-sh2-01 或 ecs-cn-sh2-07。",
            },
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
            description="Query order payment and refund status by order number.",
            tags=["order", "refund", "query"],
            input_schema_hint={"order_no": "string", "refund_no": "string?"},
            input_field_hints={
                "order_no": "需要确认订单号。",
            },
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
            operation_required_fields={"execute": ["order_no"]},
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
            input_field_hints={
                "invoice_no": "需要确认发票申请单号。",
            },
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
            session_context_bindings={
                "ticket_no": ["open_ticket_id"],
            },
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
            description="Query support ticket status and the latest progress by ticket number.",
            tags=["ticket", "query", "status"],
            input_schema_hint={"ticket_no": "string", "subject": "string?", "reply_no": "string?"},
            input_field_hints={
                "ticket_no": "需要确认工单编号。",
            },
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
            operation_required_fields={"execute": ["ticket_no"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=45,
            preview_builder=_ticket_query_ticket_preview,
            execute_builder=_ticket_query_ticket_execute,
        ),
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
            description="Query ICP filing application status by application number.",
            tags=["icp", "query", "status"],
            input_schema_hint={"application_no": "string", "domain": "string?"},
            input_field_hints={
                "application_no": "需要确认备案申请号。",
            },
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
            operation_required_fields={"execute": ["application_no"]},
            timeout_ms=5000,
            idempotent=True,
            cache_ttl_seconds=60,
            preview_builder=_icp_query_application_preview,
            execute_builder=_icp_query_application_execute,
        ),
        _tool(
            name="marketing.campaign_lookup",
            capability="ops-marketing",
            description="Find campaigns and hooks for a product or segment.",
            tags=["marketing", "campaign", "promotion"],
            input_schema_hint={
                "product": "string?",
                "product_summary": "string?",
                "user_query": "string?",
            },
            output_schema_hint={
                "matched_query": "string",
                "matched_product": "string",
                "product_summary": "string?",
                "campaigns": "object[]",
            },
            session_context_bindings={
                "product": [
                    "attributes.recommended_instance_type",
                    "attributes.recommended_instance_family",
                    "active_products",
                ],
                "product_summary": [
                    "attributes.recommended_instance_summary",
                    "attributes.last_marketing_product_summary",
                ],
            },
            session_context_output_keys=[
                "active_products",
                "attributes.last_campaign_name",
                "attributes.last_marketing_product_summary",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:marketing.read"],
            ),
            cache_ttl_seconds=120,
            preview_builder=_campaign_lookup_builder,
        ),
        _tool(
            name="marketing.poster_brief",
            capability="ops-marketing",
            description="Prepare poster/copy brief for downstream creative generation.",
            tags=["marketing", "poster", "creative"],
            input_schema_hint={
                "theme": "string",
                "product_summary": "string?",
                "cta": "string?",
            },
            input_field_hints={
                "theme": "需要确认海报主题或宣传方向。",
            },
            output_schema_hint={
                "theme": "string",
                "product": "string",
                "product_summary": "string?",
                "copy_points": "string[]",
            },
            session_context_bindings={
                "theme": ["attributes.poster_theme", "attributes.recommended_instance_summary"],
                "product_summary": [
                    "attributes.recommended_instance_summary",
                    "attributes.last_marketing_product_summary",
                ],
            },
            session_context_output_keys=[
                "attributes.poster_theme",
                "attributes.poster_cta",
                "attributes.last_marketing_product_summary",
            ],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:marketing.write"],
            ),
            operation_required_fields={"preview": ["theme"], "execute": ["theme"]},
            cache_ttl_seconds=120,
            preview_builder=_poster_brief_builder,
            execute_builder=_poster_brief_builder,
        ),
        _tool(
            name="marketing.generate_copy",
            capability="ops-marketing",
            description="Generate short-form marketing copy for a selected campaign.",
            tags=["marketing", "copy", "creative"],
            input_schema_hint={
                "campaign_name": "string",
                "product": "string?",
                "product_summary": "string?",
                "channel": "web|wechat|email|sms?",
                "tone": "professional|urgent|friendly?",
                "cta": "string?",
            },
            input_field_hints={
                "campaign_name": "需要先确认要生成文案的营销活动名称，可先查询活动后再生成。",
            },
            output_schema_hint={
                "headline": "string",
                "body": "string",
                "bullets": "string[]",
                "cta": "string",
                "product_summary": "string?",
            },
            session_context_bindings={
                "campaign_name": ["attributes.last_campaign_name"],
                "product": [
                    "attributes.recommended_instance_type",
                    "attributes.recommended_instance_family",
                    "active_products",
                ],
                "product_summary": [
                    "attributes.recommended_instance_summary",
                    "attributes.last_marketing_product_summary",
                ],
                "channel": ["attributes.promotion_channel"],
            },
            session_context_output_keys=[
                "attributes.last_marketing_copy_headline",
                "attributes.last_marketing_copy_body",
                "attributes.last_marketing_copy_campaign_name",
                "attributes.last_marketing_copy_channel",
                "attributes.last_marketing_copy_cta",
                "attributes.last_marketing_product_summary",
            ],
            prerequisite_tool_names=["marketing.campaign_lookup"],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:marketing.write"],
            ),
            operation_required_fields={"preview": ["campaign_name"], "execute": ["campaign_name"]},
            cache_ttl_seconds=120,
            preview_builder=_marketing_copy_builder,
            execute_builder=_marketing_copy_builder,
        ),
        _tool(
            name="marketing.generate_promotion_link",
            capability="ops-marketing",
            description="Create a tracked promotion link for a selected campaign.",
            tags=["marketing", "promotion-link", "write"],
            input_schema_hint={
                "campaign_name": "string",
                "channel": "web|wechat|email|sms?",
                "landing_page": "string?",
            },
            input_field_hints={
                "campaign_name": "需要先确认要绑定的营销活动名称。",
            },
            output_schema_hint={
                "promotion_link_id": "string",
                "short_url": "string",
                "utm_campaign": "string",
                "utm_source": "string",
            },
            session_context_bindings={
                "campaign_name": ["attributes.last_campaign_name"],
                "channel": ["attributes.promotion_channel"],
                "landing_page": ["attributes.landing_page", "attributes.website_url"],
            },
            session_context_output_keys=[
                "attributes.last_promotion_link_id",
                "attributes.last_promotion_link",
                "attributes.promotion_channel",
            ],
            prerequisite_tool_names=["marketing.campaign_lookup"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:marketing.write"],
            ),
            operation_required_fields={"execute": ["campaign_name"]},
            timeout_ms=10000,
            idempotent=True,
            idempotency_window_seconds=86400,
            preview_builder=_promotion_link_preview_builder,
            execute_builder=_promotion_link_execute_builder,
        ),
        _tool(
            name="marketing.generate_poster",
            capability="ops-marketing",
            description="Generate a poster asset from the prepared poster brief and campaign context.",
            tags=["marketing", "poster", "creative", "write"],
            input_schema_hint={
                "theme": "string",
                "campaign_name": "string?",
                "headline": "string?",
                "product_summary": "string?",
                "cta": "string?",
                "size": "portrait|landscape|square?",
                "channel": "web|wechat|email|sms?",
            },
            input_field_hints={
                "theme": "需要先确认海报主题，可先生成海报 brief 后再出图。",
            },
            output_schema_hint={
                "poster_asset_id": "string",
                "preview_url": "string",
                "download_path": "string",
                "headline": "string",
                "size": "string",
                "campaign_name": "string",
                "product_summary": "string?",
            },
            session_context_bindings={
                "theme": ["attributes.poster_theme"],
                "campaign_name": ["attributes.last_campaign_name", "attributes.last_marketing_copy_campaign_name"],
                "headline": ["attributes.poster_headline", "attributes.last_marketing_copy_headline"],
                "product_summary": [
                    "attributes.recommended_instance_summary",
                    "attributes.last_marketing_product_summary",
                ],
                "cta": ["attributes.poster_cta", "attributes.last_marketing_copy_cta"],
                "channel": ["attributes.last_marketing_copy_channel", "attributes.promotion_channel"],
            },
            session_context_output_keys=[
                "attributes.poster_asset_id",
                "attributes.poster_preview_url",
                "attributes.poster_download_path",
                "attributes.poster_headline",
                "attributes.poster_size",
                "attributes.poster_theme",
                "attributes.last_campaign_name",
                "attributes.last_marketing_product_summary",
            ],
            prerequisite_tool_names=["marketing.poster_brief"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:marketing.write"],
            ),
            operation_required_fields={"execute": ["theme"]},
            timeout_ms=10000,
            idempotent=True,
            idempotency_window_seconds=86400,
            preview_builder=_marketing_poster_preview_builder,
            execute_builder=_marketing_poster_execute_builder,
        ),
        _tool(
            name="research.generate_report",
            capability="deep-research",
            description="Create a structured report skeleton for research tasks.",
            tags=["research", "report"],
            input_schema_hint={"topic": "string"},
            input_field_hints={
                "topic": "需要确认调研主题。",
            },
            output_schema_hint={"topic": "string", "executive_summary": "string", "outline": "string[]"},
            session_context_output_keys=["attributes.research_topic", "attributes.report_outline"],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:research.write"],
            ),
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            cache_ttl_seconds=300,
            preview_builder=_research_generate_report_builder,
            execute_builder=_research_generate_report_builder,
        ),
        _tool(
            name="research.reference_search",
            capability="deep-research",
            description="Collect references for research tasks.",
            tags=["research", "references"],
            input_schema_hint={"topic": "string", "limit": "integer?"},
            input_field_hints={
                "topic": "需要确认调研主题。",
            },
            output_schema_hint={"references": "object[]"},
            session_context_bindings={"topic": ["attributes.research_topic"]},
            session_context_output_keys=["attributes.reference_titles"],
            prerequisite_tool_names=["research.generate_report"],
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:research.write"],
            ),
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            cache_ttl_seconds=300,
            preview_builder=_research_reference_builder,
            execute_builder=_research_reference_builder,
        ),
        _tool(
            name="research.export_report",
            capability="deep-research",
            description="Export the prepared research report to markdown or PDF.",
            tags=["research", "export", "artifact"],
            input_schema_hint={
                "topic": "string",
                "format": "markdown|pdf?",
                "outline": "string[]?",
                "reference_titles": "string[]?",
            },
            input_field_hints={
                "topic": "需要先确认调研主题或先生成调研报告。",
            },
            output_schema_hint={
                "artifact_id": "string",
                "format": "string",
                "download_path": "string",
                "content_preview": "string",
                "line_count": "integer",
            },
            session_context_bindings={
                "topic": ["attributes.research_topic"],
                "outline": ["attributes.report_outline"],
                "reference_titles": ["attributes.reference_titles"],
            },
            session_context_output_keys=[
                "attributes.last_report_export_id",
                "attributes.last_report_export_path",
                "attributes.last_report_export_format",
            ],
            prerequisite_tool_names=["research.reference_search"],
            mode="write",
            auth_requirements=ToolAuthRequirements(
                require_user_id=True,
                required_permissions=["user:research.write"],
            ),
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            timeout_ms=12000,
            idempotent=True,
            idempotency_window_seconds=86400,
            preview_builder=_research_export_report_builder,
            execute_builder=_research_export_report_builder,
        ),
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
            input_field_hints={
                "month": "需要确认账单月份，例如 2026-04。",
            },
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
            input_field_hints={
                "application_id": "需要确认备案申请号。",
            },
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
            input_field_hints={
                "topic": "需要确认调研主题。",
            },
            output_schema_hint={"outline": "string[]"},
            operation_required_fields={"preview": ["topic"], "execute": ["topic"]},
            cache_ttl_seconds=300,
            preview_builder=_legacy_research_outline_builder,
            execute_builder=_legacy_research_outline_builder,
        ),
    ]
    return {tool.definition.name: tool for tool in tools}


def filter_tool_definitions(
    items: Iterable[BusinessTool | ToolDefinition],
    *,
    capability: str | None = None,
    mode: ToolMode | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> list[ToolDefinition]:
    normalized_capability = capability.strip().lower() if capability else None
    normalized_mode = str(mode).strip().lower() if mode else None
    normalized_tag = tag.strip().lower() if tag else None
    normalized_query = query.strip().lower() if query else None

    definitions: list[ToolDefinition] = []
    for item in items:
        definition = item.definition if hasattr(item, "definition") else item
        searchable = " ".join(
            [
                definition.name,
                definition.capability,
                definition.description,
                *definition.tags,
            ]
        ).lower()
        if normalized_capability and definition.capability.lower() != normalized_capability:
            continue
        if normalized_mode and definition.mode.lower() != normalized_mode:
            continue
        if normalized_tag and normalized_tag not in {value.lower() for value in definition.tags}:
            continue
        if normalized_query and normalized_query not in searchable:
            continue
        definitions.append(definition.model_copy(deep=True))
    definitions.sort(key=lambda item: item.name)
    return definitions
