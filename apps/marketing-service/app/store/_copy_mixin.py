from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select

from app.core import metrics as _metrics
from app.core.telemetry import start_span
from app.models import (
    MarketingCopyListData,
    MarketingCopyRequest,
    MarketingCopyResult,
    ServiceError,
    StoredMarketingCopy,
    utc_now,
)
from app.services.copy_generator import CampaignContext, get_copy_generator

from ._helpers import _tenant_filter
from ._models import MarketingCopyRow


class _CopyMixin:
    """Marketing-copy generation and listing.

    Expects the host class to expose ``self._session``,
    ``self._session_factory``, ``self._lock``, ``self._run_async``, and the
    ``_get_user_visible_campaign`` helper from the campaign mixin.
    """

    def create_copy(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: MarketingCopyRequest,
    ) -> MarketingCopyResult:
        with start_span(
            "marketing.copy_generate",
            attributes={
                "operation": "copy_generation",
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
                    keywords = (
                        payload.keywords
                        or list(campaign.highlights or [])
                        or ["稳定上云", "弹性扩容", "成本可控"]
                    )
                    generated = self._run_async(
                        get_copy_generator().generate(
                            CampaignContext(
                                campaign_id=campaign.campaign_id,
                                campaign_name=campaign.name,
                                topic=payload.topic,
                                audience=payload.audience,
                                tone=payload.tone,
                                keywords=keywords,
                                highlights=list(campaign.highlights or []),
                                landing_page_url=campaign.landing_page_url,
                            ),
                            tone=payload.tone,
                            keywords=keywords,
                        )
                    )
                    created_at = utc_now()
                    row = MarketingCopyRow(
                        copy_id=f"copy_{uuid4().hex[:12]}",
                        user_id=user_id,
                        tenant_id=tenant_id,
                        campaign_id=campaign.campaign_id,
                        campaign_name=campaign.name,
                        topic=payload.topic,
                        audience=payload.audience,
                        tone=payload.tone,
                        headline=generated.headline,
                        summary=generated.summary,
                        body=generated.body,
                        call_to_action=generated.call_to_action,
                        keywords=keywords,
                        landing_page_url=campaign.landing_page_url,
                        created_at=created_at,
                    )
                    session.add(row)
                _metrics.marketing_copies_generated_total.inc()
            return MarketingCopyResult.model_validate(self._row_to_stored_copy(row).model_dump())

    def get_copy(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        copy_id: str,
    ) -> MarketingCopyResult | None:
        with self._session() as session:
            row = session.scalars(
                select(MarketingCopyRow).where(
                    MarketingCopyRow.user_id == user_id,
                    _tenant_filter(MarketingCopyRow.tenant_id, tenant_id),
                    MarketingCopyRow.copy_id == copy_id,
                )
            ).first()
        return None if row is None else MarketingCopyResult.model_validate(self._row_to_stored_copy(row).model_dump())

    def list_copies(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        campaign_id: str | None,
        tone: str | None,
    ) -> MarketingCopyListData:
        with self._session() as session:
            rows = session.scalars(
                select(MarketingCopyRow).where(
                    MarketingCopyRow.user_id == user_id,
                    _tenant_filter(MarketingCopyRow.tenant_id, tenant_id),
                )
            ).all()
        if campaign_id:
            rows = [item for item in rows if item.campaign_id == campaign_id]
        if tone:
            rows = [item for item in rows if item.tone == tone]
        reverse = sort_order != "asc"
        sort_field = sort_by if sort_by in {"created_at", "topic", "campaign_name", "tone"} else "created_at"
        rows.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
        total = len(rows)
        items = [
            MarketingCopyResult.model_validate(self._row_to_stored_copy(item).model_dump())
            for item in rows[(page - 1) * page_size : (page - 1) * page_size + page_size]
        ]
        total_pages = (total + page_size - 1) // page_size if total else 0
        return MarketingCopyListData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_field,
            sort_order="desc" if reverse else "asc",
        )

    @staticmethod
    def _row_to_stored_copy(row: MarketingCopyRow) -> StoredMarketingCopy:
        return StoredMarketingCopy(
            copy_id=row.copy_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            topic=row.topic,
            audience=row.audience,
            tone=row.tone,
            headline=row.headline,
            summary=row.summary,
            body=row.body,
            call_to_action=row.call_to_action,
            keywords=list(row.keywords or []),
            landing_page_url=row.landing_page_url,
            created_at=row.created_at.isoformat(),
        )
