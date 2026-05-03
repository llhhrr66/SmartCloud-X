#!/usr/bin/env python3
"""Minimal smoke test for the local knowledge + RAG compose baseline."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode

KNOWLEDGE_ROOT = os.getenv("KNOWLEDGE_SERVICE_ROOT", "http://localhost:8031")
RAG_ROOT = os.getenv("RAG_SERVICE_ROOT", "http://localhost:8040")
MARKETING_ROOT = os.getenv("MARKETING_SERVICE_ROOT", "http://localhost:8002")
RESEARCH_ROOT = os.getenv("RESEARCH_SERVICE_ROOT", "http://localhost:8003")
ORCHESTRATOR_ROOT = os.getenv("ORCHESTRATOR_SERVICE_ROOT", "http://localhost:8010")
WEB_ADMIN_ROOT = os.getenv("WEB_ADMIN_ROOT", "http://localhost:8050")
MYSQL_ROOT = os.getenv("MYSQL_ROOT", "http://localhost:3306")
REDIS_ROOT = os.getenv("REDIS_ROOT", "http://localhost:6379")
MONGO_ROOT = os.getenv("MONGO_ROOT", "http://localhost:27017")
MINIO_ROOT = os.getenv("MINIO_ROOT", f"http://localhost:{os.getenv('SMARTCLOUD_MINIO_HOST_PORT', '19000')}")
QDRANT_ROOT = os.getenv("QDRANT_ROOT", "http://localhost:6333")
OPENSEARCH_ROOT = os.getenv("OPENSEARCH_ROOT", "http://localhost:9200")
KNOWLEDGE_API = os.getenv("KNOWLEDGE_SERVICE_API", f"{KNOWLEDGE_ROOT}/api/knowledge/v1")
RAG_API = os.getenv("RAG_SERVICE_API", f"{RAG_ROOT}/api/rag/v1")
ADMIN_KNOWLEDGE_API = os.getenv("ADMIN_KNOWLEDGE_SERVICE_API", f"{KNOWLEDGE_ROOT}/api/v1/admin")
ADMIN_RAG_API = os.getenv("ADMIN_RAG_SERVICE_API", f"{RAG_ROOT}/api/v1/admin")
REQUEST_TIMEOUT = float(os.getenv("SMARTCLOUD_SMOKE_TIMEOUT_SECONDS", "5"))
WAIT_ATTEMPTS = int(os.getenv("SMARTCLOUD_SMOKE_WAIT_ATTEMPTS", "20"))
WAIT_SECONDS = float(os.getenv("SMARTCLOUD_SMOKE_WAIT_SECONDS", "2"))
OPERATOR_REASON_HEADER = os.getenv("SMARTCLOUD_OPERATOR_REASON_HEADER", "X-Operator-Reason")
DIFY_EXTERNAL_API_KEY = os.getenv("SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY", "smartcloud-dify-local")
DIRECT_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
EXPECTED_KNOWLEDGE_METRICS = [
    "knowledge_file_import_runs_total",
    "knowledge_admin_write_requests_total",
    "knowledge_document_reindexes_total",
    "knowledge_readiness_state",
    "knowledge_catalog_entity_count",
    "knowledge_index_outbox_status_count",
    "knowledge_index_worker_runs_total",
    "knowledge_index_connector_writes_total",
]
EXPECTED_RAG_METRICS = [
    "rag_retrieval_duration_seconds",
    "rag_answer_requests_total",
    "rag_upstream_errors_total",
    "rag_readiness_state",
    "rag_upstream_ready_state",
]
DEPENDENCY_PROBES = (
    ("mysql", f"{MYSQL_ROOT}/", None),
    ("redis", f"{REDIS_ROOT}/", None),
    ("mongodb", f"{MONGO_ROOT}/", None),
    ("minio", f"{MINIO_ROOT}/minio/health/live", None),
    ("qdrant", f"{QDRANT_ROOT}/collections", lambda payload: payload.get("status") == "ok"),
    ("opensearch", f"{OPENSEARCH_ROOT}/_cluster/health", lambda payload: payload.get("status") in {"green", "yellow"}),
)


def _build_request(
    method: str,
    url: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> urllib.request.Request:
    request_headers = {
        "Content-Type": "application/json",
        "X-Request-Id": "smartcloud-compose-smoke",
        "X-Caller-Service": "smartcloud-compose-smoke",
        **(headers or {}),
    }
    return urllib.request.Request(
        url,
        data=body,
        method=method,
        headers=request_headers,
    )


def _assert_standard_response_headers(response, url: str) -> None:
    request_id = response.headers.get("X-Request-Id")
    trace_id = response.headers.get("X-Trace-Id")
    app_name = response.headers.get("X-App-Name")
    response_time = response.headers.get("X-Response-Time")
    if not request_id or not trace_id:
        raise RuntimeError(f"missing trace headers from {url}")
    if not app_name or not response_time:
        raise RuntimeError(f"missing standard response headers from {url}")


def request(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = _build_request(method, url, body=body, headers=headers)
    with DIRECT_HTTP.open(req, timeout=REQUEST_TIMEOUT) as response:
        _assert_standard_response_headers(response, url)
        payload = json.loads(response.read().decode("utf-8"))
    if "success" in payload:
        if not payload.get("success", False):
            raise RuntimeError(f"unsuccessful response from {url}: {payload}")
        return payload.get("data") or {}
    if payload.get("code") != 0:
        raise RuntimeError(f"unsuccessful response from {url}: {payload}")
    return payload.get("data") or {}


def request_json(method: str, url: str, headers: dict[str, str] | None = None) -> Any:
    req = _build_request(method, url, headers=headers)
    with DIRECT_HTTP.open(req, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def request_text(method: str, url: str, headers: dict[str, str] | None = None) -> str:
    req = _build_request(method, url, headers=headers)
    with DIRECT_HTTP.open(req, timeout=REQUEST_TIMEOUT) as response:
        _assert_standard_response_headers(response, url)
        return response.read().decode("utf-8")


def request_raw_text(method: str, url: str, headers: dict[str, str] | None = None) -> str:
    req = _build_request(method, url, headers=headers)
    with DIRECT_HTTP.open(req, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8")


def _probe_dependency(name: str, url: str, validator) -> None:
    try:
        payload = request_json("GET", url)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"dependency {name} is unavailable: HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"dependency {name} is unavailable: {reason}") from exc
    except (TimeoutError, ValueError) as exc:
        raise RuntimeError(f"dependency {name} is unavailable: {exc}") from exc
    if validator is not None and not validator(payload):
        raise RuntimeError(f"dependency {name} is unavailable: unexpected probe payload {payload}")


def assert_required_dependencies() -> None:
    missing_dependencies: list[str] = []
    errors: list[str] = []
    for name, url, validator in DEPENDENCY_PROBES:
        try:
            _probe_dependency(name, url, validator)
        except RuntimeError as exc:
            missing_dependencies.append(name)
            errors.append(str(exc))
    if missing_dependencies:
        joined = ", ".join(missing_dependencies)
        details = "; ".join(errors)
        raise RuntimeError(f"required dependencies not ready: {joined}. {details}")


def wait_for_health(url: str, label: str) -> None:
    last_error = None
    for _attempt in range(1, WAIT_ATTEMPTS + 1):
        try:
            payload = request("GET", url)
            if payload.get("ready") is True:
                return
            last_error = RuntimeError(f"{label} returned not-ready payload: {payload}")
        except Exception as exc:  # noqa: BLE001 - smoke test should keep retrying
            last_error = exc
        time.sleep(WAIT_SECONDS)
    raise RuntimeError(f"{label} failed health checks after {WAIT_ATTEMPTS} attempts: {last_error}")


def wait_for_snapshot_event(doc_id: str, operation: str) -> tuple[dict[str, Any], dict[str, Any]]:
    last_snapshot: dict[str, Any] = {}
    for _attempt in range(1, WAIT_ATTEMPTS + 1):
        snapshot = request(
            "GET",
            f"{KNOWLEDGE_API}/snapshot?{urlencode({'auditLimit': 5})}",
        )
        last_snapshot = snapshot
        recent_events = snapshot.get("integrations", {}).get("recentEvents", [])
        for event in recent_events:
            if event.get("docId") != doc_id:
                continue
            if event.get("operation") != operation:
                continue
            connector_results = event.get("connectorResults") or []
            if event.get("status") == "completed" and connector_results:
                return snapshot, event
        time.sleep(WAIT_SECONDS)
    raise RuntimeError(
        f"snapshot did not expose a completed {operation} event for {doc_id}: {last_snapshot}"
    )


def main() -> int:
    assert_required_dependencies()
    wait_for_health(f"{KNOWLEDGE_ROOT}/healthz", "knowledge-service")
    wait_for_health(f"{RAG_ROOT}/healthz", "rag-service")

    knowledge_health = request("GET", f"{KNOWLEDGE_ROOT}/healthz")
    rag_health = request("GET", f"{RAG_ROOT}/healthz")
    marketing_health = request("GET", f"{MARKETING_ROOT}/healthz")
    research_health = request("GET", f"{RESEARCH_ROOT}/healthz")
    orchestrator_health = request("GET", f"{ORCHESTRATOR_ROOT}/healthz")
    rag_capabilities = request("GET", f"{RAG_API}/capabilities")
    web_admin_index = request_raw_text("GET", WEB_ADMIN_ROOT)

    connector_snapshot = {
        "rawStorage": knowledge_health["runtime"]["runtimeSync"]["rawStorage"].get("backend"),
        "metadataStore": knowledge_health["runtime"]["runtimeSync"]["metadataStore"].get("backend"),
        "vectorStore": knowledge_health["runtime"]["runtimeSync"]["vectorStore"].get("backend"),
        "bm25Store": knowledge_health["runtime"]["runtimeSync"]["bm25Store"].get("backend"),
        "cache": knowledge_health["runtime"]["runtimeSync"]["cache"].get("backend"),
        "taskQueue": knowledge_health["runtime"]["runtimeSync"]["taskQueue"].get("backend"),
    }
    expected_connectors = {
        "rawStorage": "minio",
        "metadataStore": "mysql",
        "vectorStore": "qdrant",
        "bm25Store": "opensearch",
        "cache": {"redis-configured", "redis-ttl"},
        "taskQueue": "redis-list-primary",
    }
    for connector_name, expected_backend in expected_connectors.items():
        actual_backend = connector_snapshot.get(connector_name)
        if isinstance(expected_backend, set):
            if actual_backend not in expected_backend:
                raise RuntimeError(
                    f"knowledge connector {connector_name} expected one of {sorted(expected_backend)}, got {actual_backend!r}"
                )
            continue
        if actual_backend != expected_backend:
            raise RuntimeError(
                f"knowledge connector {connector_name} expected {expected_backend!r}, got {actual_backend!r}"
            )

    bootstrap = request("POST", f"{KNOWLEDGE_API}/catalog:bootstrap")
    import_preview = request(
        "GET",
        f"{KNOWLEDGE_API}/imports:preview?{urlencode({'directory': 'starter', 'glob': '**/*', 'maxFiles': 10})}",
    )
    file_import = request(
        "POST",
        f"{KNOWLEDGE_API}/files:ingest",
        {
            "directory": "starter",
            "glob": "**/*",
            "maxFiles": 10,
            "source": {
                "name": "文件批量导入",
                "kind": "manual",
                "tags": ["filesystem", "starter"],
            },
            "tags": ["filesystem", "starter"],
        },
    )
    documents = request("GET", f"{KNOWLEDGE_API}/documents")
    overview = request("GET", f"{KNOWLEDGE_API}/overview")
    search = request(
        "POST",
        f"{KNOWLEDGE_API}/search",
        {
            "query": "GPU 部署前需要确认什么",
            "topK": 3,
            "tags": ["gpu", "launch"],
        },
    )
    kb_code = f"compose-smoke-{int(time.time())}"
    knowledge_base = request(
        "POST",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-bases",
        {
            "name": "Compose Smoke KB",
            "code": kb_code,
            "scene": "product",
            "language": "zh-CN",
            "retrieval_mode": "hybrid-baseline",
            "embedding_model": "baseline-keyword",
            "description": "Compose smoke-test validation knowledge base.",
        },
        headers={OPERATOR_REASON_HEADER: "compose smoke create kb"},
    )
    updated_knowledge_base = request(
        "PATCH",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-bases/{knowledge_base['kb_id']}",
        {
            "name": "Compose Smoke KB (disabled)",
            "description": "Compose smoke-test updated knowledge base.",
            "retrieval_mode": "hybrid-tightened",
            "status": "disabled",
        },
        headers={OPERATOR_REASON_HEADER: "compose smoke update kb"},
    )
    knowledge_bases = request(
        "GET",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-bases?{urlencode({'page': 1, 'page_size': 20})}",
    )
    admin_document = request(
        "POST",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-bases/{knowledge_base['kb_id']}/documents",
        {
            "file_id": "starter/gpu-release-checklist.md",
            "title": "GPU 发布核对清单",
            "tags": ["gpu", "admin"],
            "source_type": "filesystem",
        },
        headers={OPERATOR_REASON_HEADER: "compose smoke ingest doc"},
    )
    admin_document_detail = request(
        "GET",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-documents/{admin_document['doc_id']}",
    )
    admin_document_job = request(
        "GET",
        f"{ADMIN_KNOWLEDGE_API}/jobs/{admin_document_detail['chunk_stats']['latest_job_id']}",
    )
    admin_chunks = request(
        "GET",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-documents/{admin_document['doc_id']}/chunks?{urlencode({'page': 1, 'page_size': 20})}",
    )
    admin_search = request(
        "POST",
        f"{ADMIN_KNOWLEDGE_API}/retrieval/search-preview",
        {
            "query": "GPU 发布前要确认什么",
            "kb_id": knowledge_base["kb_id"],
            "top_k": 3,
            "tags": ["gpu"],
        },
    )
    admin_reindex = request(
        "POST",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-documents/{admin_document['doc_id']}/reindex",
        {
            "force": True,
            "confirm_token": f"reindex:{admin_document['doc_id']}",
        },
        headers={OPERATOR_REASON_HEADER: "compose smoke reindex"},
    )
    admin_reindex_job = request(
        "GET",
        f"{ADMIN_KNOWLEDGE_API}/jobs/{admin_reindex['job_id']}",
    )
    admin_document_detail_after_reindex = request(
        "GET",
        f"{ADMIN_KNOWLEDGE_API}/knowledge-documents/{admin_document['doc_id']}",
    )
    admin_diagnostic = request(
        "POST",
        f"{ADMIN_RAG_API}/retrieval/diagnostics",
        {
            "query": "GPU 发布前要确认什么",
            "kb_id": knowledge_base["kb_id"],
            "top_k": 3,
            "include_citations": True,
        },
    )
    dify_retrieval = request(
        "POST",
        f"{KNOWLEDGE_ROOT}/retrieval",
        {
            "knowledge_id": kb_code,
            "query": "GPU 发布前要确认什么",
            "retrieval_setting": {"top_k": 3, "score_threshold": 0.1},
            "metadata_condition": {
                "logical_operator": "and",
                "conditions": [{"name": ["tags"], "comparison_operator": "contains", "value": "gpu"}],
            },
        },
        headers={"Authorization": f"Bearer {DIFY_EXTERNAL_API_KEY}"},
    )
    admin_audit = request(
        "GET",
        f"{KNOWLEDGE_API}/admin/audit-records?{urlencode({'page': 1, 'pageSize': 10, 'resourceType': 'knowledge_document'})}",
    )
    knowledge_base_audit = request(
        "GET",
        f"{KNOWLEDGE_API}/admin/audit-records?{urlencode({'page': 1, 'pageSize': 10, 'resourceType': 'knowledge_base', 'action': 'update'})}",
    )
    snapshot, processed_snapshot_event = wait_for_snapshot_event(admin_document["doc_id"], "reindex")
    overview = request("GET", f"{KNOWLEDGE_API}/overview")
    if not documents:
        raise RuntimeError("knowledge documents list is empty after starter bootstrap")
    first_document_id = documents[0].get("id")
    if not first_document_id:
        raise RuntimeError(f"knowledge documents payload is missing document ids: {documents}")
    chunks = request(
        "GET",
        f"{KNOWLEDGE_API}/documents/{first_document_id}/chunks?{urlencode({'page': 1, 'page_size': 10})}",
    )
    document_profile = request("GET", f"{KNOWLEDGE_API}/documents/{first_document_id}")
    diagnostic = request(
        "POST",
        f"{RAG_API}/diagnostics",
        {
            "query": "GPU 发布前要确认什么",
            "topK": 3,
            "filters": {"tags": ["gpu"]},
        },
    )
    answer = request(
        "POST",
        f"{RAG_API}/answer",
        {
            "query": "GPU 发布前要确认什么",
            "topK": 3,
            "style": "brief",
            "filters": {"tags": ["gpu"]},
        },
    )
    empty_answer = request(
        "POST",
        f"{RAG_API}/answer",
        {
            "query": "一个不会命中任何知识的冷门问题",
            "topK": 3,
            "style": "brief",
            "filters": {"tags": ["definitely-missing"]},
        },
    )
    knowledge_metrics = request_text("GET", f"{KNOWLEDGE_ROOT}/metrics")
    rag_metrics = request_text("GET", f"{RAG_ROOT}/metrics")

    if not bootstrap.get("sourcesCreated"):
        raise RuntimeError(f"catalog bootstrap did not create sources: {bootstrap}")
    if import_preview.get("totalFiles", 0) < 1:
        raise RuntimeError(f"import preview did not discover starter files: {import_preview}")
    if file_import.get("importedFiles", 0) < 1:
        raise RuntimeError(f"file import did not ingest starter files: {file_import}")
    if not search.get("items"):
        raise RuntimeError(f"knowledge search returned no items: {search}")
    if not chunks.get("items"):
        raise RuntimeError(f"knowledge chunks endpoint returned no items: {chunks}")
    if not document_profile.get("chunks"):
        raise RuntimeError(f"knowledge document profile returned no chunks: {document_profile}")
    if not rag_capabilities.get("features", {}).get("hybridRetrieval"):
        raise RuntimeError(f"rag capabilities did not expose hybrid retrieval: {rag_capabilities}")
    if not diagnostic.get("candidateCount"):
        raise RuntimeError(f"rag diagnostics returned no candidates: {diagnostic}")
    if answer.get("degraded") is not False:
        raise RuntimeError(f"rag answer unexpectedly degraded: {answer}")
    citations = answer.get("citations") or []
    if not citations:
        raise RuntimeError(f"rag answer returned no citations: {answer}")
    if not all(citation.get("doc_id") for citation in citations):
        raise RuntimeError(f"rag answer citations are missing document identifiers: {citations}")
    if not all(str(citation.get("uri") or "").startswith(("kb://", "file://", "s3://", "minio://", "http://", "https://")) for citation in citations):
        raise RuntimeError(f"rag answer citations did not expose stable source URIs: {citations}")
    if any(str(citation.get("uri") or "").startswith("baseline://") for citation in citations):
        raise RuntimeError(f"rag answer citations still expose baseline placeholder URIs: {citations}")
    if not web_admin_index or '<div id="root"></div>' not in web_admin_index:
        raise RuntimeError("web-admin root did not return the expected SPA shell")
    if not knowledge_health.get("ready"):
        raise RuntimeError(f"knowledge-service health payload was not ready: {knowledge_health}")
    if not rag_health.get("ready"):
        raise RuntimeError(f"rag-service health payload was not ready: {rag_health}")
    if not marketing_health.get("ready"):
        raise RuntimeError(f"marketing-service health payload was not ready: {marketing_health}")
    if not research_health.get("ready"):
        raise RuntimeError(f"research-service health payload was not ready: {research_health}")
    if not orchestrator_health.get("ready"):
        raise RuntimeError(f"orchestrator-service health payload was not ready: {orchestrator_health}")
    if not knowledge_base.get("kb_id"):
        raise RuntimeError(f"knowledge base creation failed: {knowledge_base}")
    if updated_knowledge_base.get("status") != "disabled":
        raise RuntimeError(f"knowledge base update did not persist status change: {updated_knowledge_base}")
    if knowledge_bases.get("total", 0) < 1:
        raise RuntimeError(f"knowledge base list endpoint returned no results: {knowledge_bases}")
    if not admin_document.get("doc_id"):
        raise RuntimeError(f"admin document creation failed: {admin_document}")
    if admin_document_detail.get("document", {}).get("kb_id") != knowledge_base.get("kb_id"):
        raise RuntimeError(
            "admin document detail did not resolve the expected knowledge base: "
            f"{admin_document_detail}"
        )
    if admin_document_job.get("resource_id") != admin_document.get("doc_id"):
        raise RuntimeError(f"admin document job did not point at the created document: {admin_document_job}")
    if not admin_chunks.get("items"):
        raise RuntimeError(f"admin chunk listing returned no items: {admin_chunks}")
    if admin_search.get("total", 0) < 1:
        raise RuntimeError(f"admin search preview returned no matches: {admin_search}")
    if not admin_reindex.get("job_id"):
        raise RuntimeError(f"admin reindex did not return a job id: {admin_reindex}")
    if admin_reindex_job.get("status") != "completed":
        raise RuntimeError(f"admin reindex job did not complete: {admin_reindex_job}")
    if admin_document_detail_after_reindex.get("document", {}).get("version_no", 0) < 2:
        raise RuntimeError(
            "admin document detail did not expose the incremented document version after reindex: "
            f"{admin_document_detail_after_reindex}"
        )
    if admin_diagnostic.get("coverage", {}).get("candidate_count", 0) < 1:
        raise RuntimeError(f"admin retrieval diagnostics returned no candidates: {admin_diagnostic}")
    if len(dify_retrieval.get("records", [])) < 1:
        raise RuntimeError(f"external retrieval adapter returned no records: {dify_retrieval}")
    if admin_audit.get("total", 0) < 1:
        raise RuntimeError(f"knowledge audit endpoint returned no events: {admin_audit}")
    if knowledge_base_audit.get("total", 0) < 1:
        raise RuntimeError(f"knowledge-base audit endpoint returned no update events: {knowledge_base_audit}")

    missing_knowledge_metrics = [metric for metric in EXPECTED_KNOWLEDGE_METRICS if metric not in knowledge_metrics]
    missing_rag_metrics = [metric for metric in EXPECTED_RAG_METRICS if metric not in rag_metrics]
    integrations = snapshot.get("integrations", {})
    snapshot_document_profile = request(
        "GET",
        f"{KNOWLEDGE_API}/documents/{admin_document['doc_id']}",
    )
    if snapshot_document_profile.get("raw_object", {}).get("storage_backend") != "minio":
        raise RuntimeError(
            "knowledge document profile did not persist raw-object metadata via MinIO mirror: "
            f"{snapshot_document_profile}"
        )
    if integrations.get("backendSummary", {}).get("vector") != "qdrant":
        raise RuntimeError(f"snapshot vector backend was not Qdrant: {snapshot}")
    if integrations.get("backendSummary", {}).get("bm25") != "opensearch":
        raise RuntimeError(f"snapshot bm25 backend was not OpenSearch: {snapshot}")
    if integrations.get("backendSummary", {}).get("rawObject") != "minio":
        raise RuntimeError(f"snapshot raw object backend was not MinIO: {snapshot}")
    if integrations.get("backendSummary", {}).get("taskQueue") != "redis-primary":
        raise RuntimeError(f"snapshot task queue backend was not Redis-primary: {snapshot}")
    if int(integrations.get("eventCounters", {}).get("completed", 0)) < 1:
        raise RuntimeError(f"snapshot integration counters did not report completed events: {snapshot}")
    if processed_snapshot_event.get("status") != "completed":
        raise RuntimeError(f"snapshot worker event did not complete: {processed_snapshot_event}")
    connector_results = processed_snapshot_event.get("connectorResults") or []
    if len(connector_results) < 5:
        raise RuntimeError(
            f"snapshot worker event did not expose connector results: {processed_snapshot_event}"
        )
    if any(result.get("status") != "succeeded" for result in connector_results):
        raise RuntimeError(f"snapshot worker event had failed connector steps: {processed_snapshot_event}")
    if processed_snapshot_event.get("rawObject", {}).get("sourceUri") != snapshot_document_profile.get("source_uri"):
        raise RuntimeError(
            "snapshot raw-object source URI drifted from the exported document profile: "
            f"{processed_snapshot_event}"
        )
    if missing_knowledge_metrics:
        raise RuntimeError(f"knowledge-service metrics missing expected signals: {missing_knowledge_metrics}")
    if missing_rag_metrics:
        raise RuntimeError(f"rag-service metrics missing expected signals: {missing_rag_metrics}")
    if "knowledge_readiness_state 1.0" not in knowledge_metrics:
        raise RuntimeError("knowledge-service readiness gauge did not report ready on /metrics")
    if 'knowledge_catalog_entity_count{entity="documents"}' not in knowledge_metrics:
        raise RuntimeError("knowledge-service inventory gauges were not exported on /metrics")
    if "rag_readiness_state 1.0" not in rag_metrics:
        raise RuntimeError("rag-service readiness gauge did not report ready on /metrics")
    if "rag_upstream_ready_state 1.0" not in rag_metrics:
        raise RuntimeError("rag-service upstream readiness gauge did not report ready on /metrics")
    if empty_answer.get("degraded") is not False:
        raise RuntimeError(f"empty-answer path unexpectedly reported degraded: {empty_answer}")

    summary = {
        "health": {
            "knowledge": knowledge_health,
            "rag": rag_health,
            "marketing": marketing_health,
            "research": research_health,
            "orchestrator": orchestrator_health,
        },
        "knowledge": {
            "bootstrapSources": bootstrap.get("sourcesCreated"),
            "importPreview": import_preview,
            "overview": overview,
            "searchTotal": search.get("total"),
            "documentCount": len(documents),
            "chunkCount": len(chunks.get("items", [])),
            "documentProfile": {
                "id": document_profile.get("document", {}).get("id"),
                "sourceUri": document_profile.get("source_uri"),
            },
        },
        "admin": {
            "knowledgeBase": {
                "kbId": knowledge_base.get("kb_id"),
                "code": knowledge_base.get("code"),
                "updatedName": updated_knowledge_base.get("name"),
                "updatedStatus": updated_knowledge_base.get("status"),
                "retrievalMode": updated_knowledge_base.get("retrieval_mode"),
                "totalListed": knowledge_bases.get("total"),
            },
            "document": {
                "docId": admin_document.get("doc_id"),
                "chunkCount": admin_document.get("chunk_count"),
                "detail": {
                    "tokenCount": admin_document_detail.get("chunk_stats", {}).get("token_count"),
                    "averageTokensPerChunk": admin_document_detail.get("chunk_stats", {}).get(
                        "average_tokens_per_chunk"
                    ),
                    "latestJobId": admin_document_detail.get("chunk_stats", {}).get("latest_job_id"),
                },
            },
            "chunks": {
                "count": len(admin_chunks.get("items", [])),
            },
            "jobs": {
                "create": {
                    "jobId": admin_document_job.get("job_id"),
                    "status": admin_document_job.get("status"),
                },
                "reindex": {
                    "jobId": admin_reindex_job.get("job_id"),
                    "status": admin_reindex_job.get("status"),
                },
            },
            "searchPreview": {
                "total": admin_search.get("total"),
                "topItem": admin_search.get("items", [{}])[0],
            },
            "reindex": {
                "jobId": admin_reindex.get("job_id"),
                "status": admin_reindex.get("status"),
                "documentVersion": admin_document_detail_after_reindex.get("document", {}).get("version_no"),
            },
            "audit": {
                "total": admin_audit.get("total"),
                "latestAction": admin_audit.get("items", [{}])[0].get("action"),
            },
            "knowledgeBaseAudit": {
                "total": knowledge_base_audit.get("total"),
                "latestAction": knowledge_base_audit.get("items", [{}])[0].get("action"),
            },
            "diagnostic": {
                "candidateCount": admin_diagnostic.get("coverage", {}).get("candidate_count"),
                "notes": admin_diagnostic.get("notes"),
            },
        },
        "diagnostic": {
            "rewrittenQuery": diagnostic.get("rewrittenQuery"),
            "expandedTerms": diagnostic.get("expandedTerms"),
            "unmatchedTerms": diagnostic.get("unmatchedTerms"),
            "sourceBreakdown": diagnostic.get("sourceBreakdown"),
            "candidateCount": diagnostic.get("candidateCount"),
            "degraded": diagnostic.get("degraded"),
        },
        "capabilities": rag_capabilities,
        "webAdmin": {
            "root": WEB_ADMIN_ROOT,
            "spaShell": '<div id="root"></div>',
        },
        "answer": {
            "degraded": answer.get("degraded"),
            "preview": answer.get("answer"),
        },
        "metrics": {
            "knowledge": EXPECTED_KNOWLEDGE_METRICS,
            "rag": EXPECTED_RAG_METRICS,
            "readiness": {
                "knowledgeReady": "knowledge_readiness_state 1.0",
                "ragReady": "rag_readiness_state 1.0",
                "ragUpstreamReady": "rag_upstream_ready_state 1.0",
            },
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print(f"smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001 - concise smoke-test failure path
        print(f"smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
