from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ENV_ALIASES = {
    "APP_ENV": ("APP_ENV", "SMARTCLOUD_ENV"),
    "LOG_LEVEL": ("LOG_LEVEL", "SMARTCLOUD_LOG_LEVEL"),
    "API_PREFIX": ("API_PREFIX", "SMARTCLOUD_API_PREFIX"),
    "DEFAULT_TIMEZONE": ("DEFAULT_TIMEZONE", "SMARTCLOUD_TIMEZONE"),
    "DEFAULT_LANGUAGE": ("DEFAULT_LANGUAGE", "SMARTCLOUD_DEFAULT_LOCALE"),
    "REQUEST_TIMEOUT_MS": ("REQUEST_TIMEOUT_MS", "SMARTCLOUD_REQUEST_TIMEOUT_MS"),
    "SSE_HEARTBEAT_INTERVAL": ("SSE_HEARTBEAT_INTERVAL", "SMARTCLOUD_SSE_HEARTBEAT_INTERVAL_SECONDS"),
    "SSE_EVENT_TTL_SECONDS": ("SSE_EVENT_TTL_SECONDS",),
    "MCP_GATEWAY_URL": ("MCP_GATEWAY_URL",),
    "ORCHESTRATOR_RUNTIME_DIR": ("ORCHESTRATOR_RUNTIME_DIR",),
    "SMARTCLOUD_MYSQL_DSN": ("SMARTCLOUD_MYSQL_DSN",),
    "SMARTCLOUD_MONGODB_URI": ("SMARTCLOUD_MONGODB_URI", "MONGO_URI"),
    "SMARTCLOUD_MONGODB_DATABASE": ("SMARTCLOUD_MONGODB_DATABASE",),
    "SMARTCLOUD_REDIS_URL": ("SMARTCLOUD_REDIS_URL",),
    "CONVERSATION_DOCUMENT_STORE_REQUIRED": (
        "CONVERSATION_DOCUMENT_STORE_REQUIRED",
        "ORCHESTRATOR_CONVERSATION_DOCUMENT_STORE_REQUIRED",
    ),
    "RUN_CONTROL_STRICT": ("RUN_CONTROL_STRICT", "ORCHESTRATOR_RUN_CONTROL_STRICT"),
    "SMARTCLOUD_LLM_API_KEY": ("SMARTCLOUD_LLM_API_KEY", "OPENAI_API_KEY"),
    "SMARTCLOUD_LLM_BASE_URL": ("SMARTCLOUD_LLM_BASE_URL", "OPENAI_BASE_URL"),
    "SMARTCLOUD_LLM_MODEL": ("SMARTCLOUD_LLM_MODEL", "OPENAI_MODEL"),
    "SMARTCLOUD_RAG_SERVICE_BASE_URL": ("SMARTCLOUD_RAG_SERVICE_BASE_URL", "RAG_SERVICE_BASE_URL"),
    "SMARTCLOUD_RAG_SERVICE_API_PREFIX": ("SMARTCLOUD_RAG_SERVICE_API_PREFIX", "RAG_SERVICE_API_PREFIX"),
    "SMARTCLOUD_RAG_SERVICE_PORT": ("SMARTCLOUD_RAG_SERVICE_PORT", "RAG_SERVICE_PORT"),
    "SMARTCLOUD_LLM_TIMEOUT_SECONDS": ("SMARTCLOUD_LLM_TIMEOUT_SECONDS",),
    "TOOL_CALL_ENABLED": ("TOOL_CALL_ENABLED",),
    "MAX_TOOL_CALL_ROUNDS": ("MAX_TOOL_CALL_ROUNDS",),
    # Compaction config
    "COMPACT_ENABLED": ("COMPACT_ENABLED",),
    "COMPACT_MODEL": ("COMPACT_MODEL",),
    "COMPACT_MIN_THRESHOLD_TOKENS": ("COMPACT_MIN_THRESHOLD_TOKENS",),
    "COMPACT_RETAIN_RECENT_ROUNDS": ("COMPACT_RETAIN_RECENT_ROUNDS",),
    "COMPACT_MAX_OUTPUT_TOKENS": ("COMPACT_MAX_OUTPUT_TOKENS",),
    "COMPACT_TIMEOUT_SECONDS": ("COMPACT_TIMEOUT_SECONDS",),
    "COMPACT_STRATEGY": ("COMPACT_STRATEGY",),
    "MICRO_COMPACT_ENABLED": ("MICRO_COMPACT_ENABLED",),
    "MICRO_COMPACT_TIME_GAP_MINUTES": ("MICRO_COMPACT_TIME_GAP_MINUTES",),
    "MICRO_COMPACT_SIZE_THRESHOLD_CHARS": ("MICRO_COMPACT_SIZE_THRESHOLD_CHARS",),
    "SESSION_MEMORY_ENABLED": ("SESSION_MEMORY_ENABLED",),
    "SESSION_MEMORY_MIN_TOKENS_TO_INIT": ("SESSION_MEMORY_MIN_TOKENS_TO_INIT",),
    "SESSION_MEMORY_TOKENS_BETWEEN_UPDATES": ("SESSION_MEMORY_TOKENS_BETWEEN_UPDATES",),
    "SESSION_MEMORY_MAX_TOKENS_PER_SECTION": ("SESSION_MEMORY_MAX_TOKENS_PER_SECTION",),
    "SESSION_MEMORY_STORE_TTL_SECONDS": ("SESSION_MEMORY_STORE_TTL_SECONDS",),
}


RELEASE_ENVS = {"staging", "prod"}
LOCAL_FALLBACK_ENVS = {"local", "dev", "test"}


class LlmConfigurationError(ValueError):
    """Raised when the orchestrator LLM provider is only partially configured."""



def _coerce_value(raw: str) -> Any:
    value = raw.strip()
    lower = value.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if value.isdigit():
        return int(value)
    if "," in value and not value.startswith(("http://", "https://")):
        return [item.strip() for item in value.split(",") if item.strip()]
    if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
        return value[1:-1]
    return value


def _load_dotenv(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        data[key.strip()] = _coerce_value(value)
    return data


def _load_flat_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = _coerce_value(value)
    return data


class Settings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    app_env: Literal["local", "dev", "test", "staging", "prod"] = Field(default="dev", alias="APP_ENV")
    app_name: str = Field(default="orchestrator-service", alias="APP_NAME")
    app_version: str = Field(default="0.3.0", alias="APP_VERSION")
    app_port: int = Field(default=8010, alias="APP_PORT")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    legacy_api_prefix: str = "/api/orchestrator/v1"
    internal_api_prefix: str = "/internal/v1"
    log_level: Literal["DEBUG", "INFO", "WARN", "ERROR"] = Field(default="INFO", alias="LOG_LEVEL")
    default_timezone: str = Field(default="Asia/Shanghai", alias="DEFAULT_TIMEZONE")
    default_language: str = Field(default="zh-CN", alias="DEFAULT_LANGUAGE")
    request_timeout_ms: int = Field(default=30000, alias="REQUEST_TIMEOUT_MS")
    sse_heartbeat_interval: int = Field(default=15, alias="SSE_HEARTBEAT_INTERVAL")
    sse_event_ttl_seconds: int = Field(default=86400, alias="SSE_EVENT_TTL_SECONDS")
    request_id_header: str = Field(default="X-Request-Id", alias="SMARTCLOUD_REQUEST_ID_HEADER")
    trace_id_header: str = Field(default="X-Trace-Id", alias="SMARTCLOUD_TRACE_ID_HEADER")
    conversation_id_header: str = Field(default="X-Conversation-Id", alias="SMARTCLOUD_CONVERSATION_ID_HEADER")
    message_id_header: str = Field(default="X-Message-Id", alias="SMARTCLOUD_MESSAGE_ID_HEADER")
    tenant_id_header: str = Field(default="X-Tenant-Id", alias="SMARTCLOUD_TENANT_ID_HEADER")
    caller_service_header: str = Field(default="X-Caller-Service", alias="SMARTCLOUD_CALLER_SERVICE_HEADER")
    tool_hub_caller_service_header: str = Field(default="X-Caller-Service", alias="SMARTCLOUD_TOOL_HUB_CALLER_SERVICE_HEADER")
    tool_call_id_header: str = Field(default="X-Tool-Call-Id", alias="SMARTCLOUD_TOOL_CALL_ID_HEADER")
    idempotency_key_header: str = Field(default="Idempotency-Key", alias="SMARTCLOUD_IDEMPOTENCY_KEY_HEADER")
    max_history_turns: int = Field(default=20, alias="MAX_HISTORY_TURNS")
    max_handoff_steps: int = Field(default=3, alias="MAX_HANDOFF_STEPS")
    max_tool_calls_per_agent: int = Field(default=5, alias="MAX_TOOL_CALLS_PER_AGENT")
    default_agent_timeout_seconds: int = Field(default=90, alias="DEFAULT_AGENT_TIMEOUT_SECONDS")
    tool_hub_base_url: str = Field(default="http://localhost:8020", alias="MCP_GATEWAY_URL")
    tool_hub_internal_api_prefix: str = Field(default="/internal/v1", alias="TOOL_HUB_INTERNAL_API_PREFIX")
    tool_hub_transport: Literal["local", "http"] = Field(default="local", alias="TOOL_HUB_TRANSPORT")
    trace_enabled: bool = Field(default=True, alias="SMARTCLOUD_TRACE_ENABLED")
    allowed_internal_callers: list[str] = Field(default_factory=lambda: ["gateway-service"], alias="ALLOWED_INTERNAL_CALLERS")
    tool_query_cache_enabled: bool = Field(default=True, alias="TOOL_QUERY_CACHE_ENABLED")
    tool_query_cache_ttl_cap_seconds: int = Field(default=300, alias="TOOL_QUERY_CACHE_TTL_CAP_SECONDS")
    response_review_enabled: bool = Field(default=True, alias="RESPONSE_REVIEW_ENABLED")
    review_reasoning_summary_max_chars: int = Field(default=200, alias="REVIEW_REASONING_SUMMARY_MAX_CHARS")
    review_final_answer_max_chars: int = Field(default=800, alias="REVIEW_FINAL_ANSWER_MAX_CHARS")
    review_require_citations_when_retrieval: bool = Field(
        default=True,
        alias="REVIEW_REQUIRE_CITATIONS_WHEN_RETRIEVAL",
    )
    runtime_data_dir: str | None = Field(default=None, alias="ORCHESTRATOR_RUNTIME_DIR")
    mysql_dsn: str | None = Field(default=None, alias="SMARTCLOUD_MYSQL_DSN")
    mongodb_uri: str | None = Field(default=None, alias="SMARTCLOUD_MONGODB_URI")
    mongodb_database: str = Field(default="smartcloud", alias="SMARTCLOUD_MONGODB_DATABASE")
    redis_url: str | None = Field(default=None, alias="SMARTCLOUD_REDIS_URL")
    conversation_document_store_required: bool = Field(
        default=False,
        alias="CONVERSATION_DOCUMENT_STORE_REQUIRED",
    )
    run_control_strict: bool = Field(default=False, alias="RUN_CONTROL_STRICT")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com", alias="LANGSMITH_ENDPOINT")
    langsmith_project: str = Field(default="smartcloud-x", alias="LANGSMITH_PROJECT")
    langsmith_api_key: str | None = Field(default=None, alias="LANGSMITH_API_KEY")
    llm_api_key: str | None = Field(default=None, alias="SMARTCLOUD_LLM_API_KEY")
    llm_base_url: str | None = Field(default=None, alias="SMARTCLOUD_LLM_BASE_URL")
    llm_model: str | None = Field(default=None, alias="SMARTCLOUD_LLM_MODEL")
    llm_timeout_seconds: int = Field(default=20, alias="SMARTCLOUD_LLM_TIMEOUT_SECONDS")
    tool_call_enabled: bool = Field(default=True, alias="TOOL_CALL_ENABLED")
    max_tool_call_rounds: int = Field(default=5, alias="MAX_TOOL_CALL_ROUNDS")
    rag_service_base_url: str | None = Field(default=None, alias="SMARTCLOUD_RAG_SERVICE_BASE_URL")
    rag_service_api_prefix: str = Field(default="/api/rag/v1", alias="SMARTCLOUD_RAG_SERVICE_API_PREFIX")
    rag_service_port: int = Field(default=8040, alias="SMARTCLOUD_RAG_SERVICE_PORT")
    conversation_store_path: str | None = Field(default=None, alias="CONVERSATION_STORE_PATH")
    state_store_path: str | None = Field(default=None, alias="STATE_STORE_PATH")
    sse_event_store_path: str | None = Field(default=None, alias="SSE_EVENT_STORE_PATH")
    agent_config_store_path: str | None = Field(default=None, alias="AGENT_CONFIG_STORE_PATH")
    business_tools_idempotency_store_path: str | None = Field(
        default=None,
        alias="BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH",
    )
    business_tools_query_cache_store_path: str | None = Field(
        default=None,
        alias="BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH",
    )
    business_tools_redis_namespace: str = Field(
        default="smartcloud:business-tools",
        alias="BUSINESS_TOOLS_REDIS_NAMESPACE",
    )
    runtime_mode: Literal["shared-backend", "mixed", "local-fallback"] = "local-fallback"
    release_readiness_required_components: list[str] = Field(default_factory=list)
    local_fallback_components: list[str] = Field(default_factory=list)

    # --- Compaction settings ---
    compact_enabled: bool = Field(default=True, alias="COMPACT_ENABLED")
    compact_model: str | None = Field(default=None, alias="COMPACT_MODEL")
    compact_min_threshold_tokens: int = Field(default=60000, alias="COMPACT_MIN_THRESHOLD_TOKENS")
    compact_retain_recent_rounds: int = Field(default=3, alias="COMPACT_RETAIN_RECENT_ROUNDS")
    compact_max_output_tokens: int = Field(default=4096, alias="COMPACT_MAX_OUTPUT_TOKENS")
    compact_timeout_seconds: int = Field(default=30, alias="COMPACT_TIMEOUT_SECONDS")
    compact_strategy: Literal["full", "partial", "up_to"] = Field(default="full", alias="COMPACT_STRATEGY")
    micro_compact_enabled: bool = Field(default=True, alias="MICRO_COMPACT_ENABLED")
    micro_compact_time_gap_minutes: int = Field(default=60, alias="MICRO_COMPACT_TIME_GAP_MINUTES")
    micro_compact_size_threshold_chars: int = Field(default=3000, alias="MICRO_COMPACT_SIZE_THRESHOLD_CHARS")
    session_memory_enabled: bool = Field(default=True, alias="SESSION_MEMORY_ENABLED")
    session_memory_min_tokens_to_init: int = Field(default=8000, alias="SESSION_MEMORY_MIN_TOKENS_TO_INIT")
    session_memory_tokens_between_updates: int = Field(default=4000, alias="SESSION_MEMORY_TOKENS_BETWEEN_UPDATES")
    session_memory_max_tokens_per_section: int = Field(default=2000, alias="SESSION_MEMORY_MAX_TOKENS_PER_SECTION")
    session_memory_store_ttl_seconds: int = Field(default=604800, alias="SESSION_MEMORY_STORE_TTL_SECONDS")

    @field_validator("api_prefix", "legacy_api_prefix", "internal_api_prefix", "tool_hub_internal_api_prefix", "rag_service_api_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("API prefix must start with '/'.")
        return value.rstrip("/") or "/"

    @field_validator(
        "request_timeout_ms",
        "sse_heartbeat_interval",
        "sse_event_ttl_seconds",
        "max_history_turns",
        "max_handoff_steps",
        "max_tool_calls_per_agent",
        "default_agent_timeout_seconds",
        "tool_query_cache_ttl_cap_seconds",
        "review_reasoning_summary_max_chars",
        "review_final_answer_max_chars",
        "llm_timeout_seconds",
        "max_tool_call_rounds",
        "compact_min_threshold_tokens",
        "compact_retain_recent_rounds",
        "compact_max_output_tokens",
        "compact_timeout_seconds",
        "micro_compact_time_gap_minutes",
        "micro_compact_size_threshold_chars",
        "session_memory_min_tokens_to_init",
        "session_memory_tokens_between_updates",
        "session_memory_max_tokens_per_section",
        "session_memory_store_ttl_seconds",
    )
    @classmethod
    def _validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Numeric settings must be greater than 0.")
        return value

    @field_validator(
        "request_id_header",
        "trace_id_header",
        "conversation_id_header",
        "message_id_header",
        "tenant_id_header",
        "caller_service_header",
        "tool_call_id_header",
        "idempotency_key_header",
    )
    @classmethod
    def _validate_header_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char.isspace() for char in normalized) or ":" in normalized:
            raise ValueError("Header names must be non-empty HTTP token strings.")
        return normalized

    @field_validator("tool_hub_base_url", "rag_service_base_url")
    @classmethod
    def _validate_http_service_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("service base URL must be a valid http(s) URL.")
        return normalized.rstrip("/")

    @field_validator("mysql_dsn")
    @classmethod
    def _validate_mysql_dsn(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        effective = normalized.replace("mysql://", "mysql+pymysql://", 1) if normalized.startswith("mysql://") else normalized
        parsed = urlparse(effective)
        if parsed.scheme not in {"mysql", "mysql+pymysql"} or not parsed.hostname or not parsed.path.lstrip("/"):
            raise ValueError("SMARTCLOUD_MYSQL_DSN must be a valid mysql DSN.")
        return normalized

    @field_validator("llm_base_url")
    @classmethod
    def _validate_llm_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("SMARTCLOUD_LLM_BASE_URL must be a valid http(s) URL.")
        return normalized.rstrip("/")

    @field_validator("allowed_internal_callers", mode="before")
    @classmethod
    def _validate_callers(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        callers = [caller.strip() for caller in value if caller and caller.strip()]
        if not callers:
            raise ValueError("ALLOWED_INTERNAL_CALLERS must not be empty.")
        return callers

    @model_validator(mode="after")
    def _validate_runtime(self) -> "Settings":
        if self.app_env == "prod" and self.log_level == "DEBUG":
            raise ValueError("DEBUG logging is not allowed in prod.")
        if self.app_env in RELEASE_ENVS:
            missing: list[str] = []
            if not self.mysql_dsn:
                missing.append("SMARTCLOUD_MYSQL_DSN")
            if not self.redis_url:
                missing.append("SMARTCLOUD_REDIS_URL")
            if not self.mongodb_uri:
                missing.append("SMARTCLOUD_MONGODB_URI")
            if missing:
                joined = ", ".join(missing)
                raise ValueError(f"{self.app_env} requires middleware-backed orchestrator runtime config: {joined}.")
            if self.tool_hub_transport != "http":
                raise ValueError(f"{self.app_env} requires TOOL_HUB_TRANSPORT=http for service-to-service orchestration.")
            self.run_control_strict = True
            self.conversation_document_store_required = True
            self.release_readiness_required_components = ["mysql", "redis", "mongodb", "tool_hub_http_transport"]
            self.local_fallback_components = []
            self.runtime_mode = "shared-backend"
        else:
            fallback_components: list[str] = []
            if self.mysql_dsn and (
                self.conversation_store_path or self.state_store_path or self.agent_config_store_path
            ):
                fallback_components.extend(["conversation_store", "state_store", "agent_config_store"])
            if self.redis_url and (
                self.sse_event_store_path
                or self.business_tools_idempotency_store_path
                or self.business_tools_query_cache_store_path
            ):
                fallback_components.extend(
                    [
                        "sse_event_store",
                        "business_tools_idempotency_store",
                        "business_tools_query_cache_store",
                    ]
                )
            self.release_readiness_required_components = ["mysql", "redis", "mongodb", "tool_hub_http_transport"]
            self.local_fallback_components = fallback_components
            self.runtime_mode = "mixed" if fallback_components else "local-fallback"
        llm_missing = self.llm_missing_config()
        if self.app_env in RELEASE_ENVS and 0 < len(llm_missing) < 3:
            joined = ", ".join(llm_missing)
            raise LlmConfigurationError(
                f"partial orchestrator LLM configuration is not allowed in {self.app_env}: missing {joined}"
            )
        return self

    def llm_missing_config(self) -> list[str]:
        key_to_value = {
            "SMARTCLOUD_LLM_API_KEY": self.llm_api_key,
            "SMARTCLOUD_LLM_BASE_URL": self.llm_base_url,
            "SMARTCLOUD_LLM_MODEL": self.llm_model,
        }
        configured_count = sum(1 for value in key_to_value.values() if value)
        if configured_count == 0:
            return list(key_to_value.keys())
        return [key for key, value in key_to_value.items() if not value]

    def llm_ready(self) -> bool:
        return not self.llm_missing_config()


def build_settings(
    service_root: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Settings:
    root = service_root or Path(__file__).resolve().parents[2]
    env = dict(os.environ if environ is None else environ)
    app_env = env.get("APP_ENV") or env.get("SMARTCLOUD_ENV") or "dev"

    merged: dict[str, Any] = {}
    merged.update(_load_flat_yaml(root / "config" / "settings" / f"{app_env}.yaml"))
    merged.update(_load_dotenv(root / f".env.{app_env}"))

    for canonical, aliases in ENV_ALIASES.items():
        for alias in aliases:
            if alias in env and env[alias] not in {"", None}:
                merged[canonical] = _coerce_value(str(env[alias]))
                break

    passthrough_keys = {
        "APP_NAME",
        "APP_VERSION",
        "APP_PORT",
        "DEFAULT_TIMEZONE",
        "DEFAULT_LANGUAGE",
        "REQUEST_TIMEOUT_MS",
        "SSE_HEARTBEAT_INTERVAL",
        "SSE_EVENT_TTL_SECONDS",
        "SMARTCLOUD_REQUEST_ID_HEADER",
        "SMARTCLOUD_TRACE_ID_HEADER",
        "SMARTCLOUD_CONVERSATION_ID_HEADER",
        "SMARTCLOUD_MESSAGE_ID_HEADER",
        "SMARTCLOUD_TENANT_ID_HEADER",
        "SMARTCLOUD_CALLER_SERVICE_HEADER",
        "SMARTCLOUD_TOOL_CALL_ID_HEADER",
        "SMARTCLOUD_IDEMPOTENCY_KEY_HEADER",
        "MAX_HISTORY_TURNS",
        "MAX_HANDOFF_STEPS",
        "MAX_TOOL_CALLS_PER_AGENT",
        "DEFAULT_AGENT_TIMEOUT_SECONDS",
        "TOOL_HUB_INTERNAL_API_PREFIX",
        "TOOL_HUB_TRANSPORT",
        "SMARTCLOUD_TRACE_ENABLED",
        "ALLOWED_INTERNAL_CALLERS",
        "TOOL_QUERY_CACHE_ENABLED",
        "TOOL_QUERY_CACHE_TTL_CAP_SECONDS",
        "RESPONSE_REVIEW_ENABLED",
        "REVIEW_REASONING_SUMMARY_MAX_CHARS",
        "REVIEW_FINAL_ANSWER_MAX_CHARS",
        "REVIEW_REQUIRE_CITATIONS_WHEN_RETRIEVAL",
        "ORCHESTRATOR_RUNTIME_DIR",
        "SMARTCLOUD_MYSQL_DSN",
        "SMARTCLOUD_MONGODB_URI",
        "SMARTCLOUD_MONGODB_DATABASE",
        "SMARTCLOUD_REDIS_URL",
        "CONVERSATION_DOCUMENT_STORE_REQUIRED",
        "RUN_CONTROL_STRICT",
        "LANGSMITH_TRACING",
        "LANGSMITH_ENDPOINT",
        "LANGSMITH_PROJECT",
        "LANGSMITH_API_KEY",
        "SMARTCLOUD_LLM_API_KEY",
        "SMARTCLOUD_LLM_BASE_URL",
        "SMARTCLOUD_LLM_MODEL",
        "SMARTCLOUD_RAG_SERVICE_BASE_URL",
        "SMARTCLOUD_RAG_SERVICE_API_PREFIX",
        "SMARTCLOUD_RAG_SERVICE_PORT",
        "CONVERSATION_STORE_PATH",
        "STATE_STORE_PATH",
        "SSE_EVENT_STORE_PATH",
        "AGENT_CONFIG_STORE_PATH",
        "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH",
        "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH",
        "BUSINESS_TOOLS_REDIS_NAMESPACE",
        "TOOL_CALL_ENABLED",
        "MAX_TOOL_CALL_ROUNDS",
        # Compaction
        "COMPACT_ENABLED",
        "COMPACT_MODEL",
        "COMPACT_MIN_THRESHOLD_TOKENS",
        "COMPACT_RETAIN_RECENT_ROUNDS",
        "COMPACT_MAX_OUTPUT_TOKENS",
        "COMPACT_TIMEOUT_SECONDS",
        "COMPACT_STRATEGY",
        "MICRO_COMPACT_ENABLED",
        "MICRO_COMPACT_TIME_GAP_MINUTES",
        "MICRO_COMPACT_SIZE_THRESHOLD_CHARS",
        "SESSION_MEMORY_ENABLED",
        "SESSION_MEMORY_MIN_TOKENS_TO_INIT",
        "SESSION_MEMORY_TOKENS_BETWEEN_UPDATES",
        "SESSION_MEMORY_MAX_TOKENS_PER_SECTION",
        "SESSION_MEMORY_STORE_TTL_SECONDS",
    }
    for key in passthrough_keys:
        if key in env and env[key] not in {"", None}:
            merged[key] = _coerce_value(str(env[key]))

    runtime_dir = Path(str(merged.get("ORCHESTRATOR_RUNTIME_DIR") or (root / ".tmp" / "orchestrator-service"))).expanduser()
    merged.setdefault("ORCHESTRATOR_RUNTIME_DIR", str(runtime_dir))
    if app_env in LOCAL_FALLBACK_ENVS and merged.get("SMARTCLOUD_MYSQL_DSN") not in {None, ""}:
        merged.setdefault("CONVERSATION_STORE_PATH", str(runtime_dir / "degraded-conversation-store.json"))
        merged.setdefault("STATE_STORE_PATH", str(runtime_dir / "degraded-state-store.json"))
        merged.setdefault("AGENT_CONFIG_STORE_PATH", str(runtime_dir / "degraded-agent-config-store.json"))
    if app_env in LOCAL_FALLBACK_ENVS and merged.get("SMARTCLOUD_REDIS_URL") not in {None, ""}:
        merged.setdefault("SSE_EVENT_STORE_PATH", str(runtime_dir / "degraded-sse-event-store.json"))
        merged.setdefault(
            "BUSINESS_TOOLS_IDEMPOTENCY_STORE_PATH",
            str(runtime_dir / "degraded-business-tools-idempotency.json"),
        )
        merged.setdefault(
            "BUSINESS_TOOLS_QUERY_CACHE_STORE_PATH",
            str(runtime_dir / "degraded-business-tools-query-cache.json"),
        )

    merged.setdefault("APP_ENV", app_env)
    return Settings.model_validate(merged)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()
