import importlib
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
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

from app.api.routes import health as health_routes
from app.core.config import get_settings
from app.core.tracing import configure_tracing, get_tracer, get_tracer_provider
from app.main import app as service_app
from app.models.admin import AdminAsyncJob, KnowledgeBaseProfile, KnowledgeDocumentProfile
from app.models.knowledge import (
    CreateSourceRequest,
    FileImportPreviewRequest,
    FileImportRequest,
    IngestionJob,
    IngestDocumentRequest,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    SearchRequest,
)
from app.services.analytics import KnowledgeAnalyticsService
from app.services.analytics import get_analytics_service
from app.services.admin import get_admin_service
from app.services.admin_audit import get_admin_audit_service
from app.services import dify_dataset_sync as dify_dataset_sync_module
from app.services.dify_external import get_dify_external_knowledge_service
from app.services import file_import as file_import_module
from app.services.file_import import FileImportService, get_file_import_service
from app.services.health import get_health_service
from app.services import indexing_worker as indexing_worker_module
from app.services import metadata_backend as metadata_backend_module
from app.services import runtime_sync as runtime_sync_module
from app.services import store as store_module
from app.services.ingestion import IngestionService
from app.services.ingestion import get_ingestion_service
from app.services.indexing_worker import (
    KnowledgeIndexingWorkerService,
    get_indexing_worker_service,
)
from app.services.runtime_sync import KnowledgeRuntimeSyncService, get_runtime_sync_service
from app.services.search import SearchService
from app.services.search import get_search_service
from app.services.snapshot import KnowledgeSnapshotService
from app.services.snapshot import get_snapshot_service
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository
from app.services.embeddings import HashEmbeddingProvider
from app.services.text_processing import ChunkingService, TextProcessor, estimate_tokens


def clear_service_caches() -> None:
    get_settings.cache_clear()
    get_repository.cache_clear()
    get_ingestion_service.cache_clear()
    get_search_service.cache_clear()
    get_analytics_service.cache_clear()
    get_file_import_service.cache_clear()
    get_health_service.cache_clear()
    get_snapshot_service.cache_clear()
    get_admin_service.cache_clear()
    get_admin_audit_service.cache_clear()
    get_dify_external_knowledge_service.cache_clear()
    get_indexing_worker_service.cache_clear()
    get_runtime_sync_service.cache_clear()
    get_tracer.cache_clear()
    get_tracer_provider.cache_clear()


class TraceCollectorHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
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

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def start_trace_collector() -> tuple[ThreadingHTTPServer, Thread]:
    TraceCollectorHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), TraceCollectorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def exported_span_names() -> set[str]:
    names: set[str] = set()
    for request in TraceCollectorHandler.requests:
        if request.get("path") != "/v1/traces":
            continue
        body = request.get("body")
        if not isinstance(body, (bytes, bytearray)) or not body:
            continue
        export_request = ExportTraceServiceRequest()
        export_request.ParseFromString(body)
        for resource_span in export_request.resource_spans:
            for scope_span in resource_span.scope_spans:
                for span in scope_span.spans:
                    names.add(span.name)
    return names


class SearchBackendHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    opensearch_hits: list[dict[str, object]] = []
    qdrant_hits: list[dict[str, object]] = []
    fail_requests: bool = False

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length).decode("utf-8")
        self.__class__.requests.append({"path": self.path, "body": raw_body})
        if self.__class__.fail_requests:
            self.send_response(500)
            self.end_headers()
            return
        if self.path.endswith("/_search"):
            body = json.dumps({"hits": {"hits": self.__class__.opensearch_hits}}).encode("utf-8")
        elif self.path.endswith("/points/search"):
            body = json.dumps({"result": self.__class__.qdrant_hits}).encode("utf-8")
        elif self.path.endswith("/embeddings"):
            request = json.loads(raw_body)
            vectors = []
            for text in request.get("input") or []:
                base = float(len(text))
                vectors.append({"embedding": [base, base + 1.0, base + 2.0, base + 3.0]})
            body = json.dumps({"data": vectors}).encode("utf-8")
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def start_search_backend_server() -> tuple[ThreadingHTTPServer, Thread]:
    SearchBackendHandler.requests = []
    SearchBackendHandler.opensearch_hits = []
    SearchBackendHandler.qdrant_hits = []
    SearchBackendHandler.fail_requests = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), SearchBackendHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class FakeMinioObjectResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.closed = False

    def read(self) -> bytes:
        return self.payload

    def close(self) -> None:
        self.closed = True


class FakeMinioObjectClient:
    buckets: set[str] = set()
    objects: dict[tuple[str, str], bytes] = {}

    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure

    def bucket_exists(self, bucket_name: str) -> bool:
        return bucket_name in self.__class__.buckets

    def make_bucket(self, bucket_name: str) -> None:
        self.__class__.buckets.add(bucket_name)

    def put_object(self, bucket_name: str, object_name: str, data, length: int, content_type: str | None = None) -> None:
        self.__class__.buckets.add(bucket_name)
        self.__class__.objects[(bucket_name, object_name)] = data.read(length)

    def stat_object(self, bucket_name: str, object_name: str):
        payload = self.__class__.objects.get((bucket_name, object_name))
        if payload is None:
            raise ValueError(f"missing object {bucket_name}/{object_name}")
        return {"size": len(payload)}

    def get_object(self, bucket_name: str, object_name: str) -> FakeMinioObjectResponse:
        payload = self.__class__.objects.get((bucket_name, object_name))
        if payload is None:
            raise ValueError(f"missing object {bucket_name}/{object_name}")
        return FakeMinioObjectResponse(payload)


def metric_sample_value(text: str, metric_name: str, labels: dict[str, str] | None = None) -> float:
    for family in text_string_to_metric_families(text):
        if family.name != metric_name:
            continue
        for sample in family.samples:
            if labels is None or all(sample.labels.get(key) == value for key, value in labels.items()):
                return float(sample.value)
    raise AssertionError(f"metric {metric_name} with labels {labels} not found")


def test_hash_embedding_provider_returns_stable_vectors() -> None:
    provider = HashEmbeddingProvider(8)
    first = provider.embed(["GPU 账单"])[0]
    second = provider.embed(["GPU 账单"])[0]

    assert first == second
    assert len(first) == 8
    assert any(value != 0 for value in first)




def test_embedding_configuration_validation_reports_missing_openai_compatible_fields(monkeypatch) -> None:
    monkeypatch.setenv("SMARTCLOUD_EMBEDDING_PROVIDER", "openai-compatible")
    monkeypatch.delenv("SMARTCLOUD_EMBEDDING_API_URL", raising=False)
    monkeypatch.setenv("SMARTCLOUD_EMBEDDING_API_KEY", "secret")
    monkeypatch.setenv("SMARTCLOUD_EMBEDDING_MODEL", "text-embedding-test")
    clear_service_caches()

    try:
        get_settings()
        raise AssertionError("expected embedding configuration validation to fail")
    except Exception as exc:
        assert "SMARTCLOUD_EMBEDDING_API_URL" in str(exc)


def test_admin_create_knowledge_base_missing_operator_reason_returns_400(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SMARTCLOUD_KNOWLEDGE_DATA_PATH", str(tmp_path / "knowledge-store.json"))
    monkeypatch.setenv("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH", str(tmp_path / "knowledge-admin-audit.jsonl"))
    monkeypatch.setenv("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", str(tmp_path / "knowledge-indexing-outbox.jsonl"))
    monkeypatch.setenv(
        "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH",
        str(SERVICE_ROOT / "data" / "starter-catalog.json"),
    )
    clear_service_caches()

    client = TestClient(service_app)
    response = client.post(
        "/api/v1/admin/knowledge-bases",
        json={
            "code": "kb_acceptance",
            "name": "验收知识库",
            "description": "用于校验审计头",
            "scene": "support",
            "language": "zh-CN",
            "retrieval_mode": "hybrid",
            "embedding_model": "hash-baseline",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["error"]["type"] == "validation_error"
    assert payload["message"] == "X-Operator-Reason header is required for admin write routes"


def test_admin_create_knowledge_base_with_operator_reason_writes_audit_record(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "knowledge-store.json"
    audit_path = tmp_path / "knowledge-admin-audit.jsonl"
    outbox_path = tmp_path / "knowledge-indexing-outbox.jsonl"
    monkeypatch.setenv("SMARTCLOUD_KNOWLEDGE_DATA_PATH", str(data_path))
    monkeypatch.setenv("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH", str(audit_path))
    monkeypatch.setenv("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setenv(
        "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH",
        str(SERVICE_ROOT / "data" / "starter-catalog.json"),
    )
    clear_service_caches()

    client = TestClient(service_app)
    response = client.post(
        "/api/v1/admin/knowledge-bases",
        headers={"X-Operator-Reason": "regression-kb-create"},
        json={
            "code": "kb_acceptance_pass",
            "name": "验收知识库通过",
            "description": "用于校验审计记录",
            "scene": "support",
            "language": "zh-CN",
            "retrieval_mode": "hybrid",
            "embedding_model": "hash-baseline",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["message"] == "created"
    assert payload["data"]["code"] == "kb_acceptance_pass"
    audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
    audit_record = json.loads(audit_lines[0])
    assert audit_record["action"] == "create"
    assert audit_record["reason"] == "regression-kb-create"
    assert audit_record["resource_type"] == "knowledge_base"


def test_openai_compatible_embedding_provider_endpoint_is_used(tmp_path) -> None:
    backend_server, backend_thread = start_search_backend_server()
    base = f"http://127.0.0.1:{backend_server.server_port}/embeddings"
    original_provider = os.environ.get("SMARTCLOUD_EMBEDDING_PROVIDER")
    original_url = os.environ.get("SMARTCLOUD_EMBEDDING_API_URL")
    original_key = os.environ.get("SMARTCLOUD_EMBEDDING_API_KEY")
    original_model = os.environ.get("SMARTCLOUD_EMBEDDING_MODEL")
    os.environ["SMARTCLOUD_EMBEDDING_PROVIDER"] = "openai-compatible"
    os.environ["SMARTCLOUD_EMBEDDING_API_URL"] = base
    os.environ["SMARTCLOUD_EMBEDDING_API_KEY"] = "test-key"
    os.environ["SMARTCLOUD_EMBEDDING_MODEL"] = "text-embedding-3-small"
    clear_service_caches()

    try:
        service = SearchService(KnowledgeStoreRepository(tmp_path / "knowledge.json"))
        vector = service.embedding_provider.embed(["GPU 检索"])[0]
        assert vector[:4] == [6.0, 7.0, 8.0, 9.0]
        assert any(request["path"].endswith("/embeddings") for request in SearchBackendHandler.requests)
    finally:
        backend_server.shutdown()
        backend_thread.join(timeout=2)
        if original_provider is None:
            os.environ.pop("SMARTCLOUD_EMBEDDING_PROVIDER", None)
        else:
            os.environ["SMARTCLOUD_EMBEDDING_PROVIDER"] = original_provider
        if original_url is None:
            os.environ.pop("SMARTCLOUD_EMBEDDING_API_URL", None)
        else:
            os.environ["SMARTCLOUD_EMBEDDING_API_URL"] = original_url
        if original_key is None:
            os.environ.pop("SMARTCLOUD_EMBEDDING_API_KEY", None)
        else:
            os.environ["SMARTCLOUD_EMBEDDING_API_KEY"] = original_key
        if original_model is None:
            os.environ.pop("SMARTCLOUD_EMBEDDING_MODEL", None)
        else:
            os.environ["SMARTCLOUD_EMBEDDING_MODEL"] = original_model
        clear_service_caches()


def test_text_processor_clean_normalizes_markdown_and_punctuation() -> None:
    processor = TextProcessor()
    cleaned = processor.clean("# 标题\n\n这是一个[链接](https://example.com)，还有\u200b零宽字符。")

    assert cleaned.startswith("标题")
    assert "链接" in cleaned
    assert "https://example.com" not in cleaned
    assert "\u200b" not in cleaned
    assert "," in cleaned


def test_text_processor_extracts_language_and_domain_hints() -> None:
    processor = TextProcessor()
    metadata = processor.extract_metadata("GPU 云主机账单支持发票下载，备案场景也会显示状态。")

    assert metadata["language"] == "zh-CN"
    assert "billing" in metadata["domainHints"]
    assert "icp" in metadata["domainHints"]
    assert metadata["estimatedReadingMinutes"] >= 1


def test_text_processor_extract_keywords_prefers_informative_terms() -> None:
    processor = TextProcessor()
    keywords = processor.extract_keywords(
        "GPU 账单中心支持账单明细与发票下载，账单异常时先检查规格。",
        5,
        corpus_texts=["GPU 部署说明", "发票政策", "营销活动公告"],
    )

    assert "账单" in keywords or "发票" in keywords


def test_paragraph_chunk_strategy_preserves_section_boundaries() -> None:
    service = ChunkingService(max_chunk_chars=40, chunk_overlap_chars=8, strategy="paragraph")
    chunks = service.split("## 第一节\nGPU 部署说明。\n\n## 第二节\n账单与发票说明。")

    assert len(chunks) >= 2
    assert any("第一节" in chunk for chunk in chunks)
    assert any("第二节" in chunk for chunk in chunks)


def test_estimate_tokens_handles_chinese_better_than_len_div_four() -> None:
    text = "中文检索会让 token 估算更接近真实长度"
    assert estimate_tokens(text) > len(text) // 4


def test_ingestion_returns_chunk_quality_metrics_and_metadata(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    service = IngestionService(repository)
    response = service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(name="GPU 指南", kind="manual", tags=["gpu"]),
            title="GPU 计费与部署",
            content="GPU 云主机部署前先确认镜像与驱动。\n\n账单中心支持明细下载与发票申请。",
            tags=["billing", "product"],
        )
    )

    assert response.avg_chunk_tokens > 0
    assert response.max_chunk_tokens >= response.min_chunk_tokens
    chunk = repository.list_chunks(document_id=response.document.id)[0]
    assert chunk.metadata["language"] == "zh-CN"
    assert "embeddingPreview" in chunk.metadata


def test_search_prefers_live_backends_when_configured(tmp_path) -> None:
    backend_server, backend_thread = start_search_backend_server()
    backend_base = f"http://127.0.0.1:{backend_server.server_port}"
    original_qdrant_url = os.environ.get("SMARTCLOUD_QDRANT_URL")
    original_opensearch_url = os.environ.get("SMARTCLOUD_OPENSEARCH_URL")
    os.environ["SMARTCLOUD_QDRANT_URL"] = backend_base
    os.environ["SMARTCLOUD_OPENSEARCH_URL"] = backend_base
    clear_service_caches()

    try:
        repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
        response = IngestionService(repository).ingest_document(
            IngestDocumentRequest(
                source=CreateSourceRequest(name="GPU Live Backend", kind="manual", tags=["gpu"]),
                title="GPU Live Retrieval",
                content="GPU Live Retrieval 会验证知识搜索在配置了 Qdrant 和 OpenSearch 时优先命中实时后端结果。",
                tags=["gpu", "live"],
            )
        )
        chunk = repository.list_chunks(document_id=response.document.id)[0]
        SearchBackendHandler.opensearch_hits = [
            {
                "_score": 60.0,
                "_source": {
                    "source_id": chunk.source_id,
                    "source_name": "GPU Live Backend",
                    "document_id": chunk.document_id,
                    "document_title": chunk.document_title,
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "keywords": chunk.keywords,
                    "tags": chunk.tags,
                    "ordinal": chunk.ordinal,
                    "created_at": chunk.created_at,
                    "metadata": chunk.metadata,
                },
            }
        ]
        SearchBackendHandler.qdrant_hits = [
            {
                "score": 0.91,
                "payload": {
                    "source_id": chunk.source_id,
                    "source_name": "GPU Live Backend",
                    "document_id": chunk.document_id,
                    "document_title": chunk.document_title,
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "keywords": chunk.keywords,
                    "tags": chunk.tags,
                    "ordinal": chunk.ordinal,
                    "created_at": chunk.created_at,
                    "metadata": chunk.metadata,
                },
            }
        ]

        result = SearchService(repository).search(SearchRequest(query="GPU Live Retrieval", topK=3))

        assert result.total == 1
        assert result.backend_used == "hybrid-live-backends"
        assert result.results[0].chunk.id == chunk.id
        assert result.results[0].score <= 1.0
    finally:
        backend_server.shutdown()
        backend_thread.join(timeout=2)
        if original_qdrant_url is None:
            os.environ.pop("SMARTCLOUD_QDRANT_URL", None)
        else:
            os.environ["SMARTCLOUD_QDRANT_URL"] = original_qdrant_url
        if original_opensearch_url is None:
            os.environ.pop("SMARTCLOUD_OPENSEARCH_URL", None)
        else:
            os.environ["SMARTCLOUD_OPENSEARCH_URL"] = original_opensearch_url
        clear_service_caches()


def test_search_uses_single_backend_label_when_only_qdrant_returns(tmp_path) -> None:
    backend_server, backend_thread = start_search_backend_server()
    backend_base = f"http://127.0.0.1:{backend_server.server_port}"
    original_qdrant_url = os.environ.get("SMARTCLOUD_QDRANT_URL")
    original_opensearch_url = os.environ.get("SMARTCLOUD_OPENSEARCH_URL")
    os.environ["SMARTCLOUD_QDRANT_URL"] = backend_base
    os.environ["SMARTCLOUD_OPENSEARCH_URL"] = backend_base
    clear_service_caches()

    try:
        repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
        response = IngestionService(repository).ingest_document(
            IngestDocumentRequest(
                source=CreateSourceRequest(name="GPU Qdrant Only", kind="manual", tags=["gpu"]),
                title="GPU Qdrant Only",
                content="Qdrant 单后端场景测试，用于验证只返回向量后端结果时的 backendUsed 标签。",
                tags=["gpu"],
            )
        )
        chunk = repository.list_chunks(document_id=response.document.id)[0]
        SearchBackendHandler.opensearch_hits = []
        SearchBackendHandler.qdrant_hits = [{"score": 0.88, "payload": {"source_id": chunk.source_id, "source_name": "GPU Qdrant Only", "document_id": chunk.document_id, "document_title": chunk.document_title, "chunk_id": chunk.id, "content": chunk.content, "keywords": chunk.keywords, "tags": chunk.tags, "ordinal": chunk.ordinal, "created_at": chunk.created_at, "metadata": chunk.metadata}}]

        result = SearchService(repository).search(SearchRequest(query="Qdrant", topK=3))
        assert result.backend_used == "qdrant-only"
    finally:
        backend_server.shutdown()
        backend_thread.join(timeout=2)
        if original_qdrant_url is None:
            os.environ.pop("SMARTCLOUD_QDRANT_URL", None)
        else:
            os.environ["SMARTCLOUD_QDRANT_URL"] = original_qdrant_url
        if original_opensearch_url is None:
            os.environ.pop("SMARTCLOUD_OPENSEARCH_URL", None)
        else:
            os.environ["SMARTCLOUD_OPENSEARCH_URL"] = original_opensearch_url
        clear_service_caches()


def test_large_document_chunking_and_overlap(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    service = IngestionService(repository)
    content = ("GPU知识库。" * 2000)
    response = service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(name="Large Doc", kind="manual", tags=["gpu"]),
            title="Large Doc",
            content=content,
            tags=["gpu"],
        )
    )
    chunks = repository.list_chunks(document_id=response.document.id)
    assert len(chunks) > 5
    if len(chunks) >= 2:
        overlap = chunks[0].content[-service.settings.chunk_overlap_chars :].strip()
        assert overlap[:4] in chunks[1].content




def test_readiness_index_targets_reflect_runtime_summary_and_openapi_examples() -> None:
    original_qdrant_collection = os.environ.get("SMARTCLOUD_QDRANT_COLLECTION")
    original_opensearch_index = os.environ.get("SMARTCLOUD_OPENSEARCH_INDEX")
    os.environ["SMARTCLOUD_QDRANT_COLLECTION"] = "Knowledge Chunks"
    os.environ["SMARTCLOUD_OPENSEARCH_INDEX"] = "Knowledge Chunks"
    clear_service_caches()

    try:
        payload = get_health_service()._build_index_targets(
            {
                "vectorStore": {"target": "knowledge_chunks__technical_support"},
                "bm25Store": {"target": "knowledge_chunks__technical_support"},
            }
        )

        assert payload["active_mode"] == "single-baseline"
        assert payload["targets"] == {
            "vectorStore": "knowledge_chunks__technical_support",
            "bm25Store": "knowledge_chunks__technical_support",
        }
        assert payload["fallback_targets"] == {
            "vectorStore": "knowledge_chunks",
            "bm25Store": "knowledge_chunks",
        }

        openapi_text = (SERVICE_ROOT.parent.parent / "openapi" / "knowledge-service.openapi.yaml").read_text(
            encoding="utf-8"
        )
        assert "active_mode: mixed" in openapi_text
        assert "activeMode: mixed" not in openapi_text
    finally:
        if original_qdrant_collection is None:
            os.environ.pop("SMARTCLOUD_QDRANT_COLLECTION", None)
        else:
            os.environ["SMARTCLOUD_QDRANT_COLLECTION"] = original_qdrant_collection
        if original_opensearch_index is None:
            os.environ.pop("SMARTCLOUD_OPENSEARCH_INDEX", None)
        else:
            os.environ["SMARTCLOUD_OPENSEARCH_INDEX"] = original_opensearch_index
        clear_service_caches()
