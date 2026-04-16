from prometheus_client import Counter, Gauge, Histogram

INGESTIONS_TOTAL = Counter(
    "knowledge_ingestions_total",
    "Number of ingestion requests handled by knowledge-service.",
)
BOOTSTRAP_RUNS_TOTAL = Counter(
    "knowledge_bootstrap_runs_total",
    "Number of starter catalog bootstrap runs handled by knowledge-service.",
)
CHUNKS_CREATED_TOTAL = Counter(
    "knowledge_chunks_created_total",
    "Number of chunks created by knowledge-service.",
)
DUPLICATE_DOCUMENTS_TOTAL = Counter(
    "knowledge_duplicate_documents_total",
    "Number of duplicate document ingestion requests reused by knowledge-service.",
)
SEARCH_REQUESTS_TOTAL = Counter(
    "knowledge_search_requests_total",
    "Number of search requests handled by knowledge-service.",
)
FILE_IMPORT_RUNS_TOTAL = Counter(
    "knowledge_file_import_runs_total",
    "Number of filesystem import runs handled by knowledge-service.",
)
FILE_IMPORT_FILES_TOTAL = Counter(
    "knowledge_file_import_files_total",
    "Number of filesystem import files processed by knowledge-service.",
)
FILE_IMPORT_FAILURES_TOTAL = Counter(
    "knowledge_file_import_failures_total",
    "Number of filesystem import files that failed ingestion in knowledge-service.",
)
ADMIN_WRITE_REQUESTS_TOTAL = Counter(
    "knowledge_admin_write_requests_total",
    "Number of admin write requests handled by knowledge-service.",
    labelnames=("action", "outcome"),
)
ADMIN_AUDIT_RECORDS_TOTAL = Counter(
    "knowledge_admin_audit_records_total",
    "Number of admin audit records written by knowledge-service.",
)
DOCUMENT_REINDEX_RUNS_TOTAL = Counter(
    "knowledge_document_reindexes_total",
    "Number of document reindex operations handled by knowledge-service.",
    labelnames=("outcome",),
)
RAW_OBJECT_WRITES_TOTAL = Counter(
    "knowledge_raw_object_writes_total",
    "Number of raw knowledge documents mirrored for async indexing handoff.",
)
INDEX_OUTBOX_EVENTS_TOTAL = Counter(
    "knowledge_index_outbox_events_total",
    "Number of async indexing outbox events emitted by knowledge-service.",
    labelnames=("operation", "status"),
)
INDEX_WORKER_RUNS_TOTAL = Counter(
    "knowledge_index_worker_runs_total",
    "Number of indexing worker runs handled by knowledge-service.",
    labelnames=("outcome",),
)
INDEX_CONNECTOR_WRITES_TOTAL = Counter(
    "knowledge_index_connector_writes_total",
    "Number of connector writes attempted by the knowledge indexing worker.",
    labelnames=("connector", "outcome"),
)
INGESTION_DURATION_SECONDS = Histogram(
    "knowledge_ingestion_duration_seconds",
    "Duration of knowledge ingestion operations.",
)
READINESS_STATE = Gauge(
    "knowledge_readiness_state",
    "Whether knowledge-service is currently ready for baseline ingestion and admin workflows.",
)
READINESS_CHECK_STATE = Gauge(
    "knowledge_readiness_check_state",
    "Status of individual knowledge-service readiness checks.",
    labelnames=("check_name",),
)
HEALTH_WARNING_COUNT = Gauge(
    "knowledge_health_warning_count",
    "Number of active knowledge-service readiness warnings.",
)
CATALOG_ENTITY_COUNT = Gauge(
    "knowledge_catalog_entity_count",
    "Current knowledge-service repository entity counts.",
    labelnames=("entity",),
)
INDEX_OUTBOX_PENDING_EVENTS = Gauge(
    "knowledge_index_outbox_pending_events",
    "Current number of queued async indexing outbox events.",
)
INDEX_OUTBOX_STATUS_COUNT = Gauge(
    "knowledge_index_outbox_status_count",
    "Current number of async indexing outbox events per lifecycle status.",
    labelnames=("status",),
)

READINESS_CHECK_NAMES = (
    "data_store_access",
    "audit_log_parent",
    "starter_catalog",
    "import_root",
    "repository_counts",
)
CATALOG_ENTITY_LABELS = {
    "sources": "sources",
    "documents": "documents",
    "chunks": "chunks",
    "ingestions": "ingestions",
    "knowledgeBases": "knowledge_bases",
    "documentProfiles": "document_profiles",
    "adminJobs": "admin_jobs",
}


def update_health_metrics(
    *,
    ready: bool,
    checks: list[dict[str, str]],
    warnings: list[str],
    counts: dict[str, int],
) -> None:
    READINESS_STATE.set(1 if ready else 0)
    HEALTH_WARNING_COUNT.set(len(warnings))

    for check_name in READINESS_CHECK_NAMES:
        READINESS_CHECK_STATE.labels(check_name=check_name).set(0)
    for check in checks:
        check_name = check.get("name")
        if not check_name:
            continue
        READINESS_CHECK_STATE.labels(check_name=check_name).set(1 if check.get("status") == "ready" else 0)

    for label in CATALOG_ENTITY_LABELS.values():
        CATALOG_ENTITY_COUNT.labels(entity=label).set(0)
    for key, label in CATALOG_ENTITY_LABELS.items():
        CATALOG_ENTITY_COUNT.labels(entity=label).set(float(counts.get(key, 0)))


def update_health_metrics_from_payload(payload: dict[str, object]) -> None:
    checks = payload.get("readinessChecks") if isinstance(payload.get("readinessChecks"), list) else []
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    update_health_metrics(
        ready=bool(payload.get("ready")),
        checks=[item for item in checks if isinstance(item, dict)],
        warnings=[str(item) for item in warnings],
        counts={key: int(value) for key, value in counts.items() if isinstance(value, (int, float))},
    )
