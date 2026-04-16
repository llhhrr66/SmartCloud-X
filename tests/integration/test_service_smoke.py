from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.qa_helpers.service_loader import assert_standard_headers, service_test_client


ROOT = Path(__file__).resolve().parents[2]
AUTH_ENV = {
    "SMARTCLOUD_JWT_SECRET": "qa-test-secret",
    "SMARTCLOUD_AUTH_ISSUER": "qa-test-issuer",
    "SMARTCLOUD_AUTH_AUDIENCE": "qa-test-audience",
}


def _copy_bootstrap(rel_path: str, destination: Path) -> Path:
    source = ROOT / rel_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def _sqlite_count(db_path: Path, table_name: str) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    assert row is not None
    return int(row[0])


def _issue_access_token(tmp_path: Path) -> str:
    bootstrap_path = _copy_bootstrap(
        "apps/auth-user-service/data/auth-store.json",
        tmp_path / "auth-store.json",
    )
    db_path = tmp_path / "auth-user-service.db"
    with service_test_client(
        "auth-user-service",
        env_overrides={
            **AUTH_ENV,
            "AUTH_USER_SERVICE_BOOTSTRAP_PATH": str(bootstrap_path),
            "AUTH_USER_SERVICE_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        },
    ) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "login_type": "password",
                "account": "demo@smartcloud.local",
                "password": "Password123!",
            },
        )
    assert response.status_code == 200
    assert_standard_headers(response.headers)
    return str(response.json()["data"]["access_token"])


def _knowledge_env(tmp_path: Path) -> dict[str, str]:
    return {
        "SMARTCLOUD_KNOWLEDGE_DATA_PATH": str(tmp_path / "knowledge-store.json"),
        "SMARTCLOUD_KNOWLEDGE_AUDIT_PATH": str(tmp_path / "knowledge-admin-audit.jsonl"),
        "SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH": str(tmp_path / "knowledge-indexing-outbox.jsonl"),
        "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH": str(
            ROOT / "apps/knowledge-service/data/starter-catalog.json"
        ),
        "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT": str(ROOT / "apps/knowledge-service/data/imports"),
        "SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT": str(tmp_path / "raw-objects"),
        "SMARTCLOUD_MINIO_ENDPOINT": "http://minio.qa.local:9000",
        "SMARTCLOUD_MINIO_BUCKET": "knowledge-raw",
        "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:smartcloud@mysql.qa.local:3306/smartcloud",
        "SMARTCLOUD_QDRANT_URL": "http://qdrant.qa.local:6333",
        "SMARTCLOUD_OPENSEARCH_URL": "http://opensearch.qa.local:9200",
        "SMARTCLOUD_REDIS_URL": "redis://redis.qa.local:6379/0",
    }


def test_auth_refresh_sessions_persist_in_sqlite_across_restart(tmp_path: Path) -> None:
    bootstrap_path = _copy_bootstrap(
        "apps/auth-user-service/data/auth-store.json",
        tmp_path / "auth-store.json",
    )
    original_bootstrap = bootstrap_path.read_text(encoding="utf-8")
    db_path = tmp_path / "auth-user-service.db"
    env = {
        **AUTH_ENV,
        "AUTH_USER_SERVICE_BOOTSTRAP_PATH": str(bootstrap_path),
        "AUTH_USER_SERVICE_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
    }

    with service_test_client("auth-user-service", env_overrides=env) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "login_type": "password",
                "account": "demo@smartcloud.local",
                "password": "Password123!",
            },
        )
        assert login.status_code == 200
        assert_standard_headers(login.headers)
        refresh = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": login.json()["data"]["refresh_token"]},
        )
        assert refresh.status_code == 200
        assert_standard_headers(refresh.headers)
        first_refresh_token = refresh.json()["data"]["refresh_token"]

    with service_test_client("auth-user-service", env_overrides=env) as restarted_client:
        refresh_after_restart = restarted_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": first_refresh_token},
        )
        assert refresh_after_restart.status_code == 200
        assert_standard_headers(refresh_after_restart.headers)
        second_refresh_token = refresh_after_restart.json()["data"]["refresh_token"]

    assert second_refresh_token != first_refresh_token
    assert _sqlite_count(db_path, "auth_refresh_sessions") >= 1
    assert bootstrap_path.read_text(encoding="utf-8") == original_bootstrap
    assert first_refresh_token not in bootstrap_path.read_text(encoding="utf-8")


def test_marketing_poster_tasks_persist_in_sqlite_across_restart(tmp_path: Path) -> None:
    access_token = _issue_access_token(tmp_path / "auth")
    bootstrap_path = _copy_bootstrap(
        "apps/marketing-service/data/marketing-store.json",
        tmp_path / "marketing-store.json",
    )
    original_bootstrap = bootstrap_path.read_text(encoding="utf-8")
    db_path = tmp_path / "marketing-service.db"
    env = {
        **AUTH_ENV,
        "MARKETING_SERVICE_BOOTSTRAP_PATH": str(bootstrap_path),
        "MARKETING_SERVICE_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
    }
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    with service_test_client("marketing-service", env_overrides=env) as client:
        campaigns = client.get(
            "/api/v1/marketing/campaigns?page=1&page_size=20",
            headers=auth_headers,
        )
        assert campaigns.status_code == 200
        assert_standard_headers(campaigns.headers)
        campaign_id = campaigns.json()["data"]["items"][0]["campaign_id"]

        copy = client.post(
            "/api/v1/marketing/copy/generate",
            headers=auth_headers,
            json={
                "campaign_id": campaign_id,
                "topic": "QA restart persistence",
                "audience": "integration smoke",
                "tone": "launch",
                "keywords": ["restart", "sqlite", "qa"],
            },
        )
        assert copy.status_code == 200
        assert_standard_headers(copy.headers)
        copy_id = copy.json()["data"]["copy_id"]

        promotion = client.post(
            "/api/v1/marketing/promotion-links/generate",
            headers=auth_headers,
            json={
                "campaign_id": campaign_id,
                "channel": "wechat",
                "source": "integration-smoke",
                "content_tag": "restart-proof",
            },
        )
        assert promotion.status_code == 200
        assert_standard_headers(promotion.headers)
        link_id = promotion.json()["data"]["link_id"]

        poster = client.post(
            "/api/v1/marketing/posters",
            headers={**auth_headers, "Idempotency-Key": "qa-marketing-poster-restart-001"},
            json={
                "campaign_id": campaign_id,
                "theme": "QA smoke baseline",
                "slogan": "marketing restart persistence",
                "size": "1080x1080",
            },
        )
        assert poster.status_code == 202
        assert_standard_headers(poster.headers)
        task_id = poster.json()["data"]["task_id"]

    with service_test_client("marketing-service", env_overrides=env) as restarted_client:
        copy_detail = restarted_client.get(
            f"/api/v1/marketing/copies/{copy_id}",
            headers=auth_headers,
        )
        assert copy_detail.status_code == 200
        assert_standard_headers(copy_detail.headers)
        assert copy_detail.json()["data"]["copy_id"] == copy_id

        promotion_detail = restarted_client.get(
            f"/api/v1/marketing/promotion-links/{link_id}",
            headers=auth_headers,
        )
        assert promotion_detail.status_code == 200
        assert_standard_headers(promotion_detail.headers)
        assert promotion_detail.json()["data"]["link_id"] == link_id

        detail = restarted_client.get(
            f"/api/v1/marketing/posters/{task_id}",
            headers=auth_headers,
        )
        assert detail.status_code == 200
        assert_standard_headers(detail.headers)
        assert detail.json()["data"]["task_id"] == task_id

    bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    assert _sqlite_count(db_path, "marketing_generated_copies") >= 1
    assert _sqlite_count(db_path, "marketing_promotion_links") >= 1
    assert _sqlite_count(db_path, "marketing_poster_tasks") >= 1
    assert _sqlite_count(db_path, "marketing_poster_idempotency_records") >= 1
    assert bootstrap_text == original_bootstrap
    assert copy_id not in bootstrap_text
    assert link_id not in bootstrap_text
    assert task_id not in bootstrap_text


def test_research_tasks_persist_in_sqlite_across_restart(tmp_path: Path) -> None:
    access_token = _issue_access_token(tmp_path / "auth")
    bootstrap_path = _copy_bootstrap(
        "apps/research-service/data/research-store.json",
        tmp_path / "research-store.json",
    )
    original_bootstrap = bootstrap_path.read_text(encoding="utf-8")
    db_path = tmp_path / "research-service.db"
    env = {
        **AUTH_ENV,
        "RESEARCH_SERVICE_BOOTSTRAP_PATH": str(bootstrap_path),
        "RESEARCH_SERVICE_DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
    }
    auth_headers = {"Authorization": f"Bearer {access_token}"}

    with service_test_client("research-service", env_overrides=env) as client:
        create = client.post(
            "/api/v1/research/tasks",
            headers={**auth_headers, "Idempotency-Key": "qa-research-restart-001"},
            json={
                "topic": "QA restart persistence",
                "scope": "Validate research runtime storage survives restart.",
                "depth": "standard",
                "output_format": "markdown",
                "reference_urls": [],
            },
        )
        assert create.status_code == 202
        assert_standard_headers(create.headers)
        task_id = create.json()["data"]["task_id"]

    with service_test_client("research-service", env_overrides=env) as restarted_client:
        detail = restarted_client.get(
            f"/api/v1/research/tasks/{task_id}",
            headers=auth_headers,
        )
        assert detail.status_code == 200
        assert_standard_headers(detail.headers)
        assert detail.json()["data"]["task_id"] == task_id

    assert _sqlite_count(db_path, "research_tasks") >= 1
    assert _sqlite_count(db_path, "research_idempotency_records") >= 1
    assert bootstrap_path.read_text(encoding="utf-8") == original_bootstrap
    assert task_id not in bootstrap_path.read_text(encoding="utf-8")


def test_knowledge_snapshot_surfaces_real_connector_targets_when_env_is_configured(tmp_path: Path) -> None:
    with service_test_client(
        "knowledge-service",
        env_overrides=_knowledge_env(tmp_path),
    ) as client:
        bootstrap = client.post("/api/knowledge/v1/catalog:bootstrap")
        assert bootstrap.status_code == 200
        assert_standard_headers(bootstrap.headers)

        snapshot = client.get("/api/knowledge/v1/snapshot?auditLimit=5")
        assert snapshot.status_code == 200
        assert_standard_headers(snapshot.headers)
        integrations = snapshot.json()["data"]["integrations"]

    assert integrations["rawStorage"]["backend"] == "minio"
    assert integrations["rawStorage"]["endpoint"] == "http://minio.qa.local:9000"
    assert integrations["metadataStore"]["backend"] == "mysql"
    assert integrations["vectorStore"]["backend"] == "qdrant"
    assert integrations["bm25Store"]["backend"] == "opensearch"
    assert integrations["cache"]["backend"] == "redis-configured"
    assert integrations["taskQueue"]["backend"] == "redis-list-primary"


def test_knowledge_snapshot_and_outbox_state_persist_across_restart(tmp_path: Path) -> None:
    env = _knowledge_env(tmp_path)

    with service_test_client("knowledge-service", env_overrides=env) as client:
        bootstrap = client.post("/api/knowledge/v1/catalog:bootstrap")
        assert bootstrap.status_code == 200
        assert_standard_headers(bootstrap.headers)

        preview = client.get("/api/knowledge/v1/imports:preview?directory=starter&glob=**/*.md&maxFiles=4")
        assert preview.status_code == 200
        assert_standard_headers(preview.headers)
        preview_data = preview.json()["data"]
        assert preview_data["matchedFiles"] >= 2

        file_import = client.post(
            "/api/knowledge/v1/files:ingest",
            json={
                "directory": "starter",
                "glob": "**/*.md",
                "maxFiles": 4,
                "source": {
                    "name": "QA 重启导入知识库",
                    "kind": "manual",
                    "uri": "qa://knowledge-restart-smoke",
                    "description": "验证知识服务快照与索引出箱状态在重启后仍可回放。",
                    "tags": ["qa", "restart"],
                },
                "tags": ["qa", "restart", "imports"],
                "language": "zh-CN",
            },
        )
        assert file_import.status_code == 201
        assert_standard_headers(file_import.headers)
        file_import_data = file_import.json()["data"]
        assert file_import_data["importedFiles"] >= 2
        source_id = str(file_import_data["source"]["id"])

        first_snapshot = client.get("/api/knowledge/v1/snapshot?auditLimit=5")
        assert first_snapshot.status_code == 200
        assert_standard_headers(first_snapshot.headers)
        first_snapshot_data = first_snapshot.json()["data"]

    with service_test_client("knowledge-service", env_overrides=env) as restarted_client:
        second_snapshot = restarted_client.get("/api/knowledge/v1/snapshot?auditLimit=5")
        assert second_snapshot.status_code == 200
        assert_standard_headers(second_snapshot.headers)
        second_snapshot_data = second_snapshot.json()["data"]

    first_counts = first_snapshot_data["counts"]
    second_counts = second_snapshot_data["counts"]
    assert second_counts["sources"] == first_counts["sources"]
    assert second_counts["documents"] == first_counts["documents"]
    assert second_counts["chunks"] == first_counts["chunks"]

    first_events = first_snapshot_data["integrations"]["recentEvents"]
    second_events = second_snapshot_data["integrations"]["recentEvents"]
    first_import_event = next(event for event in first_events if event["sourceId"] == source_id)
    second_import_event = next(event for event in second_events if event["eventId"] == first_import_event["eventId"])

    assert first_import_event["operation"] == "upsert"
    assert first_import_event["status"] == "queued"
    assert first_import_event["rawObject"]["storageKind"] == "minio"
    assert first_import_event["rawObject"]["bucket"] == "knowledge-raw"
    assert Path(first_import_event["rawObject"]["mirrorPath"]).exists()
    assert first_import_event["metadataTarget"].startswith("knowledge_documents@")
    assert "mysql.qa.local:3306/smartcloud" in first_import_event["metadataTarget"]
    assert second_import_event["docId"] == first_import_event["docId"]
    assert second_import_event["rawObject"]["storageKind"] == "minio"
    assert Path(second_import_event["rawObject"]["mirrorPath"]).exists()
    assert second_snapshot_data["integrations"]["pendingEvents"] >= 1
    assert second_snapshot_data["integrations"]["rawStorage"]["backend"] == "minio"
    assert second_snapshot_data["integrations"]["metadataStore"]["backend"] == "mysql"
    assert second_snapshot_data["integrations"]["vectorStore"]["backend"] == "qdrant"
    assert second_snapshot_data["integrations"]["bm25Store"]["backend"] == "opensearch"
    assert second_snapshot_data["integrations"]["cache"]["backend"] == "redis-configured"
    assert second_snapshot_data["integrations"]["taskQueue"]["backend"] == "redis-list-primary"


def test_orchestrator_healthz_reports_degraded_fallbacks_when_shared_backends_are_unreachable(
    tmp_path: Path,
) -> None:
    with service_test_client(
        "orchestrator-service",
        env_overrides={
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:smartcloud@127.0.0.1:1/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://127.0.0.1:1/0",
            "ORCHESTRATOR_REDIS_NAMESPACE": "qa:orchestrator",
            "BUSINESS_TOOLS_REDIS_NAMESPACE": "qa:orchestrator-business-tools",
            "TOOL_HUB_TRANSPORT": "http",
            "CONVERSATION_STORE_PATH": str(tmp_path / "conversation-store.json"),
            "STATE_STORE_PATH": str(tmp_path / "state-store.json"),
            "SSE_EVENT_STORE_PATH": str(tmp_path / "sse-event-store.json"),
            "AGENT_CONFIG_STORE_PATH": str(tmp_path / "agent-config-store.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "idempotency-store.json"),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "query-cache-store.json"),
        },
    ) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert_standard_headers(response.headers)
    payload = response.json()
    runtime = payload["runtime"]
    assert payload["status"] == "degraded"
    assert "conversationStore" in payload["degraded_components"]
    assert runtime["conversationStore"]["degradedFrom"] == "mysql"
    assert runtime["conversationStore"]["runtimeCache"]["redisConfigured"] is True
    assert runtime["conversationStore"]["runtimeCache"]["redisNamespace"] == "qa:orchestrator:conversation"
    assert runtime["stateStore"]["runtimeCache"]["redisConfigured"] is True
    assert runtime["stateStore"]["runtimeCache"]["redisNamespace"] == "qa:orchestrator:state"
    assert runtime["sseStore"]["redisConfigured"] is True
    assert runtime["sseStore"]["redisNamespace"] == "qa:orchestrator:sse"
    assert runtime["runControl"]["degradedFrom"] == "redis-lock"
    assert runtime["runControl"]["redisConfigured"] is True
    assert runtime["runControl"]["redisNamespace"] == "qa:orchestrator:run-control"
    assert runtime["businessToolsQueryCache"]["backend"] == "inactive"
    assert runtime["businessToolsQueryCache"]["active"] is False
    assert runtime["businessToolsQueryCache"]["activationMode"] == "degraded-fallback-only"
    assert runtime["businessToolsQueryCache"]["redisConfigured"] is True
    assert (
        runtime["businessToolsQueryCache"]["redisNamespace"]
        == "qa:orchestrator-business-tools:query-cache"
    )
    assert runtime["businessToolsIdempotency"]["backend"] == "inactive"
    assert runtime["businessToolsIdempotency"]["active"] is False
    assert runtime["businessToolsIdempotency"]["activationMode"] == "degraded-fallback-only"
    assert runtime["businessToolsIdempotency"]["redisConfigured"] is True
    assert (
        runtime["businessToolsIdempotency"]["redisNamespace"]
        == "qa:orchestrator-business-tools:idempotency"
    )
    assert runtime["toolHubTransport"]["transport"] == "http"


def test_tool_hub_healthz_reports_degraded_fallbacks_when_shared_backends_are_unreachable(
    tmp_path: Path,
) -> None:
    with service_test_client(
        "tool-hub-service",
        env_overrides={
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:smartcloud@127.0.0.1:1/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://127.0.0.1:1/0",
            "BUSINESS_TOOLS_TRANSPORT": "http",
            "BUSINESS_TOOLS_REDIS_NAMESPACE": "qa:tool-hub-business-tools",
            "AUDIT_STORE_PATH": str(tmp_path / "audit-store.json"),
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "idempotency-store.json"),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "query-cache-store.json"),
        },
    ) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert_standard_headers(response.headers)
    payload = response.json()
    runtime = payload["runtime"]
    assert payload["status"] == "degraded"
    assert "auditStore" in payload["degraded_components"]
    assert runtime["auditStore"]["degradedFrom"] == "mysql"
    assert runtime["businessToolsTransport"]["transport"] == "http"
    assert runtime["businessToolsIdempotency"]["backend"] == "inactive"
    assert runtime["businessToolsIdempotency"]["active"] is False
    assert runtime["businessToolsIdempotency"]["activationMode"] == "degraded-fallback-only"
    assert runtime["businessToolsIdempotency"]["redisConfigured"] is True
    assert (
        runtime["businessToolsIdempotency"]["redisNamespace"]
        == "qa:tool-hub-business-tools:idempotency"
    )
    assert runtime["businessToolsQueryCache"]["backend"] == "inactive"
    assert runtime["businessToolsQueryCache"]["active"] is False
    assert runtime["businessToolsQueryCache"]["activationMode"] == "degraded-fallback-only"
    assert runtime["businessToolsQueryCache"]["redisConfigured"] is True
    assert (
        runtime["businessToolsQueryCache"]["redisNamespace"]
        == "qa:tool-hub-business-tools:query-cache"
    )


def test_business_tools_healthz_reports_degraded_fallbacks_when_redis_is_unreachable(
    tmp_path: Path,
) -> None:
    with service_test_client(
        "business-tools-service",
        env_overrides={
            "SMARTCLOUD_REDIS_URL": "redis://127.0.0.1:1/0",
            "BUSINESS_TOOLS_REDIS_NAMESPACE": "qa:business-tools",
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": str(tmp_path / "idempotency-store.json"),
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": str(tmp_path / "query-cache-store.json"),
        },
    ) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert_standard_headers(response.headers)
    payload = response.json()
    runtime = payload["runtime"]
    assert payload["status"] == "degraded"
    assert runtime["idempotency"]["degradedFrom"] == "redis"
    assert runtime["idempotency"]["redisConfigured"] is True
    assert runtime["idempotency"]["redisNamespace"] == "qa:business-tools:idempotency"
    assert runtime["queryCache"]["degradedFrom"] == "redis-ttl"
    assert runtime["queryCache"]["redisConfigured"] is True
    assert runtime["queryCache"]["redisNamespace"] == "qa:business-tools:query-cache"
