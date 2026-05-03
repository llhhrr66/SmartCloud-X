from prometheus_client import Counter, Gauge, Histogram
from prometheus_client.registry import REGISTRY


def _counter(name: str, documentation: str, *, labelnames: tuple[str, ...] = ()) -> Counter:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if isinstance(existing, Counter):
        return existing
    return Counter(name, documentation, labelnames=labelnames)


def _histogram(name: str, documentation: str, *, labelnames: tuple[str, ...] = ()) -> Histogram:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if isinstance(existing, Histogram):
        return existing
    return Histogram(name, documentation, labelnames=labelnames)


def _gauge(name: str, documentation: str, *, labelnames: tuple[str, ...] = ()) -> Gauge:
    existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
    if isinstance(existing, Gauge):
        return existing
    return Gauge(name, documentation, labelnames=labelnames)


RESEARCH_REQUESTS_TOTAL = _counter(
    "research_requests_total",
    "Number of research-service requests handled.",
    labelnames=("operation", "status", "depth"),
)
RESEARCH_REQUEST_DURATION_SECONDS = _histogram(
    "research_request_duration_seconds",
    "Duration of research-service request handlers.",
    labelnames=("operation",),
)
RESEARCH_TASKS_CREATED_TOTAL = _counter(
    "research_tasks_created_total",
    "Number of research tasks created.",
)
RESEARCH_TASKS_COMPLETED_TOTAL = _counter(
    "research_tasks_completed_total",
    "Number of research tasks completed.",
)
RESEARCH_IDEMPOTENCY_REPLAYS_TOTAL = _counter(
    "research_idempotency_replays_total",
    "Number of idempotent task creation replays.",
)
RESEARCH_UPSTREAM_ERRORS_TOTAL = _counter(
    "research_upstream_errors_total",
    "Number of upstream/dependency errors observed by research-service.",
    labelnames=("backend", "error_type"),
)
RESEARCH_READINESS_STATE = _gauge(
    "research_readiness_state",
    "Whether research-service is currently ready.",
)
RESEARCH_MONGO_OPERATIONS_TOTAL = _counter(
    "research_mongo_operations_total",
    "Number of Mongo operations attempted by research-service.",
    labelnames=("operation", "status"),
)
TASK_CANCELLED_TOTAL = _counter(
    "task_cancelled_total",
    "Number of research tasks cancelled by users.",
)
RESEARCH_PIPELINE_STEPS_TOTAL = _counter(
    "research_pipeline_steps_total",
    "Number of pipeline research steps executed.",
    labelnames=("step",),
)
RESEARCH_PIPELINE_FETCH_ERRORS_TOTAL = _counter(
    "research_pipeline_fetch_errors_total",
    "Number of web fetch errors in pipeline research.",
)
