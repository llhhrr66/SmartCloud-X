import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


def _service_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_api_prefix(service_segment: str) -> str:
    base = os.getenv("SMARTCLOUD_API_PREFIX", "/api").rstrip("/")
    version = os.getenv("SMARTCLOUD_API_VERSION", "v1").strip("/")
    return f"{base}/{service_segment}/{version}"


def _resolve_path_env(name: str, default: Path) -> Path:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return Path(raw_value).expanduser()


DEFAULT_CORS_ALLOWED_ORIGINS = [
    "http://localhost:8050",
    "http://127.0.0.1:8050",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


EMBEDDING_PROVIDER_REQUIRED_CONFIG = {
    "openai-compatible": (
        "SMARTCLOUD_EMBEDDING_API_URL",
        "SMARTCLOUD_EMBEDDING_API_KEY",
        "SMARTCLOUD_EMBEDDING_MODEL",
    ),
}


VECTOR_STORE_REQUIRED_CONFIG = {
    "vectorStore": ("SMARTCLOUD_QDRANT_URL",),
    "bm25Store": ("SMARTCLOUD_OPENSEARCH_URL",),
}


class EmbeddingConfigurationError(ValueError):
    """Raised when the configured embedding provider is missing required settings."""



def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    return [item.strip() for item in raw_value.split(",") if item.strip()]



def _parse_bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}



def _default_otlp_endpoint() -> str | None:
    return os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv(
        "SMARTCLOUD_PHOENIX_COLLECTOR_ENDPOINT"
    )



def _default_trace_enabled() -> bool:
    return _parse_bool_env("SMARTCLOUD_TRACE_ENABLED", bool(_default_otlp_endpoint()))


class Settings(BaseModel):
    app_name: str = "smartcloud-x-knowledge-service"
    app_version: str = "0.1.0"
    api_prefix: str = Field(default_factory=lambda: _build_api_prefix("knowledge"))
    env: str = Field(default_factory=lambda: os.getenv("SMARTCLOUD_ENV", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("SMARTCLOUD_LOG_LEVEL", "INFO"))
    data_path: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "SMARTCLOUD_KNOWLEDGE_DATA_PATH",
            _service_root() / "data" / "knowledge-store.json",
        )
    )
    audit_path: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "SMARTCLOUD_KNOWLEDGE_AUDIT_PATH",
            _service_root() / "data" / "knowledge-admin-audit.jsonl",
        )
    )
    outbox_path: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "SMARTCLOUD_KNOWLEDGE_OUTBOX_PATH",
            _service_root() / "data" / "knowledge-indexing-outbox.jsonl",
        )
    )
    starter_catalog_path: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "SMARTCLOUD_KNOWLEDGE_STARTER_CATALOG_PATH",
            _service_root() / "data" / "starter-catalog.json",
        )
    )
    import_root: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "SMARTCLOUD_KNOWLEDGE_IMPORT_ROOT",
            _service_root() / "data" / "imports",
        )
    )
    raw_mirror_root: Path = Field(
        default_factory=lambda: _resolve_path_env(
            "SMARTCLOUD_KNOWLEDGE_RAW_MIRROR_ROOT",
            _service_root() / "data" / "raw-objects",
        )
    )
    max_chunk_chars: int = 420
    chunk_overlap_chars: int = 60
    chunk_strategy: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_CHUNK_STRATEGY", "fixed")
    )
    max_search_results: int = 8
    max_import_files: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_KNOWLEDGE_MAX_IMPORT_FILES", "50"))
    )
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: _parse_csv_env(
            "SMARTCLOUD_CORS_ALLOWED_ORIGINS",
            DEFAULT_CORS_ALLOWED_ORIGINS,
        )
    )
    request_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_REQUEST_ID_HEADER", "X-Request-Id")
    )
    trace_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TRACE_ID_HEADER", "X-Trace-Id")
    )
    conversation_id_header: str = Field(
        default_factory=lambda: os.getenv(
            "SMARTCLOUD_CONVERSATION_ID_HEADER", "X-Conversation-Id"
        )
    )
    tenant_id_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TENANT_ID_HEADER", "X-Tenant-Id")
    )
    caller_service_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_CALLER_SERVICE_HEADER", "X-Caller-Service")
    )
    operator_reason_header: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_OPERATOR_REASON_HEADER", "X-Operator-Reason")
    )
    minio_endpoint: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_MINIO_ENDPOINT"))
    minio_bucket: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_MINIO_BUCKET"))
    minio_access_key: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_MINIO_ACCESS_KEY")
    )
    minio_secret_key: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_MINIO_SECRET_KEY")
    )
    dify_external_knowledge_api_key: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY")
    )
    dify_dataset_api_base_url: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_DIFY_DATASET_API_BASE_URL")
    )
    dify_dataset_api_key: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_DIFY_DATASET_API_KEY")
    )
    dify_dataset_id: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_DIFY_DATASET_ID")
    )
    dify_dataset_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SMARTCLOUD_DIFY_DATASET_TIMEOUT_SECONDS", "10"))
    )
    mysql_dsn: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_MYSQL_DSN"))
    mysql_table: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_MYSQL_TABLE", "knowledge_documents")
    )
    qdrant_url: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_QDRANT_URL"))
    qdrant_collection: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_QDRANT_COLLECTION", "knowledge_chunks")
    )
    opensearch_url: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_OPENSEARCH_URL"))
    opensearch_index: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_OPENSEARCH_INDEX", "knowledge_chunks")
    )
    redis_url: str | None = Field(default_factory=lambda: os.getenv("SMARTCLOUD_REDIS_URL"))
    redis_namespace: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_REDIS_NAMESPACE", "smartcloud-x:knowledge")
    )
    task_queue_name: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_TASK_QUEUE_NAME", "knowledge-indexing")
    )
    connector_timeout_ms: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_CONNECTOR_TIMEOUT_MS", "5000"))
    )
    qdrant_vector_size: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_QDRANT_VECTOR_SIZE", "32"))
    )
    embedding_provider: str = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_EMBEDDING_PROVIDER", "hash-baseline")
    )
    embedding_api_url: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_EMBEDDING_API_URL")
    )
    embedding_api_key: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_EMBEDDING_API_KEY")
    )
    embedding_model: str | None = Field(
        default_factory=lambda: os.getenv("SMARTCLOUD_EMBEDDING_MODEL")
    )
    search_remote_weight: float = Field(
        default_factory=lambda: float(os.getenv("SMARTCLOUD_SEARCH_REMOTE_WEIGHT", "0.62"))
    )
    search_lexical_weight: float = Field(
        default_factory=lambda: float(os.getenv("SMARTCLOUD_SEARCH_LEXICAL_WEIGHT", "0.38"))
    )
    search_min_score: float = Field(
        default_factory=lambda: float(os.getenv("SMARTCLOUD_SEARCH_MIN_SCORE", "0.1"))
    )
    index_worker_poll_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SMARTCLOUD_INDEX_WORKER_POLL_SECONDS", "2"))
    )
    index_worker_batch_size: int = Field(
        default_factory=lambda: int(os.getenv("SMARTCLOUD_INDEX_WORKER_BATCH_SIZE", "10"))
    )
    trace_enabled: bool = Field(default_factory=_default_trace_enabled)
    otlp_endpoint: str | None = Field(default_factory=_default_otlp_endpoint)
    otlp_protocol: str = Field(
        default_factory=lambda: os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc")
    )
    otel_service_name: str = Field(
        default_factory=lambda: os.getenv(
            "OTEL_SERVICE_NAME",
            "smartcloud-x-knowledge-service",
        )
    )

    model_config = {
        "arbitrary_types_allowed": True,
    }

    @model_validator(mode="after")
    def _validate_embedding_provider_configuration(self) -> "Settings":
        provider_name = self.embedding_provider.strip().lower()
        required_keys = EMBEDDING_PROVIDER_REQUIRED_CONFIG.get(provider_name, ())
        missing_fields = [
            key
            for key in required_keys
            if not getattr(self, key.removeprefix("SMARTCLOUD_").lower(), None)
        ]
        if missing_fields:
            joined = ", ".join(missing_fields)
            raise EmbeddingConfigurationError(
                f"embedding provider '{provider_name}' requires: {joined}"
            )
        return self

    def embedding_provider_missing_config(self) -> list[str]:
        provider_name = self.embedding_provider.strip().lower()
        required_keys = EMBEDDING_PROVIDER_REQUIRED_CONFIG.get(provider_name, ())
        missing_fields: list[str] = []
        key_to_value = {
            "SMARTCLOUD_EMBEDDING_API_URL": self.embedding_api_url,
            "SMARTCLOUD_EMBEDDING_API_KEY": self.embedding_api_key,
            "SMARTCLOUD_EMBEDDING_MODEL": self.embedding_model,
        }
        for key in required_keys:
            if not key_to_value.get(key):
                missing_fields.append(key)
        return missing_fields

    def search_backend_missing_config(self) -> dict[str, list[str]]:
        missing: dict[str, list[str]] = {}
        if not self.qdrant_url:
            missing["vectorStore"] = list(VECTOR_STORE_REQUIRED_CONFIG["vectorStore"])
        if not self.opensearch_url:
            missing["bm25Store"] = list(VECTOR_STORE_REQUIRED_CONFIG["bm25Store"])
        return missing


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
