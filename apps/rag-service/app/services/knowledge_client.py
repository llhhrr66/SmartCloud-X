import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.tracing import inject_current_context, start_span
from app.models.rag import KnowledgeSearchCandidate, KnowledgeSearchPayload, RetrieveRequest


class KnowledgeServiceProtocolError(ValueError):
    pass


class KnowledgeServiceClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def search(
        self,
        request: RetrieveRequest,
        rewritten_query: str,
        headers: dict[str, str] | None = None,
    ) -> list[KnowledgeSearchCandidate]:
        payload = {
            "query": rewritten_query,
            "topK": min(max(request.top_k * 2, request.top_k), 20),
            "sourceIds": request.filters.source_ids,
            "tags": request.filters.tags,
        }
        with start_span(
            "rag.knowledge_service.search",
            smartcloud_upstream_service="knowledge-service",
            smartcloud_upstream_path=f"{self.settings.knowledge_service_api_prefix}/search",
            smartcloud_search_query=rewritten_query,
            smartcloud_search_top_k=payload["topK"],
            smartcloud_search_source_filter_count=len(request.filters.source_ids),
            smartcloud_search_tag_filter_count=len(request.filters.tags),
        ) as span:
            outbound_headers = inject_current_context(dict(headers or {}))
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_ms / 1000) as client:
                response = await client.post(
                    f"{self.settings.knowledge_service_base_url.rstrip('/')}"
                    f"{self.settings.knowledge_service_api_prefix}/search",
                    json=payload,
                    headers=outbound_headers,
                )
                response.raise_for_status()
            if span is not None:
                span.set_attribute("smartcloud.upstream.status_code", response.status_code)

            try:
                envelope = response.json()
            except ValueError as exc:
                raise KnowledgeServiceProtocolError("knowledge-service returned invalid JSON") from exc
            if not isinstance(envelope, dict):
                raise KnowledgeServiceProtocolError("knowledge-service returned a non-object envelope")
            data = envelope.get("data") or {}
            try:
                parsed = KnowledgeSearchPayload.model_validate(data)
            except ValidationError as exc:
                raise KnowledgeServiceProtocolError(
                    "knowledge-service returned an invalid search payload"
                ) from exc
            if span is not None:
                span.set_attribute("smartcloud.upstream.result_count", len(parsed.results))
            return parsed.results
