from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from uuid import uuid4

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


class ResearchStore:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = RLock()
        self._snapshot = self._load()

    def _load(self) -> ResearchStoreSnapshot:
        if self.file_path.exists():
            return ResearchStoreSnapshot.model_validate_json(self.file_path.read_text(encoding="utf-8"))
        snapshot = ResearchStoreSnapshot()
        self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: ResearchStoreSnapshot | None = None) -> None:
        with self._lock:
            target = snapshot or self._snapshot
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path.write_text(target.model_dump_json(indent=2), encoding="utf-8")

    def clear(self) -> None:
        with self._lock:
            self._snapshot = ResearchStoreSnapshot()
            self._persist()

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
            if idempotency_key:
                existing = next(
                    (
                        item
                        for item in self._snapshot.idempotency_records
                        if item.key == idempotency_key
                        and item.user_id == user_id
                        and _tenant_scope_matches(item.tenant_id, tenant_id)
                    ),
                    None,
                )
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

            created_at = now_iso()
            task = ResearchTaskRecord(
                task_id=f"task_{uuid4().hex[:12]}",
                user_id=user_id,
                tenant_id=tenant_id,
                topic=payload.topic,
                scope=payload.scope,
                depth=payload.depth,
                output_format=payload.output_format,
                reference_urls=payload.reference_urls,
                status="queued",
                progress=10,
                created_at=created_at,
                updated_at=created_at,
            )
            self._snapshot.tasks.append(task)
            if idempotency_key:
                self._snapshot.idempotency_records.append(
                    ResearchIdempotencyRecord(
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
            self._persist()
            return ResearchTaskCreateResponseData(
                task_id=task.task_id,
                status="queued",
                estimated_minutes=estimated_minutes,
            )

    def get_task(self, *, user_id: str, tenant_id: str | None, task_id: str):
        with self._lock:
            task = next(
                (
                    item
                    for item in self._snapshot.tasks
                    if item.user_id == user_id
                    and _tenant_scope_matches(item.tenant_id, tenant_id)
                    and item.task_id == task_id
                ),
                None,
            )
            if task is None:
                return None
            changed = self._maybe_complete(task)
            if changed:
                self._persist()
            return task.to_public()

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
            tasks = [
                item
                for item in self._snapshot.tasks
                if item.user_id == user_id and _tenant_scope_matches(item.tenant_id, tenant_id)
            ]
            changed = False
            for task in tasks:
                changed = self._maybe_complete(task) or changed
            if changed:
                self._persist()
            if status:
                tasks = [item for item in tasks if item.status == status]

            reverse = sort_order != "asc"
            sort_field = sort_by if sort_by in {"created_at", "updated_at", "progress", "topic", "status"} else "updated_at"
            tasks.sort(key=lambda item: getattr(item, sort_field) or "", reverse=reverse)

            total = len(tasks)
            start = (page - 1) * page_size
            end = start + page_size
            items = [item.to_public() for item in tasks[start:end]]
            total_pages = (total + page_size - 1) // page_size if total else 0
            return ResearchTaskListData(
                items=items,
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                sort_by=sort_field,
                sort_order="desc" if reverse else "asc",
            )

    def _maybe_complete(self, task: ResearchTaskRecord) -> bool:
        if task.status not in {"queued", "running"}:
            return False
        settings = get_settings()
        created_at = datetime.fromisoformat(task.created_at)
        elapsed_seconds = max(int((utc_now() - created_at).total_seconds()), 0)
        auto_complete_seconds = max(settings.task_auto_complete_seconds, 0)
        if auto_complete_seconds > 0 and elapsed_seconds < auto_complete_seconds:
            progress = min(95, max(15, int((elapsed_seconds / auto_complete_seconds) * 100)))
            changed = False
            if task.status != "running":
                task.status = "running"
                changed = True
            if task.started_at is None:
                task.started_at = task.created_at
                changed = True
            if task.progress != progress:
                task.progress = progress
                changed = True
            if changed:
                task.updated_at = now_iso()
            return changed
        task.status = "completed"
        task.progress = 100
        task.started_at = task.started_at or task.created_at
        task.finished_at = now_iso()
        task.updated_at = task.finished_at
        task.summary = f"已生成“{task.topic}”研究草稿，包含结论、对比矩阵与实施建议。"
        task.report_file_id = f"file_report_{task.task_id}"
        return True


@lru_cache(maxsize=1)
def get_research_store() -> ResearchStore:
    return ResearchStore(get_settings().data_path)


def _tenant_scope_matches(record_tenant_id: str | None, request_tenant_id: str | None) -> bool:
    return record_tenant_id == request_tenant_id or (
        record_tenant_id is None and request_tenant_id in {None, "default"}
    )


def _payload_hash(*, user_id: str, tenant_id: str | None, normalized_payload: str) -> str:
    return hashlib.sha256(f"{tenant_id or ''}:{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()


def _legacy_payload_hash(*, user_id: str, normalized_payload: str) -> str:
    return hashlib.sha256(f"{user_id}:{normalized_payload}".encode("utf-8")).hexdigest()
