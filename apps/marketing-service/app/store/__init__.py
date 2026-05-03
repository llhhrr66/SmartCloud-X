"""Marketing-service persistence layer.

Composes ``MarketingStore`` from per-entity mixins (campaigns, copies,
promotion links, poster tasks) plus dedicated ``PosterArtifactStorage`` for
MinIO interactions. The split keeps each mixin small enough to navigate
without losing the cross-cutting setup/lifecycle logic that lives directly on
``MarketingStore``.

External callers continue to use ``from app.store import get_marketing_store``.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from functools import lru_cache
import json
from threading import RLock

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core import metrics as _metrics
from app.core.config import get_settings
from app.core.metrics import (
    marketing_celery_operations_total,
    marketing_copies_generated_total,
    marketing_idempotency_replays_total,
    marketing_links_generated_total,
    marketing_minio_operations_total,
    marketing_posters_completed_total,
    marketing_posters_created_total,
    marketing_upstream_errors_total,
)
from app.core.telemetry import set_span_attributes, start_span
from app.models import MarketingCampaignRecord, MarketingStoreSnapshot, utc_now

from ._artifact_storage import PosterArtifactStorage
from ._campaign_mixin import _CampaignMixin
from ._copy_mixin import _CopyMixin
from ._helpers import (
    _connect_args,
    _normalize_database_url,
    _parse_datetime,
    _run_coroutine_in_new_loop,
)
from ._models import (
    Base,
    CampaignRow,
    MarketingCopyRow,
    PosterIdempotencyRow,
    PosterTaskRow,
    PromotionLinkRow,
)
from ._poster_task_mixin import _PosterTaskMixin
from ._promotion_link_mixin import _PromotionLinkMixin


class MarketingStore(_CampaignMixin, _CopyMixin, _PromotionLinkMixin, _PosterTaskMixin):
    """Database-backed marketing persistence.

    Inherits domain CRUD/list logic from per-entity mixins and contributes
    the lifecycle methods: schema bootstrap, snapshot loading/replacement,
    readiness probes, and the async-loop hop helper.
    """

    def __init__(self, *, initialize_schema: bool = True) -> None:
        settings = get_settings()
        self._lock = RLock()
        self._executor = ThreadPoolExecutor(max_workers=4)
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
        self._snapshot = MarketingStoreSnapshot()
        if initialize_schema:
            Base.metadata.create_all(self._engine)
            self._bootstrap_if_needed()
            self._snapshot = self._load_snapshot()

    def _session(self) -> Session:
        return self._session_factory()

    # ------------------------------------------------------------------
    # Bootstrap / snapshot
    # ------------------------------------------------------------------

    def _bootstrap_if_needed(self) -> None:
        with self._session() as session:
            has_rows = any(
                session.execute(select(model).limit(1)).first() is not None
                for model in (
                    CampaignRow,
                    PosterTaskRow,
                    PosterIdempotencyRow,
                    MarketingCopyRow,
                    PromotionLinkRow,
                )
            )
        if has_rows:
            return
        self._replace_snapshot(self._load_bootstrap_snapshot())

    def _load_bootstrap_snapshot(self) -> MarketingStoreSnapshot:
        current_time = utc_now()
        current_year = current_time.year
        if self._bootstrap_path and self._bootstrap_path.exists():
            bootstrap_snapshot = MarketingStoreSnapshot.model_validate_json(
                self._bootstrap_path.read_text(encoding="utf-8")
            )
            return self._normalize_bootstrap_campaign_windows(bootstrap_snapshot, current_year=current_year)
        return self._normalize_bootstrap_campaign_windows(
            MarketingStoreSnapshot(
                campaigns=[]
            ),
            current_year=current_year,
        )

    @staticmethod
    def _normalize_bootstrap_campaign_windows(
        snapshot: MarketingStoreSnapshot,
        *,
        current_year: int,
    ) -> MarketingStoreSnapshot:
        normalized_campaigns = [
            MarketingCampaignRecord.model_validate(
                {
                    **campaign.model_dump(mode="json"),
                    "start_at": MarketingStore._normalize_bootstrap_datetime(
                        campaign.start_at, current_year=current_year
                    ),
                    "end_at": MarketingStore._normalize_bootstrap_datetime(
                        campaign.end_at, current_year=current_year
                    ),
                }
            )
            for campaign in snapshot.campaigns
        ]
        return snapshot.model_copy(update={"campaigns": normalized_campaigns})

    @staticmethod
    def _normalize_bootstrap_datetime(value: str, *, current_year: int) -> str:
        parsed = _parse_datetime(value)
        if parsed is None:
            return value
        if parsed.year == current_year:
            return parsed.isoformat()
        return parsed.replace(year=current_year).isoformat()

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
            generated_copies = [
                self._row_to_stored_copy(item)
                for item in session.scalars(select(MarketingCopyRow).order_by(MarketingCopyRow.created_at)).all()
            ]
            promotion_links = [
                self._row_to_stored_link(item)
                for item in session.scalars(select(PromotionLinkRow).order_by(PromotionLinkRow.created_at)).all()
            ]
            poster_idempotency_records: list = []
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
                    for model in (
                        PosterIdempotencyRow,
                        PosterTaskRow,
                        PromotionLinkRow,
                        MarketingCopyRow,
                        CampaignRow,
                    ):
                        session.execute(delete(model))
                    for item in snapshot.campaigns:
                        session.add(
                            CampaignRow(
                                campaign_id=item.campaign_id,
                                name=item.name,
                                product_type=item.product_type,
                                status=item.status,
                                start_at=_parse_datetime(item.start_at),
                                end_at=_parse_datetime(item.end_at),
                                landing_page_url=item.landing_page_url,
                                highlights=list(item.highlights),
                                deleted_at=_parse_datetime(item.deleted_at) if item.deleted_at else None,
                                discount_type=item.discount_type,
                                discount_value=item.discount_value,
                                discount_description=item.discount_description,
                                target_segment=item.target_segment,
                                region=item.region,
                                description=item.description,
                                created_by=item.created_by,
                                updated_at=_parse_datetime(item.updated_at) if item.updated_at else None,
                                max_redemptions=item.max_redemptions,
                                budget=item.budget,
                            )
                        )
            self._snapshot = self._load_snapshot()

    def clear(self) -> None:
        with self._lock:
            Base.metadata.drop_all(self._engine)
            Base.metadata.create_all(self._engine)
            self._replace_snapshot(self._load_bootstrap_snapshot())

    # ------------------------------------------------------------------
    # Readiness probes
    # ------------------------------------------------------------------

    def database_readiness(self, *, trace: bool = True) -> dict[str, object]:
        try:
            if trace:
                with start_span("marketing.database_readiness", attributes={"operation": "database_readiness"}):
                    with self._session() as session:
                        session.execute(text("SELECT 1")).scalar_one()
            else:
                with self._session() as session:
                    session.execute(text("SELECT 1")).scalar_one()
            return {"ready": True, "configured": True, "detail": "query-ok"}
        except Exception as exc:
            _metrics.marketing_upstream_errors_total.labels(backend="database", error_type=exc.__class__.__name__).inc()
            return {
                "ready": False,
                "configured": bool(get_settings().database_url),
                "detail": f"error:{exc.__class__.__name__}",
            }

    def minio_readiness(self, *, trace: bool = True) -> dict[str, object]:
        return self._artifact_storage.readiness(trace=trace)

    def celery_readiness(self, *, trace: bool = True) -> dict[str, object]:
        settings = get_settings()
        configured = bool(settings.celery_broker_url and settings.celery_result_backend)
        if not configured:
            return {"ready": True, "configured": False, "detail": "disabled"}
        span_context = (
            start_span(
                "marketing.celery_readiness",
                attributes={"operation": "celery_readiness", "queue": settings.celery_queue_name},
            )
            if trace
            else nullcontext()
        )
        with span_context as span:
            try:
                from app.celery_app import celery_app

                connection_factory = getattr(celery_app, "connection_for_read", None)
                if connection_factory is None:
                    connection_factory = celery_app.connection
                with connection_factory() as connection:
                    connection.ensure_connection(max_retries=1)
                _metrics.marketing_celery_operations_total.labels(operation="broker_connect", status="success").inc()
                set_span_attributes(span, {"status": "ok"})
                return {"ready": True, "configured": True, "detail": "broker-ok"}
            except Exception as exc:
                _metrics.marketing_celery_operations_total.labels(operation="broker_connect", status="error").inc()
                _metrics.marketing_upstream_errors_total.labels(backend="celery", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
                return {
                    "ready": False,
                    "configured": True,
                    "detail": f"error:{exc.__class__.__name__}",
                }

    # ------------------------------------------------------------------
    # Async helpers
    # ------------------------------------------------------------------

    def _run_async(self, awaitable):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        future = self._executor.submit(_run_coroutine_in_new_loop, awaitable)
        return future.result()


@lru_cache(maxsize=4)
def get_marketing_store(*, allow_fallback: bool = False) -> MarketingStore:
    try:
        return MarketingStore()
    except Exception:
        if not allow_fallback:
            raise
        return MarketingStore(initialize_schema=False)


__all__ = [
    "Base",
    "CampaignRow",
    "MarketingCopyRow",
    "MarketingStore",
    "PosterArtifactStorage",
    "PosterIdempotencyRow",
    "PosterTaskRow",
    "PromotionLinkRow",
    "get_marketing_store",
    "get_settings",
    "marketing_celery_operations_total",
    "marketing_copies_generated_total",
    "marketing_idempotency_replays_total",
    "marketing_links_generated_total",
    "marketing_minio_operations_total",
    "marketing_posters_completed_total",
    "marketing_posters_created_total",
    "marketing_upstream_errors_total",
]
