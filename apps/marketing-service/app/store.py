from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO
from threading import RLock
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.models import (
    CreatePosterTaskRequest,
    MarketingCampaign,
    MarketingCampaignListData,
    MarketingCampaignRecord,
    MarketingCopyListData,
    MarketingCopyRequest,
    MarketingCopyResult,
    MarketingStoreSnapshot,
    PosterIdempotencyRecord,
    PosterTaskCreateResponseData,
    PosterTaskListData,
    PosterTaskRecord,
    PromotionLinkListData,
    PromotionLinkRequest,
    PromotionLinkResult,
    ServiceError,
    StoredMarketingCopy,
    StoredPromotionLink,
    utc_now,
)

try:  # pragma: no cover - optional runtime dependency
    from minio import Minio
except Exception:  # pragma: no cover - optional runtime dependency
    Minio = None


class Base(DeclarativeBase):
    pass


class CampaignRow(Base):
    __tablename__ = "marketing_campaigns"

    campaign_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    product_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    landing_page_url: Mapped[str] = mapped_column(String(2048))
    highlights: Mapped[list[str]] = mapped_column(JSON, default=list)


class MarketingCopyRow(Base):
    __tablename__ = "marketing_generated_copies"

    copy_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    campaign_id: Mapped[str] = mapped_column(String(64), index=True)
    campaign_name: Mapped[str] = mapped_column(String(255))
    topic: Mapped[str] = mapped_column(String(255), index=True)
    audience: Mapped[str] = mapped_column(String(255))
    tone: Mapped[str] = mapped_column(String(32), index=True)
    headline: Mapped[str] = mapped_column(String(255))
    summary: Mapped[str] = mapped_column(String(1000))
    body: Mapped[str] = mapped_column(String(4000))
    call_to_action: Mapped[str] = mapped_column(String(255))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    landing_page_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PromotionLinkRow(Base):
    __tablename__ = "marketing_promotion_links"

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    campaign_id: Mapped[str] = mapped_column(String(64), index=True)
    campaign_name: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(64), index=True)
    short_url: Mapped[str] = mapped_column(String(2048))
    landing_page_url: Mapped[str] = mapped_column(String(2048))
    tracking_code: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    note: Mapped[str] = mapped_column(String(1000))


class PosterTaskRow(Base):
    __tablename__ = "marketing_poster_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    campaign_id: Mapped[str] = mapped_column(String(64), index=True)
    campaign_name: Mapped[str] = mapped_column(String(255))
    theme: Mapped[str] = mapped_column(String(255), index=True)
    slogan: Mapped[str] = mapped_column(String(1000))
    size: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    estimated_seconds: Mapped[int] = mapped_column(Integer)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PosterIdempotencyRow(Base):
    __tablename__ = "marketing_poster_idempotency_records"
    __table_args__ = (
        UniqueConstraint("key", "user_id", "tenant_id", name="uq_marketing_poster_idempotency_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(128))
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    accepted_status: Mapped[str] = mapped_column(String(32))
    estimated_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@dataclass
class PosterArtifactStorage:
    def store_placeholder_poster(self, task_id: str) -> str:
        settings = get_settings()
        object_name = f"{task_id}.png"
        public_url = f"{settings.poster_public_base_url.rstrip('/')}/{object_name}"
        if not settings.minio_endpoint or not settings.minio_bucket or Minio is None:
            return public_url
        if not settings.minio_access_key or not settings.minio_secret_key:
            return public_url
        try:
            parsed = urlparse(settings.minio_endpoint)
            endpoint = parsed.netloc or parsed.path
            client = Minio(
                endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=(parsed.scheme or "https") == "https",
            )
            bucket = settings.minio_bucket
            if not client.bucket_exists(bucket):
                client.make_bucket(bucket)
            payload = _placeholder_png_bytes()
            client.put_object(
                bucket,
                object_name,
                BytesIO(payload),
                len(payload),
                content_type="image/png",
            )
        except Exception:
            return public_url
        return public_url


class MarketingStore:
    def __init__(self) -> None:
        settings = get_settings()
        self._lock = RLock()
        self._engine = create_engine(
            _normalize_database_url(settings.database_url),
            future=True,
            connect_args=_connect_args(settings.database_url),
            json_serializer=lambda value: json.dumps(value, ensure_ascii=False),
            pool_pre_ping=True,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False, future=True)
        self._bootstrap_path = settings.bootstrap_path
        self._artifact_storage = PosterArtifactStorage()
        Base.metadata.create_all(self._engine)
        self._bootstrap_if_needed()
        self._snapshot = self._load_snapshot()

    def _session(self) -> Session:
        return self._session_factory()

    def _bootstrap_if_needed(self) -> None:
        with self._session() as session:
            has_rows = any(
                session.execute(select(model).limit(1)).first() is not None
                for model in (CampaignRow, PosterTaskRow, PosterIdempotencyRow, MarketingCopyRow, PromotionLinkRow)
            )
        if has_rows:
            return
        snapshot = self._load_bootstrap_snapshot()
        self._replace_snapshot(snapshot)

    def _load_bootstrap_snapshot(self) -> MarketingStoreSnapshot:
        if self._bootstrap_path and self._bootstrap_path.exists():
            return MarketingStoreSnapshot.model_validate_json(self._bootstrap_path.read_text(encoding="utf-8"))
        return self._default_snapshot()

    def _default_snapshot(self) -> MarketingStoreSnapshot:
        return MarketingStoreSnapshot(
            campaigns=[
                MarketingCampaignRecord(
                    campaign_id="cmp_gpu_launch_001",
                    name="GPU 云主机上新季",
                    product_type="gpu",
                    status="published",
                    start_at="2026-04-01T00:00:00+00:00",
                    end_at="2026-05-31T23:59:59+00:00",
                    landing_page_url="https://smartcloud.local/campaigns/gpu-spring",
                    highlights=["新品首发", "AI 算力", "弹性扩容"],
                ),
                MarketingCampaignRecord(
                    campaign_id="cmp_ecs_growth_001",
                    name="弹性云服务器增长计划",
                    product_type="ecs",
                    status="published",
                    start_at="2026-03-15T00:00:00+00:00",
                    end_at="2026-06-30T23:59:59+00:00",
                    landing_page_url="https://smartcloud.local/campaigns/ecs-growth",
                    highlights=["稳定上云", "成本可控", "企业通用"],
                ),
                MarketingCampaignRecord(
                    campaign_id="cmp_storage_draft_001",
                    name="对象存储体验周",
                    product_type="storage",
                    status="draft",
                    start_at="2026-06-01T00:00:00+00:00",
                    end_at="2026-06-30T23:59:59+00:00",
                    landing_page_url="https://smartcloud.local/campaigns/storage-week",
                    highlights=["草稿活动"],
                ),
            ]
        )

    def _load_snapshot(self) -> MarketingStoreSnapshot:
        with self._session() as session:
            campaigns = [
                self._row_to_campaign_record(item)
                for item in session.scalars(select(CampaignRow).order_by(CampaignRow.start_at)).all()
            ]
            poster_tasks = [
                self._row_to_poster_task(item)
                for item in session.scalars(select(PosterTaskRow).order_by(PosterTaskRow.created_at)).all()
            ]
            poster_idempotency_records = [
                self._row_to_poster_idempotency(item)
                for item in session.scalars(
                    select(PosterIdempotencyRow).order_by(PosterIdempotencyRow.created_at, PosterIdempotencyRow.id)
                ).all()
            ]
            generated_copies = [
                self._row_to_stored_copy(item)
                for item in session.scalars(select(MarketingCopyRow).order_by(MarketingCopyRow.created_at)).all()
            ]
            promotion_links = [
                self._row_to_stored_link(item)
                for item in session.scalars(select(PromotionLinkRow).order_by(PromotionLinkRow.created_at)).all()
            ]
        return MarketingStoreSnapshot(
            campaigns=campaigns,
            poster_tasks=poster_tasks,
            poster_idempotency_records=poster_idempotency_records,
            generated_copies=generated_copies,
            promotion_links=promotion_links,
        )

    def _replace_snapshot(self, snapshot: MarketingStoreSnapshot) -> None:
        with self._lock:
            with self._session() as session:
                with session.begin():
                    for model in (PosterIdempotencyRow, PosterTaskRow, PromotionLinkRow, MarketingCopyRow, CampaignRow):
                        session.execute(delete(model))
                    session.add_all([
                        CampaignRow(
                            campaign_id=item.campaign_id,
                            name=item.name,
                            product_type=item.product_type,
                            status=item.status,
                            start_at=_parse_datetime(item.start_at),
                            end_at=_parse_datetime(item.end_at),
                            landing_page_url=item.landing_page_url,
                            highlights=list(item.highlights),
                        )
                        for item in snapshot.campaigns
                    ])
                    session.add_all([
                        PosterTaskRow(
                            task_id=item.task_id,
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            campaign_id=item.campaign_id,
                            campaign_name=item.campaign_name,
                            theme=item.theme,
                            slogan=item.slogan,
                            size=item.size,
                            status=item.status,
                            created_at=_parse_datetime(item.created_at),
                            estimated_seconds=item.estimated_seconds,
                            image_url=item.image_url,
                            error_message=item.error_message,
                            updated_at=_parse_datetime(item.updated_at) if item.updated_at else None,
                        )
                        for item in snapshot.poster_tasks
                    ])
                    session.add_all([
                        PosterIdempotencyRow(
                            key=item.key,
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            payload_hash=item.payload_hash,
                            task_id=item.task_id,
                            accepted_status=item.accepted_status,
                            estimated_seconds=item.estimated_seconds,
                            created_at=_parse_datetime(item.created_at),
                        )
                        for item in snapshot.poster_idempotency_records
                    ])
                    session.add_all([
                        MarketingCopyRow(
                            copy_id=item.copy_id,
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            campaign_id=item.campaign_id,
                            campaign_name=item.campaign_name,
                            topic=item.topic,
                            audience=item.audience,
                            tone=item.tone,
                            headline=item.headline,
                            summary=item.summary,
                            body=item.body,
                            call_to_action=item.call_to_action,
                            keywords=list(item.keywords),
                            landing_page_url=item.landing_page_url,
                            created_at=_parse_datetime(item.created_at),
                        )
                        for item in snapshot.generated_copies
                    ])
                    session.add_all([
                        PromotionLinkRow(
                            link_id=item.link_id,
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            campaign_id=item.campaign_id,
                            campaign_name=item.campaign_name,
                            channel=item.channel,
                            short_url=item.short_url,
                            landing_page_url=item.landing_page_url,
                            tracking_code=item.tracking_code,
                            created_at=_parse_datetime(item.created_at),
                            note=item.note,
                        )
                        for item in snapshot.promotion_links
                    ])
        self._snapshot = self._load_snapshot()

    def _persist(self, snapshot: MarketingStoreSnapshot | None = None) -> None:
        self._replace_snapshot(snapshot or self._snapshot)

    def clear(self) -> None:
        with self._lock:
            Base.metadata.drop_all(self._engine)
            Base.metadata.create_all(self._engine)
            self._replace_snapshot(self._load_bootstrap_snapshot())

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
        with self._session() as session:
            current_time = utc_now()
            campaigns = [
                item
                for item in session.scalars(select(CampaignRow)).all()
                if self._is_user_visible_campaign(item, current_time=current_time)
            ]
        if status:
            campaigns = [item for item in campaigns if item.status == status]
        if product_type:
            campaigns = [item for item in campaigns if item.product_type == product_type]
        reverse = sort_order != "asc"
        sort_field = sort_by if sort_by in {"start_at", "end_at", "name", "product_type", "status"} else "start_at"
        campaigns.sort(key=lambda item: getattr(item, sort_field), reverse=reverse)
        total = len(campaigns)
        start = (page - 1) * page_size
        end = start + page_size
        items = [MarketingCampaign.model_validate(self._row_to_campaign_record(item).model_dump()) for item in campaigns[start:end]]
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

    def create_copy(self, *, user_id: str, tenant_id: str | None, payload: MarketingCopyRequest) -> MarketingCopyResult:
        with self._lock:
            with self._session_factory.begin() as session:
                campaign = self._get_user_visible_campaign(session, payload.campaign_id)
                if campaign is None:
                    raise ServiceError(404, 4040001, f"marketing campaign '{payload.campaign_id}' was not found")
                keywords = payload.keywords or list(campaign.highlights or []) or ["稳定上云", "弹性扩容", "成本可控"]
                headline_prefix = {
                    "launch": "新品首发",
                    "growth": "增长加速",
                    "professional": "企业上云",
                }[payload.tone]
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
                    headline=f"{headline_prefix}｜{payload.topic}",
                    summary=f"面向{payload.audience}，突出{'、'.join(keywords[:2])}等核心卖点。",
                    body="\n\n".join(
                        [
                            f"{campaign.name}现已开放，围绕“{payload.topic}”提供更贴近业务落地的推广素材。",
                            f"重点强调 {'、'.join(keywords)}，帮助{payload.audience}快速理解活动价值与适用场景。",
                            "建议将该文案用于落地页首屏、社群推送或销售跟进话术，并结合海报任务统一视觉输出。",
                        ]
                    ),
                    call_to_action="立即预约新品权益" if payload.tone == "launch" else "立即领取活动方案",
                    keywords=keywords,
                    landing_page_url=campaign.landing_page_url,
                    created_at=created_at,
                )
                session.add(row)
            self._snapshot = self._load_snapshot()
        return MarketingCopyResult.model_validate(self._row_to_stored_copy(row).model_dump())

    def get_copy(self, *, user_id: str, tenant_id: str | None, copy_id: str) -> MarketingCopyResult | None:
        with self._session() as session:
            row = session.scalars(
                select(MarketingCopyRow).where(
                    MarketingCopyRow.user_id == user_id,
                    _tenant_filter(MarketingCopyRow.tenant_id, tenant_id),
                    MarketingCopyRow.copy_id == copy_id,
                )
            ).first()
        if row is None:
            return None
        return MarketingCopyResult.model_validate(self._row_to_stored_copy(row).model_dump())

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
        start = (page - 1) * page_size
        end = start + page_size
        items = [MarketingCopyResult.model_validate(self._row_to_stored_copy(item).model_dump()) for item in rows[start:end]]
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

    def create_promotion_link(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: PromotionLinkRequest,
    ) -> PromotionLinkResult:
        with self._lock:
            with self._session_factory.begin() as session:
                campaign = self._get_user_visible_campaign(session, payload.campaign_id)
                if campaign is None:
                    raise ServiceError(404, 4040001, f"marketing campaign '{payload.campaign_id}' was not found")
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
                    note="database-backed placeholder promotion link; replace short-domain routing in production",
                )
                session.add(row)
            self._snapshot = self._load_snapshot()
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
        if row is None:
            return None
        return PromotionLinkResult.model_validate(self._row_to_stored_link(row).model_dump())

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
        start = (page - 1) * page_size
        end = start + page_size
        items = [PromotionLinkResult.model_validate(self._row_to_stored_link(item).model_dump()) for item in rows[start:end]]
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

    def create_poster_task(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: CreatePosterTaskRequest,
        idempotency_key: str | None,
    ) -> PosterTaskCreateResponseData:
        normalized_payload = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        payload_hash = _payload_hash(user_id=user_id, tenant_id=tenant_id, normalized_payload=normalized_payload)
        legacy_payload_hash = _legacy_payload_hash(user_id=user_id, normalized_payload=normalized_payload)
        estimated_seconds = get_settings().default_estimated_seconds
        with self._lock:
            with self._session_factory.begin() as session:
                campaign = self._get_user_visible_campaign(session, payload.campaign_id)
                if campaign is None:
                    raise ServiceError(404, 4040001, f"marketing campaign '{payload.campaign_id}' was not found")
                if idempotency_key:
                    existing = session.scalars(
                        select(PosterIdempotencyRow).where(
                            PosterIdempotencyRow.key == idempotency_key,
                            PosterIdempotencyRow.user_id == user_id,
                            _tenant_filter(PosterIdempotencyRow.tenant_id, tenant_id),
                        )
                    ).first()
                    if existing is not None:
                        existing_hash_matches = existing.payload_hash == payload_hash or (
                            existing.tenant_id is None
                            and tenant_id in {None, "default"}
                            and existing.payload_hash == legacy_payload_hash
                        )
                        if not existing_hash_matches:
                            raise ServiceError(
                                409,
                                4090001,
                                "idempotency key conflicts with a different poster task payload",
                            )
                        return PosterTaskCreateResponseData(
                            task_id=existing.task_id,
                            status=existing.accepted_status,
                            estimated_seconds=existing.estimated_seconds,
                        )
                created_at = utc_now()
                row = PosterTaskRow(
                    task_id=f"poster_{uuid4().hex[:12]}",
                    user_id=user_id,
                    tenant_id=tenant_id,
                    campaign_id=campaign.campaign_id,
                    campaign_name=campaign.name,
                    theme=payload.theme,
                    slogan=payload.slogan,
                    size=payload.size,
                    status="queued",
                    created_at=created_at,
                    estimated_seconds=estimated_seconds,
                    updated_at=created_at,
                )
                session.add(row)
                if idempotency_key:
                    session.add(
                        PosterIdempotencyRow(
                            key=idempotency_key,
                            user_id=user_id,
                            tenant_id=tenant_id,
                            payload_hash=payload_hash,
                            task_id=row.task_id,
                            accepted_status="queued",
                            estimated_seconds=estimated_seconds,
                            created_at=created_at,
                        )
                    )
            self._snapshot = self._load_snapshot()
        return PosterTaskCreateResponseData(
            task_id=row.task_id,
            status="queued",
            estimated_seconds=estimated_seconds,
        )

    def get_poster_task(self, *, user_id: str, tenant_id: str | None, task_id: str):
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(
                    select(PosterTaskRow).where(
                        PosterTaskRow.user_id == user_id,
                        _tenant_filter(PosterTaskRow.tenant_id, tenant_id),
                        PosterTaskRow.task_id == task_id,
                    )
                ).first()
                if row is None:
                    return None
                self._maybe_complete_poster(row)
                task = self._row_to_poster_task(row).to_public()
            self._snapshot = self._load_snapshot()
        return task

    def list_poster_tasks(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        status: str | None,
        campaign_id: str | None,
    ) -> PosterTaskListData:
        with self._lock:
            with self._session_factory.begin() as session:
                rows = session.scalars(
                    select(PosterTaskRow).where(
                        PosterTaskRow.user_id == user_id,
                        _tenant_filter(PosterTaskRow.tenant_id, tenant_id),
                    )
                ).all()
                for row in rows:
                    self._maybe_complete_poster(row)
                if status:
                    rows = [item for item in rows if item.status == status]
                if campaign_id:
                    rows = [item for item in rows if item.campaign_id == campaign_id]
                reverse = sort_order != "asc"
                sort_field = sort_by if sort_by in {"created_at", "updated_at", "status", "theme"} else "updated_at"
                rows.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
                total = len(rows)
                start = (page - 1) * page_size
                end = start + page_size
                items = [self._row_to_poster_task(item).to_public() for item in rows[start:end]]
                total_pages = (total + page_size - 1) // page_size if total else 0
            self._snapshot = self._load_snapshot()
        return PosterTaskListData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_field,
            sort_order="desc" if reverse else "asc",
        )

    def _maybe_complete_poster(self, row: PosterTaskRow) -> bool:
        if row.status not in {"queued", "running"}:
            return False
        settings = get_settings()
        created_at = _coerce_utc(row.created_at)
        elapsed_seconds = max(int((utc_now() - created_at).total_seconds()), 0)
        auto_complete_seconds = max(settings.task_auto_complete_seconds, 0)
        if auto_complete_seconds > 0 and elapsed_seconds < auto_complete_seconds:
            if row.status != "running":
                row.status = "running"
                row.updated_at = utc_now()
                return True
            return False
        row.status = "completed"
        row.image_url = row.image_url or self._artifact_storage.store_placeholder_poster(row.task_id)
        row.updated_at = utc_now()
        return True

    def _get_user_visible_campaign(self, session: Session, campaign_id: str) -> CampaignRow | None:
        current_time = utc_now()
        row = session.get(CampaignRow, campaign_id)
        if row is None or not self._is_user_visible_campaign(row, current_time=current_time):
            return None
        return row

    @staticmethod
    def _is_user_visible_campaign(
        campaign: CampaignRow,
        *,
        current_time: datetime | None = None,
    ) -> bool:
        if campaign.status != "published":
            return False
        now = current_time or utc_now()
        return _coerce_utc(campaign.start_at) <= now <= _coerce_utc(campaign.end_at)

    @staticmethod
    def _row_to_campaign_record(row: CampaignRow) -> MarketingCampaignRecord:
        return MarketingCampaignRecord(
            campaign_id=row.campaign_id,
            name=row.name,
            product_type=row.product_type,
            status=row.status,
            start_at=_coerce_utc(row.start_at).isoformat(),
            end_at=_coerce_utc(row.end_at).isoformat(),
            landing_page_url=row.landing_page_url,
            highlights=list(row.highlights or []),
        )

    @staticmethod
    def _row_to_poster_task(row: PosterTaskRow) -> PosterTaskRecord:
        return PosterTaskRecord(
            task_id=row.task_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            campaign_id=row.campaign_id,
            campaign_name=row.campaign_name,
            theme=row.theme,
            slogan=row.slogan,
            size=row.size,
            status=row.status,
            created_at=_coerce_utc(row.created_at).isoformat(),
            estimated_seconds=row.estimated_seconds,
            image_url=row.image_url,
            error_message=row.error_message,
            updated_at=_coerce_utc(row.updated_at).isoformat() if row.updated_at else None,
        )

    @staticmethod
    def _row_to_poster_idempotency(row: PosterIdempotencyRow) -> PosterIdempotencyRecord:
        return PosterIdempotencyRecord(
            key=row.key,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            payload_hash=row.payload_hash,
            task_id=row.task_id,
            accepted_status=row.accepted_status,
            estimated_seconds=row.estimated_seconds,
            created_at=_coerce_utc(row.created_at).isoformat(),
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
            created_at=_coerce_utc(row.created_at).isoformat(),
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
            created_at=_coerce_utc(row.created_at).isoformat(),
            note=row.note,
        )


@lru_cache(maxsize=1)
def get_marketing_store() -> MarketingStore:
    return MarketingStore()


def _tenant_filter(column, tenant_id: str | None):
    if tenant_id in {None, "default"}:
        return (column == tenant_id) | (column.is_(None))
    return column == tenant_id


def _payload_hash(*, user_id: str, tenant_id: str | None, normalized_payload: str) -> str:
    return __import__("hashlib").sha256(f"{tenant_id or ''}:{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()


def _legacy_payload_hash(*, user_id: str, normalized_payload: str) -> str:
    return __import__("hashlib").sha256(f"{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _coerce_utc(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _normalize_database_url(value: str) -> str:
    return value.replace("mysql://", "mysql+pymysql://", 1) if value.startswith("mysql://") else value


def _connect_args(database_url: str) -> dict[str, Any]:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def _placeholder_png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDATx\x9cc```\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
