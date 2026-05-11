from prometheus_client import Counter, Gauge, Histogram, REGISTRY


def _get_or_create_metric(metric_cls, name: str, documentation: str, *args, **kwargs):
    existing = REGISTRY._names_to_collectors.get(name)
    if existing is not None:
        return existing
    return metric_cls(name, documentation, *args, **kwargs)


RETRIEVAL_REQUESTS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_retrieval_requests_total",
    "Number of retrieval requests handled by rag-service.",
)
ANSWER_REQUESTS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_answer_requests_total",
    "Number of answer requests handled by rag-service.",
)
EMPTY_RETRIEVALS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_empty_retrievals_total",
    "Number of rag retrieval responses that returned zero citations.",
)
DEGRADED_RETRIEVALS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_degraded_retrievals_total",
    "Number of rag retrieval responses marked degraded.",
)
UPSTREAM_ERRORS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_upstream_errors_total",
    "Number of upstream knowledge-service failures observed by rag-service.",
)
CACHE_HITS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_cache_hits_total",
    "Number of retrieval cache hits served by rag-service.",
)
CACHE_MISSES_TOTAL = _get_or_create_metric(
    Counter,
    "rag_cache_misses_total",
    "Number of retrieval cache misses observed by rag-service.",
)
CACHE_BACKEND_ERRORS_TOTAL = _get_or_create_metric(
    Counter,
    "rag_cache_backend_errors_total",
    "Number of Redis cache backend errors observed by rag-service.",
    labelnames=("operation",),
)
RETRIEVAL_DURATION_SECONDS = _get_or_create_metric(
    Histogram,
    "rag_retrieval_duration_seconds",
    "Duration of rag retrieval operations.",
)
READINESS_STATE = _get_or_create_metric(
    Gauge,
    "rag_readiness_state",
    "Whether rag-service is currently ready for baseline retrieval workflows.",
)
UPSTREAM_REACHABLE_STATE = _get_or_create_metric(
    Gauge,
    "rag_upstream_reachable_state",
    "Whether rag-service can currently reach knowledge-service health probes.",
)
UPSTREAM_READY_STATE = _get_or_create_metric(
    Gauge,
    "rag_upstream_ready_state",
    "Whether the probed knowledge-service dependency currently reports ready.",
)
UPSTREAM_PROBE_LATENCY_MS = _get_or_create_metric(
    Gauge,
    "rag_upstream_probe_latency_ms",
    "Most recent rag-service upstream health-probe latency in milliseconds.",
)
HEALTH_WARNING_COUNT = _get_or_create_metric(
    Gauge,
    "rag_health_warning_count",
    "Number of active rag-service readiness warnings.",
)
CACHE_ENTRY_COUNT = _get_or_create_metric(
    Gauge,
    "rag_cache_entry_count",
    "Current number of cached retrieval entries held by rag-service.",
)
CACHE_HIT_RATIO = _get_or_create_metric(
    Gauge,
    "rag_cache_hit_ratio",
    "Rolling cache hit ratio observed by rag-service.",
)
SMART_CACHE_REQUESTS_TOTAL = _get_or_create_metric(
    Counter,
    "smart_cache_requests_total",
    "Total smart cache requests by layer and result.",
    labelnames=("layer", "result"),
)
SMART_CACHE_TOKEN_SAVED_TOTAL = _get_or_create_metric(
    Counter,
    "smart_cache_token_saved_total",
    "Total tokens saved by smart cache hits.",
)
FAQ_CACHE_ENTRIES = _get_or_create_metric(
    Gauge,
    "faq_cache_entries",
    "Current number of FAQ cache entries.",
)
FAQ_BM25_HITS_TOTAL = _get_or_create_metric(
    Counter,
    "faq_bm25_hits_total",
    "BM25 FAQ match hits.",
)
FAQ_TFIDF_HITS_TOTAL = _get_or_create_metric(
    Counter,
    "faq_tfidf_hits_total",
    "TF-IDF FAQ match hits.",
)


def update_cache_hit_ratio(hits: float, misses: float) -> None:
    total = hits + misses
    CACHE_HIT_RATIO.set((hits / total) if total > 0 else 0.0)


def update_health_metrics(payload: dict[str, object]) -> None:
    upstream = payload.get("upstream") if isinstance(payload.get("upstream"), dict) else {}
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    latency_ms = upstream.get("latencyMs") if isinstance(upstream, dict) else None
    cache = payload.get("cache") if isinstance(payload.get("cache"), dict) else {}

    READINESS_STATE.set(1 if payload.get("ready") else 0)
    HEALTH_WARNING_COUNT.set(len(warnings))
    UPSTREAM_REACHABLE_STATE.set(1 if isinstance(upstream, dict) and upstream.get("reachable") else 0)
    UPSTREAM_READY_STATE.set(1 if isinstance(upstream, dict) and upstream.get("ready") else 0)
    UPSTREAM_PROBE_LATENCY_MS.set(float(latency_ms) if isinstance(latency_ms, (int, float)) else 0)
    if isinstance(cache, dict):
        hit_rate = cache.get("cacheHitRate")
        if isinstance(hit_rate, (int, float)):
            CACHE_HIT_RATIO.set(float(hit_rate))
