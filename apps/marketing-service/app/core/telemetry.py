from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Any, Iterator

from fastapi import Request
from opentelemetry import context as otel_context, propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode
from dataclasses import dataclass as _dataclass_for_memory

from app.core.config import Settings, get_settings

_tracer_provider_configured = False
_tracing_lock = Lock()
_current_trace_id: ContextVar[str | None] = ContextVar('marketing_current_trace_id', default=None)
_request_trace_context: ContextVar[Any | None] = ContextVar('marketing_request_trace_context', default=None)


def reset_tracing() -> None:
    global _tracer_provider_configured, _memory_exporter
    _tracer_provider_configured = False
    _memory_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    trace.set_tracer_provider(provider)


@dataclass(slots=True)
class TracingHandle:
    enabled: bool
    tracer_name: str

    @property
    def tracer(self):
        return trace.get_tracer(self.tracer_name)


class InMemorySpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[Any] = []

    def export(self, spans: list[Any]) -> SpanExportResult:
        for span in spans:
            attributes: dict[str, Any] = {}
            try:
                raw_attributes = getattr(span, "attributes", {})
                attributes = dict(raw_attributes)
            except Exception:
                attributes = {}
            self.spans.append(MemorySpanRecord(name=getattr(span, "name", ""), attributes=attributes))
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def clear(self) -> None:
        self.spans.clear()


@_dataclass_for_memory(slots=True)
class MemorySpanRecord:
    name: str
    attributes: dict[str, Any]


class _NoopSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def record_exception(self, *_args, **_kwargs):
        return None

    def set_status(self, *_args, **_kwargs):
        return None


_memory_exporter = InMemorySpanExporter()


def get_memory_span_exporter() -> InMemorySpanExporter:
    return _memory_exporter


def configure_tracing(settings: Settings | None = None) -> TracingHandle:
    global _tracer_provider_configured
    settings = settings or get_settings()
    tracer_name = f"{settings.app_name}.http"
    if not settings.trace_enabled:
        return TracingHandle(enabled=False, tracer_name=tracer_name)
    if _tracer_provider_configured:
        return TracingHandle(enabled=True, tracer_name=tracer_name)
    with _tracing_lock:
        if _tracer_provider_configured:
            return TracingHandle(enabled=True, tracer_name=tracer_name)
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(_memory_exporter))
        if settings.otel_exporter_otlp_endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)))
        _tracer_provider_configured = True
    return TracingHandle(enabled=True, tracer_name=tracer_name)


def should_trace_path(path: str) -> bool:
    return path not in {'/healthz', '/readyz', '/metrics'}


def set_current_trace_id(value: str | None) -> None:
    _current_trace_id.set(value)


def get_current_trace_id() -> str | None:
    return _current_trace_id.get()


def extract_trace_context_headers(request: Request) -> dict[str, str]:
    headers = {}
    for key in ('traceparent', 'tracestate', 'x-trace-id'):
        value = request.headers.get(key)
        if value:
            headers[key] = value
    return headers


def _attribute_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


@contextmanager
def start_span(name: str, *, attributes: dict[str, Any] | None = None, kind: SpanKind = SpanKind.INTERNAL) -> Iterator[Any]:
    settings = get_settings()
    handle = configure_tracing(settings)
    request_context = get_request_trace_context()
    if not handle.enabled:
        span = _NoopSpan()
        set_span_attributes(span, attributes)
        start = perf_counter()
        try:
            yield span
            span.set_attribute('status', 'ok')
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.set_attribute('status', 'error')
            raise
        finally:
            span.set_attribute('duration_ms', round((perf_counter() - start) * 1000, 3))
        return
    tracer = handle.tracer
    token = otel_context.attach(request_context) if request_context is not None else None
    try:
        with tracer.start_as_current_span(name, kind=kind) as span:
            set_span_attributes(span, attributes)
            start = perf_counter()
            try:
                yield span
                current_attributes = _span_attributes_snapshot(span)
                if current_attributes.get('status') != 'error':
                    span.set_attribute('status', 'ok')
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                span.set_attribute('status', 'error')
                raise
            finally:
                span.set_attribute('duration_ms', round((perf_counter() - start) * 1000, 3))
    finally:
        if token is not None:
            otel_context.detach(token)


def set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    if span is None or not attributes:
        return
    for key, value in attributes.items():
        normalized = _attribute_value(value)
        if normalized is not None:
            span.set_attribute(key, normalized)


def _span_attributes_snapshot(span: Any) -> dict[str, Any]:
    raw = getattr(span, 'attributes', None)
    if raw:
        try:
            return dict(raw)
        except Exception:
            pass
    fallback = getattr(span, '_attributes', None)
    if fallback:
        try:
            return dict(fallback)
        except Exception:
            pass
    return {}


def attach_request_context(request: Request) -> None:
    carrier = extract_trace_context_headers(request)
    if carrier:
        context = propagate.extract(carrier)
        request.state._trace_context = context
        _request_trace_context.set(context)
    else:
        _request_trace_context.set(None)


def get_request_trace_context() -> Any | None:
    return _request_trace_context.get()


def detach_request_context(request: Request) -> None:
    if hasattr(request.state, '_trace_context'):
        delattr(request.state, '_trace_context')
    _request_trace_context.set(None)
