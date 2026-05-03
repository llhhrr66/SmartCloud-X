from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pymongo import AsyncMongoClient

from app.core.config import Settings
from app.core.metrics import marketing_mongodb_operations_total, marketing_upstream_errors_total
from app.core.telemetry import set_span_attributes, start_span
from app.models import PosterResultData, PosterTask

_MONGODB_READINESS_TIMEOUT_SECONDS = 1.0
_MONGODB_CLIENT_TIMEOUT_MS = 1000


def _build_result(task: PosterTask) -> PosterResultData:
    result_ready = bool(task.image_url and task.status == "completed")
    download_url = f"{task.image_url}?download=1" if result_ready and task.image_url else None
    return PosterResultData(
        task_id=task.task_id,
        status=task.status,
        result_ready=result_ready,
        campaign_id=task.campaign_id,
        campaign_name=task.campaign_name,
        theme=task.theme,
        slogan=task.slogan,
        size=task.size,
        image_url=task.image_url,
        preview_url=task.image_url if result_ready else None,
        download_url=download_url,
        mime_type="image/png" if result_ready else None,
        generated_at=task.updated_at,
    )


class DisabledMarketingMongoRuntime:
    enabled = False

    async def upsert_asset(self, task: PosterTask) -> PosterResultData:
        return _build_result(task)

    async def readiness(self) -> dict[str, object]:
        return {
            "ready": True,
            "configured": False,
            "detail": "disabled",
        }

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "inactive",
            "configured": False,
            "database": None,
            "collection": "marketing_assets",
        }

    def close(self) -> None:
        return None


@dataclass
class MarketingMongoRuntime:
    client: AsyncMongoClient
    database_name: str

    enabled = True
    collection_name = "marketing_assets"

    @classmethod
    async def connect(cls, settings: Settings) -> "MarketingMongoRuntime":
        client = AsyncMongoClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=_MONGODB_CLIENT_TIMEOUT_MS,
            connectTimeoutMS=_MONGODB_CLIENT_TIMEOUT_MS,
            socketTimeoutMS=_MONGODB_CLIENT_TIMEOUT_MS,
        )
        await client.aconnect()
        return cls(client=client, database_name=settings.mongodb_database)

    @property
    def collection(self):
        return self.client[self.database_name][self.collection_name]

    async def upsert_asset(self, task: PosterTask) -> PosterResultData:
        result = _build_result(task)
        document = {
            "_id": task.task_id,
            "task_id": task.task_id,
            "tenant_id": task.tenant_id,
            "user_id": task.user_id,
            "campaign_id": task.campaign_id,
            "campaign_name": task.campaign_name,
            "theme": task.theme,
            "slogan": task.slogan,
            "size": task.size,
            "status": task.status,
            "image_url": task.image_url,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "result": result.model_dump(mode="json"),
        }
        with start_span(
            "marketing.mongodb_upsert",
            attributes={
                "operation": "mongodb_upsert",
                "poster_task_id": task.task_id,
                "campaign_id": task.campaign_id,
                "user_id": task.user_id,
                "tenant_id": task.tenant_id,
            },
        ) as span:
            try:
                await self.collection.replace_one({"_id": task.task_id}, document, upsert=True)
                marketing_mongodb_operations_total.labels(operation="upsert", status="success").inc()
                set_span_attributes(span, {"status": "ok"})
            except Exception as exc:
                marketing_mongodb_operations_total.labels(operation="upsert", status="error").inc()
                marketing_upstream_errors_total.labels(backend="mongodb", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
                raise
        return result

    async def readiness(self) -> dict[str, object]:
        with start_span("marketing.mongodb_readiness", attributes={"operation": "mongodb_readiness"}) as span:
            try:
                await asyncio.wait_for(
                    self.client.admin.command("ping"),
                    timeout=_MONGODB_READINESS_TIMEOUT_SECONDS,
                )
                marketing_mongodb_operations_total.labels(operation="ping", status="success").inc()
                set_span_attributes(span, {"status": "ok"})
                return {
                    "ready": True,
                    "configured": True,
                    "detail": "ping-ok",
                }
            except TimeoutError:
                marketing_mongodb_operations_total.labels(operation="ping", status="error").inc()
                marketing_upstream_errors_total.labels(backend="mongodb", error_type="TimeoutError").inc()
                set_span_attributes(span, {"status": "error", "error_type": "TimeoutError"})
                return {
                    "ready": False,
                    "configured": True,
                    "detail": "error:TimeoutError",
                }
            except Exception as exc:
                marketing_mongodb_operations_total.labels(operation="ping", status="error").inc()
                marketing_upstream_errors_total.labels(backend="mongodb", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
                return {
                    "ready": False,
                    "configured": True,
                    "detail": f"error:{exc.__class__.__name__}",
                }

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "mongodb",
            "configured": True,
            "database": self.database_name,
            "collection": self.collection_name,
        }

    def close(self) -> None:
        self.client.close()


_runtime: DisabledMarketingMongoRuntime | MarketingMongoRuntime = DisabledMarketingMongoRuntime()


def set_marketing_mongo_runtime(
    runtime: DisabledMarketingMongoRuntime | MarketingMongoRuntime | None,
) -> None:
    global _runtime
    _runtime = runtime or DisabledMarketingMongoRuntime()


def get_marketing_mongo_runtime() -> DisabledMarketingMongoRuntime | MarketingMongoRuntime:
    return _runtime
