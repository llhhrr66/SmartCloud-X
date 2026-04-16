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

KNOWLEDGE_ROOT = os.getenv("KNOWLEDGE_SERVICE_ROOT", "http://localhost:8030")
RAG_ROOT = os.getenv("RAG_SERVICE_ROOT", "http://localhost:8040")
WEB_ADMIN_ROOT = os.getenv("WEB_ADMIN_ROOT", "http://localhost:8050")
KNOWLEDGE_API = os.getenv("KNOWLEDGE_SERVICE_API", f"{KNOWLEDGE_ROOT}/api/knowledge/v1")
RAG_API = os.getenv("RAG_SERVICE_API", f"{RAG_ROOT}/api/rag/v1")
ADMIN_KNOWLEDGE_API = os.getenv("ADMIN_KNOWLEDGE_SERVICE_API", f"{KNOWLEDGE_ROOT}/api/v1/admin")
ADMIN_RAG_API = os.getenv("ADMIN_RAG_SERVICE_API", f"{RAG_ROOT}/api/v1/admin")
REQUEST_TIMEOUT = float(os.getenv("SMARTCLOUD_SMOKE_TIMEOUT_SECONDS", "5"))
WAIT_ATTEMPTS = int(os.getenv("SMARTCLOUD_SMOKE_WAIT_ATTEMPTS", "20"))
WAIT_SECONDS = float(os.getenv("SMARTCLOUD_SMOKE_WAIT_SECONDS", "2"))
OPERATOR_REASON_HEADER = os.getenv("SMARTCLOUD_OPERATOR_REASON_HEADER", "X-Operator-Reason")
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
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        _assert_standard_response_headers(response, url)
        payload = json.loads(response.read().decode("utf-8"))
    if "success" in payload:
        if not payload.get("success", False):
            raise RuntimeError(f"unsuccessful response from {url}: {payload}")
        return payload.get("data") or {}
    if payload.get("code") != 0:
        raise RuntimeError(f"unsuccessful response from {url}: {payload}")
    return payload.get("data") or {}


def request_text(method: str, url: str, headers: dict[str, str] | None = None) -> str:
    req = _build_request(method, url, headers=headers)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        _assert_standard_response_headers(response, url)
        return response.read().decode("utf-8")


def request_raw_text(method: str, url: str, headers: dict[str, str] | None = None) -> str:
    req = _build_request(method, url, headers=headers)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8")


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
    wait_for_health(f"{KNOWLEDGE_ROOT}/healthz", "knowledge-service")
    wait_for_health(f"{RAG_ROOT}/healthz", "rag-service")

    knowledge_health = request("GET", f"{KNOWLEDGE_ROOT}/healthz")
    rag_health = request("GET", f"{RAG_ROOT}/healthz")
    rag_capabilities = request("GET", f"{RAG_API}/capabilities")
    web_admin_index = request_raw_text("GET", WEB_ADMIN_ROOT)

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
    knowledge_bases = request("GET", f"{ADMIN_KNOWLEDGE_API}/knowledge-bases?{urlencode({'page': 1, 'page_size': 20})}")
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
        f"{KNOWLEDGE_API}/chunks?{urlencode({'documentId': first_document_id})}",
    )
    diagnostic = request(
        "POST",
        f"{RAG_API}/diagnose",
        {
            "query": "GPU 部署前需要确认什么",
            "topK": 3,
            "filters": {"tags": ["gpu", "launch"]},
        },
    )
    answer = request(
        "POST",
        f"{RAG_API}/answer",
        {
            "query": "GPU 部署前需要确认什么",
            "topK": 3,
            "style": "brief",
            "filters": {"tags": ["gpu", "launch"]},
        },
    )
    empty_answer = request(
        "POST",
        f"{RAG_API}/answer",
        {
            "query": "这个标签下没有结果",
            "topK": 3,
            "style": "brief",
            "filters": {"tags": ["__smoke_missing_tag__"]},
        },
    )
    knowledge_metrics = request_text("GET", f"{KNOWLEDGE_ROOT}/metrics")
    rag_metrics = request_text("GET", f"{RAG_ROOT}/metrics")
    missing_knowledge_metrics = [
        metric for metric in EXPECTED_KNOWLEDGE_METRICS if metric not in knowledge_metrics
    ]
    missing_rag_metrics = [metric for metric in EXPECTED_RAG_METRICS if metric not in rag_metrics]
    if int(import_preview.get("matchedFiles", 0)) < 1:
        raise RuntimeError(f"filesystem preview returned no files: {import_preview}")
    if knowledge_health.get("ready") is not True:
        raise RuntimeError(f"knowledge-service health payload did not report ready: {knowledge_health}")
    if not knowledge_health.get("readinessChecks"):
        raise RuntimeError(f"knowledge-service readiness checks missing from health payload: {knowledge_health}")
    if rag_health.get("ready") is not True:
        raise RuntimeError(f"rag-service health payload did not report ready: {rag_health}")
    if rag_capabilities.get("retrieval") != "knowledge-service-search":
        raise RuntimeError(f"rag-service capabilities returned unexpected retrieval mode: {rag_capabilities}")
    if "<div id=\"root\"></div>" not in web_admin_index:
        raise RuntimeError("web-admin root page did not return the expected SPA shell")
    if not rag_health.get("upstream", {}).get("reachable"):
        raise RuntimeError(f"rag-service upstream probe was not reachable: {rag_health}")
    if int(file_import.get("importedFiles", 0)) + int(file_import.get("reusedFiles", 0)) < 1:
        raise RuntimeError(f"filesystem import did not process any files: {file_import}")
    if int(search.get("total", 0)) < 1:
        raise RuntimeError(f"knowledge search returned no hits: {search}")
    if len(chunks) < 1:
        raise RuntimeError(f"knowledge chunk inspection returned no rows: {chunks}")
    if int(diagnostic.get("candidateCount", 0)) < 1:
        raise RuntimeError(f"rag diagnostic returned no candidates: {diagnostic}")
    if int(knowledge_bases.get("total", 0)) < 1:
        raise RuntimeError(f"admin knowledge-base list returned no rows: {knowledge_bases}")
    listed_kb = next(
        (item for item in knowledge_bases.get("items", []) if item.get("kb_id") == knowledge_base.get("kb_id")),
        None,
    )
    if not listed_kb:
        raise RuntimeError(f"updated knowledge base was missing from admin list: {knowledge_bases}")
    if updated_knowledge_base.get("status") != "disabled":
        raise RuntimeError(f"admin knowledge-base update did not apply disabled status: {updated_knowledge_base}")
    if listed_kb.get("retrieval_mode") != "hybrid-tightened":
        raise RuntimeError(f"admin knowledge-base list did not reflect updated retrieval mode: {listed_kb}")
    if admin_document.get("chunk_count", 0) < 1:
        raise RuntimeError(f"admin document create returned no chunks: {admin_document}")
    if admin_document_detail.get("document", {}).get("doc_id") != admin_document.get("doc_id"):
        raise RuntimeError(f"admin document detail did not match created document: {admin_document_detail}")
    if admin_document_job.get("type") != "knowledge_document_create":
        raise RuntimeError(f"admin create job lookup returned unexpected payload: {admin_document_job}")
    if len(admin_chunks.get("items", [])) < 1:
        raise RuntimeError(f"admin chunk preview returned no rows: {admin_chunks}")
    if int(admin_search.get("total", 0)) < 1:
        raise RuntimeError(f"admin search preview returned no hits: {admin_search}")
    if admin_reindex.get("status") != "succeeded":
        raise RuntimeError(f"admin reindex did not succeed: {admin_reindex}")
    if admin_reindex_job.get("type") != "knowledge_document_reindex":
        raise RuntimeError(f"admin reindex job lookup returned unexpected payload: {admin_reindex_job}")
    if admin_document_detail_after_reindex.get("document", {}).get("version_no") != 2:
        raise RuntimeError(
            "admin document detail did not reflect reindex version increment: "
            f"{admin_document_detail_after_reindex}"
        )
    if int(admin_diagnostic.get("coverage", {}).get("candidate_count", 0)) < 1:
        raise RuntimeError(f"admin rag diagnostic returned no candidates: {admin_diagnostic}")
    if int(admin_audit.get("total", 0)) < 2:
        raise RuntimeError(f"admin audit trail returned too few document events: {admin_audit}")
    if int(knowledge_base_audit.get("total", 0)) < 1:
        raise RuntimeError(f"knowledge-base update audit record was not returned: {knowledge_base_audit}")
    if int(snapshot.get("counts", {}).get("knowledgeBases", 0)) < 1:
        raise RuntimeError(f"knowledge snapshot did not include the created knowledge base: {snapshot}")
    if int(snapshot.get("counts", {}).get("documents", 0)) < 1:
        raise RuntimeError(f"knowledge snapshot did not include any documents: {snapshot}")
    if int(snapshot.get("counts", {}).get("knowledgeBases", 0)) != len(snapshot.get("knowledgeBases", [])):
        raise RuntimeError(f"snapshot knowledge-base count drifted from payload rows: {snapshot}")
    if int(snapshot.get("counts", {}).get("documentProfiles", 0)) != len(snapshot.get("documentProfiles", [])):
        raise RuntimeError(f"snapshot document-profile count drifted from payload rows: {snapshot}")
    if len(snapshot.get("recentAuditRecords", [])) < 1:
        raise RuntimeError(f"knowledge snapshot did not include recent audit records: {snapshot}")
    snapshot_knowledge_base = next(
        (
            item
            for item in snapshot.get("knowledgeBases", [])
            if item.get("kb_id") == knowledge_base.get("kb_id")
        ),
        None,
    )
    if snapshot_knowledge_base is None:
        raise RuntimeError(f"snapshot was missing the updated knowledge base row: {snapshot}")
    if snapshot_knowledge_base.get("status") != "disabled":
        raise RuntimeError(f"snapshot knowledge-base status drifted from admin state: {snapshot_knowledge_base}")
    if snapshot_knowledge_base.get("retrieval_mode") != "hybrid-tightened":
        raise RuntimeError(
            f"snapshot knowledge-base retrieval mode drifted from admin state: {snapshot_knowledge_base}"
        )
    snapshot_document_profile = next(
        (
            item
            for item in snapshot.get("documentProfiles", [])
            if item.get("doc_id") == admin_document.get("doc_id")
        ),
        None,
    )
    if snapshot_document_profile is None:
        raise RuntimeError(f"snapshot was missing the admin document profile row: {snapshot}")
    if snapshot_document_profile.get("latest_job_id") != admin_reindex_job.get("job_id"):
        raise RuntimeError(
            "snapshot document profile did not reflect the latest reindex job: "
            f"{snapshot_document_profile}"
        )
    if snapshot_document_profile.get("source_type") != "filesystem":
        raise RuntimeError(
            f"snapshot document profile lost the filesystem source type: {snapshot_document_profile}"
        )
    integrations = snapshot.get("integrations", {})
    for connector_name in (
        "rawStorage",
        "metadataStore",
        "vectorStore",
        "bm25Store",
        "cache",
        "taskQueue",
    ):
        connector = integrations.get(connector_name, {})
        if connector.get("configured") is not True:
            raise RuntimeError(
                f"snapshot connector {connector_name} was not configured in the compose baseline: {snapshot}"
            )
    if integrations.get("rawStorage", {}).get("backend") != "minio-mirror" and integrations.get("rawStorage", {}).get("backend") != "minio":
        raise RuntimeError(f"snapshot raw storage backend was not MinIO-oriented: {snapshot}")
    if integrations.get("metadataStore", {}).get("backend") != "mysql":
        raise RuntimeError(f"snapshot metadata store backend was not MySQL-backed: {snapshot}")
    if integrations.get("vectorStore", {}).get("backend") != "qdrant":
        raise RuntimeError(f"snapshot vector store backend was not Qdrant-backed: {snapshot}")
    if integrations.get("bm25Store", {}).get("backend") != "opensearch":
        raise RuntimeError(f"snapshot BM25 store backend was not OpenSearch-backed: {snapshot}")
    if integrations.get("cache", {}).get("backend") not in {"redis-configured", "redis-ttl"}:
        raise RuntimeError(f"snapshot cache backend was not Redis-oriented: {snapshot}")
    if integrations.get("taskQueue", {}).get("backend") != "redis-list-primary":
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
    if empty_answer.get("citations") != []:
        raise RuntimeError(f"empty-answer path unexpectedly returned citations: {empty_answer}")
    if "没有检索到可引用知识" not in empty_answer.get("answer", ""):
        raise RuntimeError(f"empty-answer path did not return the empty-result guidance: {empty_answer}")

    summary = {
        "bootstrap": bootstrap,
        "filesystemImport": {
            "preview": {
                "matchedFiles": import_preview.get("matchedFiles"),
                "importableFiles": import_preview.get("importableFiles"),
                "importRoot": import_preview.get("importRoot"),
            },
            "result": {
                "processedFiles": file_import.get("processedFiles"),
                "importedFiles": file_import.get("importedFiles"),
                "reusedFiles": file_import.get("reusedFiles"),
                "failedFiles": file_import.get("failedFiles"),
            },
        },
        "documents": {
            "count": len(documents),
            "selectedDocumentId": first_document_id,
            "chunkCount": len(chunks),
        },
        "overview": {
            "counts": overview.get("counts"),
            "topTags": overview.get("topTags"),
            "largestSources": overview.get("largestSources"),
        },
        "snapshot": {
            "exportedAt": snapshot.get("exportedAt"),
            "counts": snapshot.get("counts"),
            "knowledgeBaseCount": len(snapshot.get("knowledgeBases", [])),
            "recentAuditCount": len(snapshot.get("recentAuditRecords", [])),
            "integrations": {
                "pendingEvents": integrations.get("pendingEvents"),
                "eventCounters": integrations.get("eventCounters"),
                "rawStorage": integrations.get("rawStorage", {}).get("backend"),
                "metadataStore": integrations.get("metadataStore", {}).get("backend"),
                "vectorStore": integrations.get("vectorStore", {}).get("backend"),
                "bm25Store": integrations.get("bm25Store", {}).get("backend"),
                "cache": integrations.get("cache", {}).get("backend"),
                "taskQueue": integrations.get("taskQueue", {}).get("backend"),
                "lastProcessedEvent": {
                    "eventId": processed_snapshot_event.get("eventId"),
                    "status": processed_snapshot_event.get("status"),
                    "operation": processed_snapshot_event.get("operation"),
                    "connectorResults": connector_results,
                },
            },
        },
        "search": {
            "queryTokens": search.get("queryTokens"),
            "sourceBreakdown": search.get("sourceBreakdown"),
            "total": search.get("total"),
        },
        "rag": {
            "answerCitations": len(answer.get("citations", [])),
            "emptyAnswer": {
                "degraded": empty_answer.get("degraded"),
                "coverageNotes": empty_answer.get("coverageNotes"),
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
            "spaShell": "<div id=\"root\"></div>",
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
