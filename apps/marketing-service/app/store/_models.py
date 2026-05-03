from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    discount_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    discount_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_segment: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_redemptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget: Mapped[float | None] = mapped_column(Float, nullable=True)


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
