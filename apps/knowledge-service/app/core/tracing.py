from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter as GrpcOTLPSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter as HttpOTLPSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import Settings, get_settings


def _build_resource(settings: Settings) -> Resource:
    return Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": settings.app_version,
            "deployment.environment": settings.env,
        }
    )


def _build_exporter(settings: Settings):
    endpoint = settings.otlp_endpoint
    if not endpoint:
        return None

    protocol = settings.otlp_protocol.strip().lower()
    if protocol == "http/protobuf":
        return HttpOTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")
    return GrpcOTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))


@lru_cache(maxsize=1)
def get_tracer_provider() -> TracerProvider | None:
    settings = get_settings()
    if not settings.trace_enabled:
        return None

    exporter = _build_exporter(settings)
    if exporter is None:
        return None

    provider = TracerProvider(resource=_build_resource(settings))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


@lru_cache(maxsize=1)
def get_tracer():
    provider = get_tracer_provider()
    if provider is None:
        return None
    return provider.get_tracer(get_settings().app_name)


def configure_tracing(app: FastAPI, settings: Settings) -> None:
    if getattr(app.state, "tracing_configured", False):
        return

    provider = get_tracer_provider()
    if provider is None or not settings.trace_enabled:
        return

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="/healthz,/metrics",
    )
    app.state.tracing_configured = True


def _normalize_attribute(value: Any):
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        normalized = [
            item
            for item in value
            if isinstance(item, (bool, int, float, str))
        ]
        return normalized or None
    return str(value)


def annotate_current_span(**attributes: Any) -> None:
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return

    for key, value in attributes.items():
        normalized = _normalize_attribute(value)
        if normalized is not None:
            span.set_attribute(key, normalized)


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Any]:
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        annotate_current_span(**attributes)
        yield span


def inject_current_context(headers: dict[str, str] | None = None) -> dict[str, str]:
    carrier = headers if headers is not None else {}
    inject(carrier)
    return carrier
