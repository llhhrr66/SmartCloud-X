from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import urlparse

from app.core import metrics as _metrics
from app.core.config import get_settings
from app.core.telemetry import set_span_attributes, start_span

try:
    from minio import Minio
except Exception:
    Minio = None


@dataclass
class PosterArtifactStorage:
    """Wraps MinIO interactions for poster image artefacts.

    Treats absent or misconfigured object storage as a soft failure: the
    methods return a public placeholder URL so downstream code can keep
    operating in environments that don't run MinIO (tests, local dev).
    """

    def _client(self):
        settings = get_settings()
        if not settings.minio_endpoint or not settings.minio_bucket or Minio is None:
            return None, None
        if not settings.minio_access_key or not settings.minio_secret_key:
            return None, None
        parsed = urlparse(settings.minio_endpoint)
        endpoint = parsed.netloc or parsed.path
        client = Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=(parsed.scheme or "https") == "https",
        )
        return client, settings.minio_bucket

    def readiness(self, *, trace: bool = True) -> dict[str, object]:
        settings = get_settings()
        if not settings.minio_endpoint:
            return {"ready": True, "configured": False, "detail": "disabled"}
        client, bucket = self._client()
        if client is None or bucket is None:
            return {"ready": False, "configured": True, "detail": "missing-credentials"}
        span_context = (
            start_span("marketing.minio_bucket_exists", attributes={"operation": "minio_bucket_exists", "bucket": bucket})
            if trace
            else nullcontext()
        )
        with span_context as span:
            try:
                exists = client.bucket_exists(bucket)
                if exists:
                    _metrics.marketing_minio_operations_total.labels(operation="bucket_exists", status="success").inc()
                    set_span_attributes(span, {"status": "ok", "bucket_ready": True})
                    return {"ready": True, "configured": True, "detail": "bucket-ready"}
                _metrics.marketing_minio_operations_total.labels(operation="bucket_exists", status="miss").inc()
                set_span_attributes(span, {"status": "error", "bucket_ready": False, "error_type": "bucket_missing"})
                return {"ready": False, "configured": True, "detail": "bucket-missing"}
            except Exception as exc:
                _metrics.marketing_minio_operations_total.labels(operation="bucket_exists", status="error").inc()
                _metrics.marketing_upstream_errors_total.labels(backend="minio", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
                return {"ready": False, "configured": True, "detail": f"error:{exc.__class__.__name__}"}

    def object_exists(self, task_id: str) -> bool | None:
        client, bucket = self._client()
        if client is None or bucket is None:
            return None
        with start_span(
            "marketing.minio_stat_object",
            attributes={"operation": "minio_stat_object", "poster_task_id": task_id},
        ) as span:
            try:
                client.stat_object(bucket, f"{task_id}.png")
                _metrics.marketing_minio_operations_total.labels(operation="stat_object", status="success").inc()
                set_span_attributes(span, {"status": "ok"})
            except Exception as exc:
                _metrics.marketing_minio_operations_total.labels(operation="stat_object", status="error").inc()
                _metrics.marketing_upstream_errors_total.labels(backend="minio", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
                return False
        return True

    def ensure_object_present(self, task_id: str, payload: bytes, mime_type: str = "image/png") -> str:
        existing = self.object_exists(task_id)
        settings = get_settings()
        fallback_url = f"{settings.poster_public_base_url.rstrip('/')}/{task_id}.png"
        if existing is True:
            return fallback_url
        return self.store_bytes(task_id, payload, mime_type)

    def store_bytes(self, task_id: str, payload: bytes, mime_type: str = "image/png") -> str:
        settings = get_settings()
        object_name = f"{task_id}.png"
        public_url = f"{settings.poster_public_base_url.rstrip('/')}/{object_name}"
        client, bucket = self._client()
        if client is None or bucket is None:
            return public_url
        with start_span(
            "marketing.minio_put_object",
            attributes={"operation": "minio_put_object", "poster_task_id": task_id},
        ) as span:
            try:
                bucket_exists = client.bucket_exists(bucket)
                if bucket_exists:
                    _metrics.marketing_minio_operations_total.labels(operation="bucket_exists", status="success").inc()
                else:
                    _metrics.marketing_minio_operations_total.labels(operation="bucket_exists", status="miss").inc()
                    client.make_bucket(bucket)
                    _metrics.marketing_minio_operations_total.labels(operation="make_bucket", status="success").inc()
                client.put_object(bucket, object_name, BytesIO(payload), len(payload), content_type=mime_type)
                _metrics.marketing_minio_operations_total.labels(operation="put_object", status="success").inc()
                set_span_attributes(span, {"status": "ok"})
            except Exception as exc:
                operation = "put_object"
                if "bucket_exists" in locals() and bucket_exists is False:
                    operation = "make_bucket"
                    _metrics.marketing_minio_operations_total.labels(operation="make_bucket", status="error").inc()
                else:
                    _metrics.marketing_minio_operations_total.labels(operation="put_object", status="error").inc()
                _metrics.marketing_upstream_errors_total.labels(backend="minio", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__, "failed_operation": operation})
                return public_url
        return public_url

    def delete_object(self, task_id: str) -> bool | None:
        client, bucket = self._client()
        if client is None or bucket is None:
            return None
        with start_span(
            "marketing.minio_remove_object",
            attributes={"operation": "minio_remove_object", "poster_task_id": task_id},
        ) as span:
            try:
                client.remove_object(bucket, f"{task_id}.png")
                _metrics.marketing_minio_operations_total.labels(operation="remove_object", status="success").inc()
                set_span_attributes(span, {"status": "ok"})
                return True
            except Exception as exc:
                _metrics.marketing_minio_operations_total.labels(operation="remove_object", status="error").inc()
                _metrics.marketing_upstream_errors_total.labels(backend="minio", error_type=exc.__class__.__name__).inc()
                set_span_attributes(span, {"status": "error", "error_type": exc.__class__.__name__})
                return False
