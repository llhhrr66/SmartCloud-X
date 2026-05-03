from __future__ import annotations

from urllib.parse import urlencode
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core import metrics as _metrics
from app.core.telemetry import start_span
from app.models import (
    PromotionLinkListData,
    PromotionLinkRequest,
    PromotionLinkResult,
    ServiceError,
    StoredPromotionLink,
    utc_now,
)

from ._helpers import _tenant_filter
from ._models import PromotionLinkRow


class _PromotionLinkMixin:
    """Promotion-link generation and listing for ``MarketingStore``."""

    def create_promotion_link(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: PromotionLinkRequest,
    ) -> PromotionLinkResult:
        with start_span(
            "marketing.promotion_link_generate",
            attributes={
                "operation": "promotion_link_generation",
                "campaign_id": payload.campaign_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
        ):
            with self._lock:
                with self._session_factory.begin() as session:
                    campaign = self._get_user_visible_campaign(session, payload.campaign_id)
                    if campaign is None:
                        raise ServiceError(
                            404,
                            4040001,
                            f"marketing campaign '{payload.campaign_id}' was not found",
                        )
                    tracking_params = {
                        "utm_campaign": campaign.campaign_id,
                        "utm_source": payload.source or payload.channel,
                    }
                    if payload.content_tag:
                        tracking_params["utm_content"] = payload.content_tag
                    tracking_code = urlencode(tracking_params)
                    created_at = utc_now()
                    row = PromotionLinkRow(
                        link_id=f"plink_{uuid4().hex[:12]}",
                        user_id=user_id,
                        tenant_id=tenant_id,
                        campaign_id=campaign.campaign_id,
                        campaign_name=campaign.name,
                        channel=payload.channel,
                        short_url=f"{get_settings().promotion_short_link_base_url.rstrip('/')}/{uuid4().hex[:8]}",
                        landing_page_url=f"{campaign.landing_page_url}?{tracking_code}",
                        tracking_code=tracking_code,
                        created_at=created_at,
                        note="",
                    )
                    session.add(row)
                _metrics.marketing_links_generated_total.inc()
            return PromotionLinkResult.model_validate(self._row_to_stored_link(row).model_dump())

    def get_promotion_link(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        link_id: str,
    ) -> PromotionLinkResult | None:
        with self._session() as session:
            row = session.scalars(
                select(PromotionLinkRow).where(
                    PromotionLinkRow.user_id == user_id,
                    _tenant_filter(PromotionLinkRow.tenant_id, tenant_id),
                    PromotionLinkRow.link_id == link_id,
                )
            ).first()
        return None if row is None else PromotionLinkResult.model_validate(self._row_to_stored_link(row).model_dump())

    def list_promotion_links(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        campaign_id: str | None,
        channel: str | None,
    ) -> PromotionLinkListData:
        with self._session() as session:
            rows = session.scalars(
                select(PromotionLinkRow).where(
                    PromotionLinkRow.user_id == user_id,
                    _tenant_filter(PromotionLinkRow.tenant_id, tenant_id),
                )
            ).all()
        if campaign_id:
            rows = [item for item in rows if item.campaign_id == campaign_id]
        if channel:
            rows = [item for item in rows if item.channel == channel]
        reverse = sort_order != "asc"
        sort_field = sort_by if sort_by in {"created_at", "campaign_name", "channel"} else "created_at"
        rows.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
        total = len(rows)
        items = [
            PromotionLinkResult.model_validate(self._row_to_stored_link(item).model_dump())
            for item in rows[(page - 1) * page_size : (page - 1) * page_size + page_size]
        ]
        total_pages = (total + page_size - 1) // page_size if total else 0
        return PromotionLinkListData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_field,
            sort_order="desc" if reverse else "asc",
        )

    @staticmethod
    def _row_to_stored_link(row: PromotionLinkRow) -> StoredPromotionLink:
        return StoredPromotionLink(
            link_id=row.link_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            channel=row.channel,
            short_url=row.short_url,
            landing_page_url=row.landing_page_url,
            tracking_code=row.tracking_code,
            created_at=row.created_at.isoformat(),
            note=row.note,
        )
