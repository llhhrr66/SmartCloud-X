from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol
from urllib import error, parse, request
import json
import re

from app.core.config import Settings, get_settings
from app.core.metrics import (
    RESEARCH_PIPELINE_FETCH_ERRORS_TOTAL,
    RESEARCH_PIPELINE_STEPS_TOTAL,
)
from app.models import ResearchCitation, ResearchResult, ResearchSection, ResearchTask
from app.services.synthesis import SourceDocument, synthesize_report
from app.services.web_reader import WebPage, fetch_page


class ResearchAgentProvider(Protocol):
    async def execute(
        self,
        task: ResearchTask,
        *,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> ResearchResult: ...

    def capabilities(self) -> dict[str, Any]: ...


class ExternalSearchProvider(Protocol):
    def search(self, *, topic: str, scope: str, reference_urls: list[str]) -> list[dict[str, str]]: ...

    def capabilities(self) -> dict[str, Any]: ...


class DisabledExternalSearchProvider:
    provider_name = "disabled"

    def search(self, *, topic: str, scope: str, reference_urls: list[str]) -> list[dict[str, str]]:
        return []

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": False,
            "real_search": False,
            "transport": None,
        }


class HttpStubExternalSearchProvider:
    provider_name = "http_stub"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def search(self, *, topic: str, scope: str, reference_urls: list[str]) -> list[dict[str, str]]:
        if not self._settings.external_search_api_url:
            return []
        payload = {
            "topic": topic,
            "scope": scope,
            "reference_urls": list(reference_urls),
        }
        raw_request = request.Request(
            self._settings.external_search_api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **(
                    {"Authorization": f"Bearer {self._settings.external_search_api_key}"}
                    if self._settings.external_search_api_key
                    else {}
                ),
            },
            method="POST",
        )
        try:
            with request.urlopen(raw_request, timeout=self._settings.external_search_timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError):
            return []
        results = response_payload.get("results") if isinstance(response_payload, dict) else None
        if not isinstance(results, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or url or "外部搜索结果").strip()
            snippet = str(item.get("snippet") or "").strip()
            if not url:
                continue
            normalized.append({"title": title, "url": url, "snippet": snippet})
        return normalized[:5]

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": bool(self._settings.external_search_api_url),
            "real_search": bool(self._settings.external_search_api_url),
            "transport": "http",
        }


class PlaceholderResearchAgent:
    provider_name = "placeholder"

    async def execute(
        self,
        task: ResearchTask,
        *,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> ResearchResult:
        if on_progress is not None:
            on_progress(20, "collecting_references")
            on_progress(45, "synthesizing_findings")
            on_progress(75, "drafting_sections")
            on_progress(100, "baseline_completed")
        return _build_placeholder_result(task)

    def capabilities(self) -> dict[str, Any]:
        search_provider = get_external_search_provider()
        search_capabilities = search_provider.capabilities()
        return {
            "provider": self.provider_name,
            "real_processing": True,
            "real_report_generation": True,
            "external_search": search_capabilities["real_search"],
            "external_search_mode": search_capabilities["provider"],
            "export": True,
            "formats": ["markdown", "pdf"],
            "progress_callbacks": True,
            "search_provider": search_capabilities,
        }


class HttpResearchAgent:
    provider_name = "http"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def execute(
        self,
        task: ResearchTask,
        *,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> ResearchResult:
        if not self._settings.research_agent_api_url:
            raise RuntimeError("RESEARCH_AGENT_API_URL is not configured")
        if on_progress is not None:
            on_progress(20, "http_agent_request_started")
        payload = {
            "task_id": task.task_id,
            "topic": task.topic,
            "scope": task.scope,
            "depth": task.depth,
            "output_format": task.output_format,
            "reference_urls": list(getattr(task, "reference_urls", []) or []),
        }
        raw_request = request.Request(
            self._settings.research_agent_api_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **(
                    {"Authorization": f"Bearer {self._settings.research_agent_api_key}"}
                    if self._settings.research_agent_api_key
                    else {}
                ),
            },
            method="POST",
        )
        try:
            with request.urlopen(raw_request, timeout=self._settings.research_agent_timeout_seconds) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"http research agent returned {exc.code}: {body}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"http research agent unavailable: {exc.reason}") from exc
        if on_progress is not None:
            on_progress(90, "http_agent_response_received")
        return ResearchResult.model_validate(response_payload)

    def capabilities(self) -> dict[str, Any]:
        search_provider = get_external_search_provider()
        search_capabilities = search_provider.capabilities()
        return {
            "provider": self.provider_name,
            "real_processing": True,
            "real_report_generation": True,
            "external_search": True,
            "external_search_mode": search_capabilities["provider"],
            "export": False,
            "formats": ["markdown", "pdf"],
            "progress_callbacks": True,
            "search_provider": search_capabilities,
        }


class PipelineResearchAgent:
    provider_name = "pipeline"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def execute(
        self,
        task: ResearchTask,
        *,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> ResearchResult:
        reference_urls = list(getattr(task, "reference_urls", []) or [])
        normalized_topic = task.topic.strip()
        normalized_scope = task.scope.strip()

        if on_progress:
            on_progress(10, "pipeline_planning")
        RESEARCH_PIPELINE_STEPS_TOTAL.labels(step="plan").inc()

        search_provider = get_external_search_provider()
        search_hits = search_provider.search(
            topic=normalized_topic,
            scope=normalized_scope,
            reference_urls=reference_urls,
        )
        RESEARCH_PIPELINE_STEPS_TOTAL.labels(step="search").inc()
        if on_progress:
            on_progress(30, "pipeline_search_completed")

        sources: list[SourceDocument] = []
        fetch_urls = list(reference_urls)
        for hit in search_hits:
            url = hit.get("url", "")
            if url and url not in fetch_urls:
                fetch_urls.append(url)

        for url in fetch_urls[: self._settings.pipeline_max_pages]:
            try:
                page: WebPage = fetch_page(
                    url,
                    timeout=self._settings.pipeline_fetch_timeout,
                    max_bytes=self._settings.pipeline_max_bytes,
                )
                sources.append(
                    SourceDocument(
                        title=page.title,
                        url=page.url,
                        text=page.text,
                        snippet=page.snippet,
                    )
                )
                RESEARCH_PIPELINE_STEPS_TOTAL.labels(step="fetch").inc()
            except Exception:
                RESEARCH_PIPELINE_FETCH_ERRORS_TOTAL.inc()
                for hit in search_hits:
                    if hit.get("url") == url:
                        sources.append(
                            SourceDocument(
                                title=hit.get("title", url),
                                url=url,
                                text=hit.get("snippet", ""),
                                snippet=hit.get("snippet", ""),
                            )
                        )
                        break
        if on_progress:
            on_progress(60, "pipeline_fetch_completed")

        result = synthesize_report(
            topic=normalized_topic,
            scope=normalized_scope,
            sources=sources,
            depth=task.depth,
            output_format=task.output_format,
        )
        RESEARCH_PIPELINE_STEPS_TOTAL.labels(step="synthesize").inc()
        if on_progress:
            on_progress(85, "pipeline_synthesize_completed")

        RESEARCH_PIPELINE_STEPS_TOTAL.labels(step="report").inc()
        if on_progress:
            on_progress(100, "pipeline_completed")
        return result

    def capabilities(self) -> dict[str, Any]:
        search_provider = get_external_search_provider()
        search_capabilities = search_provider.capabilities()
        return {
            "provider": self.provider_name,
            "real_processing": True,
            "real_report_generation": True,
            "external_search": search_capabilities["real_search"],
            "external_search_mode": search_capabilities["provider"],
            "web_reader": True,
            "citation_tracking": True,
            "synthesis": "deterministic-extractive",
            "export": True,
            "formats": ["markdown", "pdf"],
            "progress_callbacks": True,
            "search_provider": search_capabilities,
        }


def get_research_agent_provider() -> ResearchAgentProvider:
    settings = get_settings()
    if settings.research_agent_provider == "pipeline":
        return PipelineResearchAgent(settings)
    if settings.research_agent_provider in {"http", "http_stub"}:
        return HttpResearchAgent(settings)
    return PlaceholderResearchAgent()


def get_external_search_provider() -> ExternalSearchProvider:
    settings = get_settings()
    if settings.external_search_provider == "http_stub":
        return HttpStubExternalSearchProvider(settings)
    return DisabledExternalSearchProvider()


def describe_research_agent_configuration() -> dict[str, Any]:
    settings = get_settings()
    provider = get_research_agent_provider()
    search_provider = get_external_search_provider()
    provider_capabilities = provider.capabilities()
    search_capabilities = search_provider.capabilities()
    return {
        "provider": settings.research_agent_provider,
        "active": True,
        "capabilities": provider_capabilities,
        "configuration": {
            "api_url_configured": bool(settings.research_agent_api_url),
            "timeout_seconds": settings.research_agent_timeout_seconds,
            "api_key_configured": bool(settings.research_agent_api_key),
            "real_markdown_export": True,
            "real_pdf_export": True,
            "real_report_generation": provider_capabilities.get("real_report_generation", False),
            "external_search": search_capabilities,
            "web_reader": provider_capabilities.get("web_reader", False),
            "citation_tracking": provider_capabilities.get("citation_tracking", False),
            "pipeline_synthesis": provider_capabilities.get("synthesis"),
        },
    }


def _build_placeholder_result(task: ResearchTask) -> ResearchResult:
    reference_urls = list(getattr(task, "reference_urls", []) or [])
    normalized_topic = task.topic.strip()
    normalized_scope = task.scope.strip()
    search_provider = get_external_search_provider()
    search_hits = search_provider.search(
        topic=normalized_topic,
        scope=normalized_scope,
        reference_urls=reference_urls,
    )
    domain_hints = _extract_reference_domains(reference_urls)
    search_domains = _extract_reference_domains([item["url"] for item in search_hits])
    merged_domains: list[str] = []
    for domain in [*domain_hints, *search_domains]:
        if domain not in merged_domains:
            merged_domains.append(domain)
    topical_keywords = _extract_keywords(normalized_topic, normalized_scope)
    summary = (
        f"围绕“{normalized_topic}”完成了 {task.depth} 深度研究草稿，重点覆盖 {', '.join(topical_keywords[:3])}，"
        f"并结合 {max(len(reference_urls) + len(search_hits), 1)} 份输入/检索证据整理出结论、风险和下一步动作。"
    )
    sections = [
        ResearchSection(title="研究范围", content=normalized_scope),
        ResearchSection(
            title="关键发现",
            content=(
                f"该主题当前最值得关注的维度包括：{', '.join(topical_keywords[:4])}。"
                + (
                    f" 参考来源主要来自 {', '.join(merged_domains)}。"
                    if merged_domains
                    else " 当前输入未提供外部链接，因此结论主要依据主题与范围文本整理。"
                )
            ),
        ),
    ]
    if search_hits:
        sections.append(
            ResearchSection(
                title="外部检索补充",
                content="; ".join(f"{item['title']}：{item['snippet'] or item['url']}" for item in search_hits),
            )
        )
    sections.append(
        ResearchSection(
            title="建议动作",
            content=(
                f"建议先按 {task.output_format} 交付形式沉淀可复用结论，再补充针对“{normalized_topic}”的验证数据和成本评估。"
            ),
        )
    )
    citations = [
        ResearchCitation(
            title=f"输入参考 {index}",
            url=url,
            snippet=f"与“{normalized_topic}”相关的输入参考，重点用于支持 {topical_keywords[min(index - 1, len(topical_keywords) - 1)]} 维度。",
        )
        for index, url in enumerate(reference_urls, start=1)
    ]
    citations.extend(
        ResearchCitation(
            title=item["title"],
            url=item["url"],
            snippet=item["snippet"] or f"外部检索命中：{normalized_topic}",
        )
        for item in search_hits
    )
    if not citations:
        citations = [
            ResearchCitation(
                title="Topic brief",
                url=f"baseline://research/topic/{parse.quote(normalized_topic)}",
                snippet=f"由 topic/scope 自动生成的主题摘要，覆盖 {', '.join(topical_keywords[:3])}。",
            )
        ]
    return ResearchResult(
        summary=summary,
        sections=sections,
        citations=citations,
        metadata={
            "provider": "baseline",
            "depth": task.depth,
            "output_format": task.output_format,
            "reference_url_count": len(reference_urls),
            "topic_keywords": topical_keywords,
            "reference_domains": merged_domains,
            "external_search_provider": search_provider.capabilities()["provider"],
            "external_search_hits": len(search_hits),
        },
    )


def _extract_reference_domains(reference_urls: list[str]) -> list[str]:
    domains: list[str] = []
    for item in reference_urls:
        parsed = parse.urlparse(item)
        domain = parsed.netloc or parsed.path
        if domain and domain not in domains:
            domains.append(domain)
    return domains[:5]


def _extract_keywords(topic: str, scope: str) -> list[str]:
    raw_tokens = [token.strip("-_,.，。；;：:()[]{}") for token in re.split(r"\s+|/|,|，|。|；|;|：|:\\n", f"{topic} {scope}")]
    keywords: list[str] = []
    for token in raw_tokens:
        if len(token) < 2:
            continue
        if token not in keywords:
            keywords.append(token)
    return keywords[:8] or [topic[:24] or "研究主题"]
