from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.models.admin import AdminAsyncJob
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository


class DifyDatasetSyncNotConfiguredError(ValueError):
    pass


class DifyDatasetSyncError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class DifyDatasetSyncService:
    def __init__(self, repository: KnowledgeStoreRepository) -> None:
        self.repository = repository
        self.settings = get_settings()

    def build_status(self) -> dict[str, object]:
        configured = all(
            [
                self.settings.dify_dataset_api_base_url,
                self.settings.dify_dataset_api_key,
                self.settings.dify_dataset_id,
            ]
        )
        status = "disabled"
        if configured:
            status = "configured"
            latest_job = self._latest_sync_job()
            if latest_job is not None:
                if latest_job.status == "completed":
                    status = "verified-live"
                elif latest_job.status == "failed":
                    status = "blocked-external"
        return {
            "backend": "dify-dataset-sync",
            "configured": configured,
            "status": status,
            "endpoint": self.settings.dify_dataset_api_base_url,
            "target": self.settings.dify_dataset_id,
            "notes": [
                "dataset push/sync keeps SmartCloud-X knowledge content available inside a Dify dataset when dataset API credentials are configured",
            ],
        }

    def sync_knowledge_base(self, kb_id: str, *, force: bool = False) -> dict[str, object]:
        if not all(
            [
                self.settings.dify_dataset_api_base_url,
                self.settings.dify_dataset_api_key,
                self.settings.dify_dataset_id,
            ]
        ):
            raise DifyDatasetSyncNotConfiguredError("dify dataset sync is disabled")

        kb_profile = self.repository.get_knowledge_base_profile(kb_id)
        if kb_profile is None:
            raise DifyDatasetSyncError(f"knowledge base '{kb_id}' was not found")

        documents = self.repository.list_documents(source_id=kb_id)
        job = AdminAsyncJob(
            job_id=f"job_dify_sync_{uuid4().hex[:12]}",
            type="dify_dataset_sync",
            status="processing",
            progress=10,
            created_at=_utc_now(),
            params={
                "kb_id": kb_id,
                "kb_code": kb_profile.code,
                "dataset_id": self.settings.dify_dataset_id,
                "force": force,
                "document_count": len(documents),
            },
        )
        self.repository.save_admin_job(job)

        try:
            synced_items = self._push_documents(kb_profile.code, documents)
        except Exception as exc:
            self.repository.save_admin_job(
                job.model_copy(
                    update={
                        "status": "failed",
                        "progress": 100,
                        "error_code": "dify_dataset_sync_failed",
                        "error_message": str(exc),
                        "finished_at": _utc_now(),
                    }
                )
            )
            raise DifyDatasetSyncError(str(exc)) from exc

        completed_job = job.model_copy(
            update={
                "status": "completed",
                "progress": 100,
                "finished_at": _utc_now(),
                "params": {**(job.params or {}), "synced_document_count": len(synced_items)},
            }
        )
        self.repository.save_admin_job(completed_job)
        return {
            "job_id": completed_job.job_id,
            "status": completed_job.status,
            "dataset_id": self.settings.dify_dataset_id,
            "synced_documents": len(synced_items),
            "items": synced_items,
        }

    def _push_documents(self, kb_code: str, documents):
        dataset_id = self.settings.dify_dataset_id
        existing = self._list_remote_documents()
        synced_items: list[dict[str, str]] = []
        with httpx.Client(
            base_url=self.settings.dify_dataset_api_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.settings.dify_dataset_api_key}"},
            timeout=self.settings.dify_dataset_timeout_seconds,
            trust_env=False,
        ) as client:
            for document in documents:
                remote_name = f"{kb_code}-{document.id}"
                payload = {
                    "name": remote_name,
                    "text": document.content,
                    "indexing_technique": "high_quality",
                    "doc_form": "text_model",
                    "doc_language": document.language,
                    "process_rule": {"mode": "automatic"},
                }
                remote_document_id = existing.get(remote_name)
                if remote_document_id:
                    response = client.post(
                        f"/datasets/{dataset_id}/documents/{remote_document_id}/update-by-text",
                        json=payload,
                    )
                    action = "updated"
                else:
                    response = client.post(
                        f"/datasets/{dataset_id}/document/create-by-text",
                        json=payload,
                    )
                    action = "created"
                response.raise_for_status()
                body = response.json()
                synced_items.append(
                    {
                        "doc_id": document.id,
                        "remote_name": remote_name,
                        "remote_document_id": str((body.get("document") or {}).get("id") or remote_document_id or ""),
                        "action": action,
                    }
                )
        return synced_items

    def _list_remote_documents(self) -> dict[str, str]:
        dataset_id = self.settings.dify_dataset_id
        page = 1
        limit = 100
        records: dict[str, str] = {}
        with httpx.Client(
            base_url=self.settings.dify_dataset_api_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {self.settings.dify_dataset_api_key}"},
            timeout=self.settings.dify_dataset_timeout_seconds,
            trust_env=False,
        ) as client:
            while True:
                response = client.get(
                    f"/datasets/{dataset_id}/documents",
                    params={"page": page, "limit": limit},
                )
                response.raise_for_status()
                payload = response.json()
                raw_items = payload.get("data") or []
                has_more = payload.get("has_more")
                if isinstance(raw_items, dict):
                    has_more = raw_items.get("has_more", has_more)
                    raw_items = raw_items.get("data") or raw_items.get("items") or []
                items = list(raw_items)
                for item in items:
                    if item.get("name") and item.get("id"):
                        records[str(item["name"])] = str(item["id"])
                if has_more is False:
                    break
                if len(items) < limit:
                    break
                page += 1
        return records

    def _latest_sync_job(self) -> AdminAsyncJob | None:
        jobs = [job for job in self.repository.list_admin_jobs() if job.type == "dify_dataset_sync"]
        if not jobs:
            return None
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs[0]


def get_dify_dataset_sync_service() -> DifyDatasetSyncService:
    return DifyDatasetSyncService(get_repository())
