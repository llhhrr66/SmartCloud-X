from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from app.core.config import Settings, get_settings
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeSource

IndexTargetMode = Literal["single-baseline", "mixed", "per-domain"]
_BASELINE_TARGET = "knowledge_chunks"


@dataclass(frozen=True)
class IndexTargetResolution:
    mode: IndexTargetMode
    domain: str | None
    qdrant_collection: str
    opensearch_index: str
    fallback_qdrant_collection: str
    fallback_opensearch_index: str
    used_fallback: bool = False

    def labels(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "domain": self.domain or "baseline",
            "qdrant_collection": self.qdrant_collection,
            "opensearch_index": self.opensearch_index,
            "fallback_qdrant_collection": self.fallback_qdrant_collection,
            "fallback_opensearch_index": self.fallback_opensearch_index,
            "used_fallback": "true" if self.used_fallback else "false",
        }


class KnowledgeIndexTargetResolver:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._baseline_qdrant_collection = _clean_target_name(
            self.settings.qdrant_collection,
            fallback=_BASELINE_TARGET,
        )
        self._baseline_opensearch_index = _clean_target_name(
            self.settings.opensearch_index,
            fallback=_BASELINE_TARGET,
        )
        self._domain_prefix = _clean_target_name(
            getattr(self.settings, "app_name", None),
            fallback="knowledge",
        )

    def resolve_for_document(
        self,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        chunks: Iterable[KnowledgeChunk] | None = None,
    ) -> IndexTargetResolution:
        domain = self._derive_domain(document=document, source=source, chunks=chunks)
        return self.resolve(domain=domain)

    def resolve(self, *, domain: str | None) -> IndexTargetResolution:
        normalized_domain = _normalize_domain(domain)
        if normalized_domain is None:
            return IndexTargetResolution(
                mode="single-baseline",
                domain=None,
                qdrant_collection=self._baseline_qdrant_collection,
                opensearch_index=self._baseline_opensearch_index,
                fallback_qdrant_collection=self._baseline_qdrant_collection,
                fallback_opensearch_index=self._baseline_opensearch_index,
                used_fallback=False,
            )

        return IndexTargetResolution(
            mode="mixed",
            domain=normalized_domain,
            qdrant_collection=self._domain_target("qdrant", normalized_domain),
            opensearch_index=self._domain_target("opensearch", normalized_domain),
            fallback_qdrant_collection=self._baseline_qdrant_collection,
            fallback_opensearch_index=self._baseline_opensearch_index,
            used_fallback=False,
        )

    def search_targets(self, *, domain: str | None) -> list[IndexTargetResolution]:
        primary = self.resolve(domain=domain)
        if primary.mode == "single-baseline":
            return [primary]
        return [
            primary,
            IndexTargetResolution(
                mode="mixed",
                domain=primary.domain,
                qdrant_collection=primary.fallback_qdrant_collection,
                opensearch_index=primary.fallback_opensearch_index,
                fallback_qdrant_collection=primary.fallback_qdrant_collection,
                fallback_opensearch_index=primary.fallback_opensearch_index,
                used_fallback=True,
            ),
        ]

    def runtime_summary(self, *, domain: str | None) -> dict[str, object]:
        resolution = self.resolve(domain=domain)
        if resolution.mode == "single-baseline":
            active_mode: IndexTargetMode = "single-baseline"
        else:
            active_mode = "mixed"
        return {
            "active_mode": active_mode,
            "domain": resolution.domain,
            "qdrant_collection": resolution.qdrant_collection,
            "opensearch_index": resolution.opensearch_index,
            "fallback_qdrant_collection": resolution.fallback_qdrant_collection,
            "fallback_opensearch_index": resolution.fallback_opensearch_index,
        }

    def declared_per_domain_summary(self, *, domain: str | None) -> dict[str, object]:
        resolution = self.resolve(domain=domain)
        return {
            "active_mode": "per-domain" if resolution.domain else "single-baseline",
            "domain": resolution.domain,
            "qdrant_collection": resolution.qdrant_collection,
            "opensearch_index": resolution.opensearch_index,
        }

    def _derive_domain(
        self,
        *,
        document: KnowledgeDocument,
        source: KnowledgeSource,
        chunks: Iterable[KnowledgeChunk] | None,
    ) -> str | None:
        candidates: list[str] = []
        candidates.extend(_extract_domain_tags(document.tags))
        candidates.extend(_extract_domain_tags(source.tags))
        for chunk in chunks or []:
            candidates.extend(_extract_domain_tags(chunk.tags))
            metadata = chunk.metadata if isinstance(chunk.metadata, dict) else {}
            candidates.extend(_extract_domain_values(metadata.get("domainHints")))
            candidates.extend(_extract_domain_values(metadata.get("domain")))
        return candidates[0] if candidates else None

    def _domain_target(self, backend: Literal["qdrant", "opensearch"], domain: str) -> str:
        suffix = domain.replace("_", "-")
        prefix = self._baseline_qdrant_collection if backend == "qdrant" else self._baseline_opensearch_index
        normalized_prefix = _clean_target_name(prefix, fallback=_BASELINE_TARGET)
        return _clean_target_name(
            f"{normalized_prefix}__{suffix}",
            fallback=f"{self._domain_prefix}__{suffix}",
        )


def _clean_target_name(value: str | None, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in value.strip())
    normalized = "_".join(part for part in cleaned.split("_") if part)
    return normalized or fallback


def _normalize_domain(value: str | None) -> str | None:
    normalized = _clean_target_name(value, fallback="")
    return normalized or None


def _extract_domain_tags(values: Iterable[str] | None) -> list[str]:
    domains: list[str] = []
    for item in values or []:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower()
        if normalized.startswith("domain:"):
            domain = _normalize_domain(normalized.split(":", 1)[1])
            if domain:
                domains.append(domain)
                continue
        domain = _normalize_domain(normalized)
        if domain and domain in _KNOWN_DOMAINS:
            domains.append(domain)
    return domains


def _extract_domain_values(value: object) -> list[str]:
    if isinstance(value, str):
        normalized = _normalize_domain(value)
        return [normalized] if normalized else []
    if isinstance(value, list):
        domains: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            normalized = _normalize_domain(item)
            if normalized:
                domains.append(normalized)
        return domains
    return []


_KNOWN_DOMAINS = {
    "customer_service",
    "billing",
    "technical_support",
    "icp",
    "marketing",
    "research",
}
