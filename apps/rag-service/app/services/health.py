from __future__ import annotations

from functools import lru_cache
from time import perf_counter
from typing import Any
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
        cache_info = get_retrieval_cache().describe()
        return {
            "status": "ok" if ready else "degraded",
            "ready": ready,
            "service": self.settings.app_name,
            "knowledgeServiceBaseUrl": self.settings.knowledge_service_base_url,
            "knowledgeServiceApiPrefix": self.settings.knowledge_service_api_prefix,
            "requestTimeoutMs": self.settings.request_timeout_ms,
            "corsAllowedOrigins": self.settings.cors_allowed_origins,
            "cache": cache_info,
            "cacheHitRate": cache_info.get("cacheHitRate", 0.0),
            "cacheSize": cache_info.get("cacheSize", 0),
            "lastPruneTime": cache_info.get("lastPruneTime"),
            "upstream": upstream,
            "warnings": warnings,
        }

    async def build_readiness_payload(self) -> tuple[int, dict[str, Any]]:
        """Build the rag-service readiness payload and matching HTTP status."""
        not_ready_components: list[str] = []
        runtime_mode = self._runtime_mode()
        runtime: dict[str, Any] = {}

        knowledge_dependency = await self._probe_upstream_readiness()
        runtime["knowledgeService"] = {
            "dependencyReadiness": knowledge_dependency,
            "adminCapabilities": self._admin_capability_runtime(knowledge_dependency),
        }
        if not knowledge_dependency["ready"]:
            not_ready_components.append("knowledgeService")

        cache_probe = self._cache_backend_readiness()
        runtime["cache"] = cache_probe
        if not cache_probe["ready"]:
            not_ready_components.append("cache")

        provider_probe = self._provider_runtime_readiness()
        runtime["provider"] = provider_probe
        if not provider_probe["ready"]:
            not_ready_components.append("provider")

        payload = {
            "status": "ready" if not not_ready_components else "not_ready",
            "service": self.settings.app_name,
            "runtime_mode": runtime_mode,
            "not_ready_components": not_ready_components,
            "runtime": runtime,
        }
        return (200 if not not_ready_components else 503), payload

    async def _probe_upstream(self) -> dict[str, object]:
        url = f"{self.settings.knowledge_service_base_url.rstrip('/')}/healthz"
        request_id = f"rag-health-{uuid4().hex[:10]}"
        timeout_seconds = max(min(self.settings.request_timeout_ms, 2500), 250) / 1000
        started = perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
                response = await client.get(
                    url,
                    headers={
                        self.settings.request_id_header: request_id,
                        self.settings.caller_service_header: self.settings.app_name,
                    },
                )
            latency_ms = round((perf_counter() - started) * 1000, 2)
        except Exception as exc:
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
            result["error"] = "; ".join(str(item) for item in warnings if str(item).strip()) or "knowledge-service reported not-ready"
        return result

    async def _probe_upstream_readiness(self) -> dict[str, Any]:
        url = f"{self.settings.knowledge_service_base_url.rstrip('/')}/readyz"
        request_id = f"rag-ready-{uuid4().hex[:10]}"
        timeout_seconds = max(min(self.settings.request_timeout_ms, 2500), 250) / 1000
        started = perf_counter()

        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
                response = await client.get(
                    url,
                    params={"probe": "1"},
                    headers={
                        self.settings.request_id_header: request_id,
                        self.settings.caller_service_header: self.settings.app_name,
                    },
                )
            latency_ms = round((perf_counter() - started) * 1000, 2)
        except Exception as exc:
            return {
                "ready": False,
                "status": "not_ready",
                "service": "knowledge-service",
                "httpStatus": None,
                "latencyMs": round((perf_counter() - started) * 1000, 2),
                "notReadyComponents": ["knowledgeService"],
                "error": str(exc),
                "url": url,
            }

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if not isinstance(payload, dict):
            return {
                "ready": False,
                "status": "not_ready",
                "service": "knowledge-service",
                "httpStatus": response.status_code,
                "latencyMs": latency_ms,
                "notReadyComponents": ["knowledgeService"],
                "error": "knowledge-service readiness probe returned invalid JSON",
                "url": url,
            }

        status = payload.get("status")
        service = payload.get("service") or "knowledge-service"
        not_ready_components = payload.get("not_ready_components")
        if not isinstance(not_ready_components, list):
            not_ready_components = []

        ready = response.status_code < 400 and status == "ready"
        result = {
            "ready": ready,
            "status": status if isinstance(status, str) else "not_ready",
            "service": service,
            "httpStatus": response.status_code,
            "latencyMs": latency_ms,
            "notReadyComponents": not_ready_components,
            "runtime": payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {},
            "url": url,
        }
        if not ready:
            result["error"] = payload.get("error") or "knowledge-service readiness probe reported not-ready"
        return result

    def _cache_backend_readiness(self) -> dict[str, Any]:
        cache = get_retrieval_cache()
        description = cache.describe()
        enabled = bool(description.get("enabled", True))
        backend = str(description.get("backend", "memory"))
        if enabled and backend != "disabled":
            return {
                "ready": True,
                "status": "ready",
                "backend": backend,
                "cacheSize": description.get("cacheSize", 0),
                "cacheHitRate": description.get("cacheHitRate", 0.0),
                "namespace": self.settings.cache_namespace,
            }
        return {
            "ready": False,
            "status": "not_ready",
            "backend": backend,
            "cacheSize": description.get("cacheSize", 0),
            "cacheHitRate": description.get("cacheHitRate", 0.0),
            "namespace": self.settings.cache_namespace,
            "error": "retrieval cache disabled",
        }

    def _provider_runtime_readiness(self) -> dict[str, Any]:
        return {
            "ready": True,
            "status": "ready",
            "backend": "knowledge-service",
            "baseUrl": self.settings.knowledge_service_base_url,
            "apiPrefix": self.settings.knowledge_service_api_prefix,
            "notes": [
                "rag admin diagnostics and answer preview depend on knowledge-service retrieval/search availability",
            ],
        }

    def _admin_capability_runtime(self, knowledge_dependency: dict[str, Any]) -> dict[str, Any]:
        runtime = knowledge_dependency.get("runtime")
        object_storage_runtime = runtime.get("objectStorage") if isinstance(runtime, dict) else None
        object_storage_ready = bool(
            isinstance(object_storage_runtime, dict) and object_storage_runtime.get("ready")
        )
        object_storage_error = None
        if isinstance(object_storage_runtime, dict) and not object_storage_ready:
            object_storage_error = object_storage_runtime.get("error")

        admin_jobs_ready = bool(knowledge_dependency.get("ready"))
        audit_ready = bool(knowledge_dependency.get("ready"))
        diagnostics_ready = bool(knowledge_dependency.get("ready"))
        answer_preview_ready = bool(knowledge_dependency.get("ready"))

        return {
            "diagnostics": {
                "ready": diagnostics_ready,
                "status": "ready" if diagnostics_ready else "not_ready",
                "dependency": "knowledgeService",
                "error": knowledge_dependency.get("error") if not diagnostics_ready else None,
            },
            "answerPreview": {
                "ready": answer_preview_ready,
                "status": "ready" if answer_preview_ready else "not_ready",
                "dependency": "knowledgeService",
                "error": knowledge_dependency.get("error") if not answer_preview_ready else None,
            },
            "jobs": {
                "ready": admin_jobs_ready,
                "status": "ready" if admin_jobs_ready else "not_ready",
                "dependency": "knowledgeService",
                "error": knowledge_dependency.get("error") if not admin_jobs_ready else None,
            },
            "audit": {
                "ready": audit_ready,
                "status": "ready" if audit_ready else "not_ready",
                "dependency": "knowledgeService",
                "error": knowledge_dependency.get("error") if not audit_ready else None,
            },
            "objectStorage": {
                "ready": object_storage_ready,
                "status": "ready" if object_storage_ready else "not_ready",
                "dependency": "knowledgeService.runtime.objectStorage",
                "error": object_storage_error,
            },
        }

    def _runtime_mode(self) -> str:
        if self.settings.redis_url and self.settings.cache_enabled:
            return "shared-backend"
        if self.settings.redis_url or self.settings.cache_enabled:
            return "mixed"
        return "local-fallback"


@lru_cache(maxsize=1)
def get_health_service() -> RagHealthService:
    return RagHealthService()
