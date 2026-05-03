from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import select

from app.core import metrics as _metrics
from app.core.config import get_settings
from app.core.telemetry import set_span_attributes, start_span
from app.models import (
    CreatePosterTaskRequest,
    PosterTaskCreateResponseData,
    PosterTaskListData,
    PosterTaskRecord,
    ServiceError,
    utc_now,
)
from app.services.poster_generator import PosterTaskContext, get_poster_generator

from ._helpers import _payload_hash, _tenant_filter
from ._models import PosterIdempotencyRow, PosterTaskRow


class _PosterTaskMixin:
    """Poster-task lifecycle for ``MarketingStore``.

    Covers idempotency-aware creation, async processing, failure marking,
    deletion, and listing. Expects the host class to provide ``self._lock``,
    ``self._session``, ``self._session_factory``, ``self._artifact_storage``,
    ``self._run_async``, and the ``_get_user_visible_campaign`` helper.
    """

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
        estimated_seconds = get_settings().default_estimated_seconds
        with start_span(
            "marketing.poster_create",
            attributes={
                "operation": "poster_task_creation",
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
                    if idempotency_key:
                        existing = session.scalars(
                            select(PosterIdempotencyRow).where(
                                PosterIdempotencyRow.key == idempotency_key,
                                PosterIdempotencyRow.user_id == user_id,
                                _tenant_filter(PosterIdempotencyRow.tenant_id, tenant_id),
                            )
                        ).first()
                        if existing is not None:
                            if existing.payload_hash != payload_hash:
                                raise ServiceError(
                                    409,
                                    4090001,
                                    "idempotency key conflicts with a different poster task payload",
                                )
                            _metrics.marketing_idempotency_replays_total.inc()
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
                _metrics.marketing_posters_created_total.inc()
            return PosterTaskCreateResponseData(
                task_id=row.task_id,
                status="queued",
                estimated_seconds=estimated_seconds,
            )

    def process_poster_task(self, task_id: str) -> PosterTaskRecord:
        with start_span(
            "marketing.poster_process",
            attributes={"operation": "poster_processing", "poster_task_id": task_id},
        ) as span:
            with self._lock:
                with self._session_factory.begin() as session:
                    row = session.scalars(select(PosterTaskRow).where(PosterTaskRow.task_id == task_id)).first()
                    if row is None:
                        set_span_attributes(span, {"status": "error", "error_type": "task_not_found"})
                        raise RuntimeError(f"poster task '{task_id}' was not found")
                    if row.status != "completed":
                        row.status = "running"
                        generated = self._run_async(
                            get_poster_generator().generate(
                                PosterTaskContext(
                                    task_id=row.task_id,
                                    campaign_id=row.campaign_id,
                                    campaign_name=row.campaign_name,
                                    theme=row.theme,
                                    slogan=row.slogan,
                                    size=row.size,
                                )
                            )
                        )
                        row.image_url = self._artifact_storage.ensure_object_present(
                            row.task_id, generated.image_bytes, generated.mime_type
                        )
                        row.error_message = None
                        row.status = "completed"
                        row.updated_at = utc_now()
                        _metrics.marketing_posters_completed_total.inc()
                    elif row.image_url:
                        generated = self._run_async(
                            get_poster_generator().generate(
                                PosterTaskContext(
                                    task_id=row.task_id,
                                    campaign_id=row.campaign_id,
                                    campaign_name=row.campaign_name,
                                    theme=row.theme,
                                    slogan=row.slogan,
                                    size=row.size,
                                )
                            )
                        )
                        row.image_url = self._artifact_storage.ensure_object_present(
                            row.task_id, generated.image_bytes, generated.mime_type
                        )
                        row.updated_at = utc_now()
                    task = self._row_to_poster_task(row)
                    set_span_attributes(span, {"status": "ok", "campaign_id": row.campaign_id})
            return task

    def mark_poster_task_failed(self, task_id: str, error_message: str) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(select(PosterTaskRow).where(PosterTaskRow.task_id == task_id)).first()
                if row is None:
                    return
                row.status = "failed"
                row.error_message = error_message
                row.updated_at = utc_now()
        self._artifact_storage.delete_object(task_id)

    def delete_poster_task(self, task_id: str) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(select(PosterTaskRow).where(PosterTaskRow.task_id == task_id)).first()
                if row is not None:
                    session.delete(row)
                for idem in session.scalars(
                    select(PosterIdempotencyRow).where(PosterIdempotencyRow.task_id == task_id)
                ).all():
                    session.delete(idem)
        self._artifact_storage.delete_object(task_id)

    def get_poster_task(self, *, user_id: str, tenant_id: str | None, task_id: str):
        with self._session() as session:
            row = session.scalars(
                select(PosterTaskRow).where(
                    PosterTaskRow.task_id == task_id,
                    PosterTaskRow.user_id == user_id,
                    _tenant_filter(PosterTaskRow.tenant_id, tenant_id),
                )
            ).first()
        if row is None:
            return None
        if (
            row.status == "queued"
            and get_settings().task_auto_complete_seconds == 0
            and not (get_settings().celery_broker_url and get_settings().celery_result_backend)
        ):
            return self.process_poster_task(task_id).to_public()
        if row.status == "failed":
            self._artifact_storage.delete_object(task_id)
        return self._row_to_poster_task(row).to_public()

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
        with self._session() as session:
            rows = session.scalars(
                select(PosterTaskRow).where(
                    PosterTaskRow.user_id == user_id,
                    _tenant_filter(PosterTaskRow.tenant_id, tenant_id),
                )
            ).all()
        if status:
            rows = [item for item in rows if item.status == status]
        if campaign_id:
            rows = [item for item in rows if item.campaign_id == campaign_id]
        items = []
        for row in rows:
            if (
                row.status == "queued"
                and get_settings().task_auto_complete_seconds == 0
                and not (get_settings().celery_broker_url and get_settings().celery_result_backend)
            ):
                items.append(self.process_poster_task(row.task_id).to_public())
            else:
                items.append(self._row_to_poster_task(row).to_public())
        reverse = sort_order != "asc"
        sort_field = sort_by if sort_by in {"updated_at", "created_at", "status", "campaign_name"} else "updated_at"
        items.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
        total = len(items)
        total_pages = (total + page_size - 1) // page_size if total else 0
        return PosterTaskListData(
            items=items[(page - 1) * page_size : (page - 1) * page_size + page_size],
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_field,
            sort_order="desc" if reverse else "asc",
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
            created_at=row.created_at.isoformat(),
            estimated_seconds=row.estimated_seconds,
            image_url=row.image_url,
            error_message=row.error_message,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )
