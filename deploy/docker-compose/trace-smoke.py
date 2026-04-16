#!/usr/bin/env python3
"""QA-style OTLP trace smoke validation for local knowledge-service and rag-service."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = ROOT / "apps" / "knowledge-service"
RAG_ROOT = ROOT / "apps" / "rag-service"
PYTHON_BIN = os.getenv("SMARTCLOUD_TRACE_SMOKE_PYTHON", sys.executable)
REQUEST_TIMEOUT = float(os.getenv("SMARTCLOUD_TRACE_SMOKE_TIMEOUT_SECONDS", "5"))
WAIT_SECONDS = float(os.getenv("SMARTCLOUD_TRACE_SMOKE_WAIT_SECONDS", "0.5"))
WAIT_ATTEMPTS = int(os.getenv("SMARTCLOUD_TRACE_SMOKE_WAIT_ATTEMPTS", "30"))


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
                "bodySize": len(body),
                "timestamp": time.time(),
            }
        )
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003 - stdlib callback signature
        return


@dataclass
class ManagedProcess:
    label: str
    process: subprocess.Popen[bytes]
    log_path: Path

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def log_text(self) -> str:
        if not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8", errors="replace")


@dataclass(frozen=True)
class ExportedSpan:
    service_name: str
    span_name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_trace_collector() -> tuple[ThreadingHTTPServer, Thread]:
    TraceCollectorHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), TraceCollectorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def request(method: str, url: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Request-Id": "smartcloud-trace-smoke",
            "X-Caller-Service": "smartcloud-trace-smoke",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_ready(url: str, label: str) -> None:
    last_error: Exception | None = None
    for _ in range(WAIT_ATTEMPTS):
        try:
            payload = request("GET", url)
            if payload.get("data", {}).get("ready") is True:
                return
            last_error = RuntimeError(f"{label} returned non-ready payload: {payload}")
        except Exception as exc:  # noqa: BLE001 - smoke retries on startup races
            last_error = exc
        time.sleep(WAIT_SECONDS)
    raise RuntimeError(f"{label} did not become ready: {last_error}")


def wait_for_trace_exports(min_requests: int, label: str) -> None:
    for _ in range(WAIT_ATTEMPTS):
        if len(TraceCollectorHandler.requests) >= min_requests:
            return
        time.sleep(WAIT_SECONDS)
    raise RuntimeError(
        f"{label} did not export enough OTLP batches; got {len(TraceCollectorHandler.requests)} "
        f"expected at least {min_requests}"
    )


def decode_exported_spans() -> list[ExportedSpan]:
    spans: list[ExportedSpan] = []
    for request in TraceCollectorHandler.requests:
        if request.get("path") != "/v1/traces":
            continue
        body = request.get("body")
        if not isinstance(body, (bytes, bytearray)) or not body:
            continue
        export_request = ExportTraceServiceRequest()
        export_request.ParseFromString(body)
        for resource_span in export_request.resource_spans:
            service_name = "unknown"
            for attribute in resource_span.resource.attributes:
                if attribute.key == "service.name":
                    service_name = attribute.value.string_value or service_name
                    break
            for scope_span in resource_span.scope_spans:
                for span in scope_span.spans:
                    spans.append(
                        ExportedSpan(
                            service_name=service_name,
                            span_name=span.name,
                            trace_id=bytes(span.trace_id).hex(),
                            span_id=bytes(span.span_id).hex(),
                            parent_span_id=bytes(span.parent_span_id).hex()
                            if span.parent_span_id
                            else None,
                        )
                    )
    return spans


def wait_for_expected_spans() -> tuple[list[ExportedSpan], list[str], list[str]]:
    last_error: RuntimeError | None = None
    for _ in range(WAIT_ATTEMPTS):
        exported_spans = decode_exported_spans()
        service_names = {span.service_name for span in exported_spans}
        span_names = {span.span_name for span in exported_spans}
        rag_trace_ids = {
            span.trace_id
            for span in exported_spans
            if span.service_name == "smartcloud-x-rag-service"
        }
        knowledge_trace_ids = {
            span.trace_id
            for span in exported_spans
            if span.service_name == "smartcloud-x-knowledge-service"
        }
        shared_trace_ids = sorted(rag_trace_ids.intersection(knowledge_trace_ids))

        if "smartcloud-x-knowledge-service" not in service_names:
            last_error = RuntimeError(
                f"trace smoke did not observe knowledge-service spans: {sorted(service_names)}"
            )
        elif "smartcloud-x-rag-service" not in service_names:
            last_error = RuntimeError(
                f"trace smoke did not observe rag-service spans: {sorted(service_names)}"
            )
        else:
            missing_span_names = [
                expected_span
                for expected_span in (
                    "knowledge.search",
                    "knowledge.indexing.process_event",
                    "rag.retrieval.search_candidates",
                    "rag.answer.compose",
                )
                if expected_span not in span_names
            ]
            if missing_span_names:
                last_error = RuntimeError(
                    f"trace smoke missing expected spans {missing_span_names}: {sorted(span_names)}"
                )
            elif not shared_trace_ids:
                last_error = RuntimeError(
                    "trace smoke did not observe a shared trace ID between rag-service and knowledge-service"
                )
            else:
                return exported_spans, sorted(service_names), shared_trace_ids
        time.sleep(WAIT_SECONDS)
    raise last_error or RuntimeError("trace smoke did not observe the expected spans")


def start_uvicorn(label: str, cwd: Path, port: int, env: dict[str, str], log_dir: Path) -> ManagedProcess:
    log_path = log_dir / f"{label}.log"
    with log_path.open("wb") as handle:
        process = subprocess.Popen(
            [
                PYTHON_BIN,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=str(cwd),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    return ManagedProcess(label=label, process=process, log_path=log_path)


def run_worker_once(cwd: Path, env: dict[str, str], log_dir: Path) -> Path:
    log_path = log_dir / "knowledge-indexer.log"
    with log_path.open("wb") as handle:
        completed = subprocess.run(
            [
                PYTHON_BIN,
                "-m",
                "app.worker",
                "--once",
                "--processor-id",
                "trace-smoke-worker",
                "--max-events",
                "4",
            ],
            cwd=str(cwd),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            timeout=max(REQUEST_TIMEOUT * WAIT_ATTEMPTS, 10),
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(
            "trace smoke worker run failed:\n"
            f"{log_path.read_text(encoding='utf-8', errors='replace')}"
        )
    return log_path


def build_env(overrides: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def main() -> int:
    collector_server = None
    collector_thread = None
    managed_processes: list[ManagedProcess] = []

    try:
        collector_server, collector_thread = start_trace_collector()
        collector_endpoint = f"http://127.0.0.1:{collector_server.server_port}"
        knowledge_port = reserve_port()
        rag_port = reserve_port()

        with tempfile.TemporaryDirectory(prefix="smartcloud-trace-smoke-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            log_dir = temp_dir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            knowledge_runtime = temp_dir / "knowledge-runtime"
            knowledge_import_root = temp_dir / "imports"
            knowledge_import_root.mkdir(parents=True, exist_ok=True)
            starter_catalog_path = temp_dir / "starter-catalog.json"
            starter_catalog_path.write_text(json.dumps({"documents": []}, ensure_ascii=False), encoding="utf-8")

            knowledge_env = build_env(
                {
                    "SMARTCLOUD_TRACE_ENABLED": "true",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": collector_endpoint,
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                    "OTEL_BSP_SCHEDULE_DELAY": "200",
                    "SMARTCLOUD_KNOWLEDGE_DATA_PATH": str(knowledge_runtime / "knowledge-store.json"),
                    "SMARTCLOUD_KNOWLEDGE_AUDIT_PATH": str(knowledge_runtime / "knowledge-admin-audit.jsonl"),
                    "SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH": str(knowledge_runtime / "knowledge-indexing-outbox.jsonl"),
                    "SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT": str(knowledge_runtime / "raw-objects"),
                    "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT": str(knowledge_import_root),
                    "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH": str(starter_catalog_path),
                    "OTEL_SERVICE_NAME": "smartcloud-x-knowledge-service",
                }
            )
            rag_env = build_env(
                {
                    "SMARTCLOUD_TRACE_ENABLED": "true",
                    "OTEL_EXPORTER_OTLP_ENDPOINT": collector_endpoint,
                    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
                    "OTEL_BSP_SCHEDULE_DELAY": "200",
                    "OTEL_SERVICE_NAME": "smartcloud-x-rag-service",
                    "KNOWLEDGE_SERVICE_BASE_URL": f"http://127.0.0.1:{knowledge_port}",
                    "SMARTCLOUD_RAG_CACHE_ENABLED": "false",
                }
            )

            managed_processes.append(
                start_uvicorn("knowledge-service", KNOWLEDGE_ROOT, knowledge_port, knowledge_env, log_dir)
            )
            wait_for_ready(f"http://127.0.0.1:{knowledge_port}/healthz", "knowledge-service")

            managed_processes.append(
                start_uvicorn("rag-service", RAG_ROOT, rag_port, rag_env, log_dir)
            )
            wait_for_ready(f"http://127.0.0.1:{rag_port}/healthz", "rag-service")

            ingest_payload = request(
                "POST",
                f"http://127.0.0.1:{knowledge_port}/api/knowledge/v1/documents:ingest",
                {
                    "source": {
                        "name": "Trace Smoke KB",
                        "kind": "product",
                        "uri": "kb://trace-smoke",
                        "tags": ["trace", "smoke"],
                    },
                    "title": "Trace Smoke Validation",
                    "content": "Trace Smoke Validation 会触发知识服务和 RAG 服务的 OTLP 导出，用于验证 Phoenix 兼容链路。",
                    "tags": ["trace", "smoke"],
                },
            )
            if ingest_payload.get("success") is not True:
                raise RuntimeError(f"knowledge ingestion failed during trace smoke: {ingest_payload}")
            wait_for_trace_exports(1, "knowledge-service")

            run_worker_once(KNOWLEDGE_ROOT, knowledge_env, log_dir)
            wait_for_trace_exports(2, "knowledge-indexer")

            answer_payload = request(
                "POST",
                f"http://127.0.0.1:{rag_port}/api/rag/v1/answer",
                {
                    "query": "Trace Smoke Validation 需要验证什么",
                    "topK": 3,
                    "style": "brief",
                    "filters": {"tags": ["trace", "smoke"]},
                },
            )
            if answer_payload.get("success") is not True:
                raise RuntimeError(f"rag answer failed during trace smoke: {answer_payload}")
            if answer_payload.get("data", {}).get("degraded") is True:
                raise RuntimeError(f"rag answer degraded unexpectedly during trace smoke: {answer_payload}")
            wait_for_trace_exports(3, "rag-service")
            exported_spans, service_names, shared_trace_ids = wait_for_expected_spans()

            summary = {
                "collectorEndpoint": collector_endpoint,
                "knowledgePort": knowledge_port,
                "ragPort": rag_port,
                "traceBatches": len(TraceCollectorHandler.requests),
                "traceServices": sorted(service_names),
                "sharedTraceIds": shared_trace_ids[:3],
                "answerCitationCount": len(answer_payload.get("data", {}).get("citations", [])),
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
    except Exception as exc:  # noqa: BLE001 - smoke should print useful diagnostics on failure
        print(f"trace smoke failed: {exc}", file=sys.stderr)
        for managed in managed_processes:
            print(f"\n--- {managed.label} log ---", file=sys.stderr)
            print(managed.log_text(), file=sys.stderr)
        return 1
    finally:
        for managed in reversed(managed_processes):
            managed.stop()
        if collector_server is not None:
            collector_server.shutdown()
        if collector_thread is not None:
            collector_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
