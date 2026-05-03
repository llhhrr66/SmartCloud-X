from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
from fastapi import HTTPException, Request, Response
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.core.config import GatewaySettings
from app.core.upstreams import UpstreamDefinition
from app.services.logging import log_event
from app.services.request_context import RequestIdentity, get_request_identity


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


class UpstreamHttpService:
    def __init__(
        self,
        *,
        settings: GatewaySettings,
        registry: dict[str, UpstreamDefinition],
        transports: dict[str, httpx.BaseTransport | httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.transports = transports or {}
        self._clients: dict[str, httpx.AsyncClient] = {}

    def _client(self, upstream_name: str) -> httpx.AsyncClient:
        if upstream_name not in self._clients:
            upstream = self.registry[upstream_name]
            self._clients[upstream_name] = httpx.AsyncClient(
                base_url=upstream.base_url.rstrip("/"),
                timeout=httpx.Timeout(self.settings.request_timeout_ms / 1000),
                trust_env=False,
                transport=self.transports.get(upstream_name),
            )
        return self._clients[upstream_name]

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def request(
        self,
        upstream_name: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        request_identity: RequestIdentity | None = None,
    ) -> httpx.Response:
        client = self._client(upstream_name)
        started = time.perf_counter()
        upstream_path = path.split("?", 1)[0]
        try:
            request_coro = client.request(
                method,
                path,
                headers=normalize_headers(headers),
                content=content,
                params=params,
                timeout=timeout,
            )
            response = await asyncio.wait_for(request_coro, timeout=timeout + 0.05 if timeout else None)
        except httpx.TimeoutException as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=method,
                path=upstream_path,
                status=504,
                latency_ms=elapsed_ms(started),
                error_category="timeout",
            )
            raise HTTPException(status_code=504, detail={"code": 5040001, "message": str(exc)}) from exc
        except asyncio.TimeoutError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=method,
                path=upstream_path,
                status=504,
                latency_ms=elapsed_ms(started),
                error_category="timeout",
            )
            raise HTTPException(status_code=504, detail={"code": 5040001, "message": "upstream timed out"}) from exc
        except httpx.ConnectError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=method,
                path=upstream_path,
                status=502,
                latency_ms=elapsed_ms(started),
                error_category="connect_error",
            )
            raise HTTPException(status_code=502, detail={"code": 5020001, "message": str(exc)}) from exc
        except httpx.HTTPError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=method,
                path=upstream_path,
                status=502,
                latency_ms=elapsed_ms(started),
                error_category="bad_response",
            )
            raise HTTPException(status_code=502, detail={"code": 5020001, "message": str(exc)}) from exc
        self._log_upstream_call(
            request_identity,
            upstream_name=upstream_name,
            method=method,
            path=upstream_path,
            status=response.status_code,
            latency_ms=elapsed_ms(started),
            error_category=classify_upstream_status(response.status_code),
        )
        return response

    async def request_json(
        self,
        upstream_name: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        params: dict[str, Any] | None = None,
        request_identity: RequestIdentity | None = None,
    ) -> dict[str, Any]:
        response = await self.request(
            upstream_name,
            method,
            path,
            headers=headers,
            content=content,
            params=params,
            request_identity=request_identity,
        )
        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=method,
                path=path,
                status=response.status_code,
                latency_ms=0,
                error_category="bad_response",
            )
            raise HTTPException(
                status_code=502,
                detail={"code": 5020002, "message": f"{upstream_name} returned invalid JSON"},
            ) from exc
        return payload if isinstance(payload, dict) else {}

    async def proxy(
        self,
        request: Request,
        upstream_name: str,
        path: str | None = None,
        *,
        content: bytes | None = None,
    ) -> Response:
        response = await self.request(
            upstream_name,
            request.method,
            path or request.url.path,
            headers=forward_headers(request),
            content=content if content is not None else await request.body(),
            params=dict(request.query_params),
            request_identity=get_request_identity(request),
        )
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=response_headers(response),
            media_type=response.headers.get("content-type"),
        )

    async def stream_proxy(
        self,
        request: Request,
        upstream_name: str,
        *,
        path: str | None = None,
        content: bytes | None = None,
        transform_stream: Callable[[AsyncIterator[bytes]], AsyncIterator[bytes]] | None = None,
        timeout: float | None = None,
        on_stream_start: Callable[[int, dict[str, str]], None] | None = None,
        on_stream_end: Callable[[dict[str, Any]], None] | None = None,
    ) -> StreamingResponse:
        upstream = self.registry[upstream_name]
        temp_client: httpx.AsyncClient | None = None
        client = self._client(upstream_name)
        request_identity = get_request_identity(request)
        stream_started = time.perf_counter()
        effective_path = path or request.url.path
        if timeout is not None:
            temp_client = httpx.AsyncClient(
                base_url=upstream.base_url.rstrip("/"),
                timeout=httpx.Timeout(timeout),
                trust_env=False,
                transport=self.transports.get(upstream_name),
            )
            client = temp_client
        request_body = content if content is not None else await request.body()
        upstream_request = client.build_request(
            request.method,
            effective_path,
            headers=normalize_headers(forward_headers(request)),
            content=request_body,
            params=dict(request.query_params),
        )
        try:
            send_coro = client.send(upstream_request, stream=True)
            upstream_response = await asyncio.wait_for(send_coro, timeout=timeout + 0.05 if timeout else None)
        except httpx.TimeoutException as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=request.method,
                path=effective_path,
                status=504,
                latency_ms=elapsed_ms(stream_started),
                error_category="timeout",
            )
            raise HTTPException(status_code=504, detail={"code": 5040001, "message": str(exc)}) from exc
        except asyncio.TimeoutError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=request.method,
                path=effective_path,
                status=504,
                latency_ms=elapsed_ms(stream_started),
                error_category="timeout",
            )
            raise HTTPException(status_code=504, detail={"code": 5040001, "message": "upstream stream timed out"}) from exc
        except httpx.ConnectError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=request.method,
                path=effective_path,
                status=502,
                latency_ms=elapsed_ms(stream_started),
                error_category="connect_error",
            )
            raise HTTPException(status_code=502, detail={"code": 5020001, "message": str(exc)}) from exc
        except httpx.HTTPError as exc:  # pragma: no cover
            self._log_upstream_call(
                request_identity,
                upstream_name=upstream_name,
                method=request.method,
                path=effective_path,
                status=502,
                latency_ms=elapsed_ms(stream_started),
                error_category="bad_response",
            )
            raise HTTPException(status_code=502, detail={"code": 5020001, "message": str(exc)}) from exc

        headers = response_headers(upstream_response)
        self._log_upstream_call(
            request_identity,
            upstream_name=upstream_name,
            method=request.method,
            path=effective_path,
            status=upstream_response.status_code,
            latency_ms=elapsed_ms(stream_started),
            error_category=classify_upstream_status(upstream_response.status_code),
        )
        if on_stream_start is not None:
            on_stream_start(upstream_response.status_code, headers)

        upstream_content_type = upstream_response.headers.get("content-type", "")
        is_event_stream = upstream_content_type.startswith("text/event-stream")
        if transform_stream is None and not is_event_stream:
            body = await upstream_response.aread()
            await upstream_response.aclose()
            if temp_client is not None:
                await temp_client.aclose()
            return Response(
                content=body,
                status_code=upstream_response.status_code,
                headers=headers,
                media_type=upstream_content_type or None,
            )

        stream = upstream_response.aiter_bytes()
        if transform_stream is not None:
            stream = transform_stream(stream)

        async def monitored_stream() -> AsyncIterator[bytes]:
            total_bytes = 0
            chunk_count = 0
            completion_reason = "stream_completed"
            try:
                async for chunk in stream:
                    chunk_count += 1
                    total_bytes += len(chunk)
                    yield chunk
            except Exception:
                completion_reason = "stream_aborted"
                raise
            finally:
                if on_stream_end is not None:
                    on_stream_end(
                        {
                            "event": completion_reason,
                            "total_bytes": total_bytes,
                            "chunk_count": chunk_count,
                            "upstream_status": upstream_response.status_code,
                            "upstream_latency_ms": elapsed_ms(stream_started),
                        }
                    )

        async def _cleanup() -> None:
            await upstream_response.aclose()
            if temp_client is not None:
                await temp_client.aclose()

        return StreamingResponse(
            monitored_stream(),
            status_code=upstream_response.status_code,
            headers=headers,
            media_type="text/event-stream",
            background=BackgroundTask(_cleanup),
        )

    async def probe(self, upstream_name: str) -> dict[str, Any]:
        upstream = self.registry[upstream_name]
        started = time.perf_counter()
        timeout = 3.0
        try:
            health_response = await self.request(
                upstream_name,
                "GET",
                upstream.health_path,
                timeout=timeout,
            )
            ready = True
            ready_status = None
            if upstream.ready_path:
                ready_response = await self.request(
                    upstream_name,
                    "GET",
                    upstream.ready_path,
                    timeout=timeout,
                )
                ready_status = ready_response.status_code
                if ready_response.status_code == 404:
                    ready = health_response.status_code < 400
                else:
                    ready = ready_response.status_code < 400
            status_value = "ok" if health_response.status_code < 400 and ready else "not_ready"
            return {
                "status": status_value,
                "health_status_code": health_response.status_code,
                "ready_status_code": ready_status,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }
        except HTTPException as exc:
            return {
                "status": "not_ready",
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": exc.detail,
            }

    def _log_upstream_call(
        self,
        request_identity: RequestIdentity | None,
        *,
        upstream_name: str,
        method: str,
        path: str,
        status: int,
        latency_ms: int,
        error_category: str | None,
    ) -> None:
        log_event(
            "upstream_call",
            request_id=request_identity.request_id if request_identity else None,
            trace_id=request_identity.trace_id if request_identity else None,
            subject_type=request_identity.subject_type if request_identity else None,
            subject_id=request_identity.subject_id if request_identity else None,
            tenant_id=request_identity.tenant_id if request_identity else None,
            upstream_service=upstream_name,
            upstream_method=method,
            upstream_path=path,
            upstream_status=status,
            upstream_latency_ms=latency_ms,
            error_category=error_category,
        )


def forward_headers(request: Request, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        key: decode_header_value(value)
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "authorization"
    }
    authorization = request.headers.get("authorization")
    if authorization:
        headers["authorization"] = authorization
    headers["x-caller-service"] = "gateway-service"
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not headers.get("idempotency-key"):
        headers["idempotency-key"] = build_fallback_idempotency_key(request)
    if extra:
        headers.update({key: decode_header_value(value) for key, value in extra.items()})
    return headers


def response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def normalize_headers(headers: dict[str, str] | None) -> list[tuple[str | bytes, str | bytes]] | None:
    if headers is None:
        return None
    normalized: list[tuple[str | bytes, str | bytes]] = []
    for key, value in headers.items():
        try:
            value.encode("ascii")
            normalized.append((key, value))
        except UnicodeEncodeError:
            normalized.append((key.encode("ascii"), value.encode("utf-8")))
    return normalized


def decode_header_value(value: str) -> str:
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except UnicodeDecodeError:
        return value
    return repaired if repaired.isprintable() else value


def build_fallback_idempotency_key(request: Request) -> str:
    body = getattr(request, "_body", None)
    path_fragment = request.url.path.strip("/").replace("/", "-") or "root"
    if body is None:
        request_id = getattr(request.state, "request_id", "gateway")
        return f"gwy-{request.method.lower()}-{path_fragment}-{request_id}"
    digest = hashlib.sha256(body).hexdigest()[:24]
    return f"gwy-{request.method.lower()}-{path_fragment}-{digest}"


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def classify_upstream_status(status_code: int) -> str | None:
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if 400 <= status_code < 500:
        return "bad_request"
    if 500 <= status_code < 600:
        return "bad_response"
    return None
