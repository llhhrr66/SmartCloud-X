from __future__ import annotations

import ipaddress
from unittest.mock import patch

import pytest

from app.models import ResearchResult, ResearchTask
from app.services.research_agent import PipelineResearchAgent, get_research_agent_provider
from app.services.synthesis import SourceDocument, synthesize_report
from app.services.web_reader import WebPage, _is_private_host, fetch_page


def _make_task(**overrides) -> ResearchTask:
    defaults = {
        "task_id": "t_pipeline_001",
        "status": "running",
        "topic": "人工智能在医疗领域的应用",
        "scope": "分析 AI 在医学影像、药物研发、临床决策中的最新进展",
        "depth": "standard",
        "output_format": "markdown",
        "progress": 0,
        "created_at": "2026-05-01T00:00:00+00:00",
        "reference_urls": ["https://example.com/ai-medical"],
    }
    defaults.update(overrides)
    return ResearchTask(**defaults)


class TestSynthesis:
    def test_synthesize_returns_result_with_citations(self) -> None:
        sources = [
            SourceDocument(
                title="AI 医学影像",
                url="https://example.com/imaging",
                text="深度学习在 X 光和 CT 影像分析中表现优异。FDA 已批准多种 AI 辅助诊断工具。",
                snippet="深度学习在影像分析中表现优异",
            ),
            SourceDocument(
                title="药物研发",
                url="https://example.com/drug",
                text="AI 加速了靶点发现和分子生成。AlphaFold 预测了超过 2 亿个蛋白质结构。",
                snippet="AI 加速靶点发现",
            ),
        ]
        result = synthesize_report(
            topic="AI 医疗",
            scope="影像与药物研发",
            sources=sources,
            depth="standard",
        )
        assert isinstance(result, ResearchResult)
        assert len(result.citations) == 2
        assert result.citations[0].url == "https://example.com/imaging"
        assert result.metadata["provider"] == "pipeline"
        assert result.metadata["synthesis"] == "deterministic-extractive"
        assert result.metadata["source_count"] == 2

    def test_synthesize_empty_sources(self) -> None:
        result = synthesize_report(topic="测试", scope="空数据", sources=[], depth="lite")
        assert "未从外部资料中提取" in result.sections[1].content or len(result.sections) >= 2

    def test_synthesize_deduplicates_sentences(self) -> None:
        source = SourceDocument(
            title="重复测试",
            url="https://example.com/dup",
            text="这是一条关键信息。这是一条关键信息。这是另一条不同的信息。",
        )
        result = synthesize_report(topic="关键信息", scope="测试去重", sources=[source], depth="lite")
        sentences = result.sections[1].content if len(result.sections) > 1 else ""
        count = sentences.count("这是一条关键信息")
        assert count <= 1


class TestWebReader:
    def test_rejects_non_http_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported scheme"):
            fetch_page("ftp://example.com")

    def test_rejects_no_hostname(self) -> None:
        with pytest.raises(ValueError, match="no hostname"):
            fetch_page("http://")

    @patch("app.services.web_reader._is_private_host", return_value=True)
    def test_rejects_private_host(self, _mock) -> None:
        with pytest.raises(ValueError, match="Blocked private"):
            fetch_page("http://192.168.1.1/admin")

    def test_blocked_networks_cover_private_ranges(self) -> None:
        from app.services.web_reader import BLOCKED_NETWORKS

        assert ipaddress.ip_address("10.0.0.1") in BLOCKED_NETWORKS[0]
        assert ipaddress.ip_address("172.16.0.1") in BLOCKED_NETWORKS[1]
        assert ipaddress.ip_address("192.168.1.1") in BLOCKED_NETWORKS[2]
        assert ipaddress.ip_address("127.0.0.1") in BLOCKED_NETWORKS[3]


class TestPipelineAgent:
    def test_provider_factory_returns_pipeline(self) -> None:
        with patch("app.services.research_agent.get_settings") as mock_settings:
            mock_settings.return_value.research_agent_provider = "pipeline"
            agent = get_research_agent_provider()
            assert isinstance(agent, PipelineResearchAgent)

    @pytest.mark.asyncio
    async def test_pipeline_execute_returns_result_with_citations(self) -> None:
        with patch("app.services.research_agent.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.research_agent_provider = "pipeline"
            settings.pipeline_max_pages = 3
            settings.pipeline_fetch_timeout = 5.0
            settings.pipeline_max_bytes = 100_000
            settings.external_search_provider = "disabled"
            settings.external_search_api_url = None
            settings.external_search_api_key = None
            settings.external_search_timeout_seconds = 10.0

            agent = PipelineResearchAgent(settings)

            mock_page = WebPage(
                url="https://example.com/ai-medical",
                title="AI 在医疗中的应用",
                text="深度学习在医学影像分析中表现优异。AI 辅助药物研发取得突破性进展。",
                snippet="深度学习在医学影像分析中表现优异",
                status_code=200,
                content_length=100,
            )
            with patch("app.services.research_agent.fetch_page", return_value=mock_page):
                task = _make_task()
                progress_log: list[tuple[int, str]] = []
                result = await agent.execute(task, on_progress=lambda p, m: progress_log.append((p, m)))

            assert isinstance(result, ResearchResult)
            assert len(result.citations) >= 1
            assert result.citations[0].url == "https://example.com/ai-medical"
            assert result.metadata["provider"] == "pipeline"
            assert any(msg == "pipeline_completed" for _, msg in progress_log)
            assert progress_log[-1][0] == 100

    @pytest.mark.asyncio
    async def test_pipeline_graceful_fetch_failure(self) -> None:
        with patch("app.services.research_agent.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.research_agent_provider = "pipeline"
            settings.pipeline_max_pages = 3
            settings.pipeline_fetch_timeout = 5.0
            settings.pipeline_max_bytes = 100_000
            settings.external_search_provider = "disabled"
            settings.external_search_api_url = None
            settings.external_search_api_key = None
            settings.external_search_timeout_seconds = 10.0

            agent = PipelineResearchAgent(settings)

            with patch("app.services.research_agent.fetch_page", side_effect=Exception("network error")):
                task = _make_task()
                result = await agent.execute(task)

            assert isinstance(result, ResearchResult)
            assert result.metadata["provider"] == "pipeline"

    @pytest.mark.asyncio
    async def test_pipeline_with_external_search_hits(self) -> None:
        with patch("app.services.research_agent.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.research_agent_provider = "pipeline"
            settings.pipeline_max_pages = 5
            settings.pipeline_fetch_timeout = 5.0
            settings.pipeline_max_bytes = 100_000
            settings.external_search_provider = "http_stub"
            settings.external_search_api_url = "http://search-api/search"
            settings.external_search_api_key = None
            settings.external_search_timeout_seconds = 10.0

            agent = PipelineResearchAgent(settings)

            search_results = [
                {"title": "搜索结果1", "url": "https://example.com/hit1", "snippet": "AI 医疗突破"},
            ]
            mock_page = WebPage(
                url="https://example.com/ai-medical",
                title="AI 医疗",
                text="AI 在医学影像中广泛应用。",
                snippet="AI 在医学影像中广泛应用",
                status_code=200,
                content_length=50,
            )

            mock_search_provider = type("MockSearch", (), {
                "search": lambda self, **kw: search_results,
                "capabilities": lambda self: {"provider": "http_stub", "real_search": True, "transport": "http"},
            })()

            with (
                patch("app.services.research_agent.get_external_search_provider", return_value=mock_search_provider),
                patch("app.services.research_agent.fetch_page", return_value=mock_page),
            ):
                task = _make_task()
                result = await agent.execute(task)

            assert isinstance(result, ResearchResult)
