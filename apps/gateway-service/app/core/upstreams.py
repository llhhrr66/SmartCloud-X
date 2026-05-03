from __future__ import annotations

from dataclasses import dataclass

from app.core.config import GatewaySettings


@dataclass(frozen=True, slots=True)
class UpstreamDefinition:
    name: str
    base_url: str
    health_path: str = "/healthz"
    ready_path: str | None = None


def build_upstream_registry(settings: GatewaySettings) -> dict[str, UpstreamDefinition]:
    return {
        "auth-user-service": UpstreamDefinition(
            name="auth-user-service",
            base_url=settings.auth_user_service_base_url,
            ready_path="/readyz",
        ),
        "marketing-service": UpstreamDefinition(
            name="marketing-service",
            base_url=settings.marketing_service_base_url,
            ready_path="/readyz",
        ),
        "research-service": UpstreamDefinition(
            name="research-service",
            base_url=settings.research_service_base_url,
            ready_path="/readyz",
        ),
        "orchestrator-service": UpstreamDefinition(
            name="orchestrator-service",
            base_url=settings.orchestrator_service_base_url,
            ready_path="/readyz",
        ),
        "tool-hub-service": UpstreamDefinition(
            name="tool-hub-service",
            base_url=settings.tool_hub_service_base_url,
            ready_path="/readyz",
        ),
        "business-tools-service": UpstreamDefinition(
            name="business-tools-service",
            base_url=settings.business_tools_service_base_url,
            ready_path="/readyz",
        ),
        "knowledge-service": UpstreamDefinition(
            name="knowledge-service",
            base_url=settings.knowledge_service_base_url,
            ready_path="/readyz",
        ),
        "rag-service": UpstreamDefinition(
            name="rag-service",
            base_url=settings.rag_service_base_url,
            ready_path="/readyz",
        ),
    }
