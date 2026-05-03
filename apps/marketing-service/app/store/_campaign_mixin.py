from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.telemetry import start_span
from app.models import (
    AdminCampaignListData,
    AdminCampaignUpsertRequest,
    MarketingCampaign,
    MarketingCampaignListData,
    MarketingCampaignRecord,
    ServiceError,
    utc_now,
)

from ._helpers import _parse_datetime
from ._models import CampaignRow


class _CampaignMixin:
    """Campaign CRUD and visibility helpers for ``MarketingStore``.

    Expects the host class to expose ``self._session`` and
    ``self._session_factory`` (sessionmaker).
    """

    def list_campaigns(
        self,
        *,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        status: str | None,
        product_type: str | None,
    ) -> MarketingCampaignListData:
        with start_span("marketing.list_campaigns", attributes={"operation": "campaign_listing"}):
            with self._session() as session:
                current_time = utc_now()
                campaigns = [
                    item
                    for item in self._load_campaign_records_for_listing(session)
                    if self._is_user_visible_campaign_record(item, current_time=current_time)
                ]
            if status:
                campaigns = [item for item in campaigns if item.status == status]
            if product_type:
                campaigns = [item for item in campaigns if item.product_type == product_type]
            reverse = sort_order != "asc"
            sort_field = sort_by if sort_by in {"start_at", "end_at", "name", "product_type", "status"} else "start_at"
            campaigns.sort(key=lambda item: getattr(item, sort_field), reverse=reverse)
            total = len(campaigns)
            items = [
                MarketingCampaign.model_validate(item.model_dump())
                for item in campaigns[(page - 1) * page_size : (page - 1) * page_size + page_size]
            ]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return MarketingCampaignListData(
                items=items,
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                sort_by=sort_field,
                sort_order="desc" if reverse else "asc",
            )

    def list_admin_campaigns(
        self,
        *,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        status: str | None,
        product_type: str | None,
    ) -> AdminCampaignListData:
        with self._session() as session:
            rows = session.scalars(select(CampaignRow).where(CampaignRow.deleted_at.is_(None))).all()
        if status:
            rows = [item for item in rows if item.status == status]
        if product_type:
            rows = [item for item in rows if item.product_type == product_type]
        reverse = sort_order != "asc"
        sort_field = sort_by if sort_by in {"start_at", "end_at", "name", "product_type", "status"} else "start_at"
        rows.sort(key=lambda item: getattr(item, sort_field), reverse=reverse)
        total = len(rows)
        items = [
            MarketingCampaign.model_validate(self._row_to_campaign_record(item).model_dump())
            for item in rows[(page - 1) * page_size : (page - 1) * page_size + page_size]
        ]
        total_pages = (total + page_size - 1) // page_size if total else 0
        return AdminCampaignListData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_field,
            sort_order="desc" if reverse else "asc",
        )

    def create_admin_campaign(self, payload: AdminCampaignUpsertRequest) -> MarketingCampaign:
        from uuid import uuid4

        campaign_id = payload.campaign_id or f"cmp_{uuid4().hex[:12]}"
        try:
            with self._session_factory.begin() as session:
                row = CampaignRow(
                    campaign_id=campaign_id,
                    name=payload.name,
                    product_type=payload.product_type,
                    status=payload.status,
                    start_at=_parse_datetime(payload.start_at),
                    end_at=_parse_datetime(payload.end_at),
                    landing_page_url=payload.landing_page_url,
                    highlights=list(payload.highlights),
                    deleted_at=None,
                    discount_type=payload.discount_type,
                    discount_value=payload.discount_value,
                    discount_description=payload.discount_description,
                    target_segment=payload.target_segment,
                    region=payload.region,
                    description=payload.description,
                    created_by=payload.created_by,
                    updated_at=utc_now(),
                    max_redemptions=payload.max_redemptions,
                    budget=payload.budget,
                )
                session.add(row)
        except IntegrityError as exc:
            raise ServiceError(409, 4090001, f"marketing campaign '{campaign_id}' already exists") from exc
        return MarketingCampaign.model_validate(self._row_to_campaign_record(row).model_dump())

    def update_admin_campaign(self, campaign_id: str, payload: AdminCampaignUpsertRequest) -> MarketingCampaign:
        with self._session_factory.begin() as session:
            row = session.scalars(
                select(CampaignRow).where(
                    CampaignRow.campaign_id == campaign_id,
                    CampaignRow.deleted_at.is_(None),
                )
            ).first()
            if row is None:
                raise ServiceError(404, 4040001, f"marketing campaign '{campaign_id}' was not found")
            row.name = payload.name
            row.product_type = payload.product_type
            row.status = payload.status
            row.start_at = _parse_datetime(payload.start_at)
            row.end_at = _parse_datetime(payload.end_at)
            row.landing_page_url = payload.landing_page_url
            row.highlights = list(payload.highlights)
            row.discount_type = payload.discount_type
            row.discount_value = payload.discount_value
            row.discount_description = payload.discount_description
            row.target_segment = payload.target_segment
            row.region = payload.region
            row.description = payload.description
            row.created_by = payload.created_by
            row.updated_at = utc_now()
            row.max_redemptions = payload.max_redemptions
            row.budget = payload.budget
        return MarketingCampaign.model_validate(self._row_to_campaign_record(row).model_dump())

    def get_admin_campaign(self, campaign_id: str) -> MarketingCampaign:
        with self._session() as session:
            row = session.scalars(
                select(CampaignRow).where(
                    CampaignRow.campaign_id == campaign_id,
                    CampaignRow.deleted_at.is_(None),
                )
            ).first()
        if row is None:
            raise ServiceError(404, 4040001, f"marketing campaign '{campaign_id}' was not found")
        return MarketingCampaign.model_validate(self._row_to_campaign_record(row).model_dump())

    def patch_admin_campaign(self, campaign_id: str, updates: dict) -> MarketingCampaign:
        with self._session_factory.begin() as session:
            row = session.scalars(
                select(CampaignRow).where(
                    CampaignRow.campaign_id == campaign_id,
                    CampaignRow.deleted_at.is_(None),
                )
            ).first()
            if row is None:
                raise ServiceError(404, 4040001, f"marketing campaign '{campaign_id}' was not found")
            field_map = {
                "name": ("name", None),
                "product_type": ("product_type", None),
                "status": ("status", None),
                "start_at": ("start_at", _parse_datetime),
                "end_at": ("end_at", _parse_datetime),
                "landing_page_url": ("landing_page_url", None),
                "highlights": ("highlights", list),
                "discount_type": ("discount_type", None),
                "discount_value": ("discount_value", None),
                "discount_description": ("discount_description", None),
                "target_segment": ("target_segment", None),
                "region": ("region", None),
                "description": ("description", None),
                "created_by": ("created_by", None),
                "max_redemptions": ("max_redemptions", None),
                "budget": ("budget", None),
            }
            for key, value in updates.items():
                if key in field_map and value is not None:
                    attr, converter = field_map[key]
                    setattr(row, attr, converter(value) if converter else value)
            row.updated_at = utc_now()
        return MarketingCampaign.model_validate(self._row_to_campaign_record(row).model_dump())

    def soft_delete_admin_campaign(self, campaign_id: str) -> None:
        with self._session_factory.begin() as session:
            row = session.scalars(
                select(CampaignRow).where(
                    CampaignRow.campaign_id == campaign_id,
                    CampaignRow.deleted_at.is_(None),
                )
            ).first()
            if row is None:
                raise ServiceError(404, 4040001, f"marketing campaign '{campaign_id}' was not found")
            row.deleted_at = utc_now()

    # ------------------------------------------------------------------
    # Visibility / mapping helpers (also consumed by other entity mixins).
    # ------------------------------------------------------------------

    def _get_user_visible_campaign(self, session: Session, campaign_id: str) -> CampaignRow | None:
        row = session.scalars(
            select(CampaignRow).where(
                CampaignRow.campaign_id == campaign_id,
                CampaignRow.deleted_at.is_(None),
            )
        ).first()
        if row is None or not self._is_user_visible_campaign(row, current_time=utc_now()):
            return None
        return row

    @staticmethod
    def _is_user_visible_campaign(row: CampaignRow, *, current_time: datetime) -> bool:
        start_at = _parse_datetime(row.start_at)
        end_at = _parse_datetime(row.end_at)
        return (
            row.deleted_at is None
            and row.status == "published"
            and start_at is not None
            and end_at is not None
            and start_at <= current_time <= end_at
        )

    @staticmethod
    def _is_user_visible_campaign_record(row: MarketingCampaignRecord, *, current_time: datetime) -> bool:
        start_at = _parse_datetime(row.start_at)
        end_at = _parse_datetime(row.end_at)
        return (
            row.deleted_at is None
            and row.status == "published"
            and start_at is not None
            and end_at is not None
            and start_at <= current_time <= end_at
        )

    @staticmethod
    def _row_to_campaign_record(row: CampaignRow) -> MarketingCampaignRecord:
        return MarketingCampaignRecord(
            campaign_id=row.campaign_id,
            name=row.name,
            product_type=row.product_type,
            status=row.status,
            start_at=row.start_at.isoformat(),
            end_at=row.end_at.isoformat(),
            landing_page_url=row.landing_page_url,
            highlights=list(row.highlights or []),
            deleted_at=row.deleted_at.isoformat() if row.deleted_at else None,
            discount_type=row.discount_type,
            discount_value=row.discount_value,
            discount_description=row.discount_description,
            target_segment=row.target_segment,
            region=row.region,
            description=row.description,
            created_by=row.created_by,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
            max_redemptions=row.max_redemptions,
            budget=row.budget,
        )

    @staticmethod
    def _campaign_record_from_mapping(mapping) -> MarketingCampaignRecord:
        highlights = mapping.get("highlights") or []
        if isinstance(highlights, str):
            try:
                highlights = json.loads(highlights)
            except json.JSONDecodeError:
                highlights = [highlights]
        start_at = mapping.get("start_at")
        end_at = mapping.get("end_at")
        deleted_at = mapping.get("deleted_at")
        updated_at = mapping.get("updated_at")
        return MarketingCampaignRecord(
            campaign_id=str(mapping.get("campaign_id") or ""),
            name=str(mapping.get("name") or ""),
            product_type=str(mapping.get("product_type") or ""),
            status=str(mapping.get("status") or "draft"),
            start_at=_parse_datetime(start_at).isoformat() if _parse_datetime(start_at) else "",
            end_at=_parse_datetime(end_at).isoformat() if _parse_datetime(end_at) else "",
            landing_page_url=str(mapping.get("landing_page_url") or ""),
            highlights=list(highlights),
            deleted_at=_parse_datetime(deleted_at).isoformat() if _parse_datetime(deleted_at) else None,
            discount_type=mapping.get("discount_type"),
            discount_value=mapping.get("discount_value"),
            discount_description=mapping.get("discount_description"),
            target_segment=mapping.get("target_segment"),
            region=mapping.get("region"),
            description=mapping.get("description"),
            created_by=mapping.get("created_by"),
            updated_at=_parse_datetime(updated_at).isoformat() if _parse_datetime(updated_at) else None,
            max_redemptions=mapping.get("max_redemptions"),
            budget=mapping.get("budget"),
        )

    def _load_campaign_records_for_listing(self, session: Session) -> list[MarketingCampaignRecord]:
        statement = select(
            CampaignRow.campaign_id,
            CampaignRow.name,
            CampaignRow.product_type,
            CampaignRow.status,
            CampaignRow.start_at,
            CampaignRow.end_at,
            CampaignRow.landing_page_url,
            CampaignRow.highlights,
            CampaignRow.discount_type,
            CampaignRow.discount_value,
            CampaignRow.discount_description,
            CampaignRow.target_segment,
            CampaignRow.region,
            CampaignRow.description,
            CampaignRow.created_by,
            CampaignRow.updated_at,
            CampaignRow.max_redemptions,
            CampaignRow.budget,
        )
        rows = session.execute(statement).mappings().all()
        return [self._campaign_record_from_mapping({**row, "deleted_at": None}) for row in rows]
