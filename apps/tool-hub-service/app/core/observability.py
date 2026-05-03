from __future__ import annotations

import time
from contextlib import nullcontext
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from app.core.config import get_settings

_settings = get_settings()
_tracer_provider: TracerProvider | None = None
_memory_exporter: InMemorySpanExporter | None = None
_metrics_registry = CollectorRegistry(auto_describe=True)

REQUESTS_TOTAL = Counter(
    "tool_hub_requests_total",
    "Tool-hub requests grouped by tool, operation, status, and provider.",
    labelnames=("tool_name", "operation", "status", "provider"),
    registry=_metrics_registry,
)
REQUEST_DURATION_SECONDS = Histogram(
    "tool_hub_request_duration_seconds",
    "Tool-hub request duration in seconds.",
    labelnames=("tool_name", "operation"),
    registry=_metrics_registry,
)
CACHE_HITS_TOTAL = Counter(
    "tool_hub_cache_hits_total",
    "Observed query-cache hits.",
    registry=_metrics_registry,
)
CACHE_MISSES_TOTAL = Counter(
    "tool_hub_cache_misses_total",
    "Observed query-cache misses.",
    registry=_metrics_registry,
)
IDEMPOTENCY_HITS_TOTAL = Counter(
    "tool_hub_idempotency_hits_total",
    "Observed idempotency hits.",
    registry=_metrics_registry,
)
IDEMPOTENCY_STORES_TOTAL = Counter(
    "tool_hub_idempotency_stores_total",
    "Observed idempotency stores.",
    registry=_metrics_registry,
)
UPSTREAM_ERRORS_TOTAL = Counter(
    "tool_hub_upstream_errors_total",
    "Observed upstream provider errors.",
    labelnames=("provider", "error_type"),
    registry=_metrics_registry,
)
READINESS_STATE = Gauge(
    "tool_hub_readiness_state",
    "1 when ready, 0 when not ready.",
    registry=_metrics_registry,
)
AUDIT_RECORDS_TOTAL = Counter(
    "tool_hub_audit_records_total",
    "Persisted audit records.",
    registry=_metrics_registry,
)
IDEMPOTENCY_IN_FLIGHT = Gauge(
    "tool_hub_idempotency_in_flight",
    "Current in-flight idempotency keys.",
    registry=_metrics_registry,
)


def get_tracer(name: str = "tool-hub-service"):
    return trace.get_tracer(name)


def setup_observability(app) -> None:
    provider = _ensure_tracer_provider()
    if provider is not None:
        trace.set_tracer_provider(provider)
    if _settings.trace_enabled:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="/healthz,/readyz,/metrics",
            tracer_provider=provider,
        )


def _ensure_tracer_provider() -> TracerProvider | None:
    global _tracer_provider, _memory_exporter
    if _tracer_provider is not None:
        return _tracer_provider
    if not _settings.trace_enabled:
        return None
    resource = Resource.create({"service.name": _settings.app_name, "service.version": _settings.app_version})
    provider = TracerProvider(resource=resource)
    endpoint = getattr(_settings, "otel_exporter_otlp_endpoint", None)
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    _memory_exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
    _tracer_provider = provider
    return provider


def get_in_memory_span_exporter() -> InMemorySpanExporter | None:
    _ensure_tracer_provider()
    return _memory_exporter


def clear_in_memory_spans() -> None:
    exporter = get_in_memory_span_exporter()
    if exporter is not None:
        exporter.clear()


def start_span(name: str, *, attributes: dict[str, Any] | None = None, kind: SpanKind = SpanKind.INTERNAL, context: Context | None = None):
    tracer = get_tracer()
    span_cm = tracer.start_as_current_span(name, context=context, kind=kind)
    return _SpanContextManager(span_cm, attributes or {})


class _SpanContextManager:
    def __init__(self, span_cm, attributes: dict[str, Any]) -> None:
        self._span_cm = span_cm
        self._attributes = attributes
        self._span = None
        self._started = 0.0

    def __enter__(self):
        self._started = time.perf_counter()
        self._span = self._span_cm.__enter__()
        for key, value in self._attributes.items():
            if value is not None:
                self._span.set_attribute(key, value)
        return self._span

    def __exit__(self, exc_type, exc, tb):
        if self._span is not None:
            latency_ms = (time.perf_counter() - self._started) * 1000
            self._span.set_attribute("latency_ms", round(latency_ms, 3))
            if exc is None:
                self._span.set_status(Status(StatusCode.OK))
            else:
                self._span.record_exception(exc)
                self._span.set_status(Status(StatusCode.ERROR, str(exc)))
        return self._span_cm.__exit__(exc_type, exc, tb)


def annotate_current_span(**attributes: Any) -> None:
    span = trace.get_current_span()
    if span is None:
        return
    for key, value in attributes.items():
        if value is not None:
            span.set_attribute(key, value)


def mark_request_metric(*, tool_name: str, operation: str, status: str, provider: str, duration_seconds: float) -> None:
    REQUESTS_TOTAL.labels(tool_name=tool_name, operation=operation, status=status, provider=provider).inc()
    REQUEST_DURATION_SECONDS.labels(tool_name=tool_name, operation=operation).observe(duration_seconds)


def mark_cache_hit() -> None:
    CACHE_HITS_TOTAL.inc()


def mark_cache_miss() -> None:
    CACHE_MISSES_TOTAL.inc()


def mark_idempotency_hit() -> None:
    IDEMPOTENCY_HITS_TOTAL.inc()


def mark_idempotency_store() -> None:
    IDEMPOTENCY_STORES_TOTAL.inc()


def set_idempotency_in_flight(value: int) -> None:
    IDEMPOTENCY_IN_FLIGHT.set(value)


def mark_upstream_error(provider: str, error_type: str) -> None:
    UPSTREAM_ERRORS_TOTAL.labels(provider=provider or "unknown", error_type=error_type or "unknown").inc()


def mark_audit_record_written() -> None:
    AUDIT_RECORDS_TOTAL.inc()


def set_readiness_state(ready: bool) -> None:
    READINESS_STATE.set(1 if ready else 0)


def metrics_payload() -> bytes:
    return generate_latest(_metrics_registry)


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def metric_snapshot() -> dict[str, Any]:
    def _counter_value(counter: Counter) -> float:
        sample = next((s for s in counter.collect()[0].samples if s.name.endswith("_total")), None)
        return float(sample.value) if sample is not None else 0.0

    def _gauge_value(gauge: Gauge) -> float:
        sample = gauge.collect()[0].samples[0]
        return float(sample.value)

    return {
        "cache_hits_total": _counter_value(CACHE_HITS_TOTAL),
        "cache_misses_total": _counter_value(CACHE_MISSES_TOTAL),
        "idempotency_hits_total": _counter_value(IDEMPOTENCY_HITS_TOTAL),
        "idempotency_stores_total": _counter_value(IDEMPOTENCY_STORES_TOTAL),
        "audit_records_total": _counter_value(AUDIT_RECORDS_TOTAL),
        "readiness_state": _gauge_value(READINESS_STATE),
        "idempotency_in_flight": _gauge_value(IDEMPOTENCY_IN_FLIGHT),
    }


def span_or_noop(name: str, *, attributes: dict[str, Any] | None = None, kind: SpanKind = SpanKind.INTERNAL, context: Context | None = None):
    if not _settings.trace_enabled:
        return nullcontext()
    return start_span(name, attributes=attributes, kind=kind, context=context)
