from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.openapi_contracts import ContractValidationError, OpenApiContract
from scripts.qa.contract_policy import validate_live_response_contract
from scripts.qa.service_matrix import OPENAPI_SPECS, SERVICE_RUNTIMES, SMOKE_SCENARIOS


REQUEST_TIMEOUT = 10.0
WAIT_ATTEMPTS = 60
WAIT_SECONDS = 0.5

STANDARD_HEADERS = (
    "X-Request-Id",
    "X-Trace-Id",
    "X-App-Name",
    "X-Response-Time",
)


@dataclass(frozen=True)
class HttpResult:
    status_code: int
    payload: Any
    headers: dict[str, str]


@dataclass
class ManagedService:
    name: str
    base_url: str
    process: subprocess.Popen[str]
    log_path: Path
    health_path: str
    require_ready: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SmartCloud-X multi-service smoke scenarios.")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=sorted(SMOKE_SCENARIOS),
        help="Run only the named smoke scenario. Defaults to all scenarios.",
    )
    return parser.parse_args()


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def tail_log(path: Path, *, lines: int = 40) -> str:
    if not path.exists():
        return "<missing log>"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def build_request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {
        "Content-Type": "application/json",
        "X-Request-Id": "smartcloud-qa-smoke",
        "X-Trace-Id": "smartcloud-qa-smoke",
        "X-Caller-Service": "smartcloud-qa-smoke",
    }
    if headers:
        request_headers.update(headers)
    return Request(url, data=body, method=method, headers=request_headers)


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> HttpResult:
    req = build_request(method, url, payload=payload, headers=headers)
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else None
            return HttpResult(
                status_code=response.status,
                payload=parsed,
                headers={key: value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        parsed = json.loads(body) if body else None
        return HttpResult(
            status_code=exc.code,
            payload=parsed,
            headers={key: value for key, value in exc.headers.items()},
        )


def request_text(method: str, url: str, *, headers: dict[str, str] | None = None) -> HttpResult:
    req = build_request(method, url, headers=headers)
    try:
        with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            return HttpResult(
                status_code=response.status,
                payload=response.read().decode("utf-8"),
                headers={key: value for key, value in response.headers.items()},
            )
    except HTTPError as exc:
        return HttpResult(
            status_code=exc.code,
            payload=exc.read().decode("utf-8"),
            headers={key: value for key, value in exc.headers.items()},
        )


def assert_standard_headers(result: HttpResult, *, label: str) -> None:
    normalized = {key.lower(): value for key, value in result.headers.items()}
    missing = [header for header in STANDARD_HEADERS if not normalized.get(header.lower())]
    if missing:
        raise RuntimeError(f"{label} missing standard headers: {missing}")


def unwrap_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if "success" in payload:
        if not payload.get("success", False):
            raise RuntimeError(f"request failed: {payload}")
        return payload.get("data")
    if "code" in payload and "data" in payload:
        if int(payload["code"]) != 0:
            raise RuntimeError(f"request failed: {payload}")
        return payload.get("data")
    return payload


def assert_status(result: HttpResult, expected_status: int, *, label: str) -> Any:
    if result.status_code != expected_status:
        raise RuntimeError(
            f"{label} returned unexpected status {result.status_code}, expected {expected_status}: {result.payload}"
        )
    assert_standard_headers(result, label=label)
    return unwrap_payload(result.payload)


def wait_for_health(service: ManagedService) -> None:
    url = f"{service.base_url}{service.health_path}"
    last_error: Exception | None = None
    for _attempt in range(1, WAIT_ATTEMPTS + 1):
        if service.process.poll() is not None:
            raise RuntimeError(
                f"{service.name} exited during startup.\n--- log tail ---\n{tail_log(service.log_path)}"
            )
        try:
            result = request_json("GET", url)
            if result.status_code == 200:
                payload = unwrap_payload(result.payload)
                if not service.require_ready or bool(payload.get("ready")):
                    return
                last_error = RuntimeError(f"{service.name} not ready yet: {payload}")
            else:
                last_error = RuntimeError(f"{service.name} health returned {result.status_code}: {result.payload}")
        except (URLError, RuntimeError) as exc:
            last_error = exc
        time.sleep(WAIT_SECONDS)
    raise RuntimeError(f"{service.name} failed health checks: {last_error}")


def validate_contract(
    contracts: dict[str, OpenApiContract],
    spec_name: str,
    path: str,
    method: str,
    status_code: int,
    payload: Any,
    drift_log: list[dict[str, str]] | None = None,
) -> None:
    drift = validate_live_response_contract(contracts, spec_name, path, method, status_code, payload)
    if drift is not None and drift_log is not None:
        drift_log.append(
            {
                "spec": drift.spec_name,
                "path": drift.path,
                "method": drift.method.upper(),
                "status": str(drift.status_code),
                "changeRequest": drift.change_request,
                "summary": drift.summary,
            }
        )


def build_pythonpath(entries: tuple[Path, ...]) -> str:
    return os.pathsep.join(str(path) for path in entries)


def launch_services(temp_root: Path) -> tuple[dict[str, ManagedService], dict[str, int]]:
    ports = {name: reserve_port() for name in SERVICE_RUNTIMES}
    logs_dir = temp_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    knowledge_root = SERVICE_RUNTIMES["knowledge-service"].cwd
    shared_env = {
        "PYTHONUNBUFFERED": "1",
        "SMARTCLOUD_ENV": "test",
        "APP_ENV": "test",
        "SMARTCLOUD_LOG_LEVEL": "INFO",
        "SMARTCLOUD_JWT_SECRET": "smartcloud-qa-smoke-secret",
        "SMARTCLOUD_AUTH_ISSUER": "smartcloud-qa-smoke",
        "SMARTCLOUD_AUTH_AUDIENCE": "smartcloud-qa-clients",
        "SMARTCLOUD_INTERNAL_AUTH_AUDIENCE": "smartcloud-qa-internal",
        "SMARTCLOUD_REQUEST_TIMEOUT_MS": "10000",
    }
    runtime_env: dict[str, dict[str, str]] = {
        "auth-user-service": {
            "AUTH_USER_SERVICE_DATA_PATH": str(temp_root / "auth-user-service" / "auth-store.json"),
        },
        "marketing-service": {
            "MARKETING_SERVICE_DATA_PATH": str(temp_root / "marketing-service" / "marketing-store.json"),
        },
        "research-service": {
            "RESEARCH_SERVICE_DATA_PATH": str(temp_root / "research-service" / "research-store.json"),
        },
        "knowledge-service": {
            "SMARTCLOUD_KNOWLEDGE_DATA_PATH": str(temp_root / "knowledge-service" / "knowledge-store.json"),
            "SMARTCLOUD_KNOWLEDGE_AUDIT_PATH": str(
                temp_root / "knowledge-service" / "knowledge-admin-audit.jsonl"
            ),
            "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH": str(knowledge_root / "data" / "starter-catalog.json"),
            "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT": str(knowledge_root / "data" / "imports"),
        },
        "rag-service": {
            "KNOWLEDGE_SERVICE_BASE_URL": f"http://127.0.0.1:{ports['knowledge-service']}",
        },
        "business-tools-service": {
            "APP_PORT": str(ports["business-tools-service"]),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(
                temp_root / "business-tools-service" / "idempotency-store.json"
            ),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(
                temp_root / "business-tools-service" / "query-cache-store.json"
            ),
        },
        "tool-hub-service": {
            "APP_PORT": str(ports["tool-hub-service"]),
            "BUSINESS_TOOLS_TRANSPORT": "http",
            "BUSINESS_TOOLS_URL": f"http://127.0.0.1:{ports['business-tools-service']}",
            "AUDIT_STORE_PATH": str(temp_root / "tool-hub-service" / "audit-store.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(
                temp_root / "tool-hub-service" / "local-idempotency-store.json"
            ),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(
                temp_root / "tool-hub-service" / "local-query-cache-store.json"
            ),
        },
        "orchestrator-service": {
            "APP_PORT": str(ports["orchestrator-service"]),
            "TOOL_HUB_TRANSPORT": "http",
            "MCP_GATEWAY_URL": f"http://127.0.0.1:{ports['tool-hub-service']}",
            "CONVERSATION_STORE_PATH": str(temp_root / "orchestrator-service" / "conversation-store.json"),
            "STATE_STORE_PATH": str(temp_root / "orchestrator-service" / "state-store.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(
                temp_root / "orchestrator-service" / "local-idempotency-store.json"
            ),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(
                temp_root / "orchestrator-service" / "local-query-cache-store.json"
            ),
        },
    }

    order = (
        "business-tools-service",
        "tool-hub-service",
        "knowledge-service",
        "rag-service",
        "auth-user-service",
        "marketing-service",
        "research-service",
        "orchestrator-service",
    )
    services: dict[str, ManagedService] = {}
    for name in order:
        runtime = SERVICE_RUNTIMES[name]
        log_path = logs_dir / f"{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(shared_env)
        env.update(runtime_env.get(name, {}))
        env["PYTHONPATH"] = build_pythonpath(runtime.pythonpath)
        log_handle = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                runtime.module,
                "--host",
                "127.0.0.1",
                "--port",
                str(ports[name]),
            ],
            cwd=runtime.cwd,
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        services[name] = ManagedService(
            name=name,
            base_url=f"http://127.0.0.1:{ports[name]}",
            process=process,
            log_path=log_path,
            health_path=runtime.health_path,
            require_ready=runtime.require_ready,
        )

    for name in order:
        wait_for_health(services[name])
    return services, ports


def stop_services(services: dict[str, ManagedService]) -> None:
    for service in reversed(list(services.values())):
        if service.process.poll() is None:
            service.process.terminate()
    deadline = time.time() + 10
    for service in reversed(list(services.values())):
        if service.process.poll() is None:
            timeout = max(0.1, deadline - time.time())
            try:
                service.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                service.process.kill()
                service.process.wait(timeout=5)


def smoke_auth_marketing_research(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
) -> dict[str, Any]:
    auth_url = services["auth-user-service"].base_url
    marketing_url = services["marketing-service"].base_url
    research_url = services["research-service"].base_url

    documented_drifts: list[dict[str, str]] = []
    login = request_json(
        "POST",
        f"{auth_url}/api/v1/auth/login",
        payload={
            "login_type": "password",
            "account": "demo@smartcloud.local",
            "password": "Password123!",
        },
    )
    login_data = assert_status(login, 200, label="auth login")
    validate_contract(
        contracts,
        "auth-user-service",
        "/api/v1/auth/login",
        "post",
        200,
        login.payload,
        drift_log=documented_drifts,
    )
    access_token = login_data["access_token"]

    auth_headers = {"Authorization": f"Bearer {access_token}"}

    me = request_json("GET", f"{auth_url}/api/v1/auth/me", headers=auth_headers)
    me_data = assert_status(me, 200, label="auth me")
    validate_contract(
        contracts,
        "auth-user-service",
        "/api/v1/auth/me",
        "get",
        200,
        me.payload,
        drift_log=documented_drifts,
    )

    campaigns = request_json(
        "GET",
        f"{marketing_url}/api/v1/marketing/campaigns?{urlencode({'page': 1, 'page_size': 20})}",
        headers=auth_headers,
    )
    campaigns_data = assert_status(campaigns, 200, label="marketing campaigns")
    validate_contract(
        contracts,
        "marketing-service",
        "/api/v1/marketing/campaigns",
        "get",
        200,
        campaigns.payload,
    )
    first_campaign = campaigns_data["items"][0]

    copy = request_json(
        "POST",
        f"{marketing_url}/api/v1/marketing/copy/generate",
        headers=auth_headers,
        payload={
            "campaign_id": first_campaign["campaign_id"],
            "topic": "AI算力起量",
            "audience": "AI创业团队",
            "tone": "launch",
            "keywords": ["AI算力", "弹性扩容"],
        },
    )
    copy_data = assert_status(copy, 200, label="marketing copy generate")
    validate_contract(
        contracts,
        "marketing-service",
        "/api/v1/marketing/copy/generate",
        "post",
        200,
        copy.payload,
    )

    promotion_link = request_json(
        "POST",
        f"{marketing_url}/api/v1/marketing/promotion-links/generate",
        headers=auth_headers,
        payload={
            "campaign_id": first_campaign["campaign_id"],
            "channel": "wechat",
            "source": "social",
            "content_tag": "hero-banner",
        },
    )
    promotion_data = assert_status(promotion_link, 200, label="marketing promotion link")

    poster = request_json(
        "POST",
        f"{marketing_url}/api/v1/marketing/posters",
        headers={**auth_headers, "Idempotency-Key": "qa-smoke-poster-001"},
        payload={
            "campaign_id": first_campaign["campaign_id"],
            "theme": "新品首发",
            "slogan": "AI算力一键起飞",
            "size": "1024x1536",
        },
    )
    poster_data = assert_status(poster, 202, label="marketing poster create")
    validate_contract(
        contracts,
        "marketing-service",
        "/api/v1/marketing/posters",
        "post",
        202,
        poster.payload,
    )

    poster_detail = request_json(
        "GET",
        f"{marketing_url}/api/v1/marketing/posters/{poster_data['task_id']}",
        headers=auth_headers,
    )
    poster_detail_data = assert_status(poster_detail, 200, label="marketing poster detail")

    research_task = request_json(
        "POST",
        f"{research_url}/api/v1/research/tasks",
        headers={**auth_headers, "Idempotency-Key": "qa-smoke-research-001"},
        payload={
            "topic": "LangGraph vs CrewAI",
            "scope": "客服编排能力对比",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": ["https://docs.langchain.com/oss/python/langgraph/overview"],
        },
    )
    research_data = assert_status(research_task, 202, label="research task create")
    validate_contract(
        contracts,
        "research-service",
        "/api/v1/research/tasks",
        "post",
        202,
        research_task.payload,
    )

    research_detail = request_json(
        "GET",
        f"{research_url}/api/v1/research/tasks/{research_data['task_id']}",
        headers=auth_headers,
    )
    research_detail_data = assert_status(research_detail, 200, label="research task detail")
    validate_contract(
        contracts,
        "research-service",
        "/api/v1/research/tasks/{task_id}",
        "get",
        200,
        research_detail.payload,
    )

    return {
        "documentedContractDrifts": documented_drifts,
        "login": {"userId": me_data["user_id"], "tenantId": me_data["tenant_id"]},
        "marketing": {
            "campaignId": first_campaign["campaign_id"],
            "copyHeadline": copy_data["headline"],
            "posterTaskId": poster_data["task_id"],
            "posterStatus": poster_detail_data["status"],
            "promotionShortUrl": promotion_data["short_url"],
        },
        "research": {
            "taskId": research_data["task_id"],
            "status": research_detail_data["status"],
            "reportFileId": research_detail_data["report_file_id"],
        },
    }


def smoke_knowledge_rag_admin(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
) -> dict[str, Any]:
    knowledge_url = services["knowledge-service"].base_url
    rag_url = services["rag-service"].base_url

    documented_drifts: list[dict[str, str]] = []
    bootstrap = request_json("POST", f"{knowledge_url}/api/knowledge/v1/catalog:bootstrap")
    bootstrap_data = assert_status(bootstrap, 200, label="knowledge bootstrap")
    validate_contract(
        contracts,
        "knowledge-service",
        "/api/knowledge/v1/catalog:bootstrap",
        "post",
        200,
        bootstrap.payload,
        drift_log=documented_drifts,
    )

    import_preview = request_json(
        "GET",
        f"{knowledge_url}/api/knowledge/v1/imports:preview?"
        f"{urlencode({'directory': 'starter', 'glob': '**/*', 'maxFiles': 10})}",
    )
    import_preview_data = assert_status(import_preview, 200, label="knowledge import preview")

    file_import = request_json(
        "POST",
        f"{knowledge_url}/api/knowledge/v1/files:ingest",
        payload={
            "directory": "starter",
            "glob": "**/*",
            "maxFiles": 10,
            "source": {"name": "QA Smoke Import", "kind": "manual", "tags": ["filesystem", "starter"]},
            "tags": ["filesystem", "starter"],
        },
    )
    file_import_data = assert_status(file_import, 201, label="knowledge file ingest")

    search = request_json(
        "POST",
        f"{knowledge_url}/api/knowledge/v1/search",
        payload={"query": "GPU部署前需要确认什么", "topK": 3, "tags": ["gpu", "launch"]},
    )
    search_data = assert_status(search, 200, label="knowledge search")
    validate_contract(
        contracts,
        "knowledge-service",
        "/api/knowledge/v1/search",
        "post",
        200,
        search.payload,
        drift_log=documented_drifts,
    )

    kb_code = f"qa-smoke-{int(time.time())}"
    knowledge_base = request_json(
        "POST",
        f"{knowledge_url}/api/v1/admin/knowledge-bases",
        headers={"X-Operator-Reason": "qa smoke create kb"},
        payload={
            "name": "QA Smoke KB",
            "code": kb_code,
            "scene": "product",
            "language": "zh-CN",
            "retrieval_mode": "hybrid-baseline",
            "embedding_model": "baseline-keyword",
            "description": "QA smoke validation knowledge base.",
        },
    )
    knowledge_base_data = assert_status(knowledge_base, 201, label="admin create knowledge base")
    validate_contract(
        contracts,
        "admin-api",
        "/api/v1/admin/knowledge-bases",
        "post",
        201,
        knowledge_base.payload,
        drift_log=documented_drifts,
    )

    admin_document = request_json(
        "POST",
        f"{knowledge_url}/api/v1/admin/knowledge-bases/{knowledge_base_data['kb_id']}/documents",
        headers={"X-Operator-Reason": "qa smoke ingest doc"},
        payload={
            "file_id": "starter/gpu-release-checklist.md",
            "title": "GPU Release Checklist",
            "tags": ["gpu", "admin"],
            "source_type": "filesystem",
        },
    )
    admin_document_data = assert_status(admin_document, 202, label="admin create document")

    document_detail = request_json(
        "GET",
        f"{knowledge_url}/api/v1/admin/knowledge-documents/{admin_document_data['doc_id']}",
    )
    document_detail_data = assert_status(document_detail, 200, label="admin document detail")
    validate_contract(
        contracts,
        "admin-api",
        "/api/v1/admin/knowledge-documents/{doc_id}",
        "get",
        200,
        document_detail.payload,
        drift_log=documented_drifts,
    )

    job_detail = request_json(
        "GET",
        f"{knowledge_url}/api/v1/admin/jobs/{document_detail_data['chunk_stats']['latest_job_id']}",
    )
    job_detail_data = assert_status(job_detail, 200, label="admin job detail")

    admin_reindex = request_json(
        "POST",
        f"{knowledge_url}/api/v1/admin/knowledge-documents/{admin_document_data['doc_id']}/reindex",
        headers={"X-Operator-Reason": "qa smoke reindex"},
        payload={
            "force": True,
            "confirm_token": f"reindex:{admin_document_data['doc_id']}",
        },
    )
    admin_reindex_data = assert_status(admin_reindex, 202, label="admin reindex")

    rag_diagnose = request_json(
        "POST",
        f"{rag_url}/api/rag/v1/diagnose",
        payload={"query": "GPU部署前需要确认什么", "topK": 3, "filters": {"tags": ["gpu", "launch"]}},
    )
    rag_diagnose_data = assert_status(rag_diagnose, 200, label="rag diagnose")
    validate_contract(
        contracts,
        "rag-service",
        "/api/rag/v1/diagnose",
        "post",
        200,
        rag_diagnose.payload,
        drift_log=documented_drifts,
    )

    rag_answer = request_json(
        "POST",
        f"{rag_url}/api/rag/v1/answer",
        payload={
            "query": "GPU部署前需要确认什么",
            "topK": 3,
            "style": "brief",
            "filters": {"tags": ["gpu", "launch"]},
        },
    )
    rag_answer_data = assert_status(rag_answer, 200, label="rag answer")
    validate_contract(
        contracts,
        "rag-service",
        "/api/rag/v1/answer",
        "post",
        200,
        rag_answer.payload,
        drift_log=documented_drifts,
    )

    admin_diagnostics = request_json(
        "POST",
        f"{rag_url}/api/v1/admin/retrieval/diagnostics",
        payload={
            "query": "GPU部署前需要确认什么",
            "kb_id": knowledge_base_data["kb_id"],
            "top_k": 3,
            "include_citations": True,
        },
    )
    admin_diagnostics_data = assert_status(admin_diagnostics, 200, label="admin rag diagnostics")
    validate_contract(
        contracts,
        "admin-api",
        "/api/v1/admin/retrieval/diagnostics",
        "post",
        200,
        admin_diagnostics.payload,
        drift_log=documented_drifts,
    )

    knowledge_metrics = request_text("GET", f"{knowledge_url}/metrics")
    assert_status(knowledge_metrics, 200, label="knowledge metrics")
    rag_metrics = request_text("GET", f"{rag_url}/metrics")
    assert_status(rag_metrics, 200, label="rag metrics")

    if int(import_preview_data.get("matchedFiles", 0)) < 1:
        raise RuntimeError(f"knowledge import preview returned no files: {import_preview_data}")
    if int(file_import_data.get("importedFiles", 0)) + int(file_import_data.get("reusedFiles", 0)) < 1:
        raise RuntimeError(f"knowledge file ingest did not process files: {file_import_data}")
    if int(search_data.get("total", 0)) < 1:
        raise RuntimeError(f"knowledge search returned no hits: {search_data}")
    if int(rag_diagnose_data.get("candidateCount", 0)) < 1:
        raise RuntimeError(f"rag diagnose returned no candidates: {rag_diagnose_data}")
    if int(admin_diagnostics_data.get("coverage", {}).get("candidate_count", 0)) < 1:
        raise RuntimeError(f"admin rag diagnostics returned no candidates: {admin_diagnostics_data}")
    if "knowledge_readiness_state" not in str(knowledge_metrics.payload):
        raise RuntimeError("knowledge metrics did not expose readiness gauges")
    if "rag_upstream_ready_state" not in str(rag_metrics.payload):
        raise RuntimeError("rag metrics did not expose upstream readiness gauges")

    return {
        "documentedContractDrifts": documented_drifts,
        "knowledge": {
            "bootstrap": bootstrap_data,
            "kbId": knowledge_base_data["kb_id"],
            "docId": admin_document_data["doc_id"],
            "createJobId": job_detail_data["job_id"],
            "reindexJobId": admin_reindex_data["job_id"],
            "searchTotal": search_data["total"],
        },
        "rag": {
            "candidateCount": rag_diagnose_data["candidateCount"],
            "answerPreview": rag_answer_data["answer"],
            "adminCandidateCount": admin_diagnostics_data["coverage"]["candidate_count"],
        },
    }


def smoke_business_tools_tool_hub(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
) -> dict[str, Any]:
    business_tools_url = services["business-tools-service"].base_url
    tool_hub_url = services["tool-hub-service"].base_url

    documented_drifts: list[dict[str, str]] = []
    implementation_drifts: list[dict[str, str]] = []
    internal_headers = {"X-Caller-Service": "tool-hub-service"}
    tool_hub_internal_headers = {"X-Caller-Service": "orchestrator-service"}
    descriptor = request_json(
        "GET",
        f"{business_tools_url}/internal/v1/tools/billing.query_statement",
        headers=internal_headers,
    )
    descriptor_data = assert_status(descriptor, 200, label="business tools descriptor")
    validate_contract(
        contracts,
        "business-tools-service",
        "/internal/v1/tools/{tool_name}",
        "get",
        200,
        descriptor.payload,
        drift_log=documented_drifts,
    )

    preflight = request_json(
        "POST",
        f"{business_tools_url}/internal/v1/preflight/order.create_refund",
        headers=internal_headers,
        payload={
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "subject": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "tenant_id": "tenant-a",
                "permissions": ["user:order.read"],
            },
            "operation": "execute",
            "payload": {"reason": "误购"},
        },
    )
    preflight_data = assert_status(preflight, 200, label="business tools preflight")
    validate_contract(
        contracts,
        "business-tools-service",
        "/internal/v1/preflight/{tool_name}",
        "post",
        200,
        preflight.payload,
        drift_log=documented_drifts,
    )

    tool_list = request_json("GET", f"{tool_hub_url}/api/v1/tools")
    tool_list_data = assert_status(tool_list, 200, label="tool hub list")
    validate_contract(
        contracts,
        "tool-hub-service",
        "/api/v1/tools",
        "get",
        200,
        tool_list.payload,
        drift_log=documented_drifts,
    )

    tool_preflight_request = {
        "trace_id": "qa-th-preflight-1",
        "conversation_id": "conv-th-preflight-1",
        "tool_call_id": "tc-th-preflight-1",
        "tool_name": "order.create_refund",
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "user_context": {
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:order.read"],
        },
        "payload": {"reason": "误购"},
        "idempotency_key": "qa-th-preflight-1",
        "operation": "execute",
    }
    tool_preflight = request_json(
        "POST",
        f"{tool_hub_url}/api/v1/tools/preflight",
        payload=tool_preflight_request,
    )
    if tool_preflight.status_code in {404, 405}:
        implementation_drifts.append(
            {
                "route": "/api/v1/tools/preflight",
                "fallbackRoute": "/internal/v1/tools/preflight",
                "status": str(tool_preflight.status_code),
                "summary": "Frozen public tool-hub preflight route is not implemented; smoke used the internal route instead.",
            }
        )
        tool_preflight = request_json(
            "POST",
            f"{tool_hub_url}/internal/v1/tools/preflight",
            headers=tool_hub_internal_headers,
            payload=tool_preflight_request,
        )
    tool_preflight_data = assert_status(tool_preflight, 200, label="tool hub preflight")
    validate_contract(
        contracts,
        "tool-hub-service",
        "/api/v1/tools/preflight",
        "post",
        200,
        tool_preflight.payload,
        drift_log=documented_drifts,
    )

    tool_call_request = {
        "trace_id": "qa-th-call-1",
        "conversation_id": "conv-th-call-1",
        "tool_call_id": "tc-th-call-1",
        "tool_name": "billing.query_statement",
        "operator": {"type": "agent", "id": "Finance_Order_Agent"},
        "user_context": {
            "user_id": "u-1",
            "account_id": "acct-1",
            "permissions": ["user:billing.read"],
        },
        "payload": {"range": "this_month"},
        "idempotency_key": "qa-th-call-1",
        "operation": "execute",
    }
    tool_call = request_json(
        "POST",
        f"{tool_hub_url}/api/v1/tools/call",
        payload=tool_call_request,
    )
    if tool_call.status_code in {404, 405}:
        implementation_drifts.append(
            {
                "route": "/api/v1/tools/call",
                "fallbackRoute": "/internal/v1/tools/call",
                "status": str(tool_call.status_code),
                "summary": "Frozen public tool-hub call route is not implemented; smoke used the internal route instead.",
            }
        )
        tool_call = request_json(
            "POST",
            f"{tool_hub_url}/internal/v1/tools/call",
            headers=tool_hub_internal_headers,
            payload=tool_call_request,
        )
    tool_call_data = assert_status(tool_call, 200, label="tool hub call")
    validate_contract(
        contracts,
        "tool-hub-service",
        "/api/v1/tools/call",
        "post",
        200,
        tool_call.payload,
        drift_log=documented_drifts,
    )

    direct_invoke = request_json(
        "POST",
        f"{tool_hub_url}/api/v1/tools/billing.query_statement/invoke",
        payload={
            "operation": "execute",
            "payload": {"range": "this_month"},
            "context": {
                "request_id": "qa-th-invoke-1",
                "trace_id": "qa-th-invoke-1",
                "conversation_id": "conv-th-invoke-1",
                "tenant_id": "tenant-a",
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
                "operator_type": "agent",
                "operator_id": "Finance_Order_Agent",
            },
        },
    )
    direct_invoke_data = assert_status(direct_invoke, 200, label="tool hub direct invoke")
    validate_contract(
        contracts,
        "tool-hub-service",
        "/api/v1/tools/{tool_name}/invoke",
        "post",
        200,
        direct_invoke.payload,
        drift_log=documented_drifts,
    )

    audit_records = request_json(
        "GET",
        f"{tool_hub_url}/api/v1/tool-calls?{urlencode({'conversation_id': 'conv-th-call-1'})}",
    )
    audit_records_data = assert_status(audit_records, 200, label="tool hub audit list")
    validate_contract(
        contracts,
        "tool-hub-service",
        "/api/v1/tool-calls",
        "get",
        200,
        audit_records.payload,
        drift_log=documented_drifts,
    )

    if tool_preflight_data["status"] != "missing-payload":
        raise RuntimeError(f"expected tool-hub preflight missing-payload status: {tool_preflight_data}")
    if tool_call_data["status"] != "completed":
        raise RuntimeError(f"expected tool-hub call completion: {tool_call_data}")
    if direct_invoke_data["status"] != "completed":
        raise RuntimeError(f"expected tool-hub direct invoke completion: {direct_invoke_data}")
    if int(audit_records_data.get("total", 0)) < 1:
        raise RuntimeError(f"expected at least one tool-call audit record: {audit_records_data}")

    return {
        "documentedContractDrifts": documented_drifts,
        "implementationDrifts": implementation_drifts,
        "businessTools": {
            "descriptorName": descriptor_data["name"],
            "preflightStatus": preflight_data["status"],
        },
        "toolHub": {
            "toolCount": len(tool_list_data["items"]),
            "callSummary": tool_call_data["summary"],
            "invokeSummary": direct_invoke_data["summary"],
            "auditTotal": audit_records_data["total"],
        },
    }


def smoke_orchestrator_billing(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
) -> dict[str, Any]:
    orchestrator_url = services["orchestrator-service"].base_url

    documented_drifts: list[dict[str, str]] = []
    created = request_json(
        "POST",
        f"{orchestrator_url}/api/v1/chat/sessions",
        payload={"scene": "billing", "title": "QA smoke billing"},
    )
    created_data = assert_status(created, 200, label="orchestrator create session")
    validate_contract(
        contracts,
        "orchestrator-service",
        "/api/v1/chat/sessions",
        "post",
        200,
        created.payload,
        drift_log=documented_drifts,
    )
    conversation_id = created_data["conversation_id"]

    first_completion = request_json(
        "POST",
        f"{orchestrator_url}/api/v1/chat/completions",
        payload={
            "conversation_id": conversation_id,
            "message_id": "qa-orch-msg-1",
            "user_input": "帮我查本月账单",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
        },
    )
    first_completion_data = assert_status(first_completion, 200, label="orchestrator first completion")
    validate_contract(
        contracts,
        "orchestrator-service",
        "/api/v1/chat/completions",
        "post",
        200,
        first_completion.payload,
        drift_log=documented_drifts,
    )

    second_completion = request_json(
        "POST",
        f"{orchestrator_url}/api/v1/chat/completions",
        payload={
            "conversation_id": conversation_id,
            "message_id": "qa-orch-msg-2",
            "user_input": "继续帮我开票",
            "scene": "billing",
            "user_profile": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "session_context": {
                "confirmed_tool_names": ["billing.create_invoice"],
                "attributes": {
                    "invoice_type": "vat_special",
                    "invoice_title": "甲公司",
                },
            },
        },
    )
    second_completion_data = assert_status(second_completion, 200, label="orchestrator second completion")
    validate_contract(
        contracts,
        "orchestrator-service",
        "/api/v1/chat/completions",
        "post",
        200,
        second_completion.payload,
        drift_log=documented_drifts,
    )

    state = request_json(
        "GET",
        f"{orchestrator_url}/api/v1/sessions/{conversation_id}/state",
    )
    state_data = assert_status(state, 200, label="orchestrator state")
    validate_contract(
        contracts,
        "orchestrator-service",
        "/api/v1/sessions/{conversation_id}/state",
        "get",
        200,
        state.payload,
        drift_log=documented_drifts,
    )

    response_data = first_completion_data["response"]
    followup_data = second_completion_data["response"]
    if response_data["state_snapshot"]["session_context"]["attributes"]["statement_no"] != "stmt_2026_04_001":
        raise RuntimeError(f"unexpected persisted billing context: {response_data}")
    if followup_data["executions"][0]["tool_calls"][0]["tool_name"] != "billing.create_invoice":
        raise RuntimeError(f"orchestrator did not execute invoice tool: {followup_data}")
    if not followup_data["state_snapshot"]["session_context"]["attributes"]["invoice_no"].startswith("inv_"):
        raise RuntimeError(f"orchestrator did not persist invoice context: {followup_data}")
    if int(state_data.get("version", 0)) < 2:
        raise RuntimeError(f"orchestrator state version did not advance: {state_data}")

    return {
        "documentedContractDrifts": documented_drifts,
        "conversationId": conversation_id,
        "firstTool": first_completion_data["tool_calls"][0]["tool_name"],
        "secondTool": followup_data["executions"][0]["tool_calls"][0]["tool_name"],
        "invoiceNo": followup_data["state_snapshot"]["session_context"]["attributes"]["invoice_no"],
        "stateVersion": state_data["version"],
    }


def main() -> int:
    args = parse_args()
    selected = tuple(args.scenario or SMOKE_SCENARIOS.keys())
    temp_root = Path(tempfile.mkdtemp(prefix="smartcloud-qa-smoke-"))
    contracts = {name: OpenApiContract(spec.path) for name, spec in OPENAPI_SPECS.items()}
    services: dict[str, ManagedService] = {}

    try:
        services, ports = launch_services(temp_root)
        summary: dict[str, Any] = {
            "ok": True,
            "tempRoot": str(temp_root),
            "ports": ports,
            "scenarios": {},
            "logs": {name: str(service.log_path) for name, service in services.items()},
        }
        if "auth-marketing-research" in selected:
            summary["scenarios"]["auth-marketing-research"] = smoke_auth_marketing_research(services, contracts)
        if "knowledge-rag-admin" in selected:
            summary["scenarios"]["knowledge-rag-admin"] = smoke_knowledge_rag_admin(services, contracts)
        if "business-tools-tool-hub" in selected:
            summary["scenarios"]["business-tools-tool-hub"] = smoke_business_tools_tool_hub(services, contracts)
        if "orchestrator-billing" in selected:
            summary["scenarios"]["orchestrator-billing"] = smoke_orchestrator_billing(services, contracts)

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if services:
            stop_services(services)


if __name__ == "__main__":
    raise SystemExit(main())
