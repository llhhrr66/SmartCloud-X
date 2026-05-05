from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from business_tools.db import execute_write, query_all, query_one
from business_tools.interfaces import ToolAuthRequirements, ToolInvocationRequest

from .._factory import _tool
from .._helpers import _query_payload, _slugify_token, _with_result
from .._static_tool import StaticBusinessTool


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


# ---------------------------------------------------------------------------
# campaign_lookup
# ---------------------------------------------------------------------------

def _campaign_lookup_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    query = _query_payload(request)
    product, product_summary = _marketing_product_context(request)
    effective_query = product_summary or product or query
    lowered_query = effective_query.lower()
    gpu_context = any(
        token in lowered_query
        for token in ("gpu", "l40s", "h100", "a10", "gi4", "gn6", "gn8", "算力", "大模型")
    ) or "大模型" in effective_query

    # Try DB first
    if gpu_context:
        rows = query_all(
            "SELECT campaign_id, name, product_type, status, target_segment, "
            "discount_type, discount_value, discount_description, highlights "
            "FROM marketing_campaigns "
            "WHERE product_type = 'gpu' AND deleted_at IS NULL AND status = 'published' "
            "ORDER BY start_at DESC LIMIT 10",
        )
    else:
        rows = query_all(
            "SELECT campaign_id, name, product_type, status, target_segment, "
            "discount_type, discount_value, discount_description, highlights "
            "FROM marketing_campaigns "
            "WHERE deleted_at IS NULL AND status = 'published' "
            "ORDER BY start_at DESC LIMIT 10",
        )

    if rows:
        campaigns = []
        for r in rows:
            entry: dict[str, Any] = {
                "name": r["name"],
                "campaign_id": r["campaign_id"],
                "segment": r.get("target_segment") or r.get("product_type", ""),
                "priority": "high" if r.get("product_type") == "gpu" else "medium",
            }
            if r.get("discount_type"):
                entry["discount"] = {
                    "type": r["discount_type"],
                    "value": r.get("discount_value"),
                    "description": r.get("discount_description"),
                }
            highlights = r.get("highlights")
            if isinstance(highlights, str):
                try:
                    highlights = json.loads(highlights)
                except (json.JSONDecodeError, TypeError):
                    highlights = []
            if highlights:
                entry["highlights"] = highlights
            campaigns.append(entry)
        return _with_result(
            "已整理营销活动候选。",
            {
                "matched_query": query,
                "matched_product": product,
                "product_summary": product_summary or None,
                "campaigns": campaigns,
            },
            "db://marketing-campaigns",
        )

    # Fallback: empty baseline
    campaigns: list[dict[str, Any]] = []
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


# ---------------------------------------------------------------------------
# poster_brief
# ---------------------------------------------------------------------------

def _poster_brief_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    product, product_summary = _marketing_product_context(request)
    theme = (
        request.payload.get("theme")
        or product_summary
        or _query_payload(request)
        or "云服务推广"
    )

    # Try to enrich from campaign data
    campaign_name = request.payload.get("campaign_name")
    if campaign_name:
        row = query_one(
            "SELECT highlights, landing_page_url, discount_description "
            "FROM marketing_campaigns "
            "WHERE name = :name AND deleted_at IS NULL LIMIT 1",
            {"name": campaign_name},
        )
        if row:
            copy_points: list[str] = []
            highlights = row.get("highlights")
            if isinstance(highlights, str):
                try:
                    highlights = json.loads(highlights)
                except (json.JSONDecodeError, TypeError):
                    highlights = []
            if isinstance(highlights, list) and highlights:
                copy_points = [str(h) for h in highlights]
            if row.get("discount_description"):
                copy_points.append(row["discount_description"])
            if copy_points:
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
                    "db://marketing-campaigns",
                )

    # Fallback
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


# ---------------------------------------------------------------------------
# marketing_copy
# ---------------------------------------------------------------------------

def _marketing_copy_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    campaign_name = request.payload.get("campaign_name") or "待确认活动"
    product, product_summary = _marketing_product_context(request)
    display_product = product_summary or product
    channel = str(request.payload.get("channel", "web"))
    tone = str(request.payload.get("tone", "professional"))
    cta = str(request.payload.get("cta") or ("立即咨询" if channel == "web" else "联系专属顾问"))

    # On execute, try to look up existing copy and/or write new one
    if request.operation == "execute":
        user_id = request.context.user_id
        tenant_id = request.context.tenant_id

        # Look up campaign_id from campaign_name
        campaign_row = query_one(
            "SELECT campaign_id, name FROM marketing_campaigns "
            "WHERE name = :name AND deleted_at IS NULL LIMIT 1",
            {"name": campaign_name},
        )
        campaign_id = campaign_row["campaign_id"] if campaign_row else _slugify_token(campaign_name, fallback="campaign")

        copy_id = f"copy_{_slugify_token(campaign_name, fallback='copy')}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        lead = {
            "professional": "为企业上云准备的稳健方案",
            "urgent": "限时窗口期内的优惠机会",
            "friendly": "轻量起步、快速见效的上云选择",
        }.get(tone, "为企业上云准备的稳健方案")
        headline = f"{campaign_name} | {display_product} 专属优惠"
        body = (
            f"{lead}。围绕 {display_product} 提供高性能算力、弹性部署能力与 7x24 智能服务支持，"
            "适合需要稳定交付和快速上线的业务团队。"
        )
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
        keywords = bullets[:2]
        affected = execute_write(
            "INSERT INTO marketing_generated_copies "
            "(copy_id, user_id, tenant_id, campaign_id, campaign_name, topic, audience, "
            "tone, headline, summary, body, call_to_action, keywords, created_at) "
            "VALUES (:cid, :uid, :tid, :campid, :cname, :topic, :audience, "
            ":tone, :headline, :summary, :body, :cta, :keywords, NOW())",
            {
                "cid": copy_id,
                "uid": user_id,
                "tid": tenant_id,
                "campid": campaign_id,
                "cname": campaign_name,
                "topic": display_product,
                "audience": request.payload.get("audience", "企业客户"),
                "tone": tone,
                "headline": headline,
                "summary": lead,
                "body": body,
                "cta": cta,
                "keywords": json.dumps(keywords, ensure_ascii=False),
            },
        )
        if affected > 0:
            return _with_result(
                "已生成营销文案。",
                {
                    "copy_id": copy_id,
                    "campaign_name": campaign_name,
                    "product": product,
                    "product_summary": product_summary or None,
                    "channel": channel,
                    "tone": tone,
                    "headline": headline,
                    "body": body,
                    "bullets": bullets,
                    "cta": cta,
                },
                "db://marketing-generated-copies/" + copy_id,
            )

    # Try to look up existing copy for preview
    existing = query_one(
        "SELECT headline, summary, body, call_to_action, tone, keywords "
        "FROM marketing_generated_copies "
        "WHERE campaign_name = :cname ORDER BY created_at DESC LIMIT 1",
        {"cname": campaign_name},
    )
    if existing:
        bullets: list[str] = []
        kw = existing.get("keywords")
        if isinstance(kw, str):
            try:
                kw = json.loads(kw)
            except (json.JSONDecodeError, TypeError):
                kw = []
        if isinstance(kw, list) and kw:
            bullets = [str(k) for k in kw]
        else:
            bullets = [
                "高性能算力与弹性规格可按需扩容",
                "部署快，支持 AI/业务上云场景",
            ]
        return _with_result(
            "已整理营销文案草稿。",
            {
                "campaign_name": campaign_name,
                "product": product,
                "product_summary": product_summary or None,
                "channel": channel,
                "tone": existing.get("tone", tone),
                "headline": existing["headline"],
                "body": existing["body"],
                "bullets": bullets,
                "cta": existing.get("call_to_action", cta),
            },
            "db://marketing-generated-copies",
        )

    # Fallback
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


# ---------------------------------------------------------------------------
# marketing_poster (preview + execute)
# ---------------------------------------------------------------------------

def _marketing_poster_preview_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    _, product_summary = _marketing_product_context(request)
    theme = str(request.payload.get("theme") or _query_payload(request) or "云服务推广海报")
    campaign_name = str(request.payload.get("campaign_name") or "待确认活动")
    headline = str(request.payload.get("headline") or f"{campaign_name} | {product_summary or theme}")
    size = str(request.payload.get("size") or "portrait")
    channel = str(request.payload.get("channel") or "web")

    # Try to look up existing poster task
    row = query_one(
        "SELECT task_id, image_url, status, slogan FROM marketing_poster_tasks "
        "WHERE campaign_name = :cname AND theme = :theme AND status = 'completed' "
        "ORDER BY created_at DESC LIMIT 1",
        {"cname": campaign_name, "theme": theme},
    )
    if row and row.get("image_url"):
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
                "preview_url": row["image_url"],
                "render_status": "draft",
            },
            "db://marketing-poster-tasks/" + row["task_id"],
        )

    # Fallback
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
            "preview_url": f"/assets/posters/preview/{_slugify_token(theme, fallback='poster')}-{size}.png",
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

    # On execute, write poster task to DB
    if request.operation == "execute":
        user_id = request.context.user_id
        tenant_id = request.context.tenant_id

        # Look up campaign_id
        campaign_row = query_one(
            "SELECT campaign_id FROM marketing_campaigns "
            "WHERE name = :name AND deleted_at IS NULL LIMIT 1",
            {"name": campaign_name},
        )
        campaign_id = campaign_row["campaign_id"] if campaign_row else campaign_slug

        task_id = f"poster_{_slugify_token(campaign_name, fallback='poster')}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        affected = execute_write(
            "INSERT INTO marketing_poster_tasks "
            "(task_id, user_id, tenant_id, campaign_id, campaign_name, theme, slogan, size, status, created_at, estimated_seconds) "
            "VALUES (:tid, :uid, :tid2, :campid, :cname, :theme, :slogan, :size, 'pending', NOW(), 30)",
            {
                "tid": task_id,
                "uid": user_id,
                "tid2": tenant_id,
                "campid": campaign_id,
                "cname": campaign_name,
                "theme": theme,
                "slogan": headline,
                "size": size,
            },
        )
        if affected > 0:
            return _with_result(
                "已创建海报生成任务。",
                {
                    "poster_asset_id": task_id,
                    "theme": theme,
                    "campaign_name": campaign_name,
                    "headline": headline,
                    "product_summary": product_summary or None,
                    "cta": request.payload.get("cta", "立即咨询"),
                    "size": size,
                    "channel": channel,
                    "preview_url": f"/artifacts/posters/{task_id}.png",
                    "download_path": f"/artifacts/posters/{task_id}.png",
                    "render_status": "pending",
                },
                "db://marketing-poster-tasks/" + task_id,
            )

    # Fallback
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
            "preview_url": f"/assets/posters/{campaign_slug}/{theme_slug}-{size}-preview.png",
            "download_path": f"/artifacts/posters/{campaign_slug}-{size}.png",
            "render_status": "generated",
        },
        "baseline://marketing-poster-asset",
    )


# ---------------------------------------------------------------------------
# promotion_link (preview + execute)
# ---------------------------------------------------------------------------

def _promotion_link_preview_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    campaign_name = request.payload.get("campaign_name") or "待确认活动"
    channel = request.payload.get("channel", "web")
    campaign_slug = _slugify_token(campaign_name, fallback="campaign")

    # Try to look up existing link
    row = query_one(
        "SELECT link_id, short_url, landing_page_url, tracking_code FROM marketing_promotion_links "
        "WHERE campaign_name = :cname AND channel = :channel "
        "ORDER BY created_at DESC LIMIT 1",
        {"cname": campaign_name, "channel": channel},
    )
    if row:
        # Parse tracking_code into utm params
        utm_campaign = campaign_slug
        utm_source = channel
        tracking = row.get("tracking_code", "")
        for part in tracking.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                if k == "utm_campaign":
                    utm_campaign = v
                elif k == "utm_source":
                    utm_source = v
        return _with_result(
            "已整理推广链接草稿。",
            {
                "campaign_name": campaign_name,
                "channel": channel,
                "landing_page": row.get("landing_page_url", request.payload.get("landing_page", "")),
                "short_url_preview": row["short_url"],
                "utm_campaign": utm_campaign,
                "utm_source": utm_source,
            },
            "db://marketing-promotion-links/" + row["link_id"],
        )

    # Fallback
    return _with_result(
        "已整理推广链接草稿。",
        {
            "campaign_name": campaign_name,
            "channel": channel,
            "landing_page": request.payload.get("landing_page", ""),
            "short_url_preview": f"/p/{campaign_slug}-{channel}",
            "utm_campaign": campaign_slug,
            "utm_source": channel,
        },
        "baseline://marketing-promotion-link",
    )


def _promotion_link_execute_builder(request: ToolInvocationRequest) -> tuple[str, dict[str, Any], list[str]]:
    campaign_name = request.payload.get("campaign_name") or "待确认活动"
    channel = str(request.payload.get("channel", "web"))
    campaign_slug = _slugify_token(campaign_name, fallback="campaign")
    landing_page = request.payload.get("landing_page", "")

    # On execute, write to DB
    if request.operation == "execute":
        user_id = request.context.user_id
        tenant_id = request.context.tenant_id

        # Look up campaign_id
        campaign_row = query_one(
            "SELECT campaign_id FROM marketing_campaigns "
            "WHERE name = :name AND deleted_at IS NULL LIMIT 1",
            {"name": campaign_name},
        )
        campaign_id = campaign_row["campaign_id"] if campaign_row else campaign_slug

        link_id = f"plink_{_slugify_token(campaign_name, fallback='link')}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        short_url = f"/promo/{link_id[-8:]}"
        tracking_code = f"utm_campaign={campaign_slug}&utm_source={channel}"

        affected = execute_write(
            "INSERT INTO marketing_promotion_links "
            "(link_id, user_id, tenant_id, campaign_id, campaign_name, channel, "
            "short_url, landing_page_url, tracking_code, created_at, note) "
            "VALUES (:lid, :uid, :tid, :campid, :cname, :channel, "
            ":short_url, :landing, :tracking, NOW(), '')",
            {
                "lid": link_id,
                "uid": user_id,
                "tid": tenant_id,
                "campid": campaign_id,
                "cname": campaign_name,
                "channel": channel,
                "short_url": short_url,
                "landing": landing_page,
                "tracking": tracking_code,
            },
        )
        if affected > 0:
            return _with_result(
                "已创建推广链接。",
                {
                    "promotion_link_id": link_id,
                    "campaign_name": campaign_name,
                    "channel": channel,
                    "landing_page": landing_page,
                    "short_url": short_url,
                    "utm_campaign": campaign_slug,
                    "utm_source": channel,
                    "status": "active",
                },
                "db://marketing-promotion-links/" + link_id,
            )

    # Fallback
    return _with_result(
        "已生成推广链接。",
        {
            "promotion_link_id": f"promo_{campaign_slug}_{channel}",
            "campaign_name": campaign_name,
            "channel": channel,
            "landing_page": landing_page,
            "short_url": f"/p/{campaign_slug}-{channel}",
            "utm_campaign": campaign_slug,
            "utm_source": channel,
            "status": "active",
        },
        "baseline://marketing-promotion-link",
    )


def build_tools() -> list[StaticBusinessTool]:
    return [
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
                require_user_id=False,
                required_permissions=[],
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
            input_field_hints={"theme": "需要确认海报主题或宣传方向。"},
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
            input_field_hints={"campaign_name": "需要先确认要绑定的营销活动名称。"},
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
            input_field_hints={"theme": "需要先确认海报主题，可先生成海报 brief 后再出图。"},
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
    ]
