from pathlib import Path

import pytest

from app.core.config import build_settings


def test_build_settings_prefers_env_over_dotenv_and_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "dev.yaml").write_text("APP_PORT: 7000\nLOG_LEVEL: WARN\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text("APP_PORT=7010\nMCP_GATEWAY_URL=http://example.local\n", encoding="utf-8")

    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "dev",
            "APP_PORT": "7020",
            "LOG_LEVEL": "ERROR",
            "ALLOWED_INTERNAL_CALLERS": "gateway-service,admin-gateway",
            "TOOL_HUB_INTERNAL_API_PREFIX": "/internal/tool-hub",
            "TOOL_QUERY_CACHE_ENABLED": "false",
            "TOOL_QUERY_CACHE_TTL_CAP_SECONDS": "180",
            "RESPONSE_REVIEW_ENABLED": "false",
            "REVIEW_REASONING_SUMMARY_MAX_CHARS": "160",
            "REVIEW_FINAL_ANSWER_MAX_CHARS": "640",
            "REVIEW_REQUIRE_CITATIONS_WHEN_RETRIEVAL": "false",
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
        },
    )

    assert settings.app_port == 7020
    assert settings.log_level == "ERROR"
    assert settings.tool_hub_base_url == "http://example.local"
    assert settings.allowed_internal_callers == ["gateway-service", "admin-gateway"]
    assert settings.tool_hub_internal_api_prefix == "/internal/tool-hub"
    assert settings.tool_query_cache_enabled is False
    assert settings.tool_query_cache_ttl_cap_seconds == 180
    assert settings.response_review_enabled is False
    assert settings.review_reasoning_summary_max_chars == 160
    assert settings.review_final_answer_max_chars == 640
    assert settings.review_require_citations_when_retrieval is False
    assert settings.mysql_dsn == "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud"
    assert settings.redis_url == "redis://redis.test:6379/0"
    assert settings.conversation_document_store_required is False


def test_build_settings_loads_rag_runtime_endpoint_from_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env.dev").write_text(
        "SMARTCLOUD_RAG_SERVICE_BASE_URL=http://127.0.0.1:8040\nSMARTCLOUD_RAG_SERVICE_API_PREFIX=/api/rag/v1\n",
        encoding="utf-8",
    )

    settings = build_settings(
        service_root=tmp_path,
        environ={"APP_ENV": "dev"},
    )

    assert settings.rag_service_base_url == "http://127.0.0.1:8040"
    assert settings.rag_service_api_prefix == "/api/rag/v1"


def test_build_settings_accepts_shared_runtime_aliases(tmp_path: Path) -> None:
    settings = build_settings(
        service_root=tmp_path,
        environ={
            "SMARTCLOUD_ENV": "dev",
            "SMARTCLOUD_LOG_LEVEL": "WARN",
            "SMARTCLOUD_API_PREFIX": "/api/shared",
            "SMARTCLOUD_TIMEZONE": "UTC",
            "SMARTCLOUD_DEFAULT_LOCALE": "en-US",
            "MONGO_URI": "mongodb://mongo.local:27017",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://llm.example.com/v1",
            "OPENAI_MODEL": "gpt-test",
            "CONVERSATION_DOCUMENT_STORE_REQUIRED": "true",
        },
    )

    assert settings.app_env == "dev"
    assert settings.log_level == "WARN"
    assert settings.api_prefix == "/api/shared"
    assert settings.default_timezone == "UTC"
    assert settings.default_language == "en-US"
    assert settings.mongodb_uri == "mongodb://mongo.local:27017"
    assert settings.llm_api_key == "test-key"
    assert settings.llm_base_url == "https://llm.example.com/v1"
    assert settings.llm_model == "gpt-test"
    assert settings.conversation_document_store_required is True


def test_build_settings_derives_degraded_runtime_paths_for_middleware_backends(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "dev",
            "ORCHESTRATOR_RUNTIME_DIR": str(runtime_dir),
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
        },
    )

    assert settings.runtime_data_dir == str(runtime_dir)
    assert settings.conversation_store_path == str(runtime_dir / "degraded-conversation-store.json")
    assert settings.state_store_path == str(runtime_dir / "degraded-state-store.json")
    assert settings.agent_config_store_path == str(runtime_dir / "degraded-agent-config-store.json")
    assert settings.sse_event_store_path == str(runtime_dir / "degraded-sse-event-store.json")
    assert settings.business_tools_idempotency_store_path == str(runtime_dir / "degraded-business-tools-idempotency.json")
    assert settings.business_tools_query_cache_store_path == str(runtime_dir / "degraded-business-tools-query-cache.json")


def test_build_settings_requires_mysql_and_redis_in_prod(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="middleware-backed orchestrator runtime config"):
        build_settings(
            service_root=tmp_path,
            environ={
                "APP_ENV": "prod",
                "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud",
                "TOOL_HUB_TRANSPORT": "http",
            },
        )


def test_build_settings_requires_http_tool_hub_transport_in_prod(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TOOL_HUB_TRANSPORT=http"):
        build_settings(
            service_root=tmp_path,
            environ={
                "APP_ENV": "prod",
                "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:***@mysql.test:3306/smartcloud",
                "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
                "SMARTCLOUD_MONGODB_URI": "mongodb://mongo.test:27017",
                "TOOL_HUB_TRANSPORT": "local",
            },
        )


def test_build_settings_enables_strict_run_control_and_document_store_requirement_in_prod(tmp_path: Path) -> None:
    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "prod",
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
            "SMARTCLOUD_MONGODB_URI": "mongodb://mongo.test:27017",
            "TOOL_HUB_TRANSPORT": "http",
        },
    )

    assert settings.run_control_strict is True
    assert settings.conversation_document_store_required is True


def test_build_settings_marks_local_runtime_mode_when_no_middleware_backends(tmp_path: Path) -> None:
    settings = build_settings(
        service_root=tmp_path,
        environ={"APP_ENV": "dev"},
    )

    assert settings.runtime_mode == "local-fallback"
    assert settings.release_readiness_required_components == ["mysql", "redis", "mongodb", "tool_hub_http_transport"]
    assert settings.local_fallback_components == []


def test_build_settings_marks_mixed_runtime_mode_when_dev_uses_degraded_storage(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "dev",
            "ORCHESTRATOR_RUNTIME_DIR": str(runtime_dir),
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
        },
    )

    assert settings.runtime_mode == "mixed"
    assert settings.local_fallback_components == [
        "conversation_store",
        "state_store",
        "agent_config_store",
        "sse_event_store",
        "business_tools_idempotency_store",
        "business_tools_query_cache_store",
    ]


def test_build_settings_requires_mysql_redis_and_mongodb_in_staging(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="middleware-backed orchestrator runtime config"):
        build_settings(
            service_root=tmp_path,
            environ={
                "APP_ENV": "staging",
                "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:password@mysql.test:3306/smartcloud",
                "TOOL_HUB_TRANSPORT": "http",
            },
        )
