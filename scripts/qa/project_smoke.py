from __future__ import annotations

import argparse
import io
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urlencode, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.qa.openapi_contracts import ContractValidationError, OpenApiContract
from scripts.qa.contract_policy import validate_live_response_contract
from scripts.qa.service_matrix import OPENAPI_SPECS, SERVICE_RUNTIMES, SMOKE_SCENARIOS

DIRECT_HTTP = build_opener(ProxyHandler({}))

try:  # pragma: no cover - optional QA runtime dependency
    from minio import Minio
except Exception:  # pragma: no cover - exercised on lean runners
    Minio = None

try:  # pragma: no cover - optional QA runtime dependency
    import pymysql
    from pymysql.cursors import DictCursor
except Exception:  # pragma: no cover - exercised on lean runners
    pymysql = None
    DictCursor = None

try:  # pragma: no cover - optional QA runtime dependency
    import redis as redis_module
except Exception:  # pragma: no cover - exercised on lean runners
    redis_module = None


REQUEST_TIMEOUT = float(os.getenv("SMARTCLOUD_QA_REQUEST_TIMEOUT_SECONDS", "10"))
WAIT_ATTEMPTS = 60
WAIT_SECONDS = 0.5
SCENARIO_SERVICE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "auth-marketing-research": (
        "auth-user-service",
        "marketing-service",
        "research-service",
    ),
    "knowledge-rag-admin": (
        "knowledge-service",
        "rag-service",
    ),
    "business-tools-tool-hub": (
        "business-tools-service",
        "tool-hub-service",
    ),
    "orchestrator-billing": (
        "business-tools-service",
        "tool-hub-service",
        "orchestrator-service",
    ),
}

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
    port: int
    module: str
    cwd: Path
    env: dict[str, str]
    health_path: str
    require_ready: bool


@dataclass
class TimeoutProbeServer:
    base_url: str
    server: ThreadingHTTPServer
    thread: threading.Thread


@dataclass(frozen=True)
class BackendMode:
    live_infra: bool
    mysql_dsn: str | None
    knowledge_redis_url: str | None
    rag_redis_url: str | None
    business_tools_redis_url: str | None
    tool_hub_redis_url: str | None
    orchestrator_redis_url: str | None
    minio_endpoint: str | None
    minio_bucket: str | None
    minio_access_key: str | None
    minio_secret_key: str | None
    qdrant_url: str | None
    opensearch_url: str | None


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _redis_url_with_db(redis_url: str | None, database: int) -> str | None:
    if not redis_url:
        return None
    parsed = urlparse(redis_url)
    path = f"/{int(database)}"
    query = parsed.query
    fragment = parsed.fragment
    rebuilt = ParseResult(
        scheme=parsed.scheme or "redis",
        netloc=parsed.netloc,
        path=path,
        params=parsed.params,
        query=query,
        fragment=fragment,
    )
    return rebuilt.geturl()


def resolve_backend_mode() -> BackendMode:
    live_infra = _env_flag("SMARTCLOUD_QA_USE_LIVE_INFRA")
    mysql_dsn = os.getenv("SMARTCLOUD_QA_SHARED_MYSQL_DSN") if live_infra else None
    shared_redis_url = os.getenv("SMARTCLOUD_QA_SHARED_REDIS_URL") if live_infra else None
    shared_rag_redis_url = (
        os.getenv("SMARTCLOUD_QA_SHARED_RAG_REDIS_URL") if live_infra else None
    ) or shared_redis_url
    return BackendMode(
        live_infra=live_infra,
        mysql_dsn=mysql_dsn,
        knowledge_redis_url=_redis_url_with_db(shared_redis_url, 0) if live_infra else None,
        rag_redis_url=_redis_url_with_db(shared_rag_redis_url, 1) if live_infra else None,
        business_tools_redis_url=_redis_url_with_db(shared_redis_url, 2) if live_infra else None,
        tool_hub_redis_url=_redis_url_with_db(shared_redis_url, 3) if live_infra else None,
        orchestrator_redis_url=_redis_url_with_db(shared_redis_url, 4) if live_infra else None,
        minio_endpoint=os.getenv("SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT") if live_infra else None,
        minio_bucket=os.getenv("SMARTCLOUD_QA_SHARED_MINIO_BUCKET") if live_infra else None,
        minio_access_key=os.getenv("SMARTCLOUD_QA_SHARED_MINIO_ACCESS_KEY") if live_infra else None,
        minio_secret_key=os.getenv("SMARTCLOUD_QA_SHARED_MINIO_SECRET_KEY") if live_infra else None,
        qdrant_url=os.getenv("SMARTCLOUD_QA_SHARED_QDRANT_URL") if live_infra else None,
        opensearch_url=os.getenv("SMARTCLOUD_QA_SHARED_OPENSEARCH_URL") if live_infra else None,
    )


def _copy_bootstrap(rel_path: str, destination: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / rel_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def _sqlite_row_exists(db_path: Path, table_name: str, column_name: str, value: str) -> bool:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            f"SELECT 1 FROM {table_name} WHERE {column_name} = ? LIMIT 1",
            (value,),
        ).fetchone()
    return row is not None


def _mysql_row_exists(mysql_dsn: str, table_name: str, column_name: str, value: str) -> bool:
    if pymysql is None or DictCursor is None:
        raise RuntimeError(
            "live shared-backend QA requires pymysql in the selected runtime"
        )
    parsed = urlparse(mysql_dsn.replace("mysql+pymysql://", "mysql://", 1))
    connection = pymysql.connect(  # type: ignore[union-attr]
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        user=parsed.username or "",
        password=parsed.password or "",
        database=parsed.path.lstrip("/") or None,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT 1 AS present FROM `{table_name}` WHERE `{column_name}` = %s LIMIT 1",
                (value,),
            )
            row = cursor.fetchone()
    finally:
        connection.close()
    return row is not None


def _redis_keys(redis_url: str | None, pattern: str) -> list[str]:
    if not redis_url:
        return []
    if redis_module is None:
        raise RuntimeError("live shared-backend QA requires redis in the selected runtime")
    client = redis_module.from_url(  # type: ignore[union-attr]
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        return sorted(str(key) for key in client.scan_iter(match=pattern))
    finally:
        try:
            client.close()
        except Exception:
            pass


def _minio_object_exists(
    *,
    endpoint: str | None,
    bucket: str | None,
    access_key: str | None,
    secret_key: str | None,
    object_name: str,
) -> bool:
    if not endpoint or not bucket or not access_key or not secret_key:
        return False
    if Minio is None:
        raise RuntimeError("live shared-backend QA requires minio in the selected runtime")
    parsed = urlparse(endpoint)
    client = Minio(
        parsed.netloc or parsed.path,
        access_key=access_key,
        secret_key=secret_key,
        secure=(parsed.scheme or "https") == "https",
    )
    try:
        client.stat_object(bucket, object_name)
        return True
    except Exception:
        return False


def _minio_put_text_object(
    *,
    endpoint: str | None,
    bucket: str | None,
    access_key: str | None,
    secret_key: str | None,
    object_name: str,
    content: str,
) -> None:
    if not endpoint or not bucket or not access_key or not secret_key:
        raise RuntimeError("live shared-backend QA requires MinIO endpoint, bucket, and credentials")
    if Minio is None:
        raise RuntimeError("live shared-backend QA requires minio in the selected runtime")
    parsed = urlparse(endpoint)
    client = Minio(
        parsed.netloc or parsed.path,
        access_key=access_key,
        secret_key=secret_key,
        secure=(parsed.scheme or "https") == "https",
    )
    payload = content.encode("utf-8")
    client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type="text/markdown; charset=utf-8",
    )


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


def start_business_tools_timeout_probe(
    *,
    descriptor_payload: dict[str, Any],
    preflight_payload: dict[str, Any],
) -> TimeoutProbeServer:
    timeout_ms = int(descriptor_payload.get("timeout_ms") or 5000)
    delay_seconds = max((timeout_ms / 1000) + 1.5, 2.5)
    descriptor_body = json.dumps(descriptor_payload, ensure_ascii=False).encode("utf-8")
    preflight_body = json.dumps(preflight_payload, ensure_ascii=False).encode("utf-8")
    timeout_body = json.dumps(
        {
            "success": False,
            "code": 5003002,
            "message": "timeout probe should have timed out before this fallback payload",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    class _TimeoutProbeHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A003
            return

        def _read_body(self) -> bytes:
            raw_length = self.headers.get("Content-Length", "0")
            content_length = int(raw_length) if raw_length.isdigit() else 0
            if content_length <= 0:
                return b""
            return self.rfile.read(content_length)

        def _write_json(self, status_code: int, body: bytes) -> None:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/internal/v1/tools/billing.query_statement":
                self._write_json(200, descriptor_body)
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            self._read_body()
            if self.path == "/internal/v1/preflight/billing.query_statement":
                self._write_json(200, preflight_body)
                return
            if self.path == "/internal/v1/execute/billing.query_statement":
                time.sleep(delay_seconds)
                self._write_json(200, timeout_body)
                return
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _TimeoutProbeHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="smartcloud-qa-timeout-probe",
        daemon=True,
    )
    thread.start()
    host, port = server.server_address[:2]
    return TimeoutProbeServer(
        base_url=f"http://{host}:{port}",
        server=server,
        thread=thread,
    )


def stop_timeout_probe_server(probe: TimeoutProbeServer | None) -> None:
    if probe is None:
        return
    probe.server.shutdown()
    probe.server.server_close()
    probe.thread.join(timeout=5)


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
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Request:
    body = raw_body if raw_body is not None else (None if payload is None else json.dumps(payload).encode("utf-8"))
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
    raw_body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> HttpResult:
    req = build_request(method, url, payload=payload, raw_body=raw_body, headers=headers)
    try:
        with DIRECT_HTTP.open(req, timeout=REQUEST_TIMEOUT) as response:
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
        with DIRECT_HTTP.open(req, timeout=REQUEST_TIMEOUT) as response:
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
        is_enveloped_response = "requestId" in payload or (
            "data" in payload and "status" not in payload and "tool_call_id" not in payload
        )
        return payload.get("data") if is_enveloped_response else payload
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


def assert_backend_health_surface(
    payload: dict[str, Any],
    *,
    service_name: str,
    expected_mode: str,
    expected_backends: dict[str, dict[str, Any]],
) -> None:
    if payload.get("service") != service_name:
        raise RuntimeError(f"{service_name} health service name drifted: {payload}")
    if payload.get("runtime_mode") != expected_mode:
        raise RuntimeError(f"{service_name} runtime_mode drifted: {payload}")
    backends = payload.get("backends")
    if not isinstance(backends, dict):
        raise RuntimeError(f"{service_name} health backends payload is missing or invalid: {payload}")
    for backend_name, expectations in expected_backends.items():
        backend_payload = backends.get(backend_name)
        if not isinstance(backend_payload, dict):
            raise RuntimeError(f"{service_name} health backend '{backend_name}' is missing: {payload}")
        for field_name, expected_value in expectations.items():
            if backend_payload.get(field_name) != expected_value:
                raise RuntimeError(
                    f"{service_name} health backend '{backend_name}' field '{field_name}' drifted: "
                    f"expected {expected_value!r}, got {backend_payload.get(field_name)!r}"
                )


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


def _start_service(
    *,
    name: str,
    runtime,
    port: int,
    log_path: Path,
    env: dict[str, str],
) -> ManagedService:
    log_handle = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            runtime.module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=runtime.cwd,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return ManagedService(
        name=name,
        base_url=f"http://127.0.0.1:{port}",
        process=process,
        log_path=log_path,
        port=port,
        module=runtime.module,
        cwd=runtime.cwd,
        env=env,
        health_path=runtime.health_path,
        require_ready=runtime.require_ready,
    )


def launch_services(
    temp_root: Path,
    backend_mode: BackendMode,
    selected_scenarios: tuple[str, ...],
) -> tuple[dict[str, ManagedService], dict[str, int]]:
    required_services = {
        service_name
        for scenario_name in selected_scenarios
        for service_name in SCENARIO_SERVICE_DEPENDENCIES[scenario_name]
    }
    ports = {name: reserve_port() for name in required_services}
    logs_dir = temp_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    knowledge_root = SERVICE_RUNTIMES["knowledge-service"].cwd
    run_label = temp_root.name.replace("_", "-")
    auth_bootstrap = _copy_bootstrap(
        "apps/auth-user-service/data/auth-store.json",
        temp_root / "auth-user-service" / "auth-store.json",
    )
    marketing_bootstrap = _copy_bootstrap(
        "apps/marketing-service/data/marketing-store.json",
        temp_root / "marketing-service" / "marketing-store.json",
    )
    research_bootstrap = _copy_bootstrap(
        "apps/research-service/data/research-store.json",
        temp_root / "research-service" / "research-store.json",
    )
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
            "AUTH_USER_SERVICE_BOOTSTRAP_PATH": str(auth_bootstrap),
            "AUTH_USER_SERVICE_DATABASE_URL": (
                backend_mode.mysql_dsn
                if backend_mode.live_infra and backend_mode.mysql_dsn
                else f"sqlite:///{(temp_root / 'auth-user-service.db').as_posix()}"
            ),
        },
        "marketing-service": {
            "MARKETING_SERVICE_BOOTSTRAP_PATH": str(marketing_bootstrap),
            "MARKETING_SERVICE_DATABASE_URL": (
                backend_mode.mysql_dsn
                if backend_mode.live_infra and backend_mode.mysql_dsn
                else f"sqlite:///{(temp_root / 'marketing-service.db').as_posix()}"
            ),
        },
        "research-service": {
            "RESEARCH_SERVICE_BOOTSTRAP_PATH": str(research_bootstrap),
            "RESEARCH_SERVICE_DATABASE_URL": (
                backend_mode.mysql_dsn
                if backend_mode.live_infra and backend_mode.mysql_dsn
                else f"sqlite:///{(temp_root / 'research-service.db').as_posix()}"
            ),
        },
        "knowledge-service": {
            "SMARTCLOUD_KNOWLEDGE_DATA_PATH": str(temp_root / "knowledge-service" / "knowledge-store.json"),
            "SMARTCLOUD_KNOWLEDGE_AUDIT_PATH": str(
                temp_root / "knowledge-service" / "knowledge-admin-audit.jsonl"
            ),
            "SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH": str(
                temp_root / "knowledge-service" / "knowledge-indexing-outbox.jsonl"
            ),
            "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH": str(knowledge_root / "data" / "starter-catalog.json"),
            "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT": str(knowledge_root / "data" / "imports"),
            "SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT": str(
                temp_root / "knowledge-service" / "raw-objects"
            ),
            "SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY": "smartcloud-qa-dify-external",
        },
        "rag-service": {
            "KNOWLEDGE_SERVICE_BASE_URL": f"http://127.0.0.1:{ports.get('knowledge-service', 0)}",
        },
        "business-tools-service": {
            "APP_PORT": str(ports.get("business-tools-service", 0)),
            "BUSINESS_TOOLS_RUNTIME_DIR": str(temp_root / "business-tools-service" / "runtime"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(
                temp_root / "business-tools-service" / "idempotency-store.json"
            ),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(
                temp_root / "business-tools-service" / "query-cache-store.json"
            ),
        },
        "tool-hub-service": {
            "APP_PORT": str(ports.get("tool-hub-service", 0)),
            "BUSINESS_TOOLS_TRANSPORT": "http",
            "BUSINESS_TOOLS_URL": f"http://127.0.0.1:{ports.get('business-tools-service', 0)}",
            "TOOL_HUB_RUNTIME_DIR": str(temp_root / "tool-hub-service" / "runtime"),
            "AUDIT_STORE_PATH": str(temp_root / "tool-hub-service" / "audit-store.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(
                temp_root / "tool-hub-service" / "local-idempotency-store.json"
            ),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(
                temp_root / "tool-hub-service" / "local-query-cache-store.json"
            ),
        },
        "orchestrator-service": {
            "APP_PORT": str(ports.get("orchestrator-service", 0)),
            "TOOL_HUB_TRANSPORT": "http",
            "MCP_GATEWAY_URL": f"http://127.0.0.1:{ports.get('tool-hub-service', 0)}",
            "ORCHESTRATOR_RUNTIME_DIR": str(temp_root / "orchestrator-service" / "runtime"),
            "CONVERSATION_STORE_PATH": str(temp_root / "orchestrator-service" / "conversation-store.json"),
            "STATE_STORE_PATH": str(temp_root / "orchestrator-service" / "state-store.json"),
            "SSE_EVENT_STORE_PATH": str(temp_root / "orchestrator-service" / "sse-event-store.json"),
            "AGENT_CONFIG_STORE_PATH": str(temp_root / "orchestrator-service" / "agent-config-store.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(
                temp_root / "orchestrator-service" / "local-idempotency-store.json"
            ),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(
                temp_root / "orchestrator-service" / "local-query-cache-store.json"
            ),
        },
    }
    if backend_mode.live_infra:
        if backend_mode.minio_endpoint:
            runtime_env["knowledge-service"]["SMARTCLOUD_MINIO_ENDPOINT"] = backend_mode.minio_endpoint
        if backend_mode.minio_bucket:
            runtime_env["knowledge-service"]["SMARTCLOUD_MINIO_BUCKET"] = backend_mode.minio_bucket
            runtime_env["marketing-service"]["MARKETING_SERVICE_MINIO_BUCKET"] = backend_mode.minio_bucket
        if backend_mode.minio_access_key:
            runtime_env["knowledge-service"]["SMARTCLOUD_MINIO_ACCESS_KEY"] = backend_mode.minio_access_key
            runtime_env["marketing-service"]["MARKETING_SERVICE_MINIO_ACCESS_KEY"] = backend_mode.minio_access_key
        if backend_mode.minio_secret_key:
            runtime_env["knowledge-service"]["SMARTCLOUD_MINIO_SECRET_KEY"] = backend_mode.minio_secret_key
            runtime_env["marketing-service"]["MARKETING_SERVICE_MINIO_SECRET_KEY"] = backend_mode.minio_secret_key
        if backend_mode.minio_endpoint:
            runtime_env["knowledge-service"]["SMARTCLOUD_MINIO_ENDPOINT"] = backend_mode.minio_endpoint
            runtime_env["marketing-service"]["MARKETING_SERVICE_MINIO_ENDPOINT"] = backend_mode.minio_endpoint
        if backend_mode.mysql_dsn:
            runtime_env["knowledge-service"]["SMARTCLOUD_MYSQL_DSN"] = backend_mode.mysql_dsn
            runtime_env["tool-hub-service"]["SMARTCLOUD_MYSQL_DSN"] = backend_mode.mysql_dsn
            runtime_env["orchestrator-service"]["SMARTCLOUD_MYSQL_DSN"] = backend_mode.mysql_dsn
        if backend_mode.qdrant_url:
            runtime_env["knowledge-service"]["SMARTCLOUD_QDRANT_URL"] = backend_mode.qdrant_url
        if backend_mode.opensearch_url:
            runtime_env["knowledge-service"]["SMARTCLOUD_OPENSEARCH_URL"] = backend_mode.opensearch_url
        if backend_mode.knowledge_redis_url:
            runtime_env["knowledge-service"]["SMARTCLOUD_REDIS_URL"] = backend_mode.knowledge_redis_url
            runtime_env["knowledge-service"]["SMARTCLOUD_REDIS_NAMESPACE"] = f"smartcloud:qa:{run_label}:knowledge"
        if backend_mode.rag_redis_url:
            runtime_env["rag-service"]["SMARTCLOUD_REDIS_URL"] = backend_mode.rag_redis_url
            runtime_env["rag-service"]["SMARTCLOUD_RAG_CACHE_NAMESPACE"] = f"smartcloud:qa:{run_label}:rag"
        if backend_mode.business_tools_redis_url:
            runtime_env["business-tools-service"]["SMARTCLOUD_REDIS_URL"] = backend_mode.business_tools_redis_url
            runtime_env["business-tools-service"]["BUSINESS_TOOLS_REDIS_NAMESPACE"] = (
                f"smartcloud:qa:{run_label}:business-tools"
            )
        if backend_mode.tool_hub_redis_url:
            runtime_env["tool-hub-service"]["SMARTCLOUD_REDIS_URL"] = backend_mode.tool_hub_redis_url
            runtime_env["tool-hub-service"]["TOOL_HUB_REDIS_NAMESPACE"] = f"smartcloud:qa:{run_label}:tool-hub"
        if backend_mode.orchestrator_redis_url:
            runtime_env["orchestrator-service"]["SMARTCLOUD_REDIS_URL"] = backend_mode.orchestrator_redis_url
            runtime_env["orchestrator-service"]["ORCHESTRATOR_REDIS_NAMESPACE"] = (
                f"smartcloud:qa:{run_label}:orchestrator"
            )

    full_order = (
        "business-tools-service",
        "tool-hub-service",
        "knowledge-service",
        "rag-service",
        "auth-user-service",
        "marketing-service",
        "research-service",
        "orchestrator-service",
    )
    order = tuple(name for name in full_order if name in required_services)
    services: dict[str, ManagedService] = {}
    for name in order:
        runtime = SERVICE_RUNTIMES[name]
        log_path = logs_dir / f"{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(shared_env)
        env.update(runtime_env.get(name, {}))
        env["PYTHONPATH"] = build_pythonpath(runtime.pythonpath)
        log_path.write_text("", encoding="utf-8")
        services[name] = _start_service(
            name=name,
            runtime=runtime,
            port=ports[name],
            log_path=log_path,
            env=env,
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


def restart_service(services: dict[str, ManagedService], service_name: str) -> ManagedService:
    service = services[service_name]
    if service.process.poll() is None:
        service.process.terminate()
        try:
            service.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            service.process.kill()
            service.process.wait(timeout=5)
    restarted = _start_service(
        name=service.name,
        runtime=SERVICE_RUNTIMES[service.name],
        port=service.port,
        log_path=service.log_path,
        env=service.env,
    )
    wait_for_health(restarted)
    services[service_name] = restarted
    return restarted


def run_knowledge_worker_once(services: dict[str, ManagedService], *, max_events: int | None = None) -> None:
    service = services["knowledge-service"]
    command = [sys.executable, "-m", "app.worker", "--once"]
    if isinstance(max_events, int) and max_events > 0:
        command.extend(["--max-events", str(max_events)])
    result = subprocess.run(
        command,
        cwd=service.cwd,
        env=service.env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "knowledge worker failed during smoke validation:\
"
            f"stdout:\
{result.stdout}\n"
            f"stderr:\
{result.stderr}"
        )


def wait_for_snapshot_event(knowledge_url: str, doc_id: str, operation: str) -> tuple[dict[str, Any], dict[str, Any]]:
    last_snapshot: dict[str, Any] = {}
    for _attempt in range(1, WAIT_ATTEMPTS + 1):
        snapshot = request_json(
            "GET",
            f"{knowledge_url}/api/knowledge/v1/snapshot?{urlencode({'auditLimit': 5})}",
        )
        snapshot_data = assert_status(snapshot, 200, label="knowledge snapshot")
        last_snapshot = snapshot_data
        recent_events = snapshot_data.get("integrations", {}).get("recentEvents", [])
        for event in recent_events:
            if event.get("docId") != doc_id:
                continue
            if event.get("operation") != operation:
                continue
            connector_results = event.get("connectorResults") or []
            if event.get("status") == "completed" and connector_results:
                return snapshot_data, event
        time.sleep(WAIT_SECONDS)
    raise RuntimeError(
        f"knowledge snapshot did not expose a completed {operation} event for {doc_id}: {last_snapshot}"
    )


def find_snapshot_event(snapshot_data: dict[str, Any], doc_id: str, operation: str) -> dict[str, Any] | None:
    recent_events = snapshot_data.get("integrations", {}).get("recentEvents", [])
    for event in recent_events:
        if event.get("docId") != doc_id:
            continue
        if event.get("operation") != operation:
            continue
        return event
    return None


def smoke_auth_marketing_research(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
    *,
    temp_root: Path,
    backend_mode: BackendMode,
) -> dict[str, Any]:
    auth_url = services["auth-user-service"].base_url
    marketing_url = services["marketing-service"].base_url
    research_url = services["research-service"].base_url
    auth_bootstrap_path = temp_root / "auth-user-service" / "auth-store.json"
    marketing_bootstrap_path = temp_root / "marketing-service" / "marketing-store.json"
    research_bootstrap_path = temp_root / "research-service" / "research-store.json"
    auth_bootstrap_before = auth_bootstrap_path.read_text(encoding="utf-8")
    marketing_bootstrap_before = marketing_bootstrap_path.read_text(encoding="utf-8")
    research_bootstrap_before = research_bootstrap_path.read_text(encoding="utf-8")

    documented_drifts: list[dict[str, str]] = []
    auth_health = request_json("GET", f"{auth_url}/healthz")
    auth_health_data = assert_status(auth_health, 200, label="auth health")
    marketing_health = request_json("GET", f"{marketing_url}/healthz")
    marketing_health_data = assert_status(marketing_health, 200, label="marketing health")
    research_health = request_json("GET", f"{research_url}/healthz")
    research_health_data = assert_status(research_health, 200, label="research health")

    expected_runtime_mode = "shared-backend" if backend_mode.live_infra and backend_mode.mysql_dsn else "local-fallback"
    assert_backend_health_surface(
        auth_health_data,
        service_name="auth-user-service",
        expected_mode=expected_runtime_mode,
        expected_backends={
            "mysql": {"kind": "mysql", "role": "primary", "active": expected_runtime_mode == "shared-backend"},
            "sqlite": {"kind": "sqlite", "role": "fallback", "active": expected_runtime_mode == "local-fallback"},
            "redis": {"kind": "redis", "role": "optional", "active": False},
        },
    )
    assert_backend_health_surface(
        marketing_health_data,
        service_name="marketing-service",
        expected_mode=expected_runtime_mode,
        expected_backends={
            "mysql": {"kind": "mysql", "role": "primary", "active": expected_runtime_mode == "shared-backend"},
            "sqlite": {"kind": "sqlite", "role": "fallback", "active": expected_runtime_mode == "local-fallback"},
            "minio": {
                "kind": "minio",
                "role": "raw-object",
                "active": bool(services["marketing-service"].env.get("MARKETING_SERVICE_MINIO_ENDPOINT")),
            },
            "redis": {"kind": "redis", "role": "optional", "active": False},
        },
    )
    assert_backend_health_surface(
        research_health_data,
        service_name="research-service",
        expected_mode=expected_runtime_mode,
        expected_backends={
            "mysql": {"kind": "mysql", "role": "primary", "active": expected_runtime_mode == "shared-backend"},
            "sqlite": {"kind": "sqlite", "role": "fallback", "active": expected_runtime_mode == "local-fallback"},
            "redis": {"kind": "redis", "role": "optional", "active": False},
        },
    )

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
    refresh_token = login_data["refresh_token"]

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

    auth_url = restart_service(services, "auth-user-service").base_url
    refresh = request_json(
        "POST",
        f"{auth_url}/api/v1/auth/refresh",
        payload={"refresh_token": refresh_token},
    )
    refresh_data = assert_status(refresh, 200, label="auth refresh after restart")
    auth_headers = {"Authorization": f"Bearer {refresh_data['access_token']}"}

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

    marketing_url = restart_service(services, "marketing-service").base_url
    copy_detail = request_json(
        "GET",
        f"{marketing_url}/api/v1/marketing/copies/{copy_data['copy_id']}",
        headers=auth_headers,
    )
    copy_detail_data = assert_status(copy_detail, 200, label="marketing copy detail after restart")

    promotion_detail = request_json(
        "GET",
        f"{marketing_url}/api/v1/marketing/promotion-links/{promotion_data['link_id']}",
        headers=auth_headers,
    )
    promotion_detail_data = assert_status(
        promotion_detail,
        200,
        label="marketing promotion-link detail after restart",
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

    research_url = restart_service(services, "research-service").base_url
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

    research_status = request_json(
        "GET",
        f"{research_url}/api/v1/research/tasks/{research_data['task_id']}/status",
        headers=auth_headers,
    )
    research_status_data = assert_status(research_status, 200, label="research task status after restart")

    if refresh_data["refresh_token"] == refresh_token:
        raise RuntimeError("auth refresh token did not rotate after auth-user-service restart")
    if copy_detail_data["copy_id"] != copy_data["copy_id"]:
        raise RuntimeError(f"marketing copy did not persist across restart: {copy_detail_data}")
    if promotion_detail_data["link_id"] != promotion_data["link_id"]:
        raise RuntimeError(f"marketing promotion link did not persist across restart: {promotion_detail_data}")
    if research_status_data["task_id"] != research_data["task_id"]:
        raise RuntimeError(f"research task did not persist across restart: {research_status_data}")
    if auth_bootstrap_path.read_text(encoding="utf-8") != auth_bootstrap_before:
        raise RuntimeError("auth bootstrap JSON mutated during DB-backed smoke execution")
    if marketing_bootstrap_path.read_text(encoding="utf-8") != marketing_bootstrap_before:
        raise RuntimeError("marketing bootstrap JSON mutated during DB-backed smoke execution")
    if research_bootstrap_path.read_text(encoding="utf-8") != research_bootstrap_before:
        raise RuntimeError("research bootstrap JSON mutated during DB-backed smoke execution")
    if copy_data["copy_id"] in marketing_bootstrap_before:
        raise RuntimeError("marketing generated copy leaked into bootstrap JSON")
    if promotion_data["link_id"] in marketing_bootstrap_before:
        raise RuntimeError("marketing promotion link leaked into bootstrap JSON")
    if poster_data["task_id"] in marketing_bootstrap_before:
        raise RuntimeError("marketing poster task leaked into bootstrap JSON")
    if research_data["task_id"] in research_bootstrap_before:
        raise RuntimeError("research task leaked into bootstrap JSON")

    if backend_mode.live_infra and backend_mode.mysql_dsn:
        backend_evidence = {
            "backend": "mysql",
            "authRefreshSessionStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "auth_refresh_sessions",
                "subject_id",
                me_data["user_id"],
            ),
            "marketingCopyStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "marketing_generated_copies",
                "copy_id",
                copy_data["copy_id"],
            ),
            "marketingPromotionLinkStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "marketing_promotion_links",
                "link_id",
                promotion_data["link_id"],
            ),
            "marketingPosterTaskStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "marketing_poster_tasks",
                "task_id",
                poster_data["task_id"],
            ),
            "marketingPosterIdempotencyStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "marketing_poster_idempotency_records",
                "key",
                "qa-smoke-poster-001",
            ),
            "researchTaskStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "research_tasks",
                "task_id",
                research_data["task_id"],
            ),
            "researchIdempotencyStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "research_idempotency_records",
                "key",
                "qa-smoke-research-001",
            ),
            "bootstrapFilesStatic": True,
        }
        if services["marketing-service"].env.get("MARKETING_SERVICE_MINIO_ENDPOINT"):
            backend_evidence["marketingPosterObjectStored"] = _minio_object_exists(
                endpoint=backend_mode.minio_endpoint,
                bucket=services["marketing-service"].env.get("MARKETING_SERVICE_MINIO_BUCKET"),
                access_key=services["marketing-service"].env.get("MARKETING_SERVICE_MINIO_ACCESS_KEY"),
                secret_key=services["marketing-service"].env.get("MARKETING_SERVICE_MINIO_SECRET_KEY"),
                object_name=f"{poster_data['task_id']}.png",
            )
        missing_live_backend_evidence = [
            name for name, present in backend_evidence.items() if name != "backend" and present is False
        ]
        if missing_live_backend_evidence:
            raise RuntimeError(
                "auth-marketing-research live backend evidence was incomplete: "
                f"{missing_live_backend_evidence}"
            )
    else:
        auth_db_path = temp_root / "auth-user-service.db"
        marketing_db_path = temp_root / "marketing-service.db"
        research_db_path = temp_root / "research-service.db"
        backend_evidence = {
            "backend": "sqlite",
            "authRefreshSessionStored": _sqlite_row_exists(
                auth_db_path,
                "auth_refresh_sessions",
                "subject_id",
                me_data["user_id"],
            ),
            "marketingCopyStored": _sqlite_row_exists(
                marketing_db_path,
                "marketing_generated_copies",
                "copy_id",
                copy_data["copy_id"],
            ),
            "marketingPromotionLinkStored": _sqlite_row_exists(
                marketing_db_path,
                "marketing_promotion_links",
                "link_id",
                promotion_data["link_id"],
            ),
            "marketingPosterTaskStored": _sqlite_row_exists(
                marketing_db_path,
                "marketing_poster_tasks",
                "task_id",
                poster_data["task_id"],
            ),
            "marketingPosterIdempotencyStored": _sqlite_row_exists(
                marketing_db_path,
                "marketing_poster_idempotency_records",
                "key",
                "qa-smoke-poster-001",
            ),
            "researchTaskStored": _sqlite_row_exists(
                research_db_path,
                "research_tasks",
                "task_id",
                research_data["task_id"],
            ),
            "researchIdempotencyStored": _sqlite_row_exists(
                research_db_path,
                "research_idempotency_records",
                "key",
                "qa-smoke-research-001",
            ),
            "bootstrapFilesStatic": True,
        }
        missing_sqlite_evidence = [
            name for name, present in backend_evidence.items() if name != "backend" and present is False
        ]
        if missing_sqlite_evidence:
            raise RuntimeError(
                "auth-marketing-research sqlite backend evidence was incomplete: "
                f"{missing_sqlite_evidence}"
            )

    return {
        "documentedContractDrifts": documented_drifts,
        "backendEvidence": backend_evidence,
        "login": {
            "userId": me_data["user_id"],
            "tenantId": me_data["tenant_id"],
            "refreshSurvivedAuthRestart": True,
        },
        "marketing": {
            "campaignId": first_campaign["campaign_id"],
            "copyHeadline": copy_data["headline"],
            "copyId": copy_detail_data["copy_id"],
            "posterTaskId": poster_data["task_id"],
            "posterStatus": poster_detail_data["status"],
            "promotionShortUrl": promotion_data["short_url"],
            "promotionLinkId": promotion_detail_data["link_id"],
            "persistedAfterRestart": True,
        },
        "research": {
            "taskId": research_data["task_id"],
            "status": research_detail_data["status"],
            "reportFileId": research_detail_data["report_file_id"],
            "persistedAfterRestart": True,
        },
        "runtimeHealth": {
            "auth": auth_health_data,
            "marketing": marketing_health_data,
            "research": research_health_data,
        },
    }


def smoke_knowledge_rag_admin(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
    *,
    backend_mode: BackendMode,
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

    expected_admin_source_type = "filesystem"
    expected_admin_file_id = "starter/gpu-release-checklist.md"
    expected_admin_source_uri_prefix = "file:///"
    upload_lifecycle_verified = False
    admin_document_payload = {
        "file_id": "starter/gpu-release-checklist.md",
        "title": "GPU Release Checklist",
        "tags": ["gpu", "admin"],
        "source_type": "filesystem",
    }
    if backend_mode.live_infra:
        upload_init = request_json(
            "POST",
            f"{knowledge_url}/api/v1/admin/files/uploads",
            headers={"X-Operator-Reason": "qa smoke init upload"},
            payload={
                "filename": "gpu-release-checklist.md",
                "content_type": "text/markdown; charset=utf-8",
            },
        )
        upload_init_data = assert_status(upload_init, 201, label="admin init upload")
        upload_content = (
            "# GPU Release Checklist\n\n"
            "共享对象存储 smoke 会验证 admin 文档创建可以先通过 owner-local upload lifecycle 写入 MinIO，"
            "再由 create document 正式消费。"
        ).encode("utf-8")
        upload_content_result = request_json(
            "PUT",
            f"{knowledge_url}/api/v1/admin/files/uploads/{upload_init_data['upload_id']}/content",
            headers={
                "X-Operator-Reason": "qa smoke upload content",
                "Content-Type": "text/markdown; charset=utf-8",
            },
            raw_body=upload_content,
        )
        upload_content_data = assert_status(upload_content_result, 200, label="admin upload content")
        upload_complete = request_json(
            "POST",
            f"{knowledge_url}/api/v1/admin/files/uploads/{upload_init_data['upload_id']}:complete",
            headers={"X-Operator-Reason": "qa smoke complete upload"},
        )
        upload_complete_data = assert_status(upload_complete, 200, label="admin complete upload")
        expected_admin_source_type = "minio"
        expected_admin_file_id = upload_complete_data["resolved_file_id"]
        expected_admin_source_uri_prefix = upload_complete_data["source_uri"]
        upload_lifecycle_verified = (
            upload_init_data["status"] == "initialized"
            and upload_content_data["status"] == "uploaded"
            and upload_complete_data["status"] == "completed"
            and upload_complete_data["source_type"] == "minio"
        )
        admin_document_payload = {
            "file_id": upload_complete_data["file_id"],
            "title": "GPU Release Checklist",
            "tags": ["gpu", "admin", "minio"],
            "source_type": "minio",
            "source_uri": upload_complete_data["source_uri"],
        }

    admin_document = request_json(
        "POST",
        f"{knowledge_url}/api/v1/admin/knowledge-bases/{knowledge_base_data['kb_id']}/documents",
        headers={"X-Operator-Reason": "qa smoke ingest doc"},
        payload=admin_document_payload,
    )
    admin_document_data = assert_status(admin_document, 202, label="admin create document")
    if admin_document_data["source_type"] != expected_admin_source_type:
        raise RuntimeError(
            "admin document source_type drifted from expected smoke path: "
            f"{admin_document_data['source_type']!r} != {expected_admin_source_type!r}"
        )
    if admin_document_data["file_id"] != expected_admin_file_id:
        raise RuntimeError(
            "admin document file_id drifted from expected smoke path: "
            f"{admin_document_data['file_id']!r} != {expected_admin_file_id!r}"
        )
    if not str(admin_document_data.get("source_uri", "")).startswith(expected_admin_source_uri_prefix):
        raise RuntimeError(
            "admin document source_uri drifted from expected smoke path: "
            f"{admin_document_data.get('source_uri')!r}"
        )

    document_detail = request_json(
        "GET",
        f"{knowledge_url}/api/v1/admin/knowledge-documents/{admin_document_data['doc_id']}",
    )
    document_detail_data = assert_status(document_detail, 200, label="admin document detail")
    if document_detail_data["document"]["source_type"] != expected_admin_source_type:
        raise RuntimeError(
            "admin document detail source_type drifted from expected smoke path: "
            f"{document_detail_data['document']['source_type']!r} != {expected_admin_source_type!r}"
        )
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
    if backend_mode.live_infra:
        run_knowledge_worker_once(services, max_events=10)

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

    dify_retrieval = request_json(
        "POST",
        f"{knowledge_url}/retrieval",
        headers={"Authorization": "Bearer smartcloud-qa-dify-external"},
        payload={
            "knowledge_id": kb_code,
            "query": "GPU部署前需要确认什么",
            "retrieval_setting": {"top_k": 3, "score_threshold": 0.1},
            "metadata_condition": {
                "logical_operator": "and",
                "conditions": [
                    {"name": ["tags"], "comparison_operator": "contains", "value": "gpu"}
                ],
            },
        },
    )
    dify_retrieval_data = assert_status(dify_retrieval, 200, label="dify external retrieval")
    if len(dify_retrieval_data.get("records", [])) < 1:
        raise RuntimeError(f"dify external retrieval returned no records: {dify_retrieval_data}")

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
    if dify_retrieval_data["records"][0]["metadata"].get("knowledge_id") != kb_code:
        raise RuntimeError(
            "dify external retrieval did not preserve requested knowledge_id: "
            f"{dify_retrieval_data}"
        )
    if "knowledge_readiness_state" not in str(knowledge_metrics.payload):
        raise RuntimeError("knowledge metrics did not expose readiness gauges")
    if "rag_upstream_ready_state" not in str(rag_metrics.payload):
        raise RuntimeError("rag metrics did not expose upstream readiness gauges")

    knowledge_url = restart_service(services, "knowledge-service").base_url
    rag_url = restart_service(services, "rag-service").base_url

    document_detail_after_restart = request_json(
        "GET",
        f"{knowledge_url}/api/v1/admin/knowledge-documents/{admin_document_data['doc_id']}",
    )
    document_detail_after_restart_data = assert_status(
        document_detail_after_restart,
        200,
        label="admin document detail after restart",
    )
    validate_contract(
        contracts,
        "admin-api",
        "/api/v1/admin/knowledge-documents/{doc_id}",
        "get",
        200,
        document_detail_after_restart.payload,
        drift_log=documented_drifts,
    )

    search_after_restart = request_json(
        "POST",
        f"{knowledge_url}/api/knowledge/v1/search",
        payload={"query": "GPU部署前需要确认什么", "topK": 3, "tags": ["gpu", "launch"]},
    )
    search_after_restart_data = assert_status(
        search_after_restart,
        200,
        label="knowledge search after restart",
    )
    validate_contract(
        contracts,
        "knowledge-service",
        "/api/knowledge/v1/search",
        "post",
        200,
        search_after_restart.payload,
        drift_log=documented_drifts,
    )

    rag_diagnose_after_restart = request_json(
        "POST",
        f"{rag_url}/api/rag/v1/diagnose",
        payload={"query": "GPU部署前需要确认什么", "topK": 3, "filters": {"tags": ["gpu", "launch"]}},
    )
    rag_diagnose_after_restart_data = assert_status(
        rag_diagnose_after_restart,
        200,
        label="rag diagnose after restart",
    )
    validate_contract(
        contracts,
        "rag-service",
        "/api/rag/v1/diagnose",
        "post",
        200,
        rag_diagnose_after_restart.payload,
        drift_log=documented_drifts,
    )

    admin_diagnostics_after_restart = request_json(
        "POST",
        f"{rag_url}/api/v1/admin/retrieval/diagnostics",
        payload={
            "query": "GPU部署前需要确认什么",
            "kb_id": knowledge_base_data["kb_id"],
            "top_k": 3,
            "include_citations": True,
        },
    )
    admin_diagnostics_after_restart_data = assert_status(
        admin_diagnostics_after_restart,
        200,
        label="admin rag diagnostics after restart",
    )
    validate_contract(
        contracts,
        "admin-api",
        "/api/v1/admin/retrieval/diagnostics",
        "post",
        200,
        admin_diagnostics_after_restart.payload,
        drift_log=documented_drifts,
    )

    snapshot_after_restart = request_json(
        "GET",
        f"{knowledge_url}/api/knowledge/v1/snapshot?{urlencode({'auditLimit': 5})}",
    )
    snapshot_after_restart_data = assert_status(
        snapshot_after_restart,
        200,
        label="knowledge snapshot after restart",
    )
    snapshot_event_after_restart = find_snapshot_event(
        snapshot_after_restart_data,
        admin_document_data["doc_id"],
        "reindex",
    )

    if document_detail_after_restart_data["document"]["doc_id"] != admin_document_data["doc_id"]:
        raise RuntimeError(
            "admin document detail did not retain the ingested document across restart: "
            f"{document_detail_after_restart_data}"
        )
    if int(search_after_restart_data.get("total", 0)) < 1:
        raise RuntimeError(f"knowledge search returned no hits after restart: {search_after_restart_data}")
    if int(rag_diagnose_after_restart_data.get("candidateCount", 0)) < 1:
        raise RuntimeError(
            "rag diagnose returned no candidates after restart: "
            f"{rag_diagnose_after_restart_data}"
        )
    if int(admin_diagnostics_after_restart_data.get("coverage", {}).get("candidate_count", 0)) < 1:
        raise RuntimeError(
            "admin rag diagnostics returned no candidates after restart: "
            f"{admin_diagnostics_after_restart_data}"
        )
    if snapshot_event_after_restart is None:
        raise RuntimeError(
            "knowledge snapshot did not retain the reindex event across restart: "
            f"{snapshot_after_restart_data}"
        )

    backend_evidence: dict[str, Any] = {
        "backend": "local-runtime",
        "snapshotEventRetainedAfterRestart": True,
        "searchTotalAfterRestart": search_after_restart_data["total"],
        "ragCandidateCountAfterRestart": rag_diagnose_after_restart_data["candidateCount"],
        "adminCandidateCountAfterRestart": admin_diagnostics_after_restart_data["coverage"][
            "candidate_count"
        ],
    }
    if backend_mode.live_infra:
        integrations = snapshot_after_restart_data.get("integrations", {})
        connector_results = snapshot_event_after_restart.get("connectorResults") or []
        backend_evidence = {
            "backend": "shared-connectors",
            "rawStorage": integrations.get("rawStorage", {}).get("backend"),
            "metadataStore": integrations.get("metadataStore", {}).get("backend"),
            "vectorStore": integrations.get("vectorStore", {}).get("backend"),
            "bm25Store": integrations.get("bm25Store", {}).get("backend"),
            "difyExternalKnowledge": integrations.get("difyExternalKnowledge", {}).get("status"),
            "cache": integrations.get("cache", {}).get("backend"),
            "taskQueue": integrations.get("taskQueue", {}).get("backend"),
            "connectorResults": len(connector_results),
            "adminDocumentSourceType": document_detail_after_restart_data["document"]["source_type"],
            "uploadLifecycleVerified": upload_lifecycle_verified,
            "snapshotEventRetainedAfterRestart": True,
            "searchTotalAfterRestart": search_after_restart_data["total"],
            "ragCandidateCountAfterRestart": rag_diagnose_after_restart_data["candidateCount"],
            "adminCandidateCountAfterRestart": admin_diagnostics_after_restart_data["coverage"][
                "candidate_count"
            ],
        }
        expected_integrations = {
            "rawStorage": "minio",
            "metadataStore": "mysql",
            "vectorStore": "qdrant",
            "bm25Store": "opensearch",
            "cache": "redis-configured",
            "taskQueue": "redis-list-primary",
        }
        mismatched_integrations = [
            f"{name}={backend_evidence.get(name)!r}"
            for name, expected in expected_integrations.items()
            if backend_evidence.get(name) != expected
        ]
        if mismatched_integrations:
            raise RuntimeError(
                "knowledge live backend snapshot did not expose the expected shared connectors: "
                f"{mismatched_integrations}"
            )
        if int(backend_evidence["connectorResults"]) < 1:
            raise RuntimeError(
                "knowledge live backend snapshot exposed no connector results after restart: "
                f"{snapshot_event_after_restart}"
            )
        if backend_evidence["adminDocumentSourceType"] != expected_admin_source_type:
            raise RuntimeError(
                "knowledge live backend snapshot did not retain the expected admin source type: "
                f"{backend_evidence['adminDocumentSourceType']!r}"
            )
        if backend_evidence["uploadLifecycleVerified"] is not True:
            raise RuntimeError("knowledge live backend upload lifecycle did not complete successfully")
        if backend_evidence["difyExternalKnowledge"] != "configured":
            raise RuntimeError(
                "knowledge live backend did not expose configured Dify external knowledge status: "
                f"{backend_evidence['difyExternalKnowledge']!r}"
            )

    return {
        "documentedContractDrifts": documented_drifts,
        "backendEvidence": backend_evidence,
        "knowledge": {
            "bootstrap": bootstrap_data,
            "kbId": knowledge_base_data["kb_id"],
            "docId": admin_document_data["doc_id"],
            "createJobId": job_detail_data["job_id"],
            "reindexJobId": admin_reindex_data["job_id"],
            "searchTotal": search_data["total"],
            "searchTotalAfterRestart": search_after_restart_data["total"],
            "snapshotEventRetainedAfterRestart": True,
            "persistedAfterRestart": True,
        },
        "rag": {
            "candidateCount": rag_diagnose_data["candidateCount"],
            "answerPreview": rag_answer_data["answer"],
            "adminCandidateCount": admin_diagnostics_data["coverage"]["candidate_count"],
            "candidateCountAfterRestart": rag_diagnose_after_restart_data["candidateCount"],
            "adminCandidateCountAfterRestart": admin_diagnostics_after_restart_data["coverage"][
                "candidate_count"
            ],
            "persistedAfterRestart": True,
        },
        "difyExternalKnowledge": {
            "recordCount": len(dify_retrieval_data["records"]),
            "firstKnowledgeId": dify_retrieval_data["records"][0]["metadata"]["knowledge_id"],
        },
    }


def smoke_business_tools_tool_hub(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
    *,
    temp_root: Path,
    backend_mode: BackendMode,
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

    confirmed_write = request_json(
        "POST",
        f"{tool_hub_url}/internal/v1/tools/call",
        headers=tool_hub_internal_headers,
        payload={
            "trace_id": "qa-th-write-1",
            "conversation_id": "conv-th-write-1",
            "tool_call_id": "tc-th-write-1",
            "tool_name": "billing.create_invoice",
            "operator": {"type": "agent", "id": "Finance_Order_Agent"},
            "user_context": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "permissions": ["user:billing.read"],
            },
            "payload": {
                "statement_nos": ["stmt_qa_001"],
                "invoice_type": "vat_special",
                "title": "SmartCloud QA",
                "_confirmed": True,
            },
            "idempotency_key": "qa-th-write-1",
            "operation": "execute",
        },
    )
    confirmed_write_data = assert_status(confirmed_write, 200, label="tool hub confirmed write")

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
    if confirmed_write_data["status"] != "completed":
        raise RuntimeError(f"expected tool-hub confirmed write completion: {confirmed_write_data}")
    if len(audit_records_data) < 1:
        raise RuntimeError(f"expected at least one tool-call audit record: {audit_records_data}")

    business_tools_url = restart_service(services, "business-tools-service").base_url
    tool_hub_url = restart_service(services, "tool-hub-service").base_url
    audit_records_after_restart = request_json(
        "GET",
        f"{tool_hub_url}/api/v1/tool-calls?{urlencode({'conversation_id': 'conv-th-call-1'})}",
    )
    audit_records_after_restart_data = assert_status(
        audit_records_after_restart,
        200,
        label="tool hub audit list after restart",
    )
    if len(audit_records_after_restart_data) < len(audit_records_data):
        raise RuntimeError(
            "tool-hub audit store did not retain records across restart: "
            f"{audit_records_after_restart_data}"
        )

    write_audit = request_json(
        "GET",
        f"{tool_hub_url}/api/v1/tool-calls/tc-th-write-1",
    )
    write_audit_data = assert_status(write_audit, 200, label="tool hub write audit detail")

    business_tools_health = request_json("GET", f"{business_tools_url}/healthz")
    business_tools_health_data = assert_status(
        business_tools_health,
        200,
        label="business tools health",
    )
    tool_hub_health = request_json("GET", f"{tool_hub_url}/healthz")
    tool_hub_health_data = assert_status(tool_hub_health, 200, label="tool hub health")

    backend_evidence: dict[str, Any] = {
        "backend": "local-fallback",
        "businessToolsHealth": business_tools_health_data["runtime"],
        "toolHubHealth": tool_hub_health_data["runtime"],
    }
    if backend_mode.live_infra and backend_mode.mysql_dsn:
        business_tools_namespace = services["business-tools-service"].env.get(
            "BUSINESS_TOOLS_REDIS_NAMESPACE",
            "smartcloud:business-tools",
        )
        business_tools_query_keys = _redis_keys(
            backend_mode.business_tools_redis_url,
            f"{business_tools_namespace}:query-cache:*",
        )
        business_tools_idempotency_keys = _redis_keys(
            backend_mode.business_tools_redis_url,
            f"{business_tools_namespace}:idempotency:*",
        )
        tool_hub_query_keys = _redis_keys(
            backend_mode.tool_hub_redis_url,
            "smartcloud:business-tools:query-cache:*",
        )
        tool_hub_idempotency_keys = _redis_keys(
            backend_mode.tool_hub_redis_url,
            "smartcloud:business-tools:idempotency:*",
        )
        backend_evidence = {
            "backend": "mysql-and-redis",
            "businessToolsHealth": business_tools_health_data["runtime"],
            "toolHubHealth": tool_hub_health_data["runtime"],
            "toolHubAuditStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "tool_hub_tool_call_audits",
                "tool_call_id",
                "tc-th-write-1",
            ),
            "businessToolsQueryCacheKeys": len(business_tools_query_keys),
            "businessToolsIdempotencyKeys": len(business_tools_idempotency_keys),
            "toolHubQueryCacheKeys": len(tool_hub_query_keys),
            "toolHubIdempotencyKeys": len(tool_hub_idempotency_keys),
        }
        if business_tools_health_data["runtime"]["idempotency"]["backend"] != "redis":
            raise RuntimeError(f"business-tools live idempotency backend was not redis: {business_tools_health_data}")
        if business_tools_health_data["runtime"]["queryCache"]["backend"] != "redis-ttl":
            raise RuntimeError(f"business-tools live query-cache backend was not redis-ttl: {business_tools_health_data}")
        if tool_hub_health_data["runtime"]["auditStore"]["backend"] != "mysql":
            raise RuntimeError(f"tool-hub live audit backend was not mysql: {tool_hub_health_data}")
        if tool_hub_health_data["runtime"]["businessToolsIdempotency"]["backend"] != "inactive":
            raise RuntimeError(f"tool-hub live idempotency surface drifted from inactive: {tool_hub_health_data}")
        if (
            tool_hub_health_data["runtime"]["businessToolsIdempotency"]["activationMode"]
            != "degraded-fallback-only"
        ):
            raise RuntimeError(
                "tool-hub live idempotency activation mode drifted from degraded-fallback-only: "
                f"{tool_hub_health_data}"
            )
        if tool_hub_health_data["runtime"]["businessToolsQueryCache"]["backend"] != "inactive":
            raise RuntimeError(f"tool-hub live query-cache surface drifted from inactive: {tool_hub_health_data}")
        if (
            tool_hub_health_data["runtime"]["businessToolsQueryCache"]["activationMode"]
            != "degraded-fallback-only"
        ):
            raise RuntimeError(
                "tool-hub live query-cache activation mode drifted from degraded-fallback-only: "
                f"{tool_hub_health_data}"
            )
        if not backend_evidence["toolHubAuditStored"]:
            raise RuntimeError("tool-hub live audit row did not land in MySQL")
        if backend_evidence["businessToolsQueryCacheKeys"] < 1:
            raise RuntimeError("business-tools live query-cache did not land in Redis")
        if backend_evidence["businessToolsIdempotencyKeys"] < 1:
            raise RuntimeError("business-tools live idempotency did not land in Redis")

    return {
        "documentedContractDrifts": documented_drifts,
        "implementationDrifts": implementation_drifts,
        "backendEvidence": backend_evidence,
        "businessTools": {
            "descriptorName": descriptor_data["name"],
            "preflightStatus": preflight_data["status"],
        },
        "toolHub": {
            "toolCount": len(tool_list_data),
            "callSummary": tool_call_data["summary"],
            "invokeSummary": direct_invoke_data["summary"],
            "writeSummary": confirmed_write_data["summary"],
            "auditTotal": len(audit_records_data),
            "auditTotalAfterRestart": len(audit_records_after_restart_data),
            "writeAuditStatus": write_audit_data["status"],
            "persistedAfterRestart": True,
        },
    }


def exercise_orchestrator_timeout_chain(
    services: dict[str, ManagedService],
    *,
    backend_mode: BackendMode,
) -> dict[str, Any]:
    business_tools_url = services["business-tools-service"].base_url
    tool_hub_url = services["tool-hub-service"].base_url
    orchestrator_url = services["orchestrator-service"].base_url
    descriptor_headers = {"X-Caller-Service": "tool-hub-service"}

    descriptor = request_json(
        "GET",
        f"{business_tools_url}/internal/v1/tools/billing.query_statement",
        headers=descriptor_headers,
    )
    descriptor_data = assert_status(
        descriptor,
        200,
        label="timeout probe business-tools descriptor",
    )
    preflight = request_json(
        "POST",
        f"{business_tools_url}/internal/v1/preflight/billing.query_statement",
        headers=descriptor_headers,
        payload={
            "operator": {"type": "agent", "id": "finance_order_agent"},
            "subject": {
                "user_id": "u-1",
                "account_id": "acct-1",
                "tenant_id": "default",
                "permissions": ["user:billing.read"],
            },
            "payload": {"range": "this_month"},
            "operation": "execute",
        },
    )
    preflight_data = assert_status(preflight, 200, label="timeout probe business-tools preflight")
    if preflight_data.get("status") != "ready" or preflight_data.get("ready") is not True:
        raise RuntimeError(
            "timeout probe preflight did not stay ready before the execute timeout check: "
            f"{preflight_data}"
        )
    timeout_probe_ms = 750
    descriptor_data = {
        **descriptor_data,
        "timeout_ms": timeout_probe_ms,
    }
    preflight_data = {
        **preflight_data,
        "timeout_ms": timeout_probe_ms,
    }

    probe = start_business_tools_timeout_probe(
        descriptor_payload=descriptor_data,
        preflight_payload=preflight_data,
    )
    original_tool_hub_env = dict(services["tool-hub-service"].env)
    try:
        services["tool-hub-service"].env["BUSINESS_TOOLS_URL"] = probe.base_url
        services["tool-hub-service"].env["REQUEST_TIMEOUT_MS"] = "1000"
        tool_hub_url = restart_service(services, "tool-hub-service").base_url

        timeout_session = request_json(
            "POST",
            f"{orchestrator_url}/api/v1/chat/sessions",
            payload={"scene": "billing", "title": "QA timeout chain"},
        )
        timeout_conversation_id = assert_status(
            timeout_session,
            200,
            label="orchestrator timeout-chain session",
        )["conversation_id"]
        timeout_completion = request_json(
            "POST",
            f"{orchestrator_url}/api/v1/chat/completions",
            payload={
                "conversation_id": timeout_conversation_id,
                "message_id": "qa-orch-timeout-1",
                "user_input": "帮我查本月账单",
                "scene": "billing",
                "user_profile": {
                    "user_id": "u-1",
                    "account_id": "acct-1",
                    "permissions": ["user:billing.read"],
                },
            },
        )
        timeout_completion_data = assert_status(
            timeout_completion,
            200,
            label="orchestrator timeout-chain completion",
        )
        timeout_response = timeout_completion_data["response"]
        timeout_execution = timeout_response["executions"][0]
        timeout_tool_call = timeout_completion_data["tool_calls"][0]
        if timeout_completion_data["status"] != "failed":
            raise RuntimeError(
                "orchestrator timeout-chain completion did not report failed status: "
                f"{timeout_completion_data}"
            )
        if timeout_response["next_action"] != "retry-or-escalate":
            raise RuntimeError(
                "orchestrator timeout-chain completion did not request retry-or-escalate: "
                f"{timeout_response}"
            )
        if timeout_execution["status"] != "failed":
            raise RuntimeError(
                "orchestrator timeout-chain execution did not fail as expected: "
                f"{timeout_execution}"
            )
        if "tool_failure" not in timeout_execution["risk_flags"]:
            raise RuntimeError(
                "orchestrator timeout-chain execution missed the tool_failure risk flag: "
                f"{timeout_execution}"
            )
        if timeout_tool_call["status"] != "timeout":
            raise RuntimeError(
                "orchestrator timeout-chain tool call did not preserve timeout status: "
                f"{timeout_tool_call}"
            )
        if int(timeout_tool_call.get("code", 0)) != 5003002:
            raise RuntimeError(
                "orchestrator timeout-chain tool call did not preserve timeout code 5003002: "
                f"{timeout_tool_call}"
            )
        if timeout_tool_call.get("retryable") is not True:
            raise RuntimeError(
                "orchestrator timeout-chain tool call did not stay retryable: "
                f"{timeout_tool_call}"
            )
        if "timeout" not in str(timeout_completion_data.get("answer", "")).lower():
            raise RuntimeError(
                "orchestrator timeout-chain answer did not surface the timeout summary: "
                f"{timeout_completion_data}"
            )

        timeout_audit = request_json(
            "GET",
            f"{tool_hub_url}/api/v1/tool-calls/{timeout_tool_call['tool_call_id']}",
        )
        timeout_audit_data = assert_status(timeout_audit, 200, label="tool-hub timeout audit")
        if timeout_audit_data["status"] != "timeout":
            raise RuntimeError(
                "tool-hub timeout audit did not preserve timeout status: "
                f"{timeout_audit_data}"
            )
        if timeout_audit_data.get("error", {}).get("retryable") is not True:
            raise RuntimeError(
                "tool-hub timeout audit did not preserve retryable=true: "
                f"{timeout_audit_data}"
            )

        timeout_chain = {
            "verified": True,
            "probeBusinessToolsUrl": probe.base_url,
            "conversationId": timeout_conversation_id,
            "toolCallId": timeout_tool_call["tool_call_id"],
            "orchestratorStatus": timeout_completion_data["status"],
            "orchestratorNextAction": timeout_response["next_action"],
            "orchestratorExecutionStatus": timeout_execution["status"],
            "orchestratorToolStatus": timeout_tool_call["status"],
            "orchestratorToolSummary": timeout_tool_call["summary"],
            "toolHubAuditStatus": timeout_audit_data["status"],
            "toolHubAuditAttempts": timeout_audit_data["attempts"],
            "toolHubAuditRetryable": timeout_audit_data["error"]["retryable"],
        }
        if backend_mode.live_infra and backend_mode.mysql_dsn:
            timeout_chain.update(
                {
                    "timeoutAuditStored": _mysql_row_exists(
                        backend_mode.mysql_dsn,
                        "tool_hub_tool_call_audits",
                        "tool_call_id",
                        timeout_tool_call["tool_call_id"],
                    ),
                    "timeoutConversationStored": _mysql_row_exists(
                        backend_mode.mysql_dsn,
                        "orchestrator_conversations",
                        "conversation_id",
                        timeout_conversation_id,
                    ),
                    "timeoutStateStored": _mysql_row_exists(
                        backend_mode.mysql_dsn,
                        "orchestrator_session_state",
                        "conversation_id",
                        timeout_conversation_id,
                    ),
                }
            )
            if not timeout_chain["timeoutAuditStored"]:
                raise RuntimeError("tool-hub timeout audit row did not land in MySQL")
            if not timeout_chain["timeoutConversationStored"]:
                raise RuntimeError("orchestrator timeout conversation row did not land in MySQL")
            if not timeout_chain["timeoutStateStored"]:
                raise RuntimeError("orchestrator timeout state row did not land in MySQL")
        return timeout_chain
    finally:
        services["tool-hub-service"].env = original_tool_hub_env
        restart_service(services, "tool-hub-service")
        stop_timeout_probe_server(probe)


def smoke_orchestrator_billing(
    services: dict[str, ManagedService],
    contracts: dict[str, OpenApiContract],
    *,
    temp_root: Path,
    backend_mode: BackendMode,
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

    orchestrator_url = restart_service(services, "orchestrator-service").base_url
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

    timeout_chain = exercise_orchestrator_timeout_chain(
        services,
        backend_mode=backend_mode,
    )

    health = request_json("GET", f"{orchestrator_url}/healthz")
    health_data = assert_status(health, 200, label="orchestrator health")

    backend_evidence: dict[str, Any] = {
        "backend": "local-fallback",
        "runtime": health_data["runtime"],
        "timeoutChainVerified": timeout_chain["verified"],
    }
    if backend_mode.live_infra and backend_mode.mysql_dsn:
        orchestrator_namespace = services["orchestrator-service"].env.get(
            "ORCHESTRATOR_REDIS_NAMESPACE",
            "smartcloud:orchestrator",
        )
        sse_keys = _redis_keys(
            backend_mode.orchestrator_redis_url,
            f"{orchestrator_namespace}:sse:{conversation_id}:*",
        )
        query_cache_keys = _redis_keys(
            backend_mode.orchestrator_redis_url,
            "smartcloud:business-tools:query-cache:*",
        )
        idempotency_keys = _redis_keys(
            backend_mode.orchestrator_redis_url,
            "smartcloud:business-tools:idempotency:*",
        )
        backend_evidence = {
            "backend": "mysql-and-redis",
            "runtime": health_data["runtime"],
            "conversationStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "orchestrator_conversations",
                "conversation_id",
                conversation_id,
            ),
            "stateStored": _mysql_row_exists(
                backend_mode.mysql_dsn,
                "orchestrator_session_state",
                "conversation_id",
                conversation_id,
            ),
            "timeoutAuditStored": timeout_chain.get("timeoutAuditStored"),
            "timeoutConversationStored": timeout_chain.get("timeoutConversationStored"),
            "timeoutStateStored": timeout_chain.get("timeoutStateStored"),
            "sseRedisKeys": len(sse_keys),
            "queryCacheKeys": len(query_cache_keys),
            "idempotencyKeys": len(idempotency_keys),
        }
        runtime = health_data["runtime"]
        if runtime["conversationStore"]["backend"] != "mysql":
            raise RuntimeError(f"orchestrator live conversation backend was not mysql: {health_data}")
        if runtime["stateStore"]["backend"] != "mysql":
            raise RuntimeError(f"orchestrator live state backend was not mysql: {health_data}")
        if runtime["agentConfigStore"]["backend"] != "mysql":
            raise RuntimeError(f"orchestrator live agent-config backend was not mysql: {health_data}")
        if runtime["sseStore"]["backend"] != "redis-list":
            raise RuntimeError(f"orchestrator live SSE backend was not redis-list: {health_data}")
        if runtime["runControl"]["backend"] != "redis-lock":
            raise RuntimeError(f"orchestrator live run-control backend was not redis-lock: {health_data}")
        if runtime["businessToolsIdempotency"]["backend"] != "inactive":
            raise RuntimeError(f"orchestrator live idempotency surface drifted from inactive: {health_data}")
        if runtime["businessToolsIdempotency"]["activationMode"] != "degraded-fallback-only":
            raise RuntimeError(
                "orchestrator live idempotency activation mode drifted from degraded-fallback-only: "
                f"{health_data}"
            )
        if runtime["businessToolsQueryCache"]["backend"] != "inactive":
            raise RuntimeError(f"orchestrator live query-cache surface drifted from inactive: {health_data}")
        if runtime["businessToolsQueryCache"]["activationMode"] != "degraded-fallback-only":
            raise RuntimeError(
                "orchestrator live query-cache activation mode drifted from degraded-fallback-only: "
                f"{health_data}"
            )
        if not backend_evidence["conversationStored"]:
            raise RuntimeError("orchestrator live conversation row did not land in MySQL")
        if not backend_evidence["stateStored"]:
            raise RuntimeError("orchestrator live state row did not land in MySQL")
        if not backend_evidence["timeoutAuditStored"]:
            raise RuntimeError("orchestrator timeout-chain audit row did not land in MySQL")
        if not backend_evidence["timeoutConversationStored"]:
            raise RuntimeError("orchestrator timeout-chain conversation row did not land in MySQL")
        if not backend_evidence["timeoutStateStored"]:
            raise RuntimeError("orchestrator timeout-chain state row did not land in MySQL")
        if backend_evidence["sseRedisKeys"] < 1:
            raise RuntimeError("orchestrator live SSE events did not land in Redis")

    return {
        "documentedContractDrifts": documented_drifts,
        "backendEvidence": backend_evidence,
        "timeoutChain": timeout_chain,
        "conversationId": conversation_id,
        "firstTool": first_completion_data["tool_calls"][0]["tool_name"],
        "secondTool": followup_data["executions"][0]["tool_calls"][0]["tool_name"],
        "invoiceNo": followup_data["state_snapshot"]["session_context"]["attributes"]["invoice_no"],
        "stateVersion": state_data["version"],
        "persistedAfterRestart": True,
    }


def main() -> int:
    args = parse_args()
    selected = tuple(args.scenario or SMOKE_SCENARIOS.keys())
    temp_root = Path(tempfile.mkdtemp(prefix="smartcloud-qa-smoke-"))
    backend_mode = resolve_backend_mode()
    contracts = {name: OpenApiContract(spec.path) for name, spec in OPENAPI_SPECS.items()}
    services: dict[str, ManagedService] = {}

    try:
        services, ports = launch_services(temp_root, backend_mode, selected)
        summary: dict[str, Any] = {
            "ok": True,
            "tempRoot": str(temp_root),
            "backendMode": {
                "liveInfra": backend_mode.live_infra,
                "mysqlDsnConfigured": bool(backend_mode.mysql_dsn),
                "knowledgeRedisConfigured": bool(backend_mode.knowledge_redis_url),
                "ragRedisConfigured": bool(backend_mode.rag_redis_url),
                "businessToolsRedisConfigured": bool(backend_mode.business_tools_redis_url),
                "toolHubRedisConfigured": bool(backend_mode.tool_hub_redis_url),
                "orchestratorRedisConfigured": bool(backend_mode.orchestrator_redis_url),
                "minioConfigured": bool(backend_mode.minio_endpoint and backend_mode.minio_bucket),
                "qdrantConfigured": bool(backend_mode.qdrant_url),
                "opensearchConfigured": bool(backend_mode.opensearch_url),
            },
            "ports": ports,
            "scenarios": {},
            "logs": {name: str(service.log_path) for name, service in services.items()},
        }
        if "auth-marketing-research" in selected:
            summary["scenarios"]["auth-marketing-research"] = smoke_auth_marketing_research(
                services,
                contracts,
                temp_root=temp_root,
                backend_mode=backend_mode,
            )
        if "knowledge-rag-admin" in selected:
            summary["scenarios"]["knowledge-rag-admin"] = smoke_knowledge_rag_admin(
                services,
                contracts,
                backend_mode=backend_mode,
            )
        if "business-tools-tool-hub" in selected:
            summary["scenarios"]["business-tools-tool-hub"] = smoke_business_tools_tool_hub(
                services,
                contracts,
                temp_root=temp_root,
                backend_mode=backend_mode,
            )
        if "orchestrator-billing" in selected:
            summary["scenarios"]["orchestrator-billing"] = smoke_orchestrator_billing(
                services,
                contracts,
                temp_root=temp_root,
                backend_mode=backend_mode,
            )

        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        if services:
            stop_services(services)


if __name__ == "__main__":
    raise SystemExit(main())
