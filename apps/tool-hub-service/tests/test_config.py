from pathlib import Path

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
            "AUDIT_STORE_PATH": "/tmp/tool-hub-audit.json",
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": "/tmp/tool-hub-idempotency.json",
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": "/tmp/tool-hub-query-cache.json",
        },
    )

    assert settings.app_port == 7020
    assert settings.log_level == "ERROR"
    assert settings.allowed_internal_callers == ["orchestrator-service", "gateway-service"]
    assert settings.business_tools_base_url == "http://example.local"
    assert settings.business_tools_internal_api_prefix == "/internal/tools"
    assert settings.tool_query_cache_enabled is False
    assert settings.tool_query_cache_ttl_cap_seconds == 120
    assert settings.audit_store_path == "/tmp/tool-hub-audit.json"
    assert settings.business_tools_idempotency_store_path == "/tmp/tool-hub-idempotency.json"
    assert settings.business_tools_query_cache_store_path == "/tmp/tool-hub-query-cache.json"


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
