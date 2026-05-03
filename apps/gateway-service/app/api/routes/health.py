from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.api.common import canonical_success


router = APIRouter(tags=["health"])


def _payload_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status is None:
        return None
    return str(status).lower()


async def _request_upstream_probe(services: Any, name: str, path: str) -> tuple[int | None, dict[str, Any] | None, Any | None]:
    try:
        response = await services.http.request(name, "GET", path, timeout=3.0)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        status_code = exc.status_code if exc.status_code >= 400 else None
        return status_code, detail, exc.detail

    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload if isinstance(payload, dict) else payload, None


async def _probe_upstream_readiness(services: Any, name: str) -> dict[str, Any]:
    definition = services.registry[name]

    if definition.ready_path:
        ready_status_code, ready_payload, ready_error = await _request_upstream_probe(services, name, definition.ready_path)
        payload_status = _payload_status(ready_payload)
        result = {
            "status": "not_ready",
            "contract": "readyz",
            "http_status": ready_status_code,
            "payload": ready_payload,
            "payload_status": payload_status,
            "error": ready_error,
            "ready_status_code": ready_status_code,
            "health_status_code": None,
        }
        if ready_status_code is not None:
            result["status"] = "ready" if ready_status_code < 400 and payload_status == "ready" else "not_ready"
        return result

    health_status_code, health_payload, health_error = await _request_upstream_probe(services, name, definition.health_path)
    result = {
        "status": "not_ready",
        "contract": "healthz-fallback",
        "http_status": health_status_code,
        "payload": health_payload,
        "error": "upstream readiness contract unavailable; using /healthz fallback",
        "ready_status_code": None,
        "health_status_code": health_status_code,
    }
    if health_error is not None:
        result["error"] = health_error
    return result


@router.get("/healthz")
async def healthz(request: Request):
    services = request.app.state.gateway_services
    names = list(services.registry.keys())
    results = await asyncio.gather(*(services.http.probe(name) for name in names))
    upstreams = {name: result for name, result in zip(names, results)}
    status_value = "ok" if all(item["status"] == "ok" for item in upstreams.values()) else "degraded"
    return canonical_success(
        {
            "service": "gateway-service",
            "status": status_value,
            "upstreams": upstreams,
        },
        request.state.request_id,
    )


@router.get("/readyz")
async def readyz(request: Request):
    services = request.app.state.gateway_services
    names = list(services.registry.keys())
    results = await asyncio.gather(*(_probe_upstream_readiness(services, name) for name in names))
    upstreams = {name: result for name, result in zip(names, results)}
    not_ready = [name for name, payload in upstreams.items() if payload["status"] != "ready"]
    status_code = 200 if not not_ready else 503
    return canonical_success(
        {
            "service": "gateway-service",
            "status": "ready" if not not_ready else "not_ready",
            "not_ready_upstreams": not_ready,
            "upstreams": upstreams,
        },
        request.state.request_id,
        status_code=status_code,
    )
