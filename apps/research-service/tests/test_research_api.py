import importlib
import json
from datetime import UTC, datetime, timedelta
from threading import Barrier, Thread

from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult, SpanExporter


def _user_headers(
    token_codec,
    *permissions: str,
    user_id: str = "u_10001",
    tenant_id: str = "default",
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    token = token_codec.issue_access_token(
        subject_type="user",
        subject_id=user_id,
        tenant_id=tenant_id,
        roles=["user"],
        permissions=list(permissions),
    ).token
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers




def _extract_embedded_json(pdf_bytes: bytes) -> dict[str, object]:
    marker = b"stream\n"
    scan = 0
    while scan < len(pdf_bytes):
        start = pdf_bytes.find(marker, scan)
        if start == -1:
            break
        start += len(marker)
        end = pdf_bytes.find(b"\nendstream", start)
        if end == -1:
            break
        chunk = pdf_bytes[start:end]
        try:
            payload = json.loads(chunk.decode("utf-8"))
        except Exception:
            scan = end + len(b"\nendstream")
            continue
        if isinstance(payload, dict) and "markdown" in payload:
            return payload
        scan = end + len(b"\nendstream")
    raise AssertionError("embedded json payload not found")


class _MemoryExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        return None


def _memory_tracer_provider(service_modules):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({"service.name": "research-service-test"}))
    exporter = _MemoryExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def test_create_research_task_and_poll_completed_detail(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "research-req-000"}),
        json={
            "topic": "LangGraph vs CrewAI",
            "scope": "客服编排能力对比",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": ["https://docs.langchain.com/oss/python/langgraph/overview"],
        },
    )
    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["status"] == "completed"

    detail = client.get(
        f"/api/v1/research/tasks/{payload['task_id']}",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["status"] == "completed"
    assert detail_data["progress"] == 100
    assert detail_data["report_file_id"].startswith("file_report_")


def test_research_status_and_result_alias_routes_return_rendered_outputs(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            "user:research.read",
            extra={"Idempotency-Key": "research-req-010"},
        ),
        json={
            "topic": "云客服行业调研",
            "scope": "竞品和落地建议",
            "depth": "deep",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 202
    task_id = response.json()["data"]["task_id"]

    status = client.get(
        f"/api/v1/research/tasks/{task_id}/status",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert status.status_code == 200
    status_data = status.json()["data"]
    assert status_data["status"] == "completed"
    assert status_data["result_ready"] is True

    result = client.get(
        f"/api/v1/research/tasks/{task_id}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert result.status_code == 200
    result_data = result.json()["data"]
    assert result_data["report_file_id"].startswith("research_")
    assert result_data["download_url"].startswith("/research_")
    assert result_data["preview_text"].startswith("# 云客服行业调研")
    assert result_data["sections"][0]["title"] == "研究范围"
    assert "关键发现" in result_data["preview_text"]
    assert result_data["metadata"]["provider"] == "baseline"
    artifact_path = result_data["metadata"]["artifact_path"]
    with open(artifact_path, encoding="utf-8") as exported:
        exported_markdown = exported.read()
    assert exported_markdown.startswith("# 云客服行业调研")
    assert "输入参考链接" not in exported_markdown

    report = client.get(
        f"/api/v1/research/tasks/{task_id}/report",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert report.status_code == 200
    assert report.json()["data"] == result_data


def test_research_result_varies_by_topic_scope_and_reference_urls(client, token_codec) -> None:
    first = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", "user:research.read", extra={"Idempotency-Key": "research-variant-001"}),
        json={
            "topic": "私有化部署客服大模型",
            "scope": "关注 GPU 成本、上线周期、运维人力",
            "depth": "deep",
            "output_format": "markdown",
            "reference_urls": ["https://example.com/gpu-cost", "https://example.com/deployment-playbook"],
        },
    )
    second = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", "user:research.read", extra={"Idempotency-Key": "research-variant-002"}),
        json={
            "topic": "出海电商客服自动化",
            "scope": "关注多语言响应、SLA、跨时区团队协作",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": ["https://example.org/global-support"],
        },
    )
    assert first.status_code == 202
    assert second.status_code == 202

    first_result = client.get(
        f"/api/v1/research/tasks/{first.json()['data']['task_id']}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    second_result = client.get(
        f"/api/v1/research/tasks/{second.json()['data']['task_id']}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert first_result.status_code == 200
    assert second_result.status_code == 200
    first_data = first_result.json()["data"]
    second_data = second_result.json()["data"]
    assert first_data["summary"] != second_data["summary"]
    assert first_data["sections"][1]["content"] != second_data["sections"][1]["content"]
    assert first_data["citations"] != second_data["citations"]
    assert first_data["metadata"]["reference_domains"] == ["example.com"]
    assert second_data["metadata"]["reference_domains"] == ["example.org"]


def test_pdf_export_contains_embedded_markdown_payload(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            "user:research.read",
            extra={"Idempotency-Key": "research-pdf-embedded-001"},
        ),
        json={
            "topic": "PDF 导出验证",
            "scope": "确认 pdf 导出包含可恢复 markdown 内容",
            "depth": "standard",
            "output_format": "pdf",
            "reference_urls": ["https://example.com/pdf-proof"],
        },
    )
    assert response.status_code == 202
    task_id = response.json()["data"]["task_id"]

    result = client.get(
        f"/api/v1/research/tasks/{task_id}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert result.status_code == 200
    result_data = result.json()["data"]
    artifact_path = result_data["metadata"]["artifact_path"]
    with open(artifact_path, "rb") as exported:
        pdf_bytes = exported.read()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    embedded = _extract_embedded_json(pdf_bytes)
    assert embedded["topic"] == "PDF 导出验证"
    assert "确认 pdf 导出包含可恢复 markdown 内容" in embedded["markdown"]
    assert "https://example.com/pdf-proof" in embedded["markdown"]
    assert result_data["metadata"]["artifact_checksum_sha256"]


def test_research_capabilities_reports_external_search_stub_when_configured(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_EXTERNAL_SEARCH_PROVIDER", "http_stub")
    monkeypatch.setenv("RESEARCH_EXTERNAL_SEARCH_API_URL", "http://127.0.0.1:9/search")
    service_modules["config"].get_settings.cache_clear()

    response = client.get(
        "/api/v1/research/capabilities",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["capabilities"]["search_provider"]["provider"] == "http_stub"
    assert data["capabilities"]["search_provider"]["configured"] is True
    assert data["capabilities"]["real_report_generation"] is True
    assert data["capabilities"]["external_search_mode"] == "http_stub"
    assert data["configuration"]["external_search"]["provider"] == "http_stub"
    assert data["configuration"]["real_markdown_export"] is True
    assert data["configuration"]["real_pdf_export"] is True
    assert data["configuration"]["real_report_generation"] is True


def test_research_result_includes_external_search_stub_hits(service_modules, monkeypatch) -> None:
    search_module = importlib.import_module("app.services.research_agent")

    class FakeSearchProvider:
        def __init__(self) -> None:
            self.requests = []

        def search(self, *, topic: str, scope: str, reference_urls: list[str]) -> list[dict[str, str]]:
            self.requests.append({"topic": topic, "scope": scope, "reference_urls": list(reference_urls)})
            return [
                {
                    "title": "外部检索结果 1",
                    "url": "https://search.example.com/result-1",
                    "snippet": f"{topic} 的外部证据",
                }
            ]

        def capabilities(self) -> dict[str, object]:
            return {
                "provider": "http_stub",
                "configured": True,
                "real_search": True,
                "transport": "http",
            }

    fake_provider = FakeSearchProvider()
    monkeypatch.setattr(search_module, "get_external_search_provider", lambda: fake_provider)
    result = search_module._build_placeholder_result(  # noqa: SLF001
        service_modules["models"].ResearchTask(
            task_id="task_search_demo",
            status="completed",
            topic="external search adapter",
            scope="验证最小 http stub 检索能力",
            depth="standard",
            output_format="markdown",
            progress=100,
            created_at=service_modules["models"].utc_now().isoformat(),
            updated_at=service_modules["models"].utc_now().isoformat(),
            summary=None,
            report_file_id=None,
            started_at=None,
            finished_at=None,
            error_message=None,
            reference_urls=[],
        )
    )
    assert fake_provider.requests and fake_provider.requests[0]["topic"] == "external search adapter"
    assert fake_provider.requests[0]["reference_urls"] == []
    assert any(section.title == "外部检索补充" for section in result.sections)
    assert any(citation.url == "https://search.example.com/result-1" for citation in result.citations)
    assert result.metadata["external_search_provider"] == "http_stub"
    assert result.metadata["external_search_hits"] == 1
    assert "search.example.com" in result.metadata["reference_domains"]


def test_research_result_route_prefers_mongo_document_runtime(client, token_codec, service_modules, monkeypatch) -> None:
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            "user:research.read",
            extra={"Idempotency-Key": "research-mongo-001"},
        ),
        json={
            "topic": "Mongo 报告主链",
            "scope": "验证 result 路由优先使用 Mongo 文档",
            "depth": "deep",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    result_model = service_modules["models"].ResearchTaskResultData
    routes_module = importlib.import_module("app.routes")

    class FakeMongoRuntime:
        enabled = True

        async def upsert_report(self, task, *, report_download_base_url):
            return result_model(
                task_id=task.task_id,
                status=task.status,
                result_ready=True,
                output_format=task.output_format,
                summary="来自 Mongo 文档存储的研究摘要",
                report_file_id="mongo-report-001",
                download_url=f"{report_download_base_url.rstrip('/')}/mongo-report-001.md",
                preview_text="# Mongo 主链报告\n\n## 证据\n- result 路由已读取 Mongo 文档。",
                citations=["mongo://research/report/mongo-report-001"],
                generated_at=task.finished_at,
                sections=[{"title": "证据", "content": "result 路由已读取 Mongo 文档。"}],
                metadata={"source": "mongo"},
            )

        async def readiness(self):
            return type("Ready", (), {"ready": True, "details": {"configured": True}})()

    monkeypatch.setattr(routes_module, "get_research_mongo_runtime", lambda: FakeMongoRuntime())
    result = client.get(
        f"/api/v1/research/tasks/{task_id}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert result.status_code == 200
    result_data = result.json()["data"]
    assert result_data["summary"] == "来自 Mongo 文档存储的研究摘要"
    assert result_data["report_file_id"] == "mongo-report-001"
    assert result_data["preview_text"].startswith("# Mongo 主链报告")
    assert result_data["citations"] == ["mongo://research/report/mongo-report-001"]


def test_research_task_can_surface_running_state_before_auto_completion(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS", "10")
    service_modules["config"].get_settings.cache_clear()

    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            "user:research.read",
            extra={"Idempotency-Key": "research-req-running"},
        ),
        json={
            "topic": "异步研究进度",
            "scope": "验证运行中状态",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 202
    task_id = response.json()["data"]["task_id"]

    store = service_modules["store"].get_research_store()
    task = store._snapshot.tasks[0]
    task.agent_result = None
    task.created_at = (service_modules["models"].utc_now() - timedelta(seconds=5)).isoformat()
    task.updated_at = task.created_at
    task.status = "queued"
    task.summary = None
    task.report_file_id = None
    store._persist()

    running = client.get(
        f"/api/v1/research/tasks/{task_id}",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert running.status_code == 200
    running_data = running.json()["data"]
    assert running_data["status"] == "running"
    assert 15 <= running_data["progress"] < 100
    assert running_data["started_at"] is not None
    assert running_data["report_file_id"] is None


def test_research_task_listing_handles_mixed_naive_and_aware_datetimes(service_modules) -> None:
    store_module = service_modules["store"]
    models = service_modules["models"]
    store = store_module.get_research_store()
    now = models.utc_now()

    with store._session_factory.begin() as session:
        session.add_all(
            [
                store_module.ResearchTaskRow(
                    task_id="task_completed_001",
                    user_id="u_10001",
                    tenant_id="default",
                    topic="已完成任务",
                    scope="验证排序兼容性",
                    depth="lite",
                    output_format="markdown",
                    reference_urls=[],
                    status="completed",
                    progress=100,
                    created_at=(now - timedelta(seconds=120)).replace(tzinfo=None),
                    updated_at=(now - timedelta(seconds=120)).replace(tzinfo=None),
                    summary="completed",
                    report_file_id="file_report_task_completed_001",
                    started_at=None,
                    finished_at=(now - timedelta(seconds=60)).replace(tzinfo=None),
                    error_message=None,
                    deleted_at=None,
                    agent_result=None,
                ),
                store_module.ResearchTaskRow(
                    task_id="task_running_001",
                    user_id="u_10001",
                    tenant_id="default",
                    topic="进行中任务",
                    scope="验证排序兼容性",
                    depth="standard",
                    output_format="markdown",
                    reference_urls=[],
                    status="queued",
                    progress=10,
                    created_at=(now - timedelta(seconds=120)).replace(tzinfo=None),
                    updated_at=(now - timedelta(seconds=120)).replace(tzinfo=None),
                    summary=None,
                    report_file_id=None,
                    started_at=None,
                    finished_at=None,
                    error_message=None,
                    deleted_at=None,
                    agent_result=None,
                ),
            ]
        )

    listing = store.list_tasks(
        user_id="u_10001",
        tenant_id="default",
        page=1,
        page_size=20,
        sort_by="updated_at",
        sort_order="desc",
        status=None,
    )

    assert listing.total == 2
    assert [item.task_id for item in listing.items] == ["task_running_001", "task_completed_001"]
    assert listing.items[0].status in {"running", "completed"}


def test_research_task_creation_requires_idempotency_key(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write"),
        json={
            "topic": "缺少幂等键",
            "scope": "验证请求头校验",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == 4001001
    assert payload["error"]["field"] == "Idempotency-Key"


def test_research_task_idempotency_replays_first_acceptance(client, token_codec) -> None:
    headers = {
        **_user_headers(token_codec, "user:research.write", "user:research.read"),
        "Idempotency-Key": "research-req-001",
    }
    body = {
        "topic": "GPU 云主机选型",
        "scope": "生产环境建议",
        "depth": "deep",
        "output_format": "markdown",
        "reference_urls": [],
    }
    first = client.post("/api/v1/research/tasks", headers=headers, json=body)
    second = client.post("/api/v1/research/tasks", headers=headers, json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"] == second.json()["data"]


def test_pdf_export_writes_real_pdf_artifact(service_modules) -> None:
    renderer_module = importlib.import_module("app.services.report_renderer")
    artifact = renderer_module.render_research_artifact(
        service_modules["models"].ResearchTask(
            task_id="task_pdf_export",
            status="completed",
            topic="PDF 导出验证",
            scope="验证最小真实 PDF 导出闭环",
            depth="standard",
            output_format="pdf",
            progress=100,
            created_at=service_modules["models"].utc_now().isoformat(),
            updated_at=service_modules["models"].utc_now().isoformat(),
            summary="验证 PDF 导出",
            report_file_id=None,
            started_at=None,
            finished_at=service_modules["models"].utc_now().isoformat(),
            error_message=None,
            reference_urls=["https://example.com/pdf-proof"],
        ),
        service_modules["models"].ResearchResult(
            summary="PDF 导出测试摘要",
            sections=[service_modules["models"].ResearchSection(title="结论", content="已生成最小真实 PDF 二进制产物。")],
            citations=[service_modules["models"].ResearchCitation(title="PDF 证据", url="https://example.com/pdf-proof", snippet="导出验证")],
            metadata={"provider": "unit-test"},
        ),
    )
    assert artifact.file_path.suffix == ".pdf"
    pdf_bytes = artifact.file_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert b"%%EOF" in pdf_bytes
    assert artifact.metadata["rendered_format"] == "pdf"
    assert artifact.download_url.endswith(".pdf")


def test_research_task_idempotency_conflict_returns_409(client, token_codec) -> None:
    headers = {
        **_user_headers(token_codec, "user:research.write"),
        "Idempotency-Key": "research-req-002",
    }
    first = client.post(
        "/api/v1/research/tasks",
        headers=headers,
        json={
            "topic": "A",
            "scope": "范围A",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert first.status_code == 202

    conflict = client.post(
        "/api/v1/research/tasks",
        headers=headers,
        json={
            "topic": "B",
            "scope": "范围B",
            "depth": "deep",
            "output_format": "pdf",
            "reference_urls": [],
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == 4090001


def test_research_tasks_and_idempotency_are_tenant_scoped(client, token_codec) -> None:
    body = {
        "topic": "多租户调研",
        "scope": "验证任务隔离",
        "depth": "lite",
        "output_format": "markdown",
        "reference_urls": [],
    }
    first = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            user_id="u_10001",
            tenant_id="tenant-a",
            extra={"Idempotency-Key": "research-tenant-key"},
        ),
        json=body,
    )
    second = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            user_id="u_10001",
            tenant_id="tenant-b",
            extra={"Idempotency-Key": "research-tenant-key"},
        ),
        json=body,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["data"]["task_id"] != second.json()["data"]["task_id"]


def test_research_routes_require_valid_user_permissions(client, token_codec) -> None:
    unauthorized = client.get("/api/v1/research/tasks")
    assert unauthorized.status_code == 401

    forbidden = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:marketing.read"),
    )
    assert forbidden.status_code == 403


def test_research_routes_reject_refresh_like_tokens(client, token_codec) -> None:
    access = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        tenant_id="default",
        roles=["user"],
        permissions=["user:research.read"],
    )
    refresh_like_claims = dict(access.claims)
    refresh_like_claims["token_type"] = "refresh"
    refresh_like_token = token_codec._encode(refresh_like_claims)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/research/tasks",
        headers={"Authorization": f"Bearer {refresh_like_token}"},
    )
    assert response.status_code == 401


def test_research_routes_reject_internal_audience_user_tokens(client, token_codec, service_modules) -> None:
    settings = service_modules["config"].get_settings()
    public_access = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        tenant_id="default",
        roles=["user"],
        permissions=["user:research.read"],
    )
    internal_audience_claims = dict(public_access.claims)
    internal_audience_claims["aud"] = settings.internal_auth_audience
    internal_audience_token = token_codec._encode(internal_audience_claims)  # type: ignore[attr-defined]

    response = client.get(
        "/api/v1/research/tasks",
        headers={"Authorization": f"Bearer {internal_audience_token}"},
    )
    assert response.status_code == 401


def test_research_can_opt_into_strict_auth_current_state_validation(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def allow(_request, _token, *, settings):
        assert settings.internal_service_name == "research-service"
        return {
            "subject_type": "user",
            "subject_id": "u_10001",
            "tenant_id": "default",
            "roles": ["user"],
            "permissions": ["user:research.read"],
            "expired_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", allow)

    response = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 200


def test_research_strict_auth_validation_rejects_stale_token(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def reject(_request, _token, *, settings):
        raise service_modules["models"].ServiceError(401, 4010002, "token is no longer valid")

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", reject)

    response = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 401
    assert response.json()["message"] == "token is no longer valid"


def test_research_strict_auth_uses_validated_permissions_even_when_empty(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTH_VALIDATION_MODE", "strict")
    monkeypatch.setenv(
        "RESEARCH_SERVICE_AUTH_VALIDATE_TOKEN_URL",
        "http://auth-user-service.local/internal/v1/auth/validate-token",
    )
    service_modules["config"].get_settings.cache_clear()

    def allow_without_permissions(_request, _token, *, settings):
        return {
            "subject_type": "user",
            "subject_id": "u_10001",
            "tenant_id": "default",
            "roles": [],
            "permissions": [],
            "expired_at": "2099-01-01T00:00:00+00:00",
        }

    monkeypatch.setattr(service_modules["dependencies"], "_validate_token_with_auth_service", allow_without_permissions)

    response = client.get(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 403
    assert response.json()["message"] == "missing required permissions"


def test_openapi_publishes_status_and_result_routes(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/research/tasks/{task_id}/status" in paths
    assert "/api/v1/research/tasks/{task_id}/result" in paths
    assert "/api/v1/research/tasks/{task_id}/cancel" in paths
    assert "/api/v1/research/capabilities" in paths


def test_research_database_persists_tasks_across_store_reload(client, token_codec, service_modules) -> None:
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(
            token_codec,
            "user:research.write",
            extra={"Idempotency-Key": "research-db-persist"},
        ),
        json={
            "topic": "数据库持久化调研",
            "scope": "验证跨 store reload 持久化",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    service_modules["store"].get_research_store.cache_clear()
    reloaded_store = service_modules["store"].get_research_store()
    assert any(item.task_id == task_id for item in reloaded_store._snapshot.tasks)


def test_healthz_reports_runtime_backend_evidence_for_local_fallback(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "research-service"
    assert payload["runtime_mode"] == "local-fallback"
    assert payload["backends"]["sqlite"]["kind"] == "sqlite"
    assert payload["backends"]["mongodb"]["active"] is False


def test_metrics_endpoint_exposes_research_metrics(client, token_codec) -> None:
    client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "metrics-create"}),
        json={
            "topic": "metrics",
            "scope": "collect",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "research_requests_total" in response.text
    assert "research_tasks_created_total" in response.text


def test_metrics_endpoint_counters_change_after_task_flow(client, token_codec) -> None:
    key = "metrics-counters"
    body = {
        "topic": "metrics counters",
        "scope": "track increments",
        "depth": "deep",
        "output_format": "markdown",
        "reference_urls": [],
    }
    create_headers = _user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": key})
    read_headers = _user_headers(token_codec, "user:research.read")

    baseline_metrics = client.get("/metrics")
    assert baseline_metrics.status_code == 200
    before_text = baseline_metrics.text

    create = client.post("/api/v1/research/tasks", headers=create_headers, json=body)
    assert create.status_code == 202
    task_id = create.json()["data"]["task_id"]

    replay = client.post("/api/v1/research/tasks", headers=create_headers, json=body)
    assert replay.status_code == 202

    result = client.get(f"/api/v1/research/tasks/{task_id}/result", headers=read_headers)
    assert result.status_code == 200

    after_metrics = client.get("/metrics")
    assert after_metrics.status_code == 200
    after_text = after_metrics.text

    assert 'research_tasks_created_total 1.0' not in before_text or 'research_tasks_created_total 2.0' in after_text or 'research_tasks_created_total 1.0' in after_text
    assert 'research_tasks_created_total' in after_text
    assert 'research_tasks_completed_total' in after_text
    assert 'research_idempotency_replays_total' in after_text
    assert 'research_requests_total{depth="deep",operation="create_task",status="completed"} ' in after_text
    assert 'research_requests_total{depth="deep",operation="get_task_result",status="completed"} ' in after_text


def test_capabilities_endpoint_returns_active_provider(client, token_codec) -> None:
    response = client.get(
        "/api/v1/research/capabilities",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "placeholder"
    assert data["capabilities"]["progress_callbacks"] is True


def test_capabilities_endpoint_reports_http_provider_configuration(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "http")
    monkeypatch.setenv("RESEARCH_AGENT_API_URL", "https://agent.example.test/research")
    monkeypatch.setenv("RESEARCH_AGENT_API_KEY", "secret-token")
    monkeypatch.setenv("RESEARCH_AGENT_TIMEOUT_SECONDS", "7")
    service_modules["config"].get_settings.cache_clear()

    response = client.get(
        "/api/v1/research/capabilities",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "http"
    assert data["capabilities"]["external_search"] is True
    assert data["configuration"]["api_url_configured"] is True
    assert data["configuration"]["api_key_configured"] is True
    assert data["configuration"]["timeout_seconds"] == 7.0


def test_cancel_queued_task(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS", "30")
    service_modules["config"].get_settings.cache_clear()
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "cancel-queued"}),
        json={
            "topic": "cancel queued",
            "scope": "queued",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]
    store = service_modules["store"].get_research_store()
    record = store.get_task_record(user_id="u_10001", tenant_id="default", task_id=task_id)
    record.status = "queued"
    record.agent_result = None
    record.summary = None
    record.report_file_id = None
    store._persist()
    cancelled = client.post(
        f"/api/v1/research/tasks/{task_id}/cancel",
        headers=_user_headers(token_codec, "user:research.write"),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"


def test_cancel_completed_task_returns_error(client, token_codec) -> None:
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "cancel-completed"}),
        json={
            "topic": "cancel completed",
            "scope": "completed",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    task_id = created.json()["data"]["task_id"]
    response = client.post(
        f"/api/v1/research/tasks/{task_id}/cancel",
        headers=_user_headers(token_codec, "user:research.write"),
    )
    assert response.status_code == 409


def test_cancel_running_task_updates_status_and_metric(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS", "30")
    service_modules["config"].get_settings.cache_clear()
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "cancel-running"}),
        json={
            "topic": "cancel running",
            "scope": "running state",
            "depth": "standard",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    store = service_modules["store"].get_research_store()
    record = store.get_task_record(user_id="u_10001", tenant_id="default", task_id=task_id)
    record.status = "running"
    record.progress = 55
    record.summary = None
    record.report_file_id = None
    record.agent_result = None
    record.started_at = record.started_at or record.created_at
    record.finished_at = None
    store._persist()

    before_metrics = client.get("/metrics")
    assert before_metrics.status_code == 200

    cancelled = client.post(
        f"/api/v1/research/tasks/{task_id}/cancel",
        headers=_user_headers(token_codec, "user:research.write"),
    )
    assert cancelled.status_code == 200
    data = cancelled.json()["data"]
    assert data["status"] == "cancelled"
    assert data["error_message"] == "cancelled by user"

    detail = client.get(
        f"/api/v1/research/tasks/{task_id}",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "cancelled"

    after_metrics = client.get("/metrics")
    assert after_metrics.status_code == 200
    assert 'task_cancelled_total' in after_metrics.text


def test_delete_archives_terminal_task(client, token_codec) -> None:
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "delete-terminal"}),
        json={
            "topic": "delete terminal",
            "scope": "archive",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    task_id = created.json()["data"]["task_id"]
    response = client.delete(
        f"/api/v1/research/tasks/{task_id}",
        headers=_user_headers(token_codec, "user:research.write"),
    )
    assert response.status_code == 200
    listing = client.get("/api/v1/research/tasks", headers=_user_headers(token_codec, "user:research.read"))
    assert listing.json()["data"]["total"] == 0


def test_delete_non_terminal_task_returns_error(client, token_codec, service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_SERVICE_AUTO_COMPLETE_SECONDS", "30")
    service_modules["config"].get_settings.cache_clear()
    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "delete-running"}),
        json={
            "topic": "delete running",
            "scope": "must fail",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert created.status_code == 202
    task_id = created.json()["data"]["task_id"]

    store = service_modules["store"].get_research_store()
    record = store.get_task_record(user_id="u_10001", tenant_id="default", task_id=task_id)
    record.status = "running"
    record.progress = 40
    record.summary = None
    record.report_file_id = None
    record.agent_result = None
    record.finished_at = None
    store._persist()

    response = client.delete(
        f"/api/v1/research/tasks/{task_id}",
        headers=_user_headers(token_codec, "user:research.write"),
    )
    assert response.status_code == 409
    assert response.json()["message"] == "only terminal tasks can be deleted"


def test_readyz_reports_database_and_mongo_state(client) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["checks"]["database"]["ready"] is True
    assert payload["checks"]["mongodb"]["configured"] is False


def test_readyz_reports_degraded_when_database_probe_fails(client, service_modules, monkeypatch) -> None:
    routes_module = importlib.import_module("app.routes")
    store = service_modules["store"].get_research_store()

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            raise RuntimeError("database probe failed")

    monkeypatch.setattr(store, "_session", lambda: BrokenSession())
    monkeypatch.setattr(routes_module, "get_research_store", lambda: store)

    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["ready"] is False
    assert payload["checks"]["database"]["ready"] is False
    assert "database probe failed" in payload["checks"]["database"]["error"]


def test_readyz_reports_degraded_when_mongo_probe_fails(client, monkeypatch) -> None:
    routes_module = importlib.import_module("app.routes")

    class BrokenMongoRuntime:
        enabled = True

        async def readiness(self):
            return type(
                "Ready",
                (),
                {
                    "ready": False,
                    "details": {
                        "configured": True,
                        "backend": "mongodb",
                        "error": "ServerSelectionTimeoutError",
                        "message": "mongo probe failed",
                    },
                },
            )()

    monkeypatch.setattr(routes_module, "get_research_mongo_runtime", lambda: BrokenMongoRuntime())

    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["database"]["ready"] is True
    assert payload["checks"]["mongodb"]["ready"] is False
    assert payload["checks"]["mongodb"]["error"] == "ServerSelectionTimeoutError"


def test_concurrent_task_creation_same_idempotency_key_replays_single_task(service_modules, token_codec) -> None:
    client_factory = service_modules["main"].app
    barrier = Barrier(2)
    results = []

    def _worker():
        from fastapi.testclient import TestClient

        with TestClient(client_factory) as local_client:
            barrier.wait()
            results.append(
                local_client.post(
                    "/api/v1/research/tasks",
                    headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "concurrent-key"}),
                    json={
                        "topic": "并发创建",
                        "scope": "并发幂等",
                        "depth": "lite",
                        "output_format": "markdown",
                        "reference_urls": [],
                    },
                )
            )

    threads = [Thread(target=_worker), Thread(target=_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2
    payloads = [item.json()["data"] for item in results]
    assert payloads[0]["task_id"] == payloads[1]["task_id"]


def test_large_topic_and_scope_boundary_validation(client, token_codec) -> None:
    response = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "large-ok"}),
        json={
            "topic": "t" * 512,
            "scope": "s" * 4000,
            "depth": "deep",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert response.status_code == 202

    too_large = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "large-bad"}),
        json={
            "topic": "t" * 513,
            "scope": "ok",
            "depth": "deep",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    assert too_large.status_code == 400


def test_auth_token_edge_cases(client, token_codec) -> None:
    empty_bearer = client.get("/api/v1/research/tasks", headers={"Authorization": "Bearer "})
    assert empty_bearer.status_code == 401

    malformed = client.get("/api/v1/research/tasks", headers={"Authorization": "Bearer not-a-jwt"})
    assert malformed.status_code == 401

    expired = token_codec.issue_access_token(
        subject_type="user",
        subject_id="u_10001",
        tenant_id="default",
        roles=["user"],
        permissions=["user:research.read"],
    )
    expired_claims = dict(expired.claims)
    expired_claims["exp"] = int((datetime.now(UTC) - timedelta(seconds=60)).timestamp())
    expired_token = token_codec._encode(expired_claims)  # type: ignore[attr-defined]
    expired_response = client.get("/api/v1/research/tasks", headers={"Authorization": f"Bearer {expired_token}"})
    assert expired_response.status_code == 401

    wrong_audience_claims = dict(expired.claims)
    wrong_audience_claims["aud"] = "wrong-audience"
    wrong_audience_token = token_codec._encode(wrong_audience_claims)  # type: ignore[attr-defined]
    wrong_audience_response = client.get(
        "/api/v1/research/tasks",
        headers={"Authorization": f"Bearer {wrong_audience_token}"},
    )
    assert wrong_audience_response.status_code == 401


def test_mongo_runtime_fallback_behavior(client, token_codec, service_modules, monkeypatch) -> None:
    runtime_module = importlib.import_module("app.mongo_runtime")
    runtime = runtime_module.DisabledResearchMongoRuntime()
    result = runtime.describe_backend()
    assert result["backend"] == "inactive"

    created = client.post(
        "/api/v1/research/tasks",
        headers=_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "mongo-fallback"}),
        json={
            "topic": "fallback",
            "scope": "mongo disabled",
            "depth": "lite",
            "output_format": "markdown",
            "reference_urls": [],
        },
    )
    task_id = created.json()["data"]["task_id"]
    result_response = client.get(
        f"/api/v1/research/tasks/{task_id}/result",
        headers=_user_headers(token_codec, "user:research.read"),
    )
    assert result_response.status_code == 200
    assert result_response.json()["data"]["metadata"]["provider"] in {"baseline", "legacy-baseline"}


def test_http_research_agent_success_path(service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "http")
    monkeypatch.setenv("RESEARCH_AGENT_API_URL", "https://agent.example.test/research")
    monkeypatch.setenv("RESEARCH_AGENT_API_KEY", "secret-token")
    monkeypatch.setenv("RESEARCH_AGENT_TIMEOUT_SECONDS", "5")
    service_modules["config"].get_settings.cache_clear()

    agent_module = importlib.import_module("app.services.research_agent")
    task_model = service_modules["models"].ResearchTask
    observed = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "summary": "http summary",
                    "sections": [{"title": "发现", "content": "来自 HTTP agent"}],
                    "citations": [{"title": "Source", "url": "https://example.com"}],
                    "metadata": {"provider": "http"},
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(raw_request, timeout):
        observed["url"] = raw_request.full_url
        observed["method"] = raw_request.method
        observed["authorization"] = raw_request.headers.get("Authorization")
        observed["timeout"] = timeout
        observed["payload"] = raw_request.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr(agent_module.request, "urlopen", fake_urlopen)
    provider = agent_module.get_research_agent_provider()
    task = task_model(
        task_id="task_http_success",
        status="queued",
        topic="HTTP provider",
        scope="验证成功路径",
        depth="deep",
        output_format="markdown",
        progress=10,
        created_at="2026-04-21T00:00:00+00:00",
    )
    progress_updates = []
    result = __import__("asyncio").run(provider.execute(task, on_progress=lambda progress, note: progress_updates.append((progress, note))))

    assert result.summary == "http summary"
    assert result.sections[0].title == "发现"
    assert result.citations[0].url == "https://example.com"
    assert result.metadata["provider"] == "http"
    assert observed["url"] == "https://agent.example.test/research"
    assert observed["method"] == "POST"
    assert observed["authorization"] == "Bearer secret-token"
    assert observed["timeout"] == 5.0
    assert '"topic": "HTTP provider"' in observed["payload"]
    assert progress_updates == [(20, "http_agent_request_started"), (90, "http_agent_response_received")]


def test_http_research_agent_failure_path_marks_runtime_error(service_modules, monkeypatch) -> None:
    monkeypatch.setenv("RESEARCH_AGENT_PROVIDER", "http")
    monkeypatch.setenv("RESEARCH_AGENT_API_URL", "https://agent.example.test/research")
    service_modules["config"].get_settings.cache_clear()

    agent_module = importlib.import_module("app.services.research_agent")
    task_model = service_modules["models"].ResearchTask

    def fake_urlopen(_raw_request, timeout):
        raise agent_module.error.URLError("connect timeout")

    monkeypatch.setattr(agent_module.request, "urlopen", fake_urlopen)
    provider = agent_module.get_research_agent_provider()
    task = task_model(
        task_id="task_http_failure",
        status="queued",
        topic="HTTP provider failure",
        scope="验证失败路径",
        depth="standard",
        output_format="markdown",
        progress=10,
        created_at="2026-04-21T00:00:00+00:00",
    )

    import pytest

    with pytest.raises(RuntimeError, match="http research agent unavailable: connect timeout"):
        __import__("asyncio").run(provider.execute(task))


def test_open_telemetry_span_export_verification(service_modules, token_codec, monkeypatch) -> None:
    monkeypatch.setenv("SMARTCLOUD_TRACE_ENABLED", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel.test:4318")
    service_modules["config"].get_settings.cache_clear()
    service_modules["tracing"].get_tracer_provider.cache_clear()
    service_modules["tracing"].get_tracer.cache_clear()

    provider, exporter = _memory_tracer_provider(service_modules)
    monkeypatch.setattr(service_modules["tracing"], "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(service_modules["tracing"], "get_tracer", lambda: provider.get_tracer("research-service-test"))

    from fastapi.testclient import TestClient
    app = importlib.reload(importlib.import_module("app.main")).app
    with TestClient(app) as traced_client:
        response = traced_client.post(
            "/api/v1/research/tasks",
            headers={
                **_user_headers(token_codec, "user:research.write", extra={"Idempotency-Key": "otel-key", "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}),
                "X-Trace-Id": "trace-123",
            },
            json={
                "topic": "otel",
                "scope": "trace",
                "depth": "deep",
                "output_format": "markdown",
                "reference_urls": [],
            },
        )
        assert response.status_code == 202
        assert response.headers["X-Trace-Id"] == "trace-123"
        assert response.headers["traceparent"].startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-")
        assert response.headers["traceparent"].endswith("-01")
    assert any(span.name == "research.task.create" for span in exporter.spans)
    target = [span for span in exporter.spans if span.name == "research.task.create"][0]
    assert target.attributes["operation"] == "task_create"
    assert target.attributes["task_id"].startswith("task_")
    assert target.attributes["depth"] == "deep"
    assert target.attributes["output_format"] == "markdown"
    assert target.attributes["status"] == "completed"
