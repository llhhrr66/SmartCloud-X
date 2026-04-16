from pathlib import Path

import pytest

from app.core.config import build_settings


def test_build_settings_prefers_env_over_dotenv_and_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "dev.yaml").write_text("APP_PORT: 7000\nLOG_LEVEL: WARN\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text("APP_PORT=7010\nBUSINESS_TOOLS_URL=http://example.local\n", encoding="utf-8")

    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "dev",
            "APP_PORT": "7020",
            "LOG_LEVEL": "ERROR",
            "ALLOWED_INTERNAL_CALLERS": "orchestrator-service,gateway-service",
            "BUSINESS_TOOLS_INTERNAL_API_PREFIX": "/internal/tools",
            "TOOL_QUERY_CACHE_ENABLED": "false",
            "TOOL_QUERY_CACHE_TTL_CAP_SECONDS": "120",
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
            "TOOL_HUB_REDIS_NAMESPACE": "smartcloud:test:tool-hub",
            "AUDIT_STORE_PATH": "/tmp/tool-hub-audit.json",
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": "/tmp/tool-hub-idempotency.json",
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": "/tmp/tool-hub-query-cache.json",
            "BUSINESS_TOOLS_REDIS_NAMESPACE": "smartcloud:test:business-tools",
        },
    )

    assert settings.app_port == 7020
    assert settings.log_level == "ERROR"
    assert settings.allowed_internal_callers == ["orchestrator-service", "gateway-service"]
    assert settings.business_tools_base_url == "http://example.local"
    assert settings.business_tools_internal_api_prefix == "/internal/tools"
    assert settings.tool_query_cache_enabled is False
    assert settings.tool_query_cache_ttl_cap_seconds == 120
    assert settings.mysql_dsn == "mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud"
    assert settings.redis_url == "redis://redis.test:6379/0"
    assert settings.redis_namespace == "smartcloud:test:tool-hub"
    assert settings.audit_store_path == "/tmp/tool-hub-audit.json"
    assert settings.business_tools_idempotency_store_path == "/tmp/tool-hub-idempotency.json"
    assert settings.business_tools_query_cache_store_path == "/tmp/tool-hub-query-cache.json"
    assert settings.business_tools_redis_namespace == "smartcloud:test:business-tools"
    assert settings.runtime_data_dir == str(tmp_path / ".tmp" / "tool-hub-service")


def test_build_settings_accepts_shared_runtime_aliases(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "dev.yaml").write_text("", encoding="utf-8")

    settings = build_settings(
        service_root=tmp_path,
        environ={
            "SMARTCLOUD_ENV": "dev",
            "SMARTCLOUD_TIMEZONE": "UTC",
            "SMARTCLOUD_DEFAULT_LOCALE": "en-US",
            "SMARTCLOUD_REQUEST_TIMEOUT_MS": "12000",
            "SMARTCLOUD_TRACE_ID_HEADER": "X-Trace-Token",
            "SMARTCLOUD_MESSAGE_ID_HEADER": "X-Message-Token",
        },
    )

    assert settings.default_timezone == "UTC"
    assert settings.default_language == "en-US"
    assert settings.request_timeout_ms == 12000
    assert settings.trace_id_header == "X-Trace-Token"
    assert settings.message_id_header == "X-Message-Token"


def test_build_settings_derives_degraded_runtime_paths_for_middleware_backends(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "dev.yaml").write_text("", encoding="utf-8")

    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "dev",
            "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
            "SMARTCLOUD_REDIS_URL": "redis://redis.test:6379/0",
        },
    )

    runtime_dir = tmp_path / ".tmp" / "tool-hub-service"
    assert settings.runtime_data_dir == str(runtime_dir)
    assert settings.audit_store_path == str(runtime_dir / "degraded-audit-store.json")
    assert settings.business_tools_idempotency_store_path == str(
        runtime_dir / "degraded-business-tools-idempotency.json"
    )
    assert settings.business_tools_query_cache_store_path == str(
        runtime_dir / "degraded-business-tools-query-cache.json"
    )


def test_build_settings_requires_mysql_in_prod(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "prod.yaml").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="SMARTCLOUD_MYSQL_DSN"):
        build_settings(
            service_root=tmp_path,
            environ={"APP_ENV": "prod"},
        )


def test_build_settings_requires_http_business_tools_transport_in_prod(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "prod.yaml").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="BUSINESS_TOOLS_TRANSPORT=http"):
        build_settings(
            service_root=tmp_path,
            environ={
                "APP_ENV": "prod",
                "SMARTCLOUD_MYSQL_DSN": "mysql+pymysql://smartcloud:secret@mysql.test:3306/smartcloud",
                "BUSINESS_TOOLS_TRANSPORT": "local",
            },
        )
