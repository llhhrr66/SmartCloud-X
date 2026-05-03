from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from functools import lru_cache
from threading import RLock
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, create_engine, delete, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.core.metrics import (
    RESEARCH_IDEMPOTENCY_REPLAYS_TOTAL,
    RESEARCH_TASKS_COMPLETED_TOTAL,
    RESEARCH_TASKS_CREATED_TOTAL,
    TASK_CANCELLED_TOTAL,
)
from app.models import (
    CreateResearchTaskRequest,
    ResearchCitation,
    ResearchIdempotencyRecord,
    ResearchResult,
    ResearchSection,
    ResearchTask,
    ResearchTaskCreateResponseData,
    ResearchTaskListData,
    ResearchTaskMutationResponseData,
    ResearchTaskRecord,
    ResearchStoreSnapshot,
    ServiceError,
    utc_now,
)


class Base(DeclarativeBase):
    pass


class ResearchTaskRow(Base):
    __tablename__ = "research_tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    topic: Mapped[str] = mapped_column(String(512))
    scope: Mapped[str] = mapped_column(String(4000))
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
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


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
        self._ensure_schema_columns()
        self._bootstrap_if_needed()
        self._snapshot = self._load_snapshot()

    def _session(self) -> Session:
        return self._session_factory()

    def _ensure_schema_columns(self) -> None:
        with self._engine.begin() as connection:
            columns = {item["name"] for item in inspect(connection).get_columns("research_tasks")}
            if "deleted_at" not in columns:
                connection.exec_driver_sql("ALTER TABLE research_tasks ADD COLUMN deleted_at DATETIME")
            if "agent_result" not in columns:
                connection.exec_driver_sql("ALTER TABLE research_tasks ADD COLUMN agent_result JSON")

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
                            deleted_at=_parse_datetime(item.deleted_at) if item.deleted_at else None,
                            agent_result=item.agent_result.model_dump(mode="json") if item.agent_result else None,
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
            self._ensure_schema_columns()
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
                        RESEARCH_IDEMPOTENCY_REPLAYS_TOTAL.inc()
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
                    deleted_at=None,
                    agent_result=None,
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
                try:
                    session.flush()
                except IntegrityError:
                    session.rollback()
                    with self._session_factory.begin() as retry_session:
                        existing = retry_session.scalars(
                            select(ResearchIdempotencyRow).where(
                                ResearchIdempotencyRow.key == idempotency_key,
                                ResearchIdempotencyRow.user_id == user_id,
                                _tenant_filter(ResearchIdempotencyRow.tenant_id, tenant_id),
                            )
                        ).first()
                        if existing is None:
                            raise
                        if existing.payload_hash != payload_hash:
                            raise ServiceError(
                                409,
                                4090001,
                                "idempotency key conflicts with a different research task payload",
                            )
                        RESEARCH_IDEMPOTENCY_REPLAYS_TOTAL.inc()
                        return ResearchTaskCreateResponseData(
                            task_id=existing.task_id,
                            status=existing.accepted_status,
                            estimated_minutes=existing.estimated_minutes,
                        )
            self._snapshot = self._load_snapshot()
        RESEARCH_TASKS_CREATED_TOTAL.inc()
        return ResearchTaskCreateResponseData(
            task_id=task.task_id,
            status="queued",
            estimated_minutes=estimated_minutes,
        )

    def delete_task(self, task_id: str) -> None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(select(ResearchTaskRow).where(ResearchTaskRow.task_id == task_id)).first()
                if row is None:
                    return
                session.execute(delete(ResearchIdempotencyRow).where(ResearchIdempotencyRow.task_id == task_id))
                session.delete(row)
            self._snapshot = self._load_snapshot()

    def get_task(self, *, user_id: str, tenant_id: str | None, task_id: str):
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(
                    select(ResearchTaskRow).where(
                        ResearchTaskRow.user_id == user_id,
                        _tenant_filter(ResearchTaskRow.tenant_id, tenant_id),
                        ResearchTaskRow.task_id == task_id,
                        ResearchTaskRow.deleted_at.is_(None),
                    )
                ).first()
                if row is None:
                    return None
                self._maybe_complete(row)
                task = self._row_to_task(row).to_public()
            self._snapshot = self._load_snapshot()
        return task

    def get_task_record(self, *, user_id: str, tenant_id: str | None, task_id: str) -> ResearchTaskRecord | None:
        with self._lock:
            with self._session_factory.begin() as session:
                row = session.scalars(
                    select(ResearchTaskRow).where(
                        ResearchTaskRow.user_id == user_id,
                        _tenant_filter(ResearchTaskRow.tenant_id, tenant_id),
                        ResearchTaskRow.task_id == task_id,
                        ResearchTaskRow.deleted_at.is_(None),
                    )
                ).first()
                if row is None:
                    return None
                self._maybe_complete(row)
                record = self._row_to_task(row)
            self._snapshot = self._load_snapshot()
        return record

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
                        ResearchTaskRow.deleted_at.is_(None),
                    )
                ).all()
                for row in rows:
                    self._maybe_complete(row)
                if status:
                    rows = [item for item in rows if item.status == status]
                reverse = sort_order != "asc"
                sort_field = sort_by if sort_by in {"created_at", "updated_at", "progress", "topic", "status"} else "updated_at"
                rows.sort(key=lambda item: _sortable_value(getattr(item, sort_field)), reverse=reverse)
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

    def update_task_after_agent(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        task_id: str,
        result: ResearchResult,
        report_file_id: str | None = None,
    ) -> ResearchTaskRecord:
        with self._lock:
            with self._session_factory.begin() as session:
                row = self._get_owned_row(session, user_id=user_id, tenant_id=tenant_id, task_id=task_id)
                if row.status == "cancelled":
                    return self._row_to_task(row)
                finished_at = utc_now()
                row.status = "completed"
                row.progress = 100
                row.started_at = _coerce_utc(row.started_at) or _coerce_utc(row.created_at)
                row.finished_at = finished_at
                row.updated_at = finished_at
                row.summary = result.summary
                row.report_file_id = report_file_id or row.report_file_id or f"file_report_{row.task_id}"
                row.error_message = None
                row.agent_result = result.model_dump(mode="json")
                session.flush()
                record = self._row_to_task(row)
                session.execute(
                    select(ResearchIdempotencyRow).where(ResearchIdempotencyRow.task_id == task_id)
                )
                for item in session.scalars(select(ResearchIdempotencyRow).where(ResearchIdempotencyRow.task_id == task_id)).all():
                    item.accepted_status = row.status
            self._snapshot = self._load_snapshot()
        RESEARCH_TASKS_COMPLETED_TOTAL.inc()
        return record

    def mark_task_failed(
        self,
        *,
        user_id: str,
        tenant_id: str | None,
        task_id: str,
        error_message: str,
    ) -> ResearchTaskRecord:
        with self._lock:
            with self._session_factory.begin() as session:
                row = self._get_owned_row(session, user_id=user_id, tenant_id=tenant_id, task_id=task_id)
                if row.status == "cancelled":
                    return self._row_to_task(row)
                finished_at = utc_now()
                row.status = "failed"
                row.progress = min(max(row.progress, 15), 99)
                row.started_at = _coerce_utc(row.started_at) or _coerce_utc(row.created_at)
                row.finished_at = finished_at
                row.updated_at = finished_at
                row.error_message = error_message
                for item in session.scalars(select(ResearchIdempotencyRow).where(ResearchIdempotencyRow.task_id == task_id)).all():
                    item.accepted_status = row.status
                record = self._row_to_task(row)
            self._snapshot = self._load_snapshot()
        return record

    def cancel_task(self, *, user_id: str, tenant_id: str | None, task_id: str) -> ResearchTaskMutationResponseData:
        with self._lock:
            with self._session_factory.begin() as session:
                row = self._get_owned_row(session, user_id=user_id, tenant_id=tenant_id, task_id=task_id)
                self._maybe_complete(row)
                if row.status == "completed":
                    raise ServiceError(409, 4090002, "completed task cannot be cancelled")
                if row.status == "cancelled":
                    return ResearchTaskMutationResponseData(
                        task_id=row.task_id,
                        status="cancelled",
                        updated_at=_coerce_utc(row.updated_at).isoformat(),
                        error_message=row.error_message,
                    )
                now = utc_now()
                row.status = "cancelled"
                row.error_message = "cancelled by user"
                row.progress = min(row.progress, 99)
                row.started_at = _coerce_utc(row.started_at) if row.started_at else _coerce_utc(row.created_at)
                row.finished_at = now
                row.updated_at = now
                for item in session.scalars(select(ResearchIdempotencyRow).where(ResearchIdempotencyRow.task_id == task_id)).all():
                    item.accepted_status = row.status
                response = ResearchTaskMutationResponseData(
                    task_id=row.task_id,
                    status="cancelled",
                    updated_at=now.isoformat(),
                    error_message=row.error_message,
                )
            self._snapshot = self._load_snapshot()
        TASK_CANCELLED_TOTAL.inc()
        return response

    def archive_task(self, *, user_id: str, tenant_id: str | None, task_id: str) -> ResearchTaskMutationResponseData:
        with self._lock:
            with self._session_factory.begin() as session:
                row = self._get_owned_row(session, user_id=user_id, tenant_id=tenant_id, task_id=task_id)
                self._maybe_complete(row)
                if row.status not in {"completed", "failed", "cancelled"}:
                    raise ServiceError(409, 4090003, "only terminal tasks can be deleted")
                now = utc_now()
                row.deleted_at = now
                row.updated_at = now
                response = ResearchTaskMutationResponseData(
                    task_id=row.task_id,
                    status=row.status,
                    updated_at=now.isoformat(),
                    error_message=row.error_message,
                    deleted_at=now.isoformat(),
                )
            self._snapshot = self._load_snapshot()
        return response

    def _maybe_complete(self, row: ResearchTaskRow) -> bool:
        if row.status not in {"queued", "running"}:
            return False
        if row.agent_result:
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
        if not row.agent_result:
            row.agent_result = _build_legacy_agent_result(row).model_dump(mode="json")
        return True

    @staticmethod
    def _get_owned_row(session: Session, *, user_id: str, tenant_id: str | None, task_id: str) -> ResearchTaskRow:
        row = session.scalars(
            select(ResearchTaskRow).where(
                ResearchTaskRow.user_id == user_id,
                _tenant_filter(ResearchTaskRow.tenant_id, tenant_id),
                ResearchTaskRow.task_id == task_id,
                ResearchTaskRow.deleted_at.is_(None),
            )
        ).first()
        if row is None:
            raise ServiceError(404, 4040001, f"research task '{task_id}' was not found")
        return row

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
            deleted_at=_coerce_utc(row.deleted_at).isoformat() if row.deleted_at else None,
            agent_result=ResearchResult.model_validate(row.agent_result) if row.agent_result else None,
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


def _sortable_value(value: Any):
    if isinstance(value, datetime):
        return _coerce_utc(value)
    return value or ""


def _extract_reference_domains(reference_urls: list[str]) -> list[str]:
    domains: list[str] = []
    for item in reference_urls:
        parsed = __import__("urllib.parse").parse.urlparse(item)
        domain = parsed.netloc or parsed.path
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:5]


def _extract_keywords(topic: str, scope: str) -> list[str]:
    import re

    raw_tokens = [
        token.strip("-_,.，。；;：:()[]{}")
        for token in re.split(r"\s+|/|,|，|。|；|;|：|:\\n", f"{topic} {scope}")
    ]
    keywords: list[str] = []
    for token in raw_tokens:
        if len(token) < 2:
            continue
        if token not in keywords:
            keywords.append(token)
    return keywords[:8] or [topic[:24] or "研究主题"]


def _normalize_database_url(value: str) -> str:
    return value.replace("mysql://", "mysql+pymysql://", 1) if value.startswith("mysql://") else value


def _connect_args(database_url: str) -> dict[str, Any]:
    return {"check_same_thread": False} if database_url.startswith("sqlite") else {}


def _build_legacy_agent_result(row: ResearchTaskRow) -> ResearchResult:
    reference_urls = list(row.reference_urls or [])
    normalized_topic = row.topic.strip()
    normalized_scope = row.scope.strip()
    domain_hints = _extract_reference_domains(reference_urls)
    topical_keywords = _extract_keywords(normalized_topic, normalized_scope)
    sections = [
        ResearchSection(title="研究范围", content=normalized_scope),
        ResearchSection(
            title="关键发现",
            content=(
                f"该主题当前最值得关注的维度包括：{', '.join(topical_keywords[:4])}。"
                + (
                    f" 参考来源主要来自 {', '.join(domain_hints)}。"
                    if domain_hints
                    else " 当前输入未提供外部链接，因此结论主要依据主题与范围文本整理。"
                )
            ),
        ),
        ResearchSection(
            title="建议动作",
            content=f"建议先按 {row.output_format} 交付形式沉淀可复用结论，再补充针对“{normalized_topic}”的验证数据和成本评估。",
        ),
    ]
    citations = [
        ResearchCitation(
            title=f"输入参考 {index}",
            url=url,
            snippet=f"与“{normalized_topic}”相关的输入参考，重点用于支持 {topical_keywords[min(index - 1, len(topical_keywords) - 1)]} 维度。",
        )
        for index, url in enumerate(reference_urls, start=1)
    ]
    if not citations:
        citations = [
            ResearchCitation(
                title="Topic brief",
                url=f"baseline://research/topic/{quote(normalized_topic)}",
                snippet=f"由 topic/scope 自动生成的主题摘要，覆盖 {', '.join(topical_keywords[:3])}。",
            )
        ]
    return ResearchResult(
        summary=(
            f"围绕“{normalized_topic}”完成了 {row.depth} 深度研究草稿，重点覆盖 {', '.join(topical_keywords[:3])}，"
            f"并结合 {max(len(reference_urls), 1)} 份参考输入整理出结论、风险和下一步动作。"
        ),
        sections=sections,
        citations=citations,
        metadata={
            "provider": "baseline",
            "depth": row.depth,
            "output_format": row.output_format,
            "reference_url_count": len(reference_urls),
            "topic_keywords": topical_keywords,
            "reference_domains": domain_hints,
        },
    )
