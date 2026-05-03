from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from pymongo import AsyncMongoClient

from app.core.metrics import RESEARCH_MONGO_OPERATIONS_TOTAL
from app.models import ResearchCitation, ResearchResult, ResearchSection, ResearchTask, ResearchTaskResultData
from app.services.report_renderer import render_research_artifact

_MONGODB_READINESS_TIMEOUT_SECONDS = 1.0
_MONGODB_CLIENT_TIMEOUT_MS = 1000


@dataclass
class ReadinessState:
    ready: bool
    mongo_active: bool
    details: dict[str, Any]


def _render_preview(result: ResearchResult, *, topic: str, scope: str) -> str:
    body = [f"# {topic}", f"## 研究范围\n{scope}"]
    for section in result.sections:
        body.append(f"## {section.title}\n{section.content}")
    return "\n\n".join(body)


def _build_result(task: ResearchTask, *, report_download_base_url: str) -> ResearchTaskResultData:
    result_ready = bool(task.report_file_id and task.status == "completed")
    download_url = None
    preview_text = None
    citations: list[str] = []
    sections: list[ResearchSection] = []
    metadata: dict[str, Any] = {}
    if getattr(task, "agent_result", None):
        agent_result = ResearchResult.model_validate(task.agent_result)
        rendered = render_research_artifact(task, agent_result)
        citations = [citation.url for citation in rendered.citations]
        sections = list(rendered.sections)
        metadata = dict(rendered.metadata)
        preview_text = rendered.preview_text
        if result_ready:
            download_url = rendered.download_url
        return ResearchTaskResultData(
            task_id=task.task_id,
            status=task.status,
            result_ready=result_ready,
            output_format=task.output_format,
            summary=agent_result.summary,
            report_file_id=rendered.report_file_id,
            download_url=download_url,
            preview_text=preview_text,
            citations=citations,
            generated_at=task.finished_at,
            sections=sections,
            metadata=metadata,
        )
    if result_ready and task.report_file_id:
        fallback_result = ResearchResult(
            summary=task.summary or f"已生成“{task.topic}”研究草稿，包含结论、对比矩阵与实施建议。",
            sections=[
                ResearchSection(title="研究范围", content=task.scope),
                ResearchSection(title="研究结论", content="当前基线已生成结论摘要、对比矩阵与下一步实施建议。"),
            ],
            citations=[
                ResearchCitation(title="Legacy Summary", url="baseline://research/executive-summary"),
            ],
            metadata={"provider": "legacy-baseline"},
        )
        rendered = render_research_artifact(task, fallback_result)
        download_url = rendered.download_url
        preview_text = rendered.preview_text
        citations = [citation.url for citation in rendered.citations]
        sections = list(rendered.sections)
        metadata = dict(rendered.metadata)
    return ResearchTaskResultData(
        task_id=task.task_id,
        status=task.status,
        result_ready=result_ready,
        output_format=task.output_format,
        summary=task.summary,
        report_file_id=task.report_file_id,
        download_url=download_url,
        preview_text=preview_text,
        citations=citations,
        generated_at=task.finished_at,
        sections=sections,
        metadata=metadata,
    )


class DisabledResearchMongoRuntime:
    enabled = False

    async def upsert_report(self, task: ResearchTask, *, report_download_base_url: str) -> ResearchTaskResultData:
        RESEARCH_MONGO_OPERATIONS_TOTAL.labels(operation="upsert_report", status="disabled").inc()
        return _build_result(task, report_download_base_url=report_download_base_url)

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "inactive",
            "configured": False,
            "database": None,
            "collection": "research_reports",
        }

    async def readiness(self) -> ReadinessState:
        return ReadinessState(
            ready=True,
            mongo_active=False,
            details={
                "configured": False,
                "backend": "disabled",
                "reason": "mongodb not configured; using inline fallback",
            },
        )

    def close(self) -> None:
        return None


class ResearchMongoRuntime:
    enabled = True
    collection_name = "research_reports"

    def __init__(self, client: AsyncMongoClient, database_name: str) -> None:
        self.client = client
        self.database_name = database_name

    @classmethod
    async def connect(cls, settings) -> "ResearchMongoRuntime":
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

    async def upsert_report(
        self,
        task: ResearchTask,
        *,
        report_download_base_url: str,
    ) -> ResearchTaskResultData:
        result = _build_result(task, report_download_base_url=report_download_base_url)
        document = {
            "_id": task.task_id,
            "task_id": task.task_id,
            "tenant_id": getattr(task, "tenant_id", None),
            "user_id": getattr(task, "user_id", None),
            "topic": task.topic,
            "scope": task.scope,
            "depth": task.depth,
            "output_format": task.output_format,
            "status": task.status,
            "summary": task.summary,
            "report_file_id": task.report_file_id,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "result": result.model_dump(mode="json"),
        }
        try:
            await self.collection.replace_one({"_id": task.task_id}, document, upsert=True)
        except Exception:
            RESEARCH_MONGO_OPERATIONS_TOTAL.labels(operation="upsert_report", status="error").inc()
            raise
        RESEARCH_MONGO_OPERATIONS_TOTAL.labels(operation="upsert_report", status="ok").inc()
        return result

    def describe_backend(self) -> dict[str, object]:
        return {
            "backend": "mongodb",
            "configured": True,
            "database": self.database_name,
            "collection": self.collection_name,
        }

    async def readiness(self) -> ReadinessState:
        try:
            await asyncio.wait_for(
                self.client.admin.command("ping"),
                timeout=_MONGODB_READINESS_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return ReadinessState(
                ready=False,
                mongo_active=True,
                details={
                    "configured": True,
                    "backend": "mongodb",
                    "error": "TimeoutError",
                    "message": "mongodb readiness probe timed out",
                },
            )
        except Exception as exc:
            return ReadinessState(
                ready=False,
                mongo_active=True,
                details={
                    "configured": True,
                    "backend": "mongodb",
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
        return ReadinessState(
            ready=True,
            mongo_active=True,
            details={
                "configured": True,
                "backend": "mongodb",
                "database": self.database_name,
                "collection": self.collection_name,
            },
        )

    def close(self) -> None:
        self.client.close()


_runtime: DisabledResearchMongoRuntime | ResearchMongoRuntime = DisabledResearchMongoRuntime()


def set_research_mongo_runtime(runtime: DisabledResearchMongoRuntime | ResearchMongoRuntime | None) -> None:
    global _runtime
    _runtime = runtime or DisabledResearchMongoRuntime()


def get_research_mongo_runtime() -> DisabledResearchMongoRuntime | ResearchMongoRuntime:
    return _runtime
