from __future__ import annotations

import asyncio
from typing import Any

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from app.celery_app import celery_app
from app.core.config import get_settings
from app.mongo_runtime import MarketingMongoRuntime
from app.store import get_marketing_store


_settings = get_settings()


class PosterGenerationTask(Task):
    autoretry_for = (RuntimeError, OSError)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_jitter = False
    acks_late = True
    soft_time_limit = _settings.celery_soft_time_limit_seconds
    time_limit = _settings.celery_time_limit_seconds


def _sync_marketing_asset(task) -> None:
    settings = get_settings()
    if not settings.mongodb_uri:
        return

    async def _do():
        runtime = await MarketingMongoRuntime.connect(settings)
        try:
            await runtime.upsert_asset(task)
        finally:
            await runtime.client.close()

    asyncio.run(_do())


@celery_app.task(bind=True, base=PosterGenerationTask, name="marketing.generate_poster_task")
def generate_poster_task(self, task_id: str) -> dict[str, Any]:
    store = get_marketing_store()
    try:
        task = store.process_poster_task(task_id)
    except SoftTimeLimitExceeded:
        store.mark_poster_task_failed(task_id, "celery soft time limit exceeded")
        raise
    except Exception as exc:
        store.mark_poster_task_failed(task_id, str(exc))
        raise
    _sync_marketing_asset(task)
    return task.model_dump(mode="json")
