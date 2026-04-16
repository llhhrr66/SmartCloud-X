import importlib
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from fastapi.testclient import TestClient
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
from app.models.admin import KnowledgeBaseProfile, KnowledgeDocumentProfile
from app.models.knowledge import (
    CreateSourceRequest,
    FileImportPreviewRequest,
    FileImportRequest,
    IngestDocumentRequest,
    SearchRequest,
)
from app.services.analytics import KnowledgeAnalyticsService
from app.services.analytics import get_analytics_service
from app.services.admin import get_admin_service
from app.services.admin_audit import get_admin_audit_service
from app.services.file_import import FileImportService, get_file_import_service
from app.services.health import get_health_service
from app.services import indexing_worker as indexing_worker_module
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
    get_indexing_worker_service.cache_clear()
    get_runtime_sync_service.cache_clear()
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


class ConnectorCaptureHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []
    collections: set[str] = set()
    indices: set[str] = set()
    fail_vector_upsert: bool = False

    def _read_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(content_length)

    def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback signature
        path = self.path.split("?", 1)[0]
        self.__class__.requests.append({"method": "GET", "path": path, "body": ""})
        if path.startswith("/collections/"):
            collection = path.rsplit("/", 1)[-1]
            if collection in self.__class__.collections:
                self._send_json(200, {"status": "ok"})
                return
            self._send_json(404, {"status": "missing"})
            return
        self._send_json(404, {"status": "missing"})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback signature
        path = self.path.split("?", 1)[0]
        self.__class__.requests.append({"method": "HEAD", "path": path, "body": ""})
        if path.lstrip("/") in self.__class__.indices:
            self.send_response(200)
        else:
            self.send_response(404)
        self.end_headers()

    def do_PUT(self) -> None:  # noqa: N802 - stdlib callback signature
        path = self.path.split("?", 1)[0]
        body = self._read_body().decode("utf-8")
        self.__class__.requests.append({"method": "PUT", "path": path, "body": body})
        if path.startswith("/collections/") and path.endswith("/points"):
            if self.__class__.fail_vector_upsert:
                self._send_json(500, {"status": "vector failure"})
                return
            self._send_json(200, {"result": {"status": "acknowledged"}})
            return
        if path.startswith("/collections/"):
            self.__class__.collections.add(path.rsplit("/", 1)[-1])
            self._send_json(200, {"result": True})
            return
        self.__class__.indices.add(path.lstrip("/"))
        self._send_json(200, {"acknowledged": True})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback signature
        path = self.path.split("?", 1)[0]
        body = self._read_body().decode("utf-8")
        self.__class__.requests.append({"method": "POST", "path": path, "body": body})
        if path == "/_bulk":
            self._send_json(200, {"errors": False})
            return
        self._send_json(404, {"status": "missing"})

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib callback signature
        return


def start_connector_server() -> tuple[ThreadingHTTPServer, Thread]:
    ConnectorCaptureHandler.requests = []
    ConnectorCaptureHandler.collections = set()
    ConnectorCaptureHandler.indices = set()
    ConnectorCaptureHandler.fail_vector_upsert = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), ConnectorCaptureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class FakeMinioClient:
    uploaded: list[dict[str, str | None]] = []
    buckets: set[str] = set()

    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.__class__.buckets

    def make_bucket(self, bucket: str) -> None:
        self.__class__.buckets.add(bucket)

    def fput_object(
        self,
        bucket_name: str,
        object_name: str,
        file_path: str,
        content_type: str | None = None,
    ) -> None:
        self.__class__.uploaded.append(
            {
                "bucket": bucket_name,
                "objectName": object_name,
                "filePath": file_path,
                "contentType": content_type,
            }
        )


class FakeMySQLCursor:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        self.connection.executed.append((sql, params))


class FakeMySQLConnection:
    instances: list["FakeMySQLConnection"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.executed: list[tuple[str, object]] = []
        self.committed = False
        self.closed = False
        self.__class__.instances.append(self)

    def cursor(self) -> FakeMySQLCursor:
        return FakeMySQLCursor(self)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}
        self.published: list[tuple[str, str]] = []

    def publish(self, channel: str, payload: str) -> None:
        self.published.append((channel, payload))

    def lpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).insert(0, value)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        return [key for key in list(self.store) if key.startswith(prefix)]

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


def metric_sample_value(text: str, sample_name: str, labels: dict[str, str] | None = None) -> float:
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name != sample_name:
                continue
            if labels is not None and sample.labels != labels:
                continue
            return sample.value
    raise AssertionError(f"missing sample {sample_name} with labels {labels}")


def test_ingestion_creates_chunks_and_source_counts(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    service = IngestionService(repository)

    source = service.create_source(
        CreateSourceRequest(
            name="SmartCloud FAQ",
            kind="faq",
            tags=["faq", "billing"],
        )
    )
    response = service.ingest_document(
        IngestDocumentRequest(
            sourceId=source.id,
            title="账单与发票说明",
            content=(
                "账单中心提供按月汇总、明细下载和发票进度查询。\n\n"
                "如果扣费异常，先检查资源规格和自动续费策略，再提交工单。"
            ),
            tags=["invoice", "billing"],
        )
    )

    assert response.chunks_created >= 1
    stored_source = repository.get_source(source.id)
    assert stored_source is not None
    assert stored_source.document_count == 1
    assert stored_source.chunk_count == response.chunks_created


def test_search_matches_ingested_content(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    ingestion_service = IngestionService(repository)
    search_service = SearchService(repository)

    response = ingestion_service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(name="GPU 指南", kind="manual", tags=["gpu"]),
            title="GPU 云主机部署建议",
            content=(
                "GPU 云主机适合训练和推理工作负载。部署前应确认驱动版本、镜像规格、"
                "网络出口和弹性扩容策略。"
            ),
            tags=["deploy"],
        )
    )

    result = search_service.search(SearchRequest(query="GPU 部署", topK=3, tags=["gpu"]))

    assert result.total == 1
    assert "gpu" in result.query_tokens
    assert result.applied_filters.tags == ["gpu"]
    assert result.source_breakdown[0].source_name == "GPU 指南"
    assert any(bucket.label == "gpu" for bucket in result.tag_breakdown)
    assert result.results[0].chunk.document_id == response.document.id
    assert result.results[0].score > 0


def test_ingestion_reuses_matching_source_and_duplicate_document(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    service = IngestionService(repository)

    first = service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(name="运维手册", kind="manual", tags=["ops"]),
            title="节点扩容说明",
            content="扩容前确认节点配额、带宽策略、镜像版本和回滚预案，确保变更窗口已审批。",
            tags=["capacity"],
        )
    )
    second = service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(name="运维手册", kind="manual", tags=["ops", "scale"]),
            title="节点扩容说明",
            content="扩容前确认节点配额、带宽策略、镜像版本和回滚预案，确保变更窗口已审批。",
            tags=["capacity"],
        )
    )

    counts = repository.snapshot_counts()
    assert first.source.id == second.source.id
    assert second.chunks_created == 0
    assert second.job.warnings == ["duplicate document reused"]
    assert counts["sources"] == 1
    assert counts["documents"] == 1


def test_bootstrap_catalog_is_idempotent(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    service = IngestionService(repository)
    starter_catalog_path = tmp_path / "starter-catalog.json"
    starter_catalog_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "source": {
                            "name": "GPU 文档",
                            "kind": "manual",
                            "tags": ["gpu", "product"],
                        },
                        "title": "GPU 上线前检查",
                        "content": "上线 GPU 产品前要确认驱动版本、镜像兼容性、网络出口和监控告警。",
                        "tags": ["launch"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service.settings = service.settings.model_copy(update={"starter_catalog_path": starter_catalog_path})

    first = service.bootstrap_catalog()
    second = service.bootstrap_catalog()

    assert first.seeded_documents == 1
    assert first.reused_documents == 0
    assert second.seeded_documents == 0
    assert second.reused_documents == 1


def test_settings_accept_runtime_path_overrides(tmp_path) -> None:
    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_starter_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH")
    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    original_outbox_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH")
    original_raw_mirror_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT")
    original_operator_reason_header = os.environ.get("SMARTCLOUD_OPERATOR_REASON_HEADER")
    original_trace_enabled = os.environ.get("SMARTCLOUD_TRACE_ENABLED")
    original_otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    original_minio_endpoint = os.environ.get("SMARTCLOUD_MINIO_ENDPOINT")
    original_minio_bucket = os.environ.get("SMARTCLOUD_MINIO_BUCKET")
    original_mysql_dsn = os.environ.get("SMARTCLOUD_MYSQL_DSN")
    original_qdrant_url = os.environ.get("SMARTCLOUD_QDRANT_URL")
    original_opensearch_url = os.environ.get("SMARTCLOUD_OPENSEARCH_URL")
    original_redis_url = os.environ.get("SMARTCLOUD_REDIS_URL")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(tmp_path / "runtime" / "knowledge-store.json")
    os.environ["SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH"] = str(
        tmp_path / "runtime" / "starter-catalog.json"
    )
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(tmp_path / "runtime" / "imports")
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(
        tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    )
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(tmp_path / "runtime" / "raw-objects")
    os.environ["SMARTCLOUD_OPERATOR_REASON_HEADER"] = "X-Test-Operator-Reason"
    os.environ["SMARTCLOUD_TRACE_ENABLED"] = "true"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://phoenix.test:4317"
    os.environ["SMARTCLOUD_MINIO_ENDPOINT"] = "http://minio.test:9000"
    os.environ["SMARTCLOUD_MINIO_BUCKET"] = "knowledge-raw"
    os.environ["SMARTCLOUD_MYSQL_DSN"] = "mysql+pymysql://user:secret@mysql.test:3306/smartcloud"
    os.environ["SMARTCLOUD_QDRANT_URL"] = "http://qdrant.test:6333"
    os.environ["SMARTCLOUD_OPENSEARCH_URL"] = "http://opensearch.test:9200"
    os.environ["SMARTCLOUD_REDIS_URL"] = "redis://redis.test:6379/0"
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.data_path == tmp_path / "runtime" / "knowledge-store.json"
        assert settings.starter_catalog_path == tmp_path / "runtime" / "starter-catalog.json"
        assert settings.import_root == tmp_path / "runtime" / "imports"
        assert settings.outbox_path == tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
        assert settings.raw_mirror_root == tmp_path / "runtime" / "raw-objects"
        assert settings.operator_reason_header == "X-Test-Operator-Reason"
        assert settings.trace_enabled is True
        assert settings.otlp_endpoint == "http://phoenix.test:4317"
        assert settings.minio_endpoint == "http://minio.test:9000"
        assert settings.minio_bucket == "knowledge-raw"
        assert settings.mysql_dsn == "mysql+pymysql://user:secret@mysql.test:3306/smartcloud"
        assert settings.qdrant_url == "http://qdrant.test:6333"
        assert settings.opensearch_url == "http://opensearch.test:9200"
        assert settings.redis_url == "redis://redis.test:6379/0"
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_starter_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH"] = original_starter_path
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        if original_outbox_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = original_outbox_path
        if original_raw_mirror_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = original_raw_mirror_root
        if original_operator_reason_header is None:
            os.environ.pop("SMARTCLOUD_OPERATOR_REASON_HEADER", None)
        else:
            os.environ["SMARTCLOUD_OPERATOR_REASON_HEADER"] = original_operator_reason_header
        if original_trace_enabled is None:
            os.environ.pop("SMARTCLOUD_TRACE_ENABLED", None)
        else:
            os.environ["SMARTCLOUD_TRACE_ENABLED"] = original_trace_enabled
        if original_otlp_endpoint is None:
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        else:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = original_otlp_endpoint
        if original_minio_endpoint is None:
            os.environ.pop("SMARTCLOUD_MINIO_ENDPOINT", None)
        else:
            os.environ["SMARTCLOUD_MINIO_ENDPOINT"] = original_minio_endpoint
        if original_minio_bucket is None:
            os.environ.pop("SMARTCLOUD_MINIO_BUCKET", None)
        else:
            os.environ["SMARTCLOUD_MINIO_BUCKET"] = original_minio_bucket
        if original_mysql_dsn is None:
            os.environ.pop("SMARTCLOUD_MYSQL_DSN", None)
        else:
            os.environ["SMARTCLOUD_MYSQL_DSN"] = original_mysql_dsn
        if original_qdrant_url is None:
            os.environ.pop("SMARTCLOUD_QDRANT_URL", None)
        else:
            os.environ["SMARTCLOUD_QDRANT_URL"] = original_qdrant_url
        if original_opensearch_url is None:
            os.environ.pop("SMARTCLOUD_OPENSEARCH_URL", None)
        else:
            os.environ["SMARTCLOUD_OPENSEARCH_URL"] = original_opensearch_url
        if original_redis_url is None:
            os.environ.pop("SMARTCLOUD_REDIS_URL", None)
        else:
            os.environ["SMARTCLOUD_REDIS_URL"] = original_redis_url
        get_settings.cache_clear()


def test_snapshot_service_prefers_active_repository_state(tmp_path) -> None:
    empty_repository = KnowledgeStoreRepository(tmp_path / "empty.json")
    active_repository = KnowledgeStoreRepository(tmp_path / "active.json")
    audit_service = get_admin_audit_service()
    audit_service.path = tmp_path / "audit.jsonl"
    runtime_sync_service = KnowledgeRuntimeSyncService(active_repository)

    ingestion_service = IngestionService(active_repository)
    source = ingestion_service.create_source(
        CreateSourceRequest(
            name="GPU Snapshot KB",
            kind="product",
            uri="kb://gpu-snapshot",
            description="active snapshot repository",
            tags=["gpu", "product"],
        )
    )
    active_repository.save_knowledge_base_profile(
        KnowledgeBaseProfile(
            kb_id=source.id,
            code="gpu-snapshot",
            scene="product",
            language="zh-CN",
            retrieval_mode="hybrid-baseline",
            embedding_model="baseline-keyword",
            status="ready",
            created_at=source.created_at,
            updated_at=source.updated_at,
        )
    )
    ingestion_service.ingest_document(
        IngestDocumentRequest(
            sourceId=source.id,
            title="GPU 快照文档",
            content="GPU 快照服务会把运行时状态、知识库概览和文档索引计划一并导出。",
            tags=["gpu", "snapshot"],
        )
    )

    snapshot_service = KnowledgeSnapshotService(
        empty_repository,
        KnowledgeAnalyticsService(active_repository),
        audit_service,
        runtime_sync_service,
    )

    snapshot = snapshot_service.build_snapshot()

    assert snapshot.counts["knowledgeBases"] == 1
    assert snapshot.overview.counts["knowledgeBases"] == 1
    assert len(snapshot.knowledge_bases) == 1
    assert snapshot.knowledge_bases[0].kb_id == source.id
    assert snapshot.documents[0].source_id == source.id


def test_snapshot_service_repairs_missing_profiles_and_counts(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    audit_service = get_admin_audit_service()
    audit_service.path = tmp_path / "audit.jsonl"
    runtime_sync_service = KnowledgeRuntimeSyncService(repository)
    ingestion_service = IngestionService(repository)

    response = ingestion_service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(
                name="GPU Snapshot Repair KB",
                kind="product",
                uri="kb://gpu-snapshot-repair",
                tags=["gpu", "repair"],
            ),
            title="GPU Snapshot Repair",
            content="GPU Snapshot Repair 会验证快照导出时自动补齐知识库和文档画像，避免运行时状态与导出数据失配。",
            tags=["gpu", "snapshot", "repair"],
        )
    )

    assert repository.get_knowledge_base_profile(response.source.id) is None
    assert repository.get_document_profile(response.document.id) is None

    snapshot_service = KnowledgeSnapshotService(
        repository,
        KnowledgeAnalyticsService(repository),
        audit_service,
        runtime_sync_service,
    )
    snapshot = snapshot_service.build_snapshot()

    repaired_kb_profile = repository.get_knowledge_base_profile(response.source.id)
    repaired_document_profile = repository.get_document_profile(response.document.id)

    assert repaired_kb_profile is not None
    assert repaired_kb_profile.code == "gpu-snapshot-repair"
    assert repaired_document_profile is not None
    assert repaired_document_profile.latest_job_id == response.job.id
    assert snapshot.counts["sources"] == 1
    assert snapshot.counts["documents"] == 1
    assert snapshot.counts["knowledgeBases"] == 1
    assert snapshot.counts["documentProfiles"] == 1
    assert snapshot.counts["knowledgeBases"] == len(snapshot.knowledge_bases)
    assert snapshot.counts["documentProfiles"] == len(snapshot.document_profiles)
    assert snapshot.knowledge_bases[0].kb_id == response.source.id
    assert snapshot.document_profiles[0].doc_id == response.document.id


def test_snapshot_service_normalizes_profile_keys_and_prunes_orphans(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    audit_service = get_admin_audit_service()
    audit_service.path = tmp_path / "audit.jsonl"
    runtime_sync_service = KnowledgeRuntimeSyncService(repository)
    ingestion_service = IngestionService(repository)

    response = ingestion_service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(
                name="GPU Snapshot Normalization KB",
                kind="product",
                uri="kb://gpu-snapshot-normalization",
                tags=["gpu", "normalize"],
            ),
            title="GPU Snapshot Normalization",
            content="GPU Snapshot Normalization 会验证快照导出时清理孤儿画像并修复旧键值存储。",
            tags=["gpu", "snapshot", "normalize"],
        )
    )

    repository._state.knowledge_base_profiles = {
        "legacy-kb-key": KnowledgeBaseProfile(
            kb_id=response.source.id,
            code="gpu-snapshot-normalization",
            scene="product",
            language="zh-CN",
            retrieval_mode="hybrid-baseline",
            embedding_model="baseline-keyword",
            status="ready",
            created_at=response.source.created_at,
            updated_at=response.source.updated_at,
        ),
        "stale-kb-key": KnowledgeBaseProfile(
            kb_id="src-missing",
            code="stale-kb",
            scene="product",
            language="zh-CN",
            retrieval_mode="hybrid-baseline",
            embedding_model="baseline-keyword",
            status="disabled",
            created_at=response.source.created_at,
            updated_at=response.source.updated_at,
        ),
    }
    repository._state.document_profiles = {
        "legacy-doc-key": KnowledgeDocumentProfile(
            doc_id=response.document.id,
            kb_id=response.source.id,
            status="active",
            parse_status="completed",
            index_status="ready",
            version_no=1,
            source_type="filesystem",
            source_uri="file:///tmp/gpu-snapshot-normalization.md",
            indexed_at=response.document.updated_at,
            error_message=None,
            latest_job_id=None,
        ),
        "stale-doc-key": KnowledgeDocumentProfile(
            doc_id="doc-missing",
            kb_id="src-missing",
            status="active",
            parse_status="completed",
            index_status="ready",
            version_no=1,
            source_type="inline",
            source_uri="kb://stale-kb",
            indexed_at=response.document.updated_at,
            error_message=None,
            latest_job_id=None,
        ),
    }
    repository._persist()

    snapshot_service = KnowledgeSnapshotService(
        repository,
        KnowledgeAnalyticsService(repository),
        audit_service,
        runtime_sync_service,
    )
    snapshot = snapshot_service.build_snapshot()

    normalized_kb_profile = repository.get_knowledge_base_profile(response.source.id)
    normalized_document_profile = repository.get_document_profile(response.document.id)

    assert normalized_kb_profile is not None
    assert normalized_kb_profile.code == "gpu-snapshot-normalization"
    assert repository.get_knowledge_base_profile("src-missing") is None
    assert normalized_document_profile is not None
    assert normalized_document_profile.source_type == "filesystem"
    assert normalized_document_profile.latest_job_id == response.job.id
    assert repository.get_document_profile("doc-missing") is None
    assert snapshot.counts["knowledgeBases"] == 1
    assert snapshot.counts["documentProfiles"] == 1
    assert len(snapshot.knowledge_bases) == 1
    assert len(snapshot.document_profiles) == 1
    assert snapshot.knowledge_bases[0].kb_id == response.source.id
    assert snapshot.document_profiles[0].doc_id == response.document.id


def test_snapshot_service_prefers_informative_profile_fields_across_legacy_duplicates(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    audit_service = get_admin_audit_service()
    audit_service.path = tmp_path / "audit.jsonl"
    runtime_sync_service = KnowledgeRuntimeSyncService(repository)
    ingestion_service = IngestionService(repository)

    response = ingestion_service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(
                name="GPU Snapshot Duplicate KB",
                kind="product",
                uri="kb://gpu-snapshot-duplicate",
                tags=["gpu", "duplicate"],
            ),
            title="GPU Snapshot Duplicate",
            content="GPU Snapshot Duplicate 会验证旧的重复画像中即使存在更新版本号，也不会覆盖更有信息量的文件来源字段。",
            tags=["gpu", "snapshot", "duplicate"],
        )
    )

    repository._state.document_profiles = {
        response.document.id: KnowledgeDocumentProfile(
            doc_id=response.document.id,
            kb_id=response.source.id,
            status="active",
            parse_status="completed",
            index_status="ready",
            version_no=2,
            file_id="starter/gpu-snapshot-duplicate.md",
            source_type="filesystem",
            source_uri="file:///tmp/gpu-snapshot-duplicate.md",
            indexed_at=response.document.updated_at,
            error_message=None,
            latest_job_id=response.job.id,
        ),
        "legacy-inline-key": KnowledgeDocumentProfile(
            doc_id=response.document.id,
            kb_id=response.source.id,
            status="active",
            parse_status="completed",
            index_status="ready",
            version_no=3,
            file_id=None,
            source_type="inline",
            source_uri=None,
            indexed_at=response.document.updated_at,
            error_message=None,
            latest_job_id=None,
        ),
    }
    repository._persist()

    snapshot_service = KnowledgeSnapshotService(
        repository,
        KnowledgeAnalyticsService(repository),
        audit_service,
        runtime_sync_service,
    )
    snapshot = snapshot_service.build_snapshot()

    normalized_document_profile = repository.get_document_profile(response.document.id)

    assert normalized_document_profile is not None
    assert normalized_document_profile.version_no == 3
    assert normalized_document_profile.source_type == "filesystem"
    assert normalized_document_profile.file_id == "starter/gpu-snapshot-duplicate.md"
    assert normalized_document_profile.source_uri == "file:///tmp/gpu-snapshot-duplicate.md"
    assert normalized_document_profile.latest_job_id == response.job.id
    assert len(snapshot.document_profiles) == 1
    assert snapshot.document_profiles[0].source_type == "filesystem"
    assert snapshot.document_profiles[0].file_id == "starter/gpu-snapshot-duplicate.md"


def test_runtime_sync_mirrors_raw_documents_and_records_outbox(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    outbox_path = tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    raw_root = tmp_path / "runtime" / "raw-objects"

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_outbox_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH")
    original_raw_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT")
    original_minio_endpoint = os.environ.get("SMARTCLOUD_MINIO_ENDPOINT")
    original_minio_bucket = os.environ.get("SMARTCLOUD_MINIO_BUCKET")
    original_mysql_dsn = os.environ.get("SMARTCLOUD_MYSQL_DSN")
    original_qdrant_url = os.environ.get("SMARTCLOUD_QDRANT_URL")
    original_opensearch_url = os.environ.get("SMARTCLOUD_OPENSEARCH_URL")
    original_redis_url = os.environ.get("SMARTCLOUD_REDIS_URL")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(outbox_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(raw_root)
    os.environ["SMARTCLOUD_MINIO_ENDPOINT"] = "http://minio.test:9000"
    os.environ["SMARTCLOUD_MINIO_BUCKET"] = "knowledge-raw"
    os.environ["SMARTCLOUD_MYSQL_DSN"] = "mysql+pymysql://user:secret@mysql.test:3306/smartcloud"
    os.environ["SMARTCLOUD_QDRANT_URL"] = "http://qdrant.test:6333"
    os.environ["SMARTCLOUD_OPENSEARCH_URL"] = "http://opensearch.test:9200"
    os.environ["SMARTCLOUD_REDIS_URL"] = "redis://redis.test:6379/0"
    clear_service_caches()

    try:
        repository = get_repository()
        service = IngestionService(repository)
        source = service.create_source(
            CreateSourceRequest(
                name="GPU Runtime KB",
                kind="product",
                uri="kb://gpu-runtime",
                tags=["gpu"],
            )
        )
        repository.save_knowledge_base_profile(
            KnowledgeBaseProfile(
                kb_id=source.id,
                code="gpu-runtime",
                scene="product",
                language="zh-CN",
                retrieval_mode="hybrid-baseline",
                embedding_model="baseline-keyword",
                status="ready",
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
        )

        response = service.ingest_document(
            IngestDocumentRequest(
                sourceId=source.id,
                title="GPU Runtime Sync",
                content="GPU Runtime Sync 会把文档原文复制到原始镜像目录，并生成供 Qdrant 与 OpenSearch 消费的索引事件。",
                tags=["gpu", "runtime"],
            )
        )

        assert outbox_path.exists()
        events = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(events) == 1
        event = events[0]
        assert event["docId"] == response.document.id
        assert event["rawObject"]["sourceType"] == "inline"
        assert event["rawObject"]["sourceUri"] == source.uri
        assert event["metadataTarget"].startswith("knowledge_documents@mysql+pymysql://mysql.test:3306")
        assert event["vectorTarget"] == "knowledge_chunks"
        assert event["bm25Target"] == "knowledge_chunks"
        assert event["cacheNamespace"] == "smartcloud-x:knowledge"

        mirror_path = Path(event["rawObject"]["mirrorPath"])
        assert mirror_path.exists()
        assert mirror_path.read_text(encoding="utf-8") == response.document.content

        integrations = KnowledgeRuntimeSyncService(repository).build_integrations()
        assert integrations.pending_events == 1
        assert integrations.event_counters["queued"] == 1
        assert integrations.recent_events[0].doc_id == response.document.id
        assert integrations.raw_storage.backend == "minio-mirror"
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_outbox_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = original_outbox_path
        if original_raw_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = original_raw_root
        if original_minio_endpoint is None:
            os.environ.pop("SMARTCLOUD_MINIO_ENDPOINT", None)
        else:
            os.environ["SMARTCLOUD_MINIO_ENDPOINT"] = original_minio_endpoint
        if original_minio_bucket is None:
            os.environ.pop("SMARTCLOUD_MINIO_BUCKET", None)
        else:
            os.environ["SMARTCLOUD_MINIO_BUCKET"] = original_minio_bucket
        if original_mysql_dsn is None:
            os.environ.pop("SMARTCLOUD_MYSQL_DSN", None)
        else:
            os.environ["SMARTCLOUD_MYSQL_DSN"] = original_mysql_dsn
        if original_qdrant_url is None:
            os.environ.pop("SMARTCLOUD_QDRANT_URL", None)
        else:
            os.environ["SMARTCLOUD_QDRANT_URL"] = original_qdrant_url
        if original_opensearch_url is None:
            os.environ.pop("SMARTCLOUD_OPENSEARCH_URL", None)
        else:
            os.environ["SMARTCLOUD_OPENSEARCH_URL"] = original_opensearch_url
        if original_redis_url is None:
            os.environ.pop("SMARTCLOUD_REDIS_URL", None)
        else:
            os.environ["SMARTCLOUD_REDIS_URL"] = original_redis_url
        clear_service_caches()


def test_runtime_sync_tracks_outbox_event_lifecycle(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    outbox_path = tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    raw_root = tmp_path / "runtime" / "raw-objects"

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_outbox_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH")
    original_raw_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT")
    clear_service_caches()
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(outbox_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(raw_root)
    clear_service_caches()

    try:
        repository = get_repository()
        service = IngestionService(repository)
        source = service.create_source(
            CreateSourceRequest(
                name="GPU Queue KB",
                kind="product",
                uri="kb://gpu-queue",
                tags=["gpu"],
            )
        )
        repository.save_knowledge_base_profile(
            KnowledgeBaseProfile(
                kb_id=source.id,
                code="gpu-queue",
                scene="product",
                language="zh-CN",
                retrieval_mode="hybrid-baseline",
                embedding_model="baseline-keyword",
                status="ready",
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
        )

        response = service.ingest_document(
            IngestDocumentRequest(
                sourceId=source.id,
                title="GPU Queue Lifecycle",
                content="GPU Queue Lifecycle 会验证索引事件可以被领取、失败重试并最终标记完成。",
                tags=["gpu", "queue"],
            )
        )

        runtime_sync = KnowledgeRuntimeSyncService(repository)
        assert runtime_sync.event_counters()["queued"] == 1

        claimed = runtime_sync.claim_next_event("worker-a")
        assert claimed is not None
        assert claimed.doc_id == response.document.id
        assert claimed.status == "processing"
        assert claimed.processor_id == "worker-a"
        assert claimed.attempt_count == 1
        assert runtime_sync.event_counters()["processing"] == 1

        failed = runtime_sync.mark_event_failed(claimed.event_id, "qdrant unavailable")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.last_error == "qdrant unavailable"
        assert runtime_sync.event_counters()["failed"] == 1
        assert runtime_sync.pending_events() == 1

        retried = runtime_sync.claim_next_event("worker-b")
        assert retried is not None
        assert retried.event_id == claimed.event_id
        assert retried.processor_id == "worker-b"
        assert retried.attempt_count == 2

        completed = runtime_sync.mark_event_completed(retried.event_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.completed_at is not None

        integrations = runtime_sync.build_integrations()
        assert integrations.pending_events == 0
        assert integrations.event_counters["completed"] == 1
        assert integrations.recent_events[0].status == "completed"
        assert integrations.recent_events[0].processor_id == "worker-b"
        assert integrations.recent_events[0].attempt_count == 2
        assert integrations.recent_events[0].completed_at is not None
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_outbox_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = original_outbox_path
        if original_raw_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = original_raw_root
        clear_service_caches()


def test_indexing_worker_processes_configured_connectors_and_records_results(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    outbox_path = tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    raw_root = tmp_path / "runtime" / "raw-objects"
    connector_server, connector_thread = start_connector_server()
    connector_base = f"http://127.0.0.1:{connector_server.server_port}"
    fake_redis = FakeRedisClient()
    FakeMinioClient.uploaded = []
    FakeMinioClient.buckets = set()
    FakeMySQLConnection.instances = []

    original_env = {
        name: os.environ.get(name)
        for name in (
            "SMARTCLOUD_KNOWLEDGE_DATA_PATH",
            "SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH",
            "SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT",
            "SMARTCLOUD_MINIO_ENDPOINT",
            "SMARTCLOUD_MINIO_BUCKET",
            "SMARTCLOUD_MINIO_ACCESS_KEY",
            "SMARTCLOUD_MINIO_SECRET_KEY",
            "SMARTCLOUD_MYSQL_DSN",
            "SMARTCLOUD_QDRANT_URL",
            "SMARTCLOUD_OPENSEARCH_URL",
            "SMARTCLOUD_REDIS_URL",
        )
    }
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(outbox_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(raw_root)
    os.environ["SMARTCLOUD_MINIO_ENDPOINT"] = connector_base
    os.environ["SMARTCLOUD_MINIO_BUCKET"] = "knowledge-raw"
    os.environ["SMARTCLOUD_MINIO_ACCESS_KEY"] = "smartcloud"
    os.environ["SMARTCLOUD_MINIO_SECRET_KEY"] = "smartcloud123"
    os.environ["SMARTCLOUD_MYSQL_DSN"] = "mysql+pymysql://smartcloud:smartcloud@mysql.test:3306/smartcloud"
    os.environ["SMARTCLOUD_QDRANT_URL"] = connector_base
    os.environ["SMARTCLOUD_OPENSEARCH_URL"] = connector_base
    os.environ["SMARTCLOUD_REDIS_URL"] = "redis://redis.test:6379/0"
    clear_service_caches()

    monkeypatch.setattr(indexing_worker_module, "Minio", FakeMinioClient)
    monkeypatch.setattr(
        indexing_worker_module,
        "pymysql",
        type("FakePyMySQL", (), {"connect": staticmethod(lambda **kwargs: FakeMySQLConnection(**kwargs))}),
    )
    monkeypatch.setattr(
        indexing_worker_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    try:
        repository = get_repository()
        ingestion_service = IngestionService(repository)
        source = ingestion_service.create_source(
            CreateSourceRequest(
                name="GPU Worker KB",
                kind="product",
                uri="kb://gpu-worker",
                tags=["gpu"],
            )
        )
        repository.save_knowledge_base_profile(
            KnowledgeBaseProfile(
                kb_id=source.id,
                code="gpu-worker",
                scene="product",
                language="zh-CN",
                retrieval_mode="hybrid-baseline",
                embedding_model="baseline-keyword",
                status="ready",
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
        )

        response = ingestion_service.ingest_document(
            IngestDocumentRequest(
                sourceId=source.id,
                title="GPU Worker Connectors",
                content="GPU Worker Connectors 会验证索引 worker 把原始镜像、元数据、向量、BM25 和 Redis 通知都真正处理出去。",
                tags=["gpu", "worker"],
                sourceType="filesystem",
                sourceUri="file:///tmp/gpu-worker-connectors.md",
            )
        )

        worker = KnowledgeIndexingWorkerService(repository, KnowledgeRuntimeSyncService(repository))
        processed = worker.process_next_event(processor_id="worker-test")

        assert processed is not None
        assert processed.status == "completed"
        assert processed.processor_id == "worker-test"
        connector_statuses = {
            result.connector: result.status for result in processed.connector_results
        }
        assert connector_statuses == {
            "raw_object_sync": "succeeded",
            "metadata_upsert": "succeeded",
            "vector_upsert": "succeeded",
            "bm25_upsert": "succeeded",
            "queue_publish": "succeeded",
        }

        assert FakeMinioClient.uploaded[0]["bucket"] == "knowledge-raw"
        assert FakeMinioClient.uploaded[0]["objectName"] == processed.raw_object.object_key

        mysql_connection = FakeMySQLConnection.instances[-1]
        assert mysql_connection.committed is True
        insert_params = next(
            params for sql, params in mysql_connection.executed if isinstance(params, tuple)
        )
        assert insert_params[5] == "filesystem"
        assert insert_params[6] == "file:///tmp/gpu-worker-connectors.md"

        assert any(
            request["path"] == f"/collections/{get_settings().qdrant_collection}"
            and request["method"] in {"GET", "PUT"}
            for request in ConnectorCaptureHandler.requests
        )
        assert any(
            request["path"] == f"/collections/{get_settings().qdrant_collection}/points"
            and request["method"] == "PUT"
            for request in ConnectorCaptureHandler.requests
        )
        assert any(
            request["path"] == "/_bulk" and request["method"] == "POST"
            for request in ConnectorCaptureHandler.requests
        )
        assert any("filesystem" in str(request["body"]) for request in ConnectorCaptureHandler.requests)

        assert fake_redis.published
        assert any(key.endswith(":last-processed") for key in fake_redis.store)

        integrations = KnowledgeRuntimeSyncService(repository).build_integrations()
        assert integrations.pending_events == 0
        assert integrations.event_counters["completed"] == 1
        assert integrations.recent_events[0].status == "completed"
        assert integrations.recent_events[0].connector_results[0].status == "succeeded"
        assert integrations.recent_events[0].doc_id == response.document.id
    finally:
        connector_server.shutdown()
        connector_thread.join(timeout=2)
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_service_caches()


def test_indexing_worker_marks_event_failed_when_vector_sync_errors(
    tmp_path,
    monkeypatch,
) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    outbox_path = tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    raw_root = tmp_path / "runtime" / "raw-objects"
    connector_server, connector_thread = start_connector_server()
    connector_base = f"http://127.0.0.1:{connector_server.server_port}"
    ConnectorCaptureHandler.fail_vector_upsert = True
    fake_redis = FakeRedisClient()
    FakeMinioClient.uploaded = []
    FakeMinioClient.buckets = set()
    FakeMySQLConnection.instances = []

    original_env = {
        name: os.environ.get(name)
        for name in (
            "SMARTCLOUD_KNOWLEDGE_DATA_PATH",
            "SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH",
            "SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT",
            "SMARTCLOUD_MINIO_ENDPOINT",
            "SMARTCLOUD_MINIO_BUCKET",
            "SMARTCLOUD_MINIO_ACCESS_KEY",
            "SMARTCLOUD_MINIO_SECRET_KEY",
            "SMARTCLOUD_MYSQL_DSN",
            "SMARTCLOUD_QDRANT_URL",
            "SMARTCLOUD_OPENSEARCH_URL",
            "SMARTCLOUD_REDIS_URL",
        )
    }
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(outbox_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(raw_root)
    os.environ["SMARTCLOUD_MINIO_ENDPOINT"] = connector_base
    os.environ["SMARTCLOUD_MINIO_BUCKET"] = "knowledge-raw"
    os.environ["SMARTCLOUD_MINIO_ACCESS_KEY"] = "smartcloud"
    os.environ["SMARTCLOUD_MINIO_SECRET_KEY"] = "smartcloud123"
    os.environ["SMARTCLOUD_MYSQL_DSN"] = "mysql+pymysql://smartcloud:smartcloud@mysql.test:3306/smartcloud"
    os.environ["SMARTCLOUD_QDRANT_URL"] = connector_base
    os.environ["SMARTCLOUD_OPENSEARCH_URL"] = connector_base
    os.environ["SMARTCLOUD_REDIS_URL"] = "redis://redis.test:6379/0"
    clear_service_caches()

    monkeypatch.setattr(indexing_worker_module, "Minio", FakeMinioClient)
    monkeypatch.setattr(
        indexing_worker_module,
        "pymysql",
        type("FakePyMySQL", (), {"connect": staticmethod(lambda **kwargs: FakeMySQLConnection(**kwargs))}),
    )
    monkeypatch.setattr(
        indexing_worker_module,
        "redis",
        type("FakeRedisModule", (), {"from_url": staticmethod(lambda *args, **kwargs: fake_redis)}),
    )

    try:
        repository = get_repository()
        ingestion_service = IngestionService(repository)
        source = ingestion_service.create_source(
            CreateSourceRequest(
                name="GPU Worker Failure KB",
                kind="product",
                uri="kb://gpu-worker-failure",
                tags=["gpu"],
            )
        )
        repository.save_knowledge_base_profile(
            KnowledgeBaseProfile(
                kb_id=source.id,
                code="gpu-worker-failure",
                scene="product",
                language="zh-CN",
                retrieval_mode="hybrid-baseline",
                embedding_model="baseline-keyword",
                status="ready",
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
        )

        ingestion_service.ingest_document(
            IngestDocumentRequest(
                sourceId=source.id,
                title="GPU Worker Failure",
                content="GPU Worker Failure 会验证连接器失败时 outbox 事件会保留失败状态和分步结果，供稍后重试。",
                tags=["gpu", "failure"],
            )
        )

        worker = KnowledgeIndexingWorkerService(repository, KnowledgeRuntimeSyncService(repository))
        failed = worker.process_next_event(processor_id="worker-failure")

        assert failed is not None
        assert failed.status == "failed"
        assert "vector_upsert failed" in (failed.last_error or "")
        connector_statuses = {
            result.connector: result.status for result in failed.connector_results
        }
        assert connector_statuses["raw_object_sync"] == "succeeded"
        assert connector_statuses["metadata_upsert"] == "succeeded"
        assert connector_statuses["vector_upsert"] == "failed"
        assert KnowledgeRuntimeSyncService(repository).pending_events() == 1
    finally:
        connector_server.shutdown()
        connector_thread.join(timeout=2)
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_service_caches()


def test_admin_write_routes_accept_configured_operator_reason_header(tmp_path) -> None:
    runtime_import_root = tmp_path / "imports"
    runtime_import_root.mkdir(parents=True)
    (runtime_import_root / "starter.md").write_text(
        "# GPU 验证文档\n\n管理员导入文档时需要携带自定义操作原因头，方便与共享运行时配置对齐。",
        encoding="utf-8",
    )

    starter_catalog_path = tmp_path / "starter-catalog.json"
    starter_catalog_path.write_text(json.dumps({"documents": []}, ensure_ascii=False), encoding="utf-8")

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_audit_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH")
    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    original_starter_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH")
    original_operator_reason_header = os.environ.get("SMARTCLOUD_OPERATOR_REASON_HEADER")

    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(tmp_path / "runtime" / "knowledge-store.json")
    os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = str(tmp_path / "runtime" / "knowledge-admin-audit.jsonl")
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(runtime_import_root)
    os.environ["SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH"] = str(starter_catalog_path)
    os.environ["SMARTCLOUD_OPERATOR_REASON_HEADER"] = "X-Admin-Reason-Test"
    clear_service_caches()

    try:
        client = TestClient(service_app)

        create_kb_response = client.post(
            "/api/v1/admin/knowledge-bases",
            headers={"X-Admin-Reason-Test": "custom header create kb"},
            json={
                "name": "Custom Header KB",
                "code": "custom-header-kb",
                "scene": "product",
                "language": "zh-CN",
                "retrieval_mode": "hybrid-baseline",
                "embedding_model": "baseline-keyword",
                "description": "Uses a configured operator-reason header.",
            },
        )
        assert create_kb_response.status_code == 201
        create_kb_payload = create_kb_response.json()["data"]

        update_kb_response = client.patch(
            f"/api/v1/admin/knowledge-bases/{create_kb_payload['kb_id']}",
            headers={"X-Admin-Reason-Test": "custom header update kb"},
            json={
                "description": "Updated through a configured operator-reason header.",
                "retrieval_mode": "hybrid-updated",
                "status": "disabled",
            },
        )
        assert update_kb_response.status_code == 200

        create_document_response = client.post(
            f"/api/v1/admin/knowledge-bases/{create_kb_payload['kb_id']}/documents",
            headers={"X-Admin-Reason-Test": "custom header create document"},
            json={
                "file_id": "starter.md",
                "title": "GPU 验证文档",
                "tags": ["gpu", "admin"],
                "source_type": "filesystem",
            },
        )
        assert create_document_response.status_code == 202
        created_document = create_document_response.json()["data"]

        reindex_response = client.post(
            f"/api/v1/admin/knowledge-documents/{created_document['doc_id']}/reindex",
            headers={"X-Admin-Reason-Test": "custom header reindex"},
            json={
                "force": True,
                "confirm_token": f"reindex:{created_document['doc_id']}",
            },
        )
        assert reindex_response.status_code == 202
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_audit_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = original_audit_path
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        if original_starter_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH"] = original_starter_path
        if original_operator_reason_header is None:
            os.environ.pop("SMARTCLOUD_OPERATOR_REASON_HEADER", None)
        else:
            os.environ["SMARTCLOUD_OPERATOR_REASON_HEADER"] = original_operator_reason_header
        clear_service_caches()


def test_overview_summarizes_catalog_inventory(tmp_path) -> None:
    repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
    ingestion_service = IngestionService(repository)
    analytics_service = KnowledgeAnalyticsService(repository)

    response = ingestion_service.ingest_document(
        IngestDocumentRequest(
            source=CreateSourceRequest(name="GPU 文档", kind="manual", tags=["gpu", "product"]),
            title="GPU 上架步骤",
            content="发布 GPU 服务前先确认驱动版本、镜像兼容性、库存策略与告警通知。",
            tags=["launch", "gpu"],
        )
    )

    overview = analytics_service.build_overview()

    assert overview.counts["documents"] == 1
    assert overview.average_chunks_per_document >= 1
    assert overview.sources_by_kind[0].label == "manual"
    assert any(bucket.label == "gpu" for bucket in overview.top_tags)
    assert any(bucket.label == "zh-CN" for bucket in overview.document_languages)
    assert overview.largest_sources[0].source_name == response.source.name
    assert overview.recent_ingestions[0].document_title == response.document.title


def test_file_import_preview_lists_supported_candidates(tmp_path) -> None:
    import_root = tmp_path / "imports"
    starter_dir = import_root / "starter"
    starter_dir.mkdir(parents=True)
    (starter_dir / "gpu.md").write_text(
        "# GPU 导入样例\n\n导入批次需要确认驱动版本、镜像兼容性和监控告警。",
        encoding="utf-8",
    )
    (starter_dir / "skip.png").write_bytes(b"not-text")

    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    get_settings.cache_clear()

    try:
        preview = FileImportService(IngestionService(KnowledgeStoreRepository(tmp_path / "knowledge.json"))).preview(
            FileImportPreviewRequest(directory="starter", glob="**/*", maxFiles=10)
        )
        assert preview.matched_files == 2
        assert preview.importable_files == 1
        assert any(item.path == "starter/gpu.md" and item.importable for item in preview.items)
        assert any(item.path == "starter/skip.png" and not item.importable for item in preview.items)
    finally:
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        get_settings.cache_clear()


def test_file_import_preview_rejects_directory_outside_import_root(tmp_path) -> None:
    import_root = tmp_path / "imports"
    allowed_dir = import_root / "starter"
    outside_dir = tmp_path / "outside"
    allowed_dir.mkdir(parents=True)
    outside_dir.mkdir(parents=True)

    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    get_settings.cache_clear()

    try:
        service = FileImportService(IngestionService(KnowledgeStoreRepository(tmp_path / "knowledge.json")))
        try:
            service.preview(
                FileImportPreviewRequest(directory=str(outside_dir), glob="**/*", maxFiles=10)
            )
        except ValueError as exc:
            assert "outside the configured import root" in str(exc)
        else:
            raise AssertionError("expected outside-root preview directory to be rejected")
    finally:
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        get_settings.cache_clear()


def test_file_import_preview_rejects_glob_escape_outside_import_root(tmp_path) -> None:
    import_root = tmp_path / "imports"
    starter_dir = import_root / "starter"
    outside_dir = tmp_path / "outside"
    starter_dir.mkdir(parents=True)
    outside_dir.mkdir(parents=True)
    (outside_dir / "secret.md").write_text(
        "# Secret\n\nThis file must stay outside the configured import root boundary.",
        encoding="utf-8",
    )

    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    get_settings.cache_clear()

    try:
        service = FileImportService(IngestionService(KnowledgeStoreRepository(tmp_path / "knowledge.json")))
        try:
            service.preview(
                FileImportPreviewRequest(directory="starter", glob="../outside/*", maxFiles=10)
            )
        except ValueError as exc:
            assert "outside the configured import root" in str(exc)
        else:
            raise AssertionError("expected outside-root glob pattern to be rejected")
    finally:
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        get_settings.cache_clear()


def test_file_import_ingests_and_reuses_directory_documents(tmp_path) -> None:
    import_root = tmp_path / "imports"
    starter_dir = import_root / "starter"
    starter_dir.mkdir(parents=True)
    (starter_dir / "gpu-release.md").write_text(
        "# GPU 发布检查\n\nGPU 发布前应确认驱动版本、镜像适配、库存和告警联系人。",
        encoding="utf-8",
    )
    (starter_dir / "icp-handoff.md").write_text(
        "# ICP 交接说明\n\n备案交接时需要确认实名认证材料、域名信息与审核时长。",
        encoding="utf-8",
    )

    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    get_settings.cache_clear()

    try:
        repository = KnowledgeStoreRepository(tmp_path / "knowledge.json")
        file_service = FileImportService(IngestionService(repository))

        first = file_service.import_files(
            FileImportRequest(directory="starter", glob="**/*", maxFiles=10, tags=["batch"])
        )
        second = file_service.import_files(
            FileImportRequest(directory="starter", glob="**/*", maxFiles=10, tags=["batch"])
        )

        counts = repository.snapshot_counts()
        assert first.imported_files == 2
        assert first.failed_files == 0
        assert second.reused_files == 2
        assert counts["documents"] == 2
        assert first.source.document_count == 2
    finally:
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        get_settings.cache_clear()


def test_healthz_sets_standard_trace_headers() -> None:
    client = TestClient(service_app)
    response = client.get("/healthz", headers={"X-Request-Id": "req-knowledge-1"})

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "req-knowledge-1"
    assert response.headers["X-Trace-Id"] == "req-knowledge-1"
    assert response.headers["X-App-Name"] == "smartcloud-x-knowledge-service"
    assert response.headers["X-App-Version"] == "0.1.0"
    assert response.headers["X-Response-Time"].endswith("ms")
    payload = response.json()
    assert payload["requestId"] == "req-knowledge-1"
    assert payload["trace"]["traceId"] == "req-knowledge-1"
    assert "importRoot" in payload["data"]
    assert payload["data"]["ready"] is True


def test_healthz_reports_readiness_failures_for_missing_assets(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    audit_path = tmp_path / "runtime" / "knowledge-admin-audit.jsonl"
    missing_starter_path = tmp_path / "missing" / "starter-catalog.json"
    missing_import_root = tmp_path / "missing" / "imports"

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_audit_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH")
    original_starter_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH")
    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")

    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = str(audit_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH"] = str(missing_starter_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(missing_import_root)
    activate_service_imports()
    __import__("app.services.store_provider")
    clear_service_caches()

    try:
        client = TestClient(service_app)
        response = client.get("/healthz")

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["status"] == "degraded"
        assert payload["ready"] is False
        check_statuses = {item["name"]: item["status"] for item in payload["readinessChecks"]}
        assert check_statuses["starter_catalog"] == "failed"
        assert check_statuses["import_root"] == "failed"
        assert any("missing file" in warning for warning in payload["warnings"])
        assert any("missing directory" in warning for warning in payload["warnings"])
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_audit_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = original_audit_path
        if original_starter_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH"] = original_starter_path
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        clear_service_caches()


def test_metrics_refreshes_readiness_and_inventory_gauges(monkeypatch) -> None:
    class FakeHealthService:
        def build_payload(self):
            return {
                "status": "degraded",
                "ready": False,
                "service": "smartcloud-x-knowledge-service",
                "counts": {
                    "sources": 2,
                    "documents": 3,
                    "chunks": 7,
                    "ingestions": 4,
                    "knowledgeBases": 1,
                    "documentProfiles": 3,
                    "adminJobs": 2,
                },
                "readinessChecks": [
                    {"name": "data_store_access", "status": "ready", "detail": "ok"},
                    {"name": "audit_log_parent", "status": "ready", "detail": "ok"},
                    {"name": "starter_catalog", "status": "failed", "detail": "missing file"},
                    {"name": "import_root", "status": "failed", "detail": "missing directory"},
                    {"name": "repository_counts", "status": "ready", "detail": "counts available"},
                ],
                "warnings": ["missing file", "missing directory"],
            }

    monkeypatch.setattr(health_routes, "get_health_service", lambda: FakeHealthService())
    client = TestClient(service_app)
    response = client.get("/metrics")

    assert response.status_code == 200
    text = response.text
    assert metric_sample_value(text, "knowledge_readiness_state") == 0
    assert metric_sample_value(text, "knowledge_health_warning_count") == 2
    assert (
        metric_sample_value(
            text,
            "knowledge_readiness_check_state",
            {"check_name": "starter_catalog"},
        )
        == 0
    )
    assert (
        metric_sample_value(
            text,
            "knowledge_readiness_check_state",
            {"check_name": "data_store_access"},
        )
        == 1
    )
    assert (
        metric_sample_value(
            text,
            "knowledge_catalog_entity_count",
            {"entity": "knowledge_bases"},
        )
        == 1
    )


def test_chunks_endpoint_returns_selected_document_chunks(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    activate_service_imports()
    __import__("app.services.store_provider")
    clear_service_caches()

    try:
        client = TestClient(service_app)
        ingest_response = client.post(
            "/api/knowledge/v1/documents:ingest",
            json={
                "source": {
                    "name": "运维手册",
                    "kind": "manual",
                    "tags": ["ops", "chunking"],
                },
                "title": "扩容实施步骤",
                "content": (
                    "扩容前确认节点配额、带宽策略、镜像版本和回滚预案。"
                    "执行窗口内要同步监控、负责人和值班电话，确保变更可追踪。"
                ),
                "tags": ["capacity", "change"],
            },
        )
        assert ingest_response.status_code == 201
        document_id = ingest_response.json()["data"]["document"]["id"]

        chunks_response = client.get(
            "/api/knowledge/v1/chunks",
            params={"documentId": document_id},
        )

        assert chunks_response.status_code == 200
        payload = chunks_response.json()
        assert payload["success"] is True
        assert len(payload["data"]) >= 1
        assert all(chunk["documentId"] == document_id for chunk in payload["data"])
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        clear_service_caches()


def test_import_preview_and_file_ingest_endpoints(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    import_root = tmp_path / "runtime" / "imports"
    starter_dir = import_root / "starter"
    starter_dir.mkdir(parents=True)
    (starter_dir / "gpu-release.md").write_text(
        "# GPU 文件导入\n\n文件导入前需要确认驱动版本、镜像兼容性和网络出口。",
        encoding="utf-8",
    )

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    activate_service_imports()
    __import__("app.services.store_provider")
    clear_service_caches()

    try:
        client = TestClient(service_app)
        preview_response = client.get(
            "/api/knowledge/v1/imports:preview",
            params={"directory": "starter", "glob": "**/*", "maxFiles": 10},
        )
        assert preview_response.status_code == 200
        preview_payload = preview_response.json()["data"]
        assert preview_payload["matchedFiles"] == 1
        assert preview_payload["importableFiles"] == 1

        import_response = client.post(
            "/api/knowledge/v1/files:ingest",
            json={
                "directory": "starter",
                "glob": "**/*",
                "maxFiles": 10,
                "source": {
                    "name": "文件批量导入",
                    "kind": "manual",
                    "tags": ["filesystem", "starter"],
                },
                "tags": ["filesystem"],
            },
        )
        assert import_response.status_code == 201
        payload = import_response.json()["data"]
        assert payload["processedFiles"] == 1
        assert payload["importedFiles"] == 1
        assert payload["results"][0]["documentId"]
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        clear_service_caches()


def test_admin_knowledge_base_document_and_reindex_routes(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    audit_path = tmp_path / "runtime" / "knowledge-admin-audit.jsonl"
    import_root = tmp_path / "runtime" / "imports"
    starter_dir = import_root / "starter"
    starter_dir.mkdir(parents=True)
    (starter_dir / "gpu-admin.md").write_text(
        "# GPU 管理台导入\n\n管理员导入前需要确认驱动版本、镜像兼容性、网络出口和告警联系人。",
        encoding="utf-8",
    )

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_audit_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH")
    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = str(audit_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    activate_service_imports()
    __import__("app.services.store_provider")
    clear_service_caches()

    try:
        client = TestClient(service_app)
        kb_response = client.post(
            "/api/v1/admin/knowledge-bases",
            headers={"X-Operator-Reason": "create baseline kb"},
            json={
                "name": "GPU 管理知识库",
                "code": "gpu-admin",
                "scene": "product",
                "language": "zh-CN",
                "retrieval_mode": "hybrid-baseline",
                "embedding_model": "baseline-keyword",
                "description": "供管理员验证索引与检索的知识库。",
            },
        )
        assert kb_response.status_code == 201
        kb_payload = kb_response.json()
        assert kb_payload["code"] == 0
        kb_id = kb_payload["data"]["kb_id"]

        invalid_update_kb_response = client.patch(
            f"/api/v1/admin/knowledge-bases/{kb_id}",
            headers={"X-Operator-Reason": "reject empty update"},
            json={"status": None},
        )
        assert invalid_update_kb_response.status_code == 400

        update_kb_response = client.patch(
            f"/api/v1/admin/knowledge-bases/{kb_id}",
            headers={"X-Operator-Reason": "tighten retrieval baseline"},
            json={
                "name": "GPU 管理知识库（停用验证）",
                "description": "供管理员验证索引、检索和停用切换。",
                "retrieval_mode": "hybrid-tightened",
                "status": "disabled",
            },
        )
        assert update_kb_response.status_code == 200
        update_kb_payload = update_kb_response.json()["data"]
        assert update_kb_payload["kb_id"] == kb_id
        assert update_kb_payload["name"] == "GPU 管理知识库（停用验证）"
        assert update_kb_payload["retrieval_mode"] == "hybrid-tightened"
        assert update_kb_payload["status"] == "disabled"

        list_response = client.get("/api/v1/admin/knowledge-bases", params={"page": 1, "page_size": 20})
        assert list_response.status_code == 200
        assert list_response.json()["data"]["items"][0]["kb_id"] == kb_id
        assert list_response.json()["data"]["items"][0]["status"] == "disabled"

        create_doc_response = client.post(
            f"/api/v1/admin/knowledge-bases/{kb_id}/documents",
            headers={"X-Operator-Reason": "seed admin document"},
            json={
                "file_id": "starter/gpu-admin.md",
                "title": "GPU 管理台导入",
                "tags": ["gpu", "admin"],
                "source_type": "filesystem",
            },
        )
        assert create_doc_response.status_code == 202
        doc_payload = create_doc_response.json()["data"]
        assert doc_payload["chunk_count"] >= 1
        doc_id = doc_payload["doc_id"]

        detail_response = client.get(f"/api/v1/admin/knowledge-documents/{doc_id}")
        assert detail_response.status_code == 200
        detail_payload = detail_response.json()["data"]
        assert detail_payload["document"]["doc_id"] == doc_id
        assert detail_payload["chunk_stats"]["latest_job_id"] is not None
        create_job_id = detail_payload["chunk_stats"]["latest_job_id"]

        job_response = client.get(f"/api/v1/admin/jobs/{create_job_id}")
        assert job_response.status_code == 200
        job_payload = job_response.json()["data"]
        assert job_payload["job_id"] == create_job_id
        assert job_payload["type"] == "knowledge_document_create"
        assert job_payload["status"] == "succeeded"

        chunks_response = client.get(
            f"/api/v1/admin/knowledge-documents/{doc_id}/chunks",
            params={"page": 1, "page_size": 20},
        )
        assert chunks_response.status_code == 200
        assert chunks_response.json()["data"]["items"][0]["doc_id"] == doc_id

        search_preview_response = client.post(
            "/api/v1/admin/retrieval/search-preview",
            json={"query": "GPU 导入前确认什么", "kb_id": kb_id, "top_k": 5, "tags": ["gpu"]},
        )
        assert search_preview_response.status_code == 200
        preview_payload = search_preview_response.json()["data"]
        assert preview_payload["total"] >= 1
        assert preview_payload["items"][0]["kb_id"] == kb_id

        invalid_reindex_response = client.post(
            f"/api/v1/admin/knowledge-documents/{doc_id}/reindex",
            headers={"X-Operator-Reason": "reindex validation"},
            json={"force": True, "confirm_token": "wrong"},
        )
        assert invalid_reindex_response.status_code == 400

        reindex_response = client.post(
            f"/api/v1/admin/knowledge-documents/{doc_id}/reindex",
            headers={"X-Operator-Reason": "reindex validation"},
            json={"force": True, "confirm_token": f"reindex:{doc_id}"},
        )
        assert reindex_response.status_code == 202
        reindex_payload = reindex_response.json()["data"]
        assert reindex_payload["status"] == "succeeded"

        reindex_job_response = client.get(f"/api/v1/admin/jobs/{reindex_payload['job_id']}")
        assert reindex_job_response.status_code == 200
        assert reindex_job_response.json()["data"]["type"] == "knowledge_document_reindex"

        detail_after_reindex_response = client.get(f"/api/v1/admin/knowledge-documents/{doc_id}")
        assert detail_after_reindex_response.status_code == 200
        detail_after_reindex_payload = detail_after_reindex_response.json()["data"]
        assert detail_after_reindex_payload["document"]["version_no"] == 2
        assert (
            detail_after_reindex_payload["chunk_stats"]["latest_job_id"]
            == reindex_payload["job_id"]
        )

        audit_response = client.get(
            "/api/knowledge/v1/admin/audit-records",
            params={
                "page": 1,
                "pageSize": 10,
                "resourceType": "knowledge_document",
            },
        )
        assert audit_response.status_code == 200
        audit_payload = audit_response.json()["data"]
        assert audit_payload["total"] == 2
        assert audit_payload["items"][0]["action"] == "reindex"
        assert audit_payload["items"][1]["action"] == "create"

        kb_audit_response = client.get(
            "/api/knowledge/v1/admin/audit-records",
            params={
                "page": 1,
                "pageSize": 10,
                "resourceType": "knowledge_base",
                "action": "update",
            },
        )
        assert kb_audit_response.status_code == 200
        kb_audit_payload = kb_audit_response.json()["data"]
        assert kb_audit_payload["total"] == 1
        assert kb_audit_payload["items"][0]["resource_id"] == kb_id
        assert kb_audit_payload["items"][0]["action"] == "update"
        assert kb_audit_payload["items"][0]["after_json"]["status"] == "disabled"

        audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(audit_lines) == 4
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_audit_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = original_audit_path
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        clear_service_caches()


def test_snapshot_endpoint_exports_runtime_state(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    audit_path = tmp_path / "runtime" / "knowledge-admin-audit.jsonl"
    outbox_path = tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    raw_root = tmp_path / "runtime" / "raw-objects"
    import_root = tmp_path / "runtime" / "imports"
    starter_dir = import_root / "starter"
    starter_dir.mkdir(parents=True)
    (starter_dir / "gpu-snapshot.md").write_text(
        "# GPU 快照导出\n\n导出运行时快照前先导入一篇文档，确保知识库、审计和概览数据同步可见。",
        encoding="utf-8",
    )

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_audit_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH")
    original_import_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT")
    original_outbox_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH")
    original_raw_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = str(audit_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = str(import_root)
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(outbox_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(raw_root)
    activate_service_imports()
    __import__("app.services.store_provider")
    clear_service_caches()

    try:
        client = TestClient(service_app)
        kb_response = client.post(
            "/api/v1/admin/knowledge-bases",
            headers={"X-Operator-Reason": "snapshot create kb"},
            json={
                "name": "GPU 快照知识库",
                "code": "gpu-snapshot",
                "scene": "product",
                "language": "zh-CN",
                "retrieval_mode": "hybrid-baseline",
                "embedding_model": "baseline-keyword",
                "description": "用于验证运行时快照导出。",
            },
        )
        assert kb_response.status_code == 201
        kb_id = kb_response.json()["data"]["kb_id"]

        create_doc_response = client.post(
            f"/api/v1/admin/knowledge-bases/{kb_id}/documents",
            headers={"X-Operator-Reason": "snapshot create document"},
            json={
                "file_id": "starter/gpu-snapshot.md",
                "title": "GPU 快照导出",
                "tags": ["gpu", "snapshot"],
                "source_type": "filesystem",
            },
        )
        assert create_doc_response.status_code == 202
        doc_id = create_doc_response.json()["data"]["doc_id"]

        snapshot_response = client.get(
            "/api/knowledge/v1/snapshot",
            params={"auditLimit": 1},
        )
        assert snapshot_response.status_code == 200
        payload = snapshot_response.json()["data"]
        assert payload["service"] == "smartcloud-x-knowledge-service"
        assert payload["counts"]["knowledgeBases"] == 1
        assert payload["counts"]["documents"] >= 1
        assert payload["overview"]["counts"]["knowledgeBases"] == 1
        assert payload["counts"] == payload["overview"]["counts"]
        assert payload["counts"]["knowledgeBases"] == len(payload["knowledgeBases"])
        assert payload["counts"]["documentProfiles"] == len(payload["documentProfiles"])
        assert len(payload["knowledgeBases"]) == 1
        assert payload["knowledgeBases"][0]["kb_id"] == kb_id
        assert any(document["id"] == doc_id for document in payload["documents"])
        assert len(payload["recentAuditRecords"]) == 1
        assert payload["recentAuditRecords"][0]["action"] == "create"
        assert payload["recentAuditRecords"][0]["resource_type"] == "knowledge_document"
        assert payload["integrations"]["pendingEvents"] >= 1
        assert payload["integrations"]["eventCounters"]["queued"] >= 1
        assert payload["integrations"]["recentEvents"][0]["docId"] == doc_id
        document_profile = next(
            item for item in payload["documentProfiles"] if item["doc_id"] == doc_id
        )
        assert document_profile["source_type"] == "filesystem"
        assert payload["integrations"]["recentEvents"][0]["kbId"] == kb_id
        assert payload["integrations"]["recentEvents"][0]["rawObject"]["sourceType"] == "filesystem"
        assert (
            payload["integrations"]["recentEvents"][0]["rawObject"]["sourceUri"]
            == document_profile["source_uri"]
        )
        assert payload["integrations"]["recentEvents"][0]["rawObject"]["objectKey"].startswith(
            "gpu-snapshot/"
        )
        mirror_path = Path(payload["integrations"]["recentEvents"][0]["rawObject"]["mirrorPath"])
        assert mirror_path.exists()
        assert mirror_path.read_text(encoding="utf-8").startswith("# GPU 快照导出")
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_audit_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_AUDIT_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_AUDIT_PATH"] = original_audit_path
        if original_import_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT"] = original_import_root
        if original_outbox_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = original_outbox_path
        if original_raw_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = original_raw_root
        clear_service_caches()


def test_snapshot_endpoint_repairs_missing_profiles_for_public_ingestion(tmp_path) -> None:
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    outbox_path = tmp_path / "runtime" / "knowledge-indexing-outbox.jsonl"
    raw_root = tmp_path / "runtime" / "raw-objects"

    original_data_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_DATA_PATH")
    original_outbox_path = os.environ.get("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH")
    original_raw_root = os.environ.get("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT")
    os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = str(runtime_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = str(outbox_path)
    os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = str(raw_root)
    activate_service_imports()
    __import__("app.services.store_provider")
    clear_service_caches()

    try:
        client = TestClient(service_app)
        ingest_response = client.post(
            "/api/knowledge/v1/documents:ingest",
            json={
                "source": {
                    "name": "GPU Public Snapshot KB",
                    "kind": "product",
                    "uri": "kb://gpu-public-snapshot",
                    "tags": ["gpu", "public"],
                },
                "title": "GPU Public Snapshot",
                "content": "GPU Public Snapshot 会验证公开 ingestion 路径生成的运行时状态也能在快照导出时补齐知识库画像。",
                "tags": ["gpu", "snapshot"],
            },
        )
        assert ingest_response.status_code == 201
        ingest_payload = ingest_response.json()["data"]

        snapshot_response = client.get("/api/knowledge/v1/snapshot")
        assert snapshot_response.status_code == 200
        payload = snapshot_response.json()["data"]

        assert payload["counts"]["sources"] == 1
        assert payload["counts"]["documents"] == 1
        assert payload["counts"]["knowledgeBases"] == 1
        assert payload["counts"]["documentProfiles"] == 1
        assert payload["counts"]["knowledgeBases"] == len(payload["knowledgeBases"])
        assert payload["counts"]["documentProfiles"] == len(payload["documentProfiles"])
        assert payload["knowledgeBases"][0]["kb_id"] == ingest_payload["source"]["id"]
        assert payload["knowledgeBases"][0]["code"] == "gpu-public-snapshot"
        assert payload["documentProfiles"][0]["doc_id"] == ingest_payload["document"]["id"]
        assert payload["documentProfiles"][0]["latest_job_id"] == ingest_payload["job"]["id"]
    finally:
        if original_data_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_DATA_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_DATA_PATH"] = original_data_path
        if original_outbox_path is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH"] = original_outbox_path
        if original_raw_root is None:
            os.environ.pop("SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT", None)
        else:
            os.environ["SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT"] = original_raw_root
        clear_service_caches()


def test_admin_validation_errors_use_canonical_envelope() -> None:
    client = TestClient(service_app)

    response = client.post(
        "/api/v1/admin/knowledge-bases",
        headers={"X-Request-Id": "req-admin-validation-1", "X-Operator-Reason": "validate"},
        json={"name": "missing-required-fields"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["request_id"] == "req-admin-validation-1"
    assert payload["error"]["type"] == "validation_error"


def test_otlp_tracing_exports_ingestion_request(tmp_path) -> None:
    server, thread = start_trace_collector()
    runtime_path = tmp_path / "runtime" / "knowledge-store.json"
    import_root = tmp_path / "runtime" / "imports"
    import_root.mkdir(parents=True)

    tracked_keys = {
        "SMARTCLOUD_KNOWLEDGE_DATA_PATH": str(runtime_path),
        "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT": str(import_root),
        "SMARTCLOUD_TRACE_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    }
    originals = {key: os.environ.get(key) for key in tracked_keys}
    for key, value in tracked_keys.items():
        os.environ[key] = value

    try:
        clear_service_caches()
        if hasattr(service_app.state, "tracing_configured"):
            delattr(service_app.state, "tracing_configured")
        configure_tracing(service_app, get_settings())
        client = TestClient(service_app)
        response = client.post(
            "/api/knowledge/v1/documents:ingest",
            json={
                "source": {
                    "name": "Trace Export KB",
                    "kind": "manual",
                    "tags": ["trace"],
                },
                "title": "Trace Export Validation",
                "content": "Trace Export Validation 会触发知识服务的 OpenTelemetry span，并通过 OTLP HTTP 导出到测试收集器。",
                "tags": ["trace", "otlp"],
            },
        )
        assert response.status_code == 201
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
