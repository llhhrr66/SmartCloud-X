from __future__ import annotations

from typing import Any

from business_tools.interfaces import ToolDefinition, ToolInvocationRequest

from ._helpers import _list_strings, _normalize_string_list


def _build_session_context_patch(
    definition: ToolDefinition,
    request: ToolInvocationRequest,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Compute the session-context patch produced by a successful tool call.

    Each branch maps a specific tool's result back into the session-context
    keys downstream agents and routing rules look at. Kept exhaustive (rather
    than table-driven) because the mapping shapes vary widely per tool.
    """
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
