from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.models.common import ApiEnvelope, ErrorInfo, TraceContext


logger = logging.getLogger(__name__)


class RagClientError(RuntimeError):
    """Base exception raised for rag-service client failures."""


class RagClientProtocolError(RagClientError):
    """Raised when rag-service returns an invalid envelope or payload."""


class RagClientUnavailableError(RagClientError):
    """Raised when rag-service is unreachable or times out."""


class RagClientResponseError(RagClientError):
    """Raised when rag-service returns an error response."""

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        self.request_id = request_id


class RagClient:
    """HTTP client for orchestrator -> rag-service internal contracts.

    Centralises endpoint paths, timeout handling, required trace headers, tenant /
    authorization forwarding, ApiEnvelope parsing and baseline error mapping so
    downstream business code does not need to deal with raw httpx details.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._base_url, self._base_url_source = self._resolve_base_url()
        self._api_prefix, self._api_prefix_source = self._resolve_api_prefix()
        logger.info(
            "rag-service client configured",
            extra={
                "rag_base_url": self._base_url,
                "rag_base_url_source": self._base_url_source,
                "rag_api_prefix": self._api_prefix,
                "rag_api_prefix_source": self._api_prefix_source,
            },
        )

    def retrieve(
        self,
        payload: dict[str, Any],
        *,
        trace: TraceContext | None = None,
        tenant_id: str | None = None,
        authorization: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Call rag-service retrieve and return the unwrapped data payload.

        Args:
            payload: Internal retrieve request payload sent to rag-service.
            trace: Optional trace context used to populate request headers.
            tenant_id: Optional tenant identifier propagated via header.
            authorization: Optional bearer token forwarded to rag-service.
            timeout: Optional request timeout in seconds.

        Returns:
            The `data` object from rag-service `ApiEnvelope`.

        Raises:
            RagClientUnavailableError: When rag-service is unreachable or times out.
            RagClientResponseError: When rag-service returns a structured error.
            RagClientProtocolError: When rag-service returns an invalid envelope.
        """

        return self._post(
            "/retrieve",
            payload,
            trace=trace,
            tenant_id=tenant_id,
            authorization=authorization,
            timeout=timeout,
        )

    def build_context(
        self,
        payload: dict[str, Any],
        *,
        trace: TraceContext | None = None,
        tenant_id: str | None = None,
        authorization: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Call rag-service context and return the unwrapped data payload.

        Args:
            payload: Internal context request payload sent to rag-service.
            trace: Optional trace context used to populate request headers.
            tenant_id: Optional tenant identifier propagated via header.
            authorization: Optional bearer token forwarded to rag-service.
            timeout: Optional request timeout in seconds.

        Returns:
            The `data` object from rag-service `ApiEnvelope`.

        Raises:
            RagClientUnavailableError: When rag-service is unreachable or times out.
            RagClientResponseError: When rag-service returns a structured error.
            RagClientProtocolError: When rag-service returns an invalid envelope.
        """

        return self._post(
            "/context",
            payload,
            trace=trace,
            tenant_id=tenant_id,
            authorization=authorization,
            timeout=timeout,
        )

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        trace: TraceContext | None,
        tenant_id: str | None,
        authorization: str | None,
        timeout: float | None,
    ) -> dict[str, Any]:
        request_headers = self._build_headers(
            trace=trace,
            tenant_id=tenant_id,
            authorization=authorization,
        )
        effective_timeout = timeout or (self.settings.request_timeout_ms / 1000)
        try:
            with self._http_client(timeout=effective_timeout) as client:
                response = client.post(f"{self._api_prefix}{path}", json=payload, headers=request_headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            logger.warning(
                "rag-service request failed",
                extra={
                    "rag_base_url": self._base_url,
                    "rag_base_url_source": self._base_url_source,
                    "rag_api_prefix": self._api_prefix,
                    "rag_api_prefix_source": self._api_prefix_source,
                    "rag_path": path,
                    "rag_timeout_seconds": effective_timeout,
                    "rag_request_headers": sorted(request_headers.keys()),
                    "error_class": exc.__class__.__name__,
                },
            )
            raise RagClientUnavailableError("rag-service request timed out or could not connect.") from exc
        except httpx.HTTPError as exc:
            raise RagClientUnavailableError("rag-service request failed before a response was received.") from exc

        envelope = self._parse_envelope(response)
        if not envelope.success:
            error = envelope.error or ErrorInfo(code="RAG_RETRIEVAL_UNAVAILABLE", message="rag-service returned an unknown error")
            raise RagClientResponseError(
                status_code=response.status_code,
                error_code=error.code,
                message=error.message,
                details=error.details,
                retryable=False,
                request_id=envelope.request_id,
            )
        if envelope.data is None:
            raise RagClientProtocolError("rag-service returned a success envelope without data.")
        if not isinstance(envelope.data, dict):
            raise RagClientProtocolError("rag-service returned a non-object data payload.")
        return envelope.data

    def _http_client(self, *, timeout: float) -> httpx.Client:
        kwargs: dict[str, Any] = {
            "base_url": self._base_url,
            "timeout": timeout,
        }
        if self._is_loopback_base_url(self._base_url):
            kwargs["trust_env"] = False
        return httpx.Client(**kwargs)

    def _build_headers(
        self,
        *,
        trace: TraceContext | None,
        tenant_id: str | None,
        authorization: str | None,
    ) -> dict[str, str]:
        request_id = trace.request_id if trace and trace.request_id else None
        trace_id = trace.trace_id if trace and trace.trace_id else request_id
        conversation_id = trace.conversation_id if trace and trace.conversation_id else None
        headers = {
            self.settings.caller_service_header: self.settings.app_name,
        }
        if request_id:
            headers[self.settings.request_id_header] = request_id
        if trace_id:
            headers[self.settings.trace_id_header] = trace_id
        if conversation_id:
            headers[self.settings.conversation_id_header] = conversation_id
        if tenant_id:
            headers[self.settings.tenant_id_header] = tenant_id
        if authorization:
            headers["Authorization"] = authorization
        return headers

    def _parse_envelope(self, response: httpx.Response) -> ApiEnvelope[dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RagClientProtocolError("rag-service returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise RagClientProtocolError("rag-service returned a non-object envelope.")
        try:
            envelope = ApiEnvelope[dict[str, Any]].model_validate(payload)
        except ValidationError as exc:
            raise RagClientProtocolError("rag-service returned an invalid ApiEnvelope payload.") from exc
        if response.status_code >= 400 and envelope.error is None:
            raise RagClientResponseError(
                status_code=response.status_code,
                error_code="RAG_RETRIEVAL_UNAVAILABLE",
                message="rag-service returned an HTTP error without structured error payload.",
                request_id=envelope.request_id,
            )
        return envelope

    def describe_runtime(self) -> dict[str, Any]:
        """Return the effective rag-service client runtime configuration."""

        return {
            "baseUrl": self._base_url,
            "baseUrlSource": self._base_url_source,
            "apiPrefix": self._api_prefix,
            "apiPrefixSource": self._api_prefix_source,
            "loopback": self._is_loopback_base_url(self._base_url),
            "timeoutSeconds": self.settings.request_timeout_ms / 1000,
            "callerService": self.settings.app_name,
        }

    def _resolve_base_url(self) -> tuple[str, str]:
        for candidate in (
            "SMARTCLOUD_RAG_SERVICE_BASE_URL",
            "RAG_SERVICE_BASE_URL",
        ):
            value = self._read_env(candidate)
            if value:
                return self._normalize_base_url(value, source=candidate), candidate
        if self.settings.rag_service_base_url:
            return self._normalize_base_url(
                self.settings.rag_service_base_url,
                source="settings.rag_service_base_url",
            ), "settings.rag_service_base_url"
        port = self._read_env("SMARTCLOUD_RAG_SERVICE_PORT") or self._read_env("RAG_SERVICE_PORT")
        if port:
            return self._normalize_base_url(f"http://localhost:{port}", source="env-port"), "env-port"
        return self._normalize_base_url(
            f"http://localhost:{self.settings.rag_service_port}",
            source="settings.rag_service_port",
        ), "settings.rag_service_port"

    def _resolve_api_prefix(self) -> tuple[str, str]:
        for candidate in (
            "SMARTCLOUD_RAG_SERVICE_API_PREFIX",
            "RAG_SERVICE_API_PREFIX",
        ):
            value = self._read_env(candidate)
            if value:
                normalized = value.strip()
                if normalized.startswith("/"):
                    return normalized.rstrip("/") or "/", candidate
        if self.settings.rag_service_api_prefix.startswith("/"):
            normalized = self.settings.rag_service_api_prefix.rstrip("/") or "/"
            return normalized, "settings.rag_service_api_prefix"
        return "/api/rag/v1", "default"

    def _normalize_base_url(self, value: str, *, source: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == 8030:
            corrected = parsed._replace(netloc=f"{parsed.hostname}:8040").geturl().rstrip("/")
            logger.warning(
                "rag-service base url %s from %s points to legacy port 8030; overriding to %s to avoid business-tools misrouting.",
                normalized,
                source,
                corrected,
            )
            return corrected
        return normalized

    @staticmethod
    def _read_env(key: str) -> str | None:
        value = os.environ.get(key)
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _is_loopback_base_url(base_url: str) -> bool:
        hostname = (urlparse(base_url).hostname or "").lower()
        return hostname in {"127.0.0.1", "localhost", "::1"}
