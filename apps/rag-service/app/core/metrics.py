from prometheus_client import Counter, Gauge, Histogram

RETRIEVAL_REQUESTS_TOTAL = Counter(
    "rag_retrieval_requests_total",
    "Number of retrieval requests handled by rag-service.",
)
ANSWER_REQUESTS_TOTAL = Counter(
    "rag_answer_requests_total",
    "Number of answer requests handled by rag-service.",
)
EMPTY_RETRIEVALS_TOTAL = Counter(
    "rag_empty_retrievals_total",
    "Number of rag retrieval responses that returned zero citations.",
)
DEGRADED_RETRIEVALS_TOTAL = Counter(
    "rag_degraded_retrievals_total",
    "Number of rag retrieval responses marked degraded.",
)
UPSTREAM_ERRORS_TOTAL = Counter(
    "rag_upstream_errors_total",
    "Number of upstream knowledge-service failures observed by rag-service.",
)
CACHE_HITS_TOTAL = Counter(
    "rag_cache_hits_total",
    "Number of retrieval cache hits served by rag-service.",
)
CACHE_MISSES_TOTAL = Counter(
    "rag_cache_misses_total",
    "Number of retrieval cache misses observed by rag-service.",
)
CACHE_BACKEND_ERRORS_TOTAL = Counter(
    "rag_cache_backend_errors_total",
    "Number of Redis cache backend errors observed by rag-service.",
    labelnames=("operation",),
)
RETRIEVAL_DURATION_SECONDS = Histogram(
    "rag_retrieval_duration_seconds",
    "Duration of rag retrieval operations.",
)
READINESS_STATE = Gauge(
    "rag_readiness_state",
    "Whether rag-service is currently ready for baseline retrieval workflows.",
)
UPSTREAM_REACHABLE_STATE = Gauge(
    "rag_upstream_reachable_state",
    "Whether rag-service can currently reach knowledge-service health probes.",
)
UPSTREAM_READY_STATE = Gauge(
    "rag_upstream_ready_state",
    "Whether the probed knowledge-service dependency currently reports ready.",
)
UPSTREAM_PROBE_LATENCY_MS = Gauge(
    "rag_upstream_probe_latency_ms",
    "Most recent rag-service upstream health-probe latency in milliseconds.",
)
HEALTH_WARNING_COUNT = Gauge(
    "rag_health_warning_count",
    "Number of active rag-service readiness warnings.",
)
CACHE_ENTRY_COUNT = Gauge(
    "rag_cache_entry_count",
    "Current number of cached retrieval entries held by rag-service.",
)


def update_health_metrics(payload: dict[str, object]) -> None:
    upstream = payload.get("upstream") if isinstance(payload.get("upstream"), dict) else {}
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    latency_ms = upstream.get("latencyMs") if isinstance(upstream, dict) else None

    READINESS_STATE.set(1 if payload.get("ready") else 0)
    HEALTH_WARNING_COUNT.set(len(warnings))
    UPSTREAM_REACHABLE_STATE.set(1 if isinstance(upstream, dict) and upstream.get("reachable") else 0)
    UPSTREAM_READY_STATE.set(1 if isinstance(upstream, dict) and upstream.get("ready") else 0)
    UPSTREAM_PROBE_LATENCY_MS.set(float(latency_ms) if isinstance(latency_ms, (int, float)) else 0)
