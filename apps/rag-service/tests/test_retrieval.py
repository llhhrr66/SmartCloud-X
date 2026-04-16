import asyncio
import importlib
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from fastapi.testclient import TestClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, TraceState, use_span
from prometheus_client.parser import text_string_to_metric_families


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def activate_service_imports() -> None:
    for module_name in list(sys.modules):
        if module_name == "app" or module_name.startswith("app."):
            sys.modules.pop(module_name, None)
    if str(SERVICE_ROOT) in sys.path:
        sys.path.remove(str(SERVICE_ROOT))
    sys.path.insert(0, str(SERVICE_ROOT))


activate_service_imports()

from app.api.dependencies import build_upstream_headers
from app.api.routes import admin as admin_routes
from app.api.routes import health as health_routes
from app.api.routes import rag as rag_routes
from app.core.config import get_settings
from app.core.metrics import (
    CACHE_BACKEND_ERRORS_TOTAL,
    CACHE_HITS_TOTAL,
    CACHE_MISSES_TOTAL,
    DEGRADED_RETRIEVALS_TOTAL,
    EMPTY_RETRIEVALS_TOTAL,
    RETRIEVAL_DURATION_SECONDS,
)
from app.core.tracing import configure_tracing, get_tracer, get_tracer_provider
from app.main import app as service_app
from app.models.common import TraceContext
from app.models.rag import (
    AnswerRequest,
    KnowledgeChunkRecord,
    KnowledgeSearchCandidate,
    QueryRewriteResult,
    RetrieveRequest,
)
from app.services.answer import AnswerComposer
from app.services import cache as cache_module
from app.services.cache import get_retrieval_cache
from app.services import knowledge_client as knowledge_client_module
from app.services.knowledge_client import KnowledgeServiceClient, KnowledgeServiceProtocolError
from app.services.health import get_health_service
from app.services.providers import get_knowledge_client
from app.services.query_rewriter import QueryRewriter
from app.services.retrieval import RetrievalService, get_retrieval_service


def clear_service_caches() -> None:
    get_settings.cache_clear()
    get_knowledge_client.cache_clear()
    get_retrieval_cache.cache_clear()
    get_retrieval_service.cache_clear()
    get_health_service.cache_clear()
    get_tracer.cache_clear()
    get_tracer_provider.cache_clear()


class TraceCollectorHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback signature
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        self.__class__.requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib callback signature
        return


def start_trace_collector() -> tuple[ThreadingHTTPServer, Thread]:
    TraceCollectorHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), TraceCollectorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class FakeKnowledgeClient:
    def __init__(self, candidates: list[KnowledgeSearchCandidate]) -> None:
        self.candidates = candidates

    async def search(self, request, rewritten_query: str, headers=None) -> list[KnowledgeSearchCandidate]:
        return self.candidates


class FakeMalformedHttpxResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"data": {"query": "GPU 部署", "total": 1, "results": [{"score": 0.8}]}}


class FakeHttpxAsyncClient:
    def __init__(self, response) -> None:
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        return self.response


class FakeRedisClient:
    def __init__(self, *, fail_operations: bool = False) -> None:
        self.fail_operations = fail_operations
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        if self.fail_operations:
            raise RuntimeError("redis get failed")
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        if self.fail_operations:
            raise RuntimeError("redis set failed")
        self.values[key] = value

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        return [key for key in list(self.values) if key.startswith(prefix)]

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def histogram_count(metric) -> float:
    for collected_metric in metric.collect():
        for sample in collected_metric.samples:
            if sample.name == f"{metric._name}_count":
                return sample.value
    raise AssertionError(f"count sample missing for metric {metric._name}")


def counter_value(metric) -> float:
    for collected_metric in metric.collect():
        for sample in collected_metric.samples:
            if sample.name in {metric._name, f"{metric._name}_total"}:
                return sample.value
    raise AssertionError(f"value sample missing for metric {metric._name}")


def counter_total(metric) -> float:
    total = 0.0
    for collected_metric in metric.collect():
        for sample in collected_metric.samples:
            if sample.name in {metric._name, f"{metric._name}_total"}:
                total += sample.value
    return total


def metric_sample_value(text: str, sample_name: str, labels: dict[str, str] | None = None) -> float:
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name != sample_name:
                continue
            if labels is not None and sample.labels != labels:
                continue
            return sample.value
    raise AssertionError(f"missing sample {sample_name} with labels {labels}")


def test_query_rewriter_expands_known_terms() -> None:
    result = QueryRewriter().rewrite("GPU 部署")

    assert "算力" in result.expanded_terms
    assert "配置" in result.expanded_terms


def test_retrieval_reranks_and_answer_composes() -> None:
    service = RetrievalService(QueryRewriter())
    candidates = [
        KnowledgeSearchCandidate(
            chunk=KnowledgeChunkRecord(
                id="chk-1",
                sourceId="src-1",
                documentId="doc-1",
                documentTitle="GPU 云主机部署建议",
                ordinal=1,
                content="部署 GPU 云主机前先确认驱动版本和镜像规格。",
                tokenEstimate=20,
                keywords=["gpu", "部署", "驱动"],
                tags=["gpu"],
                createdAt="2026-04-16T00:00:00+00:00",
            ),
            sourceName="GPU 文档",
            score=0.7,
            matchReason="matched tokens: gpu, 部署",
        ),
        KnowledgeSearchCandidate(
            chunk=KnowledgeChunkRecord(
                id="chk-2",
                sourceId="src-2",
                documentId="doc-2",
                documentTitle="账单 FAQ",
                ordinal=1,
                content="账单中心支持按月查询。",
                tokenEstimate=10,
                keywords=["账单"],
                tags=["billing"],
                createdAt="2026-04-16T00:00:00+00:00",
            ),
            sourceName="FAQ",
            score=0.4,
            matchReason="matched tokens: 账单",
        ),
    ]

    retrieval = service.build_response(RetrieveRequest(query="GPU 部署", topK=2), candidates, "gpu 部署")
    answer = AnswerComposer().compose("GPU 部署", retrieval, style="brief")

    assert retrieval.citations[0].document_title == "GPU 云主机部署建议"
    assert "GPU 云主机部署建议" in answer.answer
    assert not answer.degraded


def test_diagnostic_exposes_expanded_terms_and_filters() -> None:
    service = RetrievalService(QueryRewriter())
    rewrite = service.rewrite_query("GPU 部署")
    candidates = [
        KnowledgeSearchCandidate(
            chunk=KnowledgeChunkRecord(
                id="chk-1",
                sourceId="src-1",
                documentId="doc-1",
                documentTitle="GPU 云主机部署建议",
                ordinal=1,
                content="部署 GPU 云主机前先确认驱动版本和镜像规格。",
                tokenEstimate=20,
                keywords=["gpu", "部署", "驱动"],
                tags=["gpu", "launch"],
                createdAt="2026-04-16T00:00:00+00:00",
            ),
            sourceName="GPU 文档",
            score=0.7,
            matchReason="matched tokens: gpu, 部署",
        )
    ]

    diagnostic = service.build_diagnostic(
        RetrieveRequest(query="GPU 部署", topK=3, filters={"tags": ["gpu"], "sourceIds": ["src-1"]}),
        candidates,
        rewrite,
    )

    assert diagnostic.candidate_count == 1
    assert "算力" in diagnostic.expanded_terms
    assert "gpu" in diagnostic.query_terms
    assert "配置" in diagnostic.unmatched_terms
    assert diagnostic.applied_filters.tags == ["gpu"]
    assert diagnostic.applied_filters.source_ids == ["src-1"]
    assert diagnostic.source_breakdown[0].source_name == "GPU 文档"
    assert any(bucket.label == "gpu" for bucket in diagnostic.tag_breakdown)


def test_search_candidates_records_retrieval_duration_metric() -> None:
    service = RetrievalService(QueryRewriter())
    before = histogram_count(RETRIEVAL_DURATION_SECONDS)

    asyncio.run(
        service.search_candidates(
            RetrieveRequest(query="GPU 部署", topK=2),
            FakeKnowledgeClient([]),
        )
    )

    after = histogram_count(RETRIEVAL_DURATION_SECONDS)
    assert after == before + 1


def test_search_candidates_uses_cache_on_repeat_requests() -> None:
    service = RetrievalService(QueryRewriter())
    cache = get_retrieval_cache()
    cache.clear()
    hits_before = counter_value(CACHE_HITS_TOTAL)
    misses_before = counter_value(CACHE_MISSES_TOTAL)
    client = FakeKnowledgeClient(
        [
            KnowledgeSearchCandidate(
                chunk=KnowledgeChunkRecord(
                    id="chk-cache-1",
                    sourceId="src-cache-1",
                    documentId="doc-cache-1",
                    documentTitle="GPU 缓存测试",
                    ordinal=1,
                    content="GPU 缓存测试文档用于验证 rag-service 的检索缓存。",
                    tokenEstimate=14,
                    keywords=["gpu", "缓存"],
                    tags=["gpu", "cache"],
                    createdAt="2026-04-16T00:00:00+00:00",
                ),
                sourceName="GPU Cache",
                score=0.82,
                matchReason="matched tokens: gpu, 缓存",
            )
        ]
    )

    request = RetrieveRequest(query="GPU 缓存", topK=2, filters={"tags": ["gpu"]})
    first_rewrite, first_candidates = asyncio.run(
        service.search_candidates(request, client, cache_service=cache)
    )
    second_rewrite, second_candidates = asyncio.run(
        service.search_candidates(request, client, cache_service=cache)
    )

    assert first_rewrite.rewritten_query == second_rewrite.rewritten_query
    assert first_candidates[0].chunk.id == second_candidates[0].chunk.id
    assert counter_value(CACHE_MISSES_TOTAL) == misses_before + 1
    assert counter_value(CACHE_HITS_TOTAL) == hits_before + 1


def test_retrieval_cache_uses_redis_backend_when_configured(monkeypatch) -> None:
    fake_redis = FakeRedisClient()
    original_redis_url = os.environ.get("SMARTCLOUD_REDIS_URL")
    os.environ["SMARTCLOUD_REDIS_URL"] = "redis://redis.test:6379/1"
    clear_service_caches()
    monkeypatch.setattr(
        cache_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    try:
        cache = get_retrieval_cache()
        request = RetrieveRequest(query="GPU Redis 缓存", topK=2, filters={"tags": ["gpu"]})
        rewrite = QueryRewriteResult(
            originalQuery="GPU Redis 缓存",
            rewrittenQuery="gpu redis 缓存",
            expandedTerms=["gpu", "缓存"],
        )
        candidates = [
            KnowledgeSearchCandidate(
                chunk=KnowledgeChunkRecord(
                    id="chk-redis-1",
                    sourceId="src-redis-1",
                    documentId="doc-redis-1",
                    documentTitle="GPU Redis 缓存",
                    ordinal=1,
                    content="GPU Redis 缓存验证检索结果可以持久化到 Redis。",
                    tokenEstimate=12,
                    keywords=["gpu", "redis"],
                    tags=["gpu", "cache"],
                    createdAt="2026-04-16T00:00:00+00:00",
                ),
                sourceName="GPU Redis",
                score=0.88,
                matchReason="matched tokens: gpu, redis",
            )
        ]

        cache.set(request, rewrite, candidates)
        cached = cache.get(request)

        assert cache.describe()["backend"] == "redis-ttl"
        assert cached is not None
        assert cached[0].rewritten_query == "gpu redis 缓存"
        assert cached[1][0].chunk.id == "chk-redis-1"
        assert fake_redis.values
    finally:
        if original_redis_url is None:
            os.environ.pop("SMARTCLOUD_REDIS_URL", None)
        else:
            os.environ["SMARTCLOUD_REDIS_URL"] = original_redis_url
        clear_service_caches()


def test_retrieval_cache_falls_back_to_memory_when_redis_errors(monkeypatch) -> None:
    original_redis_url = os.environ.get("SMARTCLOUD_REDIS_URL")
    os.environ["SMARTCLOUD_REDIS_URL"] = "redis://redis.test:6379/1"
    clear_service_caches()
    monkeypatch.setattr(
        cache_module,
        "redis",
        type(
            "FakeRedisModule",
            (),
            {"from_url": staticmethod(lambda *args, **kwargs: FakeRedisClient(fail_operations=True))},
        ),
    )

    try:
        errors_before = counter_total(CACHE_BACKEND_ERRORS_TOTAL)
        cache = get_retrieval_cache()
        request = RetrieveRequest(query="GPU Redis Fallback", topK=2, filters={"tags": ["gpu"]})
        rewrite = QueryRewriteResult(
            originalQuery="GPU Redis Fallback",
            rewrittenQuery="gpu redis fallback",
            expandedTerms=["gpu", "fallback"],
        )
        candidates = [
            KnowledgeSearchCandidate(
                chunk=KnowledgeChunkRecord(
                    id="chk-fallback-1",
                    sourceId="src-fallback-1",
                    documentId="doc-fallback-1",
                    documentTitle="GPU Redis Fallback",
                    ordinal=1,
                    content="当 Redis 不可用时，rag-service 会回退到本地 TTL 缓存。",
                    tokenEstimate=12,
                    keywords=["gpu", "fallback"],
                    tags=["gpu", "cache"],
                    createdAt="2026-04-16T00:00:00+00:00",
                ),
                sourceName="GPU Fallback",
                score=0.8,
                matchReason="matched tokens: gpu, fallback",
            )
        ]

        cache.set(request, rewrite, candidates)
        cached = cache.get(request)

        assert cached is not None
        assert cached[0].rewritten_query == "gpu redis fallback"
        assert counter_total(CACHE_BACKEND_ERRORS_TOTAL) >= errors_before + 1
    finally:
        if original_redis_url is None:
            os.environ.pop("SMARTCLOUD_REDIS_URL", None)
        else:
            os.environ["SMARTCLOUD_REDIS_URL"] = original_redis_url
        clear_service_caches()


def test_answer_falls_back_when_no_citations() -> None:
    service = RetrievalService(QueryRewriter())
    empty_before = counter_value(EMPTY_RETRIEVALS_TOTAL)
    degraded_before = counter_value(DEGRADED_RETRIEVALS_TOTAL)
    retrieval = service.build_response(
        AnswerRequest(query="未知问题", topK=3),
        [],
        rewritten_query="未知问题",
        degraded=True,
        degradation_note="upstream unavailable",
    )
    answer = AnswerComposer().compose("未知问题", retrieval)

    assert answer.degraded is True
    assert "没有检索到可引用知识" in answer.answer
    assert counter_value(EMPTY_RETRIEVALS_TOTAL) == empty_before + 1
    assert counter_value(DEGRADED_RETRIEVALS_TOTAL) == degraded_before + 1


def test_upstream_headers_preserve_trace_context() -> None:
    with use_span(
        NonRecordingSpan(
            SpanContext(
                trace_id=0x1234567890ABCDEF1234567890ABCDEF,
                span_id=0x1234567890ABCDEF,
                is_remote=False,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
                trace_state=TraceState(),
            )
        )
    ):
        headers = build_upstream_headers(
            TraceContext(
                requestId="req-1",
                traceId="trace-1",
                conversationId="conv-1",
                tenantId="tenant-1",
            )
        )

    assert headers["X-Request-Id"] == "req-1"
    assert headers["X-Trace-Id"] == "trace-1"
    assert headers["X-Conversation-Id"] == "conv-1"
    assert headers["X-Tenant-Id"] == "tenant-1"
    assert headers["X-Caller-Service"] == "smartcloud-x-rag-service"
    assert headers["traceparent"].startswith("00-1234567890abcdef1234567890abcdef-1234567890abcdef-01")


def test_knowledge_client_rejects_invalid_search_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_client_module.httpx,
        "AsyncClient",
        lambda timeout: FakeHttpxAsyncClient(FakeMalformedHttpxResponse()),
    )
    client = KnowledgeServiceClient()

    async def run() -> None:
        try:
            await client.search(RetrieveRequest(query="GPU 部署", topK=2), "gpu 部署")
        except KnowledgeServiceProtocolError as exc:
            assert "invalid search payload" in str(exc)
        else:
            raise AssertionError("expected malformed payload to raise protocol error")

    asyncio.run(run())


def test_retrieve_route_degrades_on_protocol_errors(monkeypatch) -> None:
    async def broken_search(*args, **kwargs):
        raise KnowledgeServiceProtocolError("knowledge-service returned an invalid search payload")

    monkeypatch.setattr(rag_routes, "get_knowledge_client", lambda: object())
    monkeypatch.setattr(rag_routes, "get_retrieval_service", lambda: RetrievalService(QueryRewriter()))
    monkeypatch.setattr(RetrievalService, "search_candidates", broken_search)
    client = TestClient(service_app)

    response = client.post(
        "/api/rag/v1/retrieve",
        headers={"X-Request-Id": "req-rag-protocol-1"},
        json={"query": "GPU 部署", "topK": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["degraded"] is True
    assert "invalid search payload" in payload["data"]["coverageNotes"][0]


def test_answer_route_degrades_on_upstream_timeout(monkeypatch) -> None:
    async def broken_search(*args, **kwargs):
        raise knowledge_client_module.httpx.ReadTimeout("timed out", request=None)

    monkeypatch.setattr(rag_routes, "get_knowledge_client", lambda: object())
    monkeypatch.setattr(rag_routes, "get_retrieval_service", lambda: RetrievalService(QueryRewriter()))
    monkeypatch.setattr(RetrievalService, "search_candidates", broken_search)
    client = TestClient(service_app)

    response = client.post(
        "/api/rag/v1/answer",
        headers={"X-Request-Id": "req-rag-timeout-1"},
        json={"query": "GPU 部署", "topK": 3},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["degraded"] is True
    assert "没有检索到可引用知识" in payload["answer"]
    assert payload["coverageNotes"][0] == "knowledge-service unavailable: ReadTimeout"


def test_healthz_sets_standard_trace_headers() -> None:
    client = TestClient(service_app)
    response = client.get("/healthz", headers={"X-Request-Id": "req-rag-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-rag-1"
    assert response.headers["X-Trace-Id"] == "req-rag-1"
    assert response.headers["X-App-Name"] == "smartcloud-x-rag-service"
    assert response.headers["X-App-Version"] == "0.1.0"
    assert response.headers["X-Response-Time"].endswith("ms")
    payload = response.json()
    assert payload["requestId"] == "req-rag-1"
    assert payload["trace"]["traceId"] == "req-rag-1"


def test_healthz_surfaces_upstream_readiness(monkeypatch) -> None:
    class FakeHealthService:
        async def build_payload(self):
            return {
                "status": "degraded",
                "ready": False,
                "service": "smartcloud-x-rag-service",
                "knowledgeServiceBaseUrl": "http://knowledge-service:8030",
                "knowledgeServiceApiPrefix": "/api/knowledge/v1",
                "requestTimeoutMs": 10000,
                "corsAllowedOrigins": ["http://localhost:8050"],
                "upstream": {
                    "url": "http://knowledge-service:8030/healthz",
                    "reachable": True,
                    "ready": False,
                    "status": "degraded",
                    "latencyMs": 12.4,
                    "error": "missing starter catalog",
                },
                "warnings": ["missing starter catalog"],
            }

    monkeypatch.setattr(health_routes, "get_health_service", lambda: FakeHealthService())
    client = TestClient(service_app)
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "degraded"
    assert payload["ready"] is False
    assert payload["upstream"]["reachable"] is True
    assert payload["upstream"]["ready"] is False
    assert payload["warnings"] == ["missing starter catalog"]


def test_metrics_refreshes_readiness_and_upstream_gauges(monkeypatch) -> None:
    class FakeHealthService:
        async def build_payload(self):
            return {
                "status": "degraded",
                "ready": False,
                "service": "smartcloud-x-rag-service",
                "knowledgeServiceBaseUrl": "http://knowledge-service:8030",
                "knowledgeServiceApiPrefix": "/api/knowledge/v1",
                "requestTimeoutMs": 10000,
                "corsAllowedOrigins": ["http://localhost:8050"],
                "upstream": {
                    "url": "http://knowledge-service:8030/healthz",
                    "reachable": True,
                    "ready": False,
                    "status": "degraded",
                    "latencyMs": 12.4,
                    "error": "missing starter catalog",
                },
                "warnings": ["missing starter catalog"],
            }

    monkeypatch.setattr(health_routes, "get_health_service", lambda: FakeHealthService())
    client = TestClient(service_app)
    response = client.get("/metrics")

    assert response.status_code == 200
    text = response.text
    assert metric_sample_value(text, "rag_readiness_state") == 0
    assert metric_sample_value(text, "rag_upstream_reachable_state") == 1
    assert metric_sample_value(text, "rag_upstream_ready_state") == 0
    assert abs(metric_sample_value(text, "rag_upstream_probe_latency_ms") - 12.4) < 0.001
    assert metric_sample_value(text, "rag_health_warning_count") == 1


def test_admin_diagnostics_route_returns_canonical_envelope(monkeypatch) -> None:
    candidates = [
        KnowledgeSearchCandidate(
            chunk=KnowledgeChunkRecord(
                id="chk-1",
                sourceId="src-1",
                documentId="doc-1",
                documentTitle="GPU 云主机部署建议",
                ordinal=1,
                content="部署前确认驱动版本、镜像规格和网络出口。",
                tokenEstimate=18,
                keywords=["gpu", "部署", "驱动"],
                tags=["gpu"],
                createdAt="2026-04-16T00:00:00+00:00",
            ),
            sourceName="GPU 文档",
            score=0.72,
            matchReason="matched tokens: gpu, 部署",
        )
    ]
    monkeypatch.setattr(admin_routes, "get_knowledge_client", lambda: FakeKnowledgeClient(candidates))
    client = TestClient(service_app)

    response = client.post(
        "/api/v1/admin/retrieval/diagnostics",
        headers={"X-Request-Id": "req-admin-rag-1"},
        json={
            "query": "GPU 部署",
            "kb_id": "src-1",
            "top_k": 3,
            "include_citations": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["request_id"] == "req-admin-rag-1"
    assert payload["data"]["query"] == "GPU 部署"
    assert payload["data"]["coverage"]["candidate_count"] == 1
    assert payload["data"]["sources"][0]["kb_id"] == "src-1"
    assert payload["data"]["debug"]["citations"][0]["chunkId"] == "chk-1"


def test_admin_diagnostics_validation_errors_use_canonical_envelope() -> None:
    client = TestClient(service_app)

    response = client.post(
        "/api/v1/admin/retrieval/diagnostics",
        headers={"X-Request-Id": "req-admin-rag-validation-1"},
        json={"query": ""},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["request_id"] == "req-admin-rag-validation-1"
    assert payload["error"]["type"] == "validation_error"


def test_otlp_tracing_exports_rag_answer_request(monkeypatch) -> None:
    server, thread = start_trace_collector()
    tracked_keys = {
        "SMARTCLOUD_TRACE_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "SMARTCLOUD_RAG_CACHE_ENABLED": "false",
    }
    originals = {key: os.environ.get(key) for key in tracked_keys}
    for key, value in tracked_keys.items():
        os.environ[key] = value

    try:
        clear_service_caches()
        if hasattr(service_app.state, "tracing_configured"):
            delattr(service_app.state, "tracing_configured")
        configure_tracing(service_app, get_settings())
        monkeypatch.setattr(
            rag_routes,
            "get_knowledge_client",
            lambda: FakeKnowledgeClient(
                [
                    KnowledgeSearchCandidate(
                        chunk=KnowledgeChunkRecord(
                            id="chk-trace-1",
                            sourceId="src-trace-1",
                            documentId="doc-trace-1",
                            documentTitle="GPU Trace 文档",
                            ordinal=1,
                            content="GPU Trace 文档用于验证 rag-service 的 OTLP 导出。",
                            tokenEstimate=12,
                            keywords=["gpu", "trace"],
                            tags=["gpu", "trace"],
                            createdAt="2026-04-16T00:00:00+00:00",
                        ),
                        sourceName="GPU Trace",
                        score=0.91,
                        matchReason="matched tokens: gpu, trace",
                    )
                ]
            ),
        )
        client = TestClient(service_app)
        response = client.post(
            "/api/rag/v1/answer",
            json={"query": "GPU trace", "topK": 2},
        )
        assert response.status_code == 200
        provider = get_tracer_provider()
        assert provider is not None
        provider.force_flush()
        time.sleep(0.2)

        assert any(
            request["path"] == "/v1/traces" and request["body"]
            for request in TraceCollectorHandler.requests
        )
    finally:
        server.shutdown()
        thread.join(timeout=2)
        for key, value in originals.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_service_caches()
