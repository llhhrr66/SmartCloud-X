from pathlib import Path

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
            "CONVERSATION_STORE_PATH": "/tmp/orch-conversations.json",
            "STATE_STORE_PATH": "/tmp/orch-state.json",
            "SSE_EVENT_STORE_PATH": "/tmp/orch-stream-events.json",
            "DEFAULT_AGENT_TIMEOUT_SECONDS": "75",
            "AGENT_CONFIG_STORE_PATH": "/tmp/orch-agent-configs.json",
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH": "/tmp/orch-idempotency.json",
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH": "/tmp/orch-query-cache.json",
        },
    )

    assert settings.app_port == 7020
    assert settings.log_level == "ERROR"
    assert settings.tool_hub_base_url == "http://example.local"
    assert settings.tool_hub_internal_api_prefix == "/internal/tool-hub"
    assert settings.allowed_internal_callers == ["gateway-service", "admin-gateway"]
    assert settings.tool_query_cache_enabled is False
    assert settings.tool_query_cache_ttl_cap_seconds == 180
    assert settings.response_review_enabled is False
    assert settings.review_reasoning_summary_max_chars == 160
    assert settings.review_final_answer_max_chars == 640
    assert settings.review_require_citations_when_retrieval is False
    assert settings.conversation_store_path == "/tmp/orch-conversations.json"
    assert settings.state_store_path == "/tmp/orch-state.json"
    assert settings.sse_event_store_path == "/tmp/orch-stream-events.json"
    assert settings.default_agent_timeout_seconds == 75
    assert settings.agent_config_store_path == "/tmp/orch-agent-configs.json"
    assert settings.business_tools_idempotency_store_path == "/tmp/orch-idempotency.json"
    assert settings.business_tools_query_cache_store_path == "/tmp/orch-query-cache.json"


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
            "SMARTCLOUD_REQUEST_TIMEOUT_MS": "15000",
            "SMARTCLOUD_SSE_HEARTBEAT_INTERVAL_SECONDS": "9",
            "SMARTCLOUD_REQUEST_ID_HEADER": "X-Correlation-Id",
            "SMARTCLOUD_MESSAGE_ID_HEADER": "X-Message-Token",
        },
    )

    assert settings.default_timezone == "UTC"
    assert settings.default_language == "en-US"
    assert settings.request_timeout_ms == 15000
    assert settings.sse_heartbeat_interval == 9
    assert settings.request_id_header == "X-Correlation-Id"
    assert settings.message_id_header == "X-Message-Token"
