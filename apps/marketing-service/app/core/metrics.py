from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

_registry = CollectorRegistry()
_ALL_COUNTERS: list[Counter] = []
_ALL_GAUGES: list[Gauge] = []
_ALL_HISTOGRAMS: list[Histogram] = []


def _tracked_counter(*args, **kwargs) -> Counter:
    counter = Counter(*args, **kwargs)
    _ALL_COUNTERS.append(counter)
    return counter


def _tracked_gauge(*args, **kwargs) -> Gauge:
    gauge = Gauge(*args, **kwargs)
    _ALL_GAUGES.append(gauge)
    return gauge


def _tracked_histogram(*args, **kwargs) -> Histogram:
    histogram = Histogram(*args, **kwargs)
    _ALL_HISTOGRAMS.append(histogram)
    return histogram

marketing_requests_total = _tracked_counter(
    'marketing_requests_total',
    'Marketing API requests total',
    ['operation', 'status', 'resource_type'],
    registry=_registry,
)
marketing_request_duration_seconds = _tracked_histogram(
    'marketing_request_duration_seconds',
    'Marketing API request duration seconds',
    ['operation'],
    registry=_registry,
)
marketing_posters_created_total = _tracked_counter('marketing_posters_created_total', 'Poster tasks created', registry=_registry)
marketing_posters_completed_total = _tracked_counter('marketing_posters_completed_total', 'Poster tasks completed', registry=_registry)
marketing_copies_generated_total = _tracked_counter('marketing_copies_generated_total', 'Marketing copies generated', registry=_registry)
marketing_links_generated_total = _tracked_counter('marketing_links_generated_total', 'Promotion links generated', registry=_registry)
marketing_idempotency_replays_total = _tracked_counter('marketing_idempotency_replays_total', 'Poster idempotency replays', registry=_registry)
marketing_upstream_errors_total = _tracked_counter(
    'marketing_upstream_errors_total',
    'Upstream/backend errors',
    ['backend', 'error_type'],
    registry=_registry,
)
marketing_minio_operations_total = _tracked_counter(
    'marketing_minio_operations_total',
    'MinIO operations',
    ['operation', 'status'],
    registry=_registry,
)
marketing_mongodb_operations_total = _tracked_counter(
    'marketing_mongodb_operations_total',
    'MongoDB operations',
    ['operation', 'status'],
    registry=_registry,
)
marketing_celery_operations_total = _tracked_counter(
    'marketing_celery_operations_total',
    'Celery operations',
    ['operation', 'status'],
    registry=_registry,
)
marketing_auth_validation_total = _tracked_counter(
    'marketing_auth_validation_total',
    'Auth validation outcomes',
    ['status'],
    registry=_registry,
)
marketing_readiness_state = _tracked_gauge('marketing_readiness_state', 'Readiness state', registry=_registry)


@dataclass(slots=True)
class ReadinessReport:
    ready: bool
    components: dict[str, dict[str, Any]]


def record_request(operation: str, status: str, resource_type: str) -> None:
    marketing_requests_total.labels(operation=operation, status=status, resource_type=resource_type).inc()


def observe_duration(operation: str, seconds: float) -> None:
    marketing_request_duration_seconds.labels(operation=operation).observe(seconds)


def export_metrics() -> tuple[bytes, str]:
    return generate_latest(_registry), CONTENT_TYPE_LATEST


def reset_metrics() -> None:
    for metric in [*_ALL_COUNTERS, *_ALL_GAUGES, *_ALL_HISTOGRAMS]:
        children = getattr(metric, "_metrics", None)
        if isinstance(children, dict):
            children.clear()
        value = getattr(metric, "_value", None)
        if value is not None and hasattr(value, "set"):
            value.set(0)
        sum_value = getattr(metric, "_sum", None)
        if sum_value is not None and hasattr(sum_value, "set"):
            sum_value.set(0)
        buckets = getattr(metric, "_buckets", None)
        if isinstance(buckets, (list, tuple)):
            for bucket in buckets:
                bucket_value = getattr(bucket, "set", None)
                if callable(bucket_value):
                    bucket.set(0)
