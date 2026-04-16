from collections import Counter
from functools import lru_cache

from app.models.knowledge import (
    CountBucket,
    KnowledgeOverviewResponse,
    RecentIngestionActivity,
    SourceSnapshot,
)
from app.services.store import KnowledgeStoreRepository
from app.services.store_provider import get_repository


class KnowledgeAnalyticsService:
    def __init__(self, repository: KnowledgeStoreRepository) -> None:
        self.repository = repository

    def build_overview(
        self,
        recent_limit: int = 6,
        top_tag_limit: int = 8,
    ) -> KnowledgeOverviewResponse:
        sources = self.repository.list_sources()
        documents = self.repository.list_documents()
        ingestions = self.repository.list_ingestions()
        counts = self.repository.snapshot_counts()

        kind_counts = Counter(source.kind for source in sources)
        language_counts = Counter(document.language or "unknown" for document in documents)
        tag_counts = Counter()
        for source in sources:
            tag_counts.update(tag.lower() for tag in source.tags)
        for document in documents:
            tag_counts.update(tag.lower() for tag in document.tags)

        recent_ingestions = []
        for job in ingestions[:recent_limit]:
            source = self.repository.get_source(job.source_id)
            document = self.repository.get_document(job.document_id)
            recent_ingestions.append(
                RecentIngestionActivity(
                    jobId=job.id,
                    sourceId=job.source_id,
                    sourceName=source.name if source else job.source_id,
                    documentId=job.document_id,
                    documentTitle=document.title if document else job.document_id,
                    status=job.status,
                    chunksCreated=job.chunks_created,
                    completedAt=job.completed_at,
                    warnings=job.warnings,
                )
            )

        average_chunks = 0.0
        if counts["documents"] > 0:
            average_chunks = round(counts["chunks"] / counts["documents"], 2)

        largest_sources = [
            SourceSnapshot(
                sourceId=source.id,
                sourceName=source.name,
                kind=source.kind,
                documentCount=source.document_count,
                chunkCount=source.chunk_count,
                updatedAt=source.updated_at,
                tags=source.tags,
            )
            for source in sorted(
                sources,
                key=lambda item: (item.chunk_count, item.document_count, item.updated_at),
                reverse=True,
            )[:5]
        ]

        return KnowledgeOverviewResponse(
            counts=counts,
            averageChunksPerDocument=average_chunks,
            latestIngestionAt=ingestions[0].completed_at if ingestions else None,
            sourcesByKind=self._to_buckets(kind_counts),
            topTags=self._to_buckets(tag_counts, limit=top_tag_limit),
            documentLanguages=self._to_buckets(language_counts),
            largestSources=largest_sources,
            recentIngestions=recent_ingestions,
        )

    @staticmethod
    def _to_buckets(counter: Counter[str], limit: int | None = None) -> list[CountBucket]:
        items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if limit is not None:
            items = items[:limit]
        return [CountBucket(label=label, count=count) for label, count in items]


@lru_cache(maxsize=1)
def get_analytics_service() -> KnowledgeAnalyticsService:
    return KnowledgeAnalyticsService(get_repository())
