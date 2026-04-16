from pathlib import Path

from business_tools_service.core.config import build_settings


def test_build_settings_prefers_env_over_dotenv_and_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "settings"
    config_dir.mkdir(parents=True)
    (config_dir / "dev.yaml").write_text("APP_PORT: 8030\nLOG_LEVEL: WARN\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text("APP_PORT=8040\n", encoding="utf-8")

    settings = build_settings(
        service_root=tmp_path,
        environ={
            "APP_ENV": "dev",
            "APP_PORT": "8050",
            "LOG_LEVEL": "ERROR",
            "ALLOWED_INTERNAL_CALLERS": "tool-hub-service,orchestrator-service",
            "TOOL_QUERY_CACHE_ENABLED": "false",
            "TOOL_QUERY_CACHE_TTL_CAP_SECONDS": "90",
            "API_PREFIX": "/api/tools",
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": "/tmp/biz-idempotency.json",
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": "/tmp/biz-query-cache.json",
        },
    )

    assert settings.app_port == 8050
    assert settings.log_level == "ERROR"
    assert settings.allowed_internal_callers == ["tool-hub-service", "orchestrator-service"]
    assert settings.api_prefix == "/api/tools"
    assert settings.tool_query_cache_enabled is False
    assert settings.tool_query_cache_ttl_cap_seconds == 90
    assert settings.idempotency_store_path == "/tmp/biz-idempotency.json"
    assert settings.query_cache_store_path == "/tmp/biz-query-cache.json"


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
            "SMARTCLOUD_REQUEST_TIMEOUT_MS": "11000",
            "SMARTCLOUD_IDEMPOTENCY_KEY_HEADER": "X-Idempotency-Key",
            "SMARTCLOUD_MESSAGE_ID_HEADER": "X-Message-Token",
        },
    )

    assert settings.default_timezone == "UTC"
    assert settings.default_language == "en-US"
    assert settings.request_timeout_ms == 11000
    assert settings.idempotency_key_header == "X-Idempotency-Key"
    assert settings.message_id_header == "X-Message-Token"
