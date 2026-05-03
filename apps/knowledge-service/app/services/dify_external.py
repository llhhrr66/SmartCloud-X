from __future__ import annotations

import hmac
from functools import lru_cache

from app.core.config import get_settings
from app.models.dify import (
    DifyExternalKnowledgeRecord,
    DifyExternalKnowledgeRequest,
    DifyExternalKnowledgeResponse,
)
from app.models.knowledge import SearchRequest
from app.models.runtime import RuntimeConnectorStatus
from app.services.search import SearchService, get_search_service
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository


class DifyExternalAuthError(ValueError):
    pass


class DifyExternalNotConfiguredError(ValueError):
    pass


class DifyExternalValidationError(ValueError):
    pass


class DifyExternalKnowledgeService:
    def __init__(self, repository: KnowledgeStoreRepository, search_service: SearchService) -> None:
        self.repository = repository
        self.search_service = (
            search_service
            if getattr(search_service, "repository", None) is repository
            else SearchService(repository)
        )
        self.settings = get_settings()

    def build_status(self, *, external_consumer_verified: bool = False) -> RuntimeConnectorStatus:
        configured = bool(self.settings.dify_external_knowledge_api_key)
        status = "verified-live" if configured and external_consumer_verified else (
            "configured" if configured else "disabled"
        )
        return RuntimeConnectorStatus(
            backend="dify-external-knowledge",
            configured=configured,
            status=status,
            endpoint="/retrieval",
            target="knowledge_id -> kb_id|code",
            notes=[
                "Dify external knowledge adapter reuses SmartCloud-X search instead of duplicating corpus storage",
                "Bearer token is validated locally with SMARTCLOUD_DIFY_EXTERNAL_KNOWLEDGE_API_KEY",
            ],
        )

    def authorize(self, authorization: str | None) -> None:
        expected = self.settings.dify_external_knowledge_api_key
        if not expected:
            raise DifyExternalNotConfiguredError("dify external knowledge adapter is disabled")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.strip().lower() != "bearer" or not token.strip():
            raise DifyExternalAuthError("missing bearer token")
        if not hmac.compare_digest(token.strip(), expected):
            raise DifyExternalAuthError("invalid bearer token")

    def retrieve(self, payload: DifyExternalKnowledgeRequest) -> DifyExternalKnowledgeResponse:
        source_id = self._resolve_knowledge_source_id(payload.knowledge_id)
        tags = self._extract_tag_filters(payload)
        search = self.search_service.search(
            SearchRequest(
                query=payload.query,
                topK=payload.retrieval_setting.top_k,
                sourceIds=[source_id],
                tags=tags,
            )
        )
        records: list[DifyExternalKnowledgeRecord] = []
        for item in search.results:
            metadata = {
                "knowledge_id": payload.knowledge_id,
                "kb_id": source_id,
                "source_id": item.chunk.source_id,
                "source_name": item.source_name,
                "chunk_id": item.chunk.id,
                "document_id": item.chunk.document_id,
                "source_type": self._document_source_type(item.chunk.document_id),
                "source_uri": self._document_source_uri(item.chunk.document_id),
                "tags": item.chunk.tags,
                "match_reason": item.match_reason,
            }
            normalized_score = max(0.0, min(float(item.score), 1.0))
            if normalized_score < payload.retrieval_setting.score_threshold:
                continue
            if not self._matches_metadata_conditions(metadata, payload):
                continue
            records.append(
                DifyExternalKnowledgeRecord(
                    content=item.chunk.content,
                    score=round(normalized_score, 4),
                    title=item.chunk.document_title,
                    metadata=metadata,
                )
            )
        return DifyExternalKnowledgeResponse(records=records)

    def _resolve_knowledge_source_id(self, knowledge_id: str) -> str:
        source = self.repository.get_source(knowledge_id)
        if source is not None:
            return source.id
        profile = self.repository.find_knowledge_base_profile_by_code(knowledge_id)
        if profile is not None:
            return profile.kb_id
        raise DifyExternalValidationError(f"unknown knowledge_id: {knowledge_id}")

    def _document_source_type(self, document_id: str) -> str | None:
        profile = self.repository.get_document_profile(document_id)
        return profile.source_type if profile is not None else None

    def _document_source_uri(self, document_id: str) -> str | None:
        profile = self.repository.get_document_profile(document_id)
        return profile.source_uri if profile is not None else None

    @staticmethod
    def _extract_tag_filters(payload: DifyExternalKnowledgeRequest) -> list[str]:
        if payload.metadata_condition is None:
            return []
        tags: list[str] = []
        for condition in payload.metadata_condition.conditions:
            names = {name.strip().lower() for name in condition.name}
            if not names.intersection({"tag", "tags"}):
                continue
            if condition.comparison_operator.strip().lower() != "contains" or not condition.value:
                continue
            tags.append(condition.value.strip())
        return tags

    def _matches_metadata_conditions(
        self,
        metadata: dict[str, object],
        payload: DifyExternalKnowledgeRequest,
    ) -> bool:
        if payload.metadata_condition is None or not payload.metadata_condition.conditions:
            return True
        logical_operator = payload.metadata_condition.logical_operator.strip().lower() or "and"
        evaluations = [
            self._evaluate_condition(metadata, condition)
            for condition in payload.metadata_condition.conditions
        ]
        if logical_operator == "or":
            return any(evaluations)
        return all(evaluations)

    @staticmethod
    def _evaluate_condition(
        metadata: dict[str, object],
        condition,
    ) -> bool:
        operator = condition.comparison_operator.strip().lower()
        if operator not in {"contains", "is", "empty", "not empty"}:
            raise DifyExternalValidationError(f"unsupported comparison operator: {condition.comparison_operator}")

        matches = []
        for name in condition.name:
            key = name.strip().lower()
            value = metadata.get(key)
            if operator == "empty":
                matches.append(value in {None, "", []})
                continue
            if operator == "not empty":
                matches.append(value not in {None, "", []})
                continue
            if condition.value is None:
                raise DifyExternalValidationError("metadata condition value is required for this operator")
            expected = condition.value.strip().lower()
            if isinstance(value, list):
                lowered_items = [str(item).strip().lower() for item in value]
                if operator == "contains":
                    matches.append(any(expected in item for item in lowered_items))
                else:
                    matches.append(expected in lowered_items)
                continue
            text = "" if value is None else str(value).strip().lower()
            if operator == "contains":
                matches.append(expected in text)
            else:
                matches.append(text == expected)
        return any(matches)


@lru_cache(maxsize=1)
def get_dify_external_knowledge_service() -> DifyExternalKnowledgeService:
    return DifyExternalKnowledgeService(get_repository(), get_search_service())
