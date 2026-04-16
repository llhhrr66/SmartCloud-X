from __future__ import annotations

from functools import lru_cache
from time import perf_counter
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.services.cache import get_retrieval_cache


class RagHealthService:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def build_payload(self) -> dict[str, object]:
        upstream = await self._probe_upstream()
        ready = bool(upstream["reachable"] and upstream["ready"])
        warnings = [str(upstream["error"])] if upstream.get("error") else []
        return {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "service": self.settings.app_name,
            "knowledgeServiceBaseUrl": self.settings.knowledge_service_base_url,
            "knowledgeServiceApiPrefix": self.settings.knowledge_service_api_prefix,
            "requestTimeoutMs": self.settings.request_timeout_ms,
            "corsAllowedOrigins": self.settings.cors_allowed_origins,
            "cache": get_retrieval_cache().describe(),
            "upstream": upstream,
            "warnings": warnings,
        }

    async def _probe_upstream(self) -> dict[str, object]:
        url = f"{self.settings.knowledge_service_base_url.rstrip('/')}/healthz"
        request_id = f"rag-health-{uuid4().hex[:10]}"
        timeout_seconds = max(min(self.settings.request_timeout_ms, 2500), 250) / 1000
        started = perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.get(
                    url,
                    headers={
                        self.settings.request_id_header: request_id,
                        self.settings.caller_service_header: self.settings.app_name,
                    },
                )
            latency_ms = round((perf_counter() - started) * 1000, 2)
        except Exception as exc:  # noqa: BLE001 - health payload should degrade, not crash
            return {
                "url": url,
                "reachable": False,
                "ready": False,
                "status": "unreachable",
                "latencyMs": round((perf_counter() - started) * 1000, 2),
                "error": str(exc),
            }

        try:
            envelope = response.json()
        except ValueError:
            envelope = None

        if response.status_code >= 400:
            return {
                "url": url,
                "reachable": False,
                "ready": False,
                "status": f"http_{response.status_code}",
                "latencyMs": latency_ms,
                "error": f"knowledge-service health probe returned HTTP {response.status_code}",
            }

        data = envelope.get("data") if isinstance(envelope, dict) else {}
        ready = bool(isinstance(data, dict) and data.get("ready"))
        status = data.get("status") if isinstance(data, dict) else "invalid-payload"

        result = {
            "url": url,
            "reachable": True,
            "ready": ready,
            "status": status or "unknown",
            "latencyMs": latency_ms,
        }
        if not isinstance(envelope, dict):
            result["error"] = "knowledge-service health probe returned invalid JSON"
        elif not isinstance(data, dict):
            result["error"] = "knowledge-service health probe returned an invalid envelope"
        elif not ready:
            warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
            result["error"] = (
                "; ".join(str(item) for item in warnings if str(item).strip())
                or "knowledge-service reported not-ready"
            )
        return result


@lru_cache(maxsize=1)
def get_health_service() -> RagHealthService:
    return RagHealthService()
