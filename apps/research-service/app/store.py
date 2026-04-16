from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, create_engine, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.models import (
    CreateResearchTaskRequest,
    ResearchIdempotencyRecord,
    ResearchTaskCreateResponseData,
    ResearchTaskListData,
    ResearchTaskRecord,
    ResearchStoreSnapshot,
    ServiceError,
    now_iso,
    utc_now,
)


class Base(DeclarativeBase):
    pass


class ResearchTaskRow(Base):
    __tablename__ = "research_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    topic: Mapped[str] = mapped_column(String(255))
    scope: Mapped[str] = mapped_column(String(2000))
    depth: Mapped[str] = mapped_column(String(32))
    output_format: Mapped[str] = mapped_column(String(32))
    reference_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    report_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class ResearchIdempotencyRow(Base):
    __tablename__ = "research_idempotency_records"
    __table_args__ = (
        UniqueConstraint("key", "user_id", "tenant_id", name="uq_research_idempotency_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(128))
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    accepted_status: Mapped[str] = mapped_column(String(32))
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ResearchStore:
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
        Base.metadata.create_all(self._engine)
        self._bootstrap_if_needed()
        self._snapshot = self._load_snapshot()

    def _session(self) -> Session:
        return self._session_factory()

    def _bootstrap_if_needed(self) -> None:
        with self._session() as session:
            has_rows = session.execute(select(ResearchTaskRow).limit(1)).first() is not None or session.execute(
                select(ResearchIdempotencyRow).limit(1)
            ).first() is not None
        if has_rows:
            return
        snapshot = self._load_bootstrap_snapshot()
        self._replace_snapshot(snapshot)

    def _load_bootstrap_snapshot(self) -> ResearchStoreSnapshot:
        if self._bootstrap_path and self._bootstrap_path.exists():
            return ResearchStoreSnapshot.model_validate_json(self._bootstrap_path.read_text(encoding="utf-8"))
        return ResearchStoreSnapshot()

    def _load_snapshot(self) -> ResearchStoreSnapshot:
        with self._session() as session:
            tasks = [
                self._row_to_task(item)
                for item in session.scalars(select(ResearchTaskRow).order_by(ResearchTaskRow.created_at)).all()
            ]
            idempotency_records = [
                self._row_to_idempotency(item)
                for item in session.scalars(
                    select(ResearchIdempotencyRow).order_by(ResearchIdempotencyRow.created_at, ResearchIdempotencyRow.id)
                ).all()
            ]
        return ResearchStoreSnapshot(tasks=tasks, idempotency_records=idempotency_records)

    def _replace_snapshot(self, snapshot: ResearchStoreSnapshot) -> None:
        with self._lock:
            with self._session() as session:
                with session.begin():
                    session.execute(delete(ResearchIdempotencyRow))
                    session.execute(delete(ResearchTaskRow))
                    session.add_all([
                        ResearchTaskRow(
                            task_id=item.task_id,
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            topic=item.topic,
                            scope=item.scope,
                            depth=item.depth,
                            output_format=item.output_format,
                            reference_urls=list(item.reference_urls),
                            status=item.status,
                            progress=item.progress,
                            created_at=_parse_datetime(item.created_at),
                            updated_at=_parse_datetime(item.updated_at),
                            summary=item.summary,
                            report_file_id=item.report_file_id,
                            started_at=_parse_datetime(item.started_at) if item.started_at else None,
                            finished_at=_parse_datetime(item.finished_at) if item.finished_at else None,
                            error_message=item.error_message,
                        )
                        for item in snapshot.tasks
                    ])
                    session.add_all([
                        ResearchIdempotencyRow(
                            key=item.key,
                            user_id=item.user_id,
                            tenant_id=item.tenant_id,
                            payload_hash=item.payload_hash,
                            task_id=item.task_id,
                            accepted_status=item.accepted_status,
                            estimated_minutes=item.estimated_minutes,
                            created_at=_parse_datetime(item.created_at),
                        )
                        for item in snapshot.idempotency_records
                    ])
        self._snapshot = self._load_snapshot()

    def _persist(self, snapshot: ResearchStoreSnapshot | None = None) -> None:
        self._replace_snapshot(snapshot or self._snapshot)

    def clear(self) -> None:
        with self._lock:
            Base.metadata.drop_all(self._engine)
            Base.metadata.create_all(self._engine)
            self._replace_snapshot(self._load_bootstrap_snapshot())

    def create_task(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        payload: CreateResearchTaskRequest,
        idempotency_key: str | None,
    ) -> ResearchTaskCreateResponseData:
        normalized_payload = json.dumps(payload.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        payload_hash = _payload_hash(user_id=user_id, tenant_id=tenant_id, normalized_payload=normalized_payload)
        legacy_payload_hash = _legacy_payload_hash(user_id=user_id, normalized_payload=normalized_payload)
        estimated_minutes = get_settings().default_estimated_minutes
        with self._lock:
            with self._session_factory.begin() as session:
                if idempotency_key:
                    existing = session.scalars(
                        select(ResearchIdempotencyRow).where(
                            ResearchIdempotencyRow.key == idempotency_key,
                            ResearchIdempotencyRow.user_id == user_id,
                            _tenant_filter(ResearchIdempotencyRow.tenant_id, tenant_id),
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
                                "idempotency key conflicts with a different research task payload",
                            )
                        return ResearchTaskCreateResponseData(
                            task_id=existing.task_id,
                            status=existing.accepted_status,
                            estimated_minutes=existing.estimated_minutes,
                        )

                created_at = utc_now()
                task = ResearchTaskRow(
                    task_id=f"task_{uuid4().hex[:12]}",
                    user_id=user_id,
                    tenant_id=tenant_id,
                    topic=payload.topic,
                    scope=payload.scope,
                    depth=payload.depth,
                    output_format=payload.output_format,
                    reference_urls=list(payload.reference_urls),
                    status="queued",
                    progress=10,
                    created_at=created_at,
                    updated_at=created_at,
                )
                session.add(task)
                if idempotency_key:
                    session.add(
                        ResearchIdempotencyRow(
                            key=idempotency_key,
                            user_id=user_id,
                            tenant_id=tenant_id,
                            payload_hash=payload_hash,
                            task_id=task.task_id,
                            accepted_status="queued",
                            estimated_minutes=estimated_minutes,
                            created_at=created_at,
                        )
                    )
            self._snapshot = self._load_snapshot()
        return ResearchTaskCreateResponseData(
            task_id=task.task_id,
            status="queued",
            estimated_minutes=estimated_minutes,
        )

    def get_task(self, *, user_id: str, tenant_id: str | None, task_id: str):
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(
                    select(ResearchTaskRow).where(
                        ResearchTaskRow.user_id == user_id,
                        _tenant_filter(ResearchTaskRow.tenant_id, tenant_id),
                        ResearchTaskRow.task_id == task_id,
                    )
                ).first()
                if row is None:
                    return None
                self._maybe_complete(row)
                task = self._row_to_task(row).to_public()
            self._snapshot = self._load_snapshot()
        return task

    def list_tasks(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
        status: str | None,
    ) -> ResearchTaskListData:
        with self._lock:
            with self._session_factory.begin() as session:
                rows = session.scalars(
                    select(ResearchTaskRow).where(
                        ResearchTaskRow.user_id == user_id,
                        _tenant_filter(ResearchTaskRow.tenant_id, tenant_id),
                    )
                ).all()
                for row in rows:
                    self._maybe_complete(row)
                if status:
                    rows = [item for item in rows if item.status == status]
                reverse = sort_order != "asc"
                sort_field = sort_by if sort_by in {"created_at", "updated_at", "progress", "topic", "status"} else "updated_at"
                rows.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)
                total = len(rows)
                start = (page - 1) * page_size
                end = start + page_size
                items = [self._row_to_task(item).to_public() for item in rows[start:end]]
                total_pages = (total + page_size - 1) // page_size if total else 0
            self._snapshot = self._load_snapshot()
        return ResearchTaskListData(
            items=items,
            page=page,
            page_size=page_size,
            total=total,
            total_pages=total_pages,
            sort_by=sort_field,
            sort_order="desc" if reverse else "asc",
        )

    def _maybe_complete(self, row: ResearchTaskRow) -> bool:
        if row.status not in {"queued", "running"}:
            return False
        settings = get_settings()
        created_at = _coerce_utc(row.created_at)
        elapsed_seconds = max(int((utc_now() - created_at).total_seconds()), 0)
        auto_complete_seconds = max(settings.task_auto_complete_seconds, 0)
        if auto_complete_seconds > 0 and elapsed_seconds < auto_complete_seconds:
            progress = min(95, max(15, int((elapsed_seconds / auto_complete_seconds) * 100)))
            changed = False
            if row.status != "running":
                row.status = "running"
                changed = True
            if row.started_at is None:
                row.started_at = created_at
                changed = True
            if row.progress != progress:
                row.progress = progress
                changed = True
            if changed:
                row.updated_at = utc_now()
            return changed
        row.status = "completed"
        row.progress = 100
        row.started_at = _coerce_utc(row.started_at) or created_at
        row.finished_at = row.finished_at or utc_now()
        row.updated_at = row.finished_at
        row.summary = row.summary or f"已生成“{row.topic}”研究草稿，包含结论、对比矩阵与实施建议。"
        row.report_file_id = row.report_file_id or f"file_report_{row.task_id}"
        return True

    @staticmethod
    def _row_to_task(row: ResearchTaskRow) -> ResearchTaskRecord:
        return ResearchTaskRecord(
            task_id=row.task_id,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            topic=row.topic,
            scope=row.scope,
            depth=row.depth,
            output_format=row.output_format,
            reference_urls=list(row.reference_urls or []),
            status=row.status,
            progress=row.progress,
            created_at=_coerce_utc(row.created_at).isoformat(),
            updated_at=_coerce_utc(row.updated_at).isoformat(),
            summary=row.summary,
            report_file_id=row.report_file_id,
            started_at=_coerce_utc(row.started_at).isoformat() if row.started_at else None,
            finished_at=_coerce_utc(row.finished_at).isoformat() if row.finished_at else None,
            error_message=row.error_message,
        )

    @staticmethod
    def _row_to_idempotency(row: ResearchIdempotencyRow) -> ResearchIdempotencyRecord:
        return ResearchIdempotencyRecord(
            key=row.key,
            user_id=row.user_id,
            tenant_id=row.tenant_id,
            payload_hash=row.payload_hash,
            task_id=row.task_id,
            accepted_status=row.accepted_status,
            estimated_minutes=row.estimated_minutes,
            created_at=_coerce_utc(row.created_at).isoformat(),
        )


@lru_cache(maxsize=1)
def get_research_store() -> ResearchStore:
    return ResearchStore()


def _tenant_scope_matches(record_tenant_id: str | None, request_tenant_id: str | None) -> bool:
    return record_tenant_id == request_tenant_id or (
        record_tenant_id is None and request_tenant_id in {None, "default"}
    )


def _tenant_filter(column, tenant_id: str | None):
    if tenant_id in {None, "default"}:
        return (column == tenant_id) | (column.is_(None))
    return column == tenant_id


def _payload_hash(*, user_id: str, tenant_id: str | None, normalized_payload: str) -> str:
    return hashlib.sha256(f"{tenant_id or ''}:{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()


def _legacy_payload_hash(*, user_id: str, normalized_payload: str) -> str:
    return hashlib.sha256(f"{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()


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
