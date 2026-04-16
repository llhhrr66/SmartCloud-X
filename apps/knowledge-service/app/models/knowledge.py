from typing import Literal

from pydantic import BaseModel, Field, model_validator


SourceKind = Literal["faq", "playbook", "policy", "product", "manual", "note", "other"]
FileImportStatus = Literal["imported", "reused", "failed"]


class SourceSeed(BaseModel):
    name: str = Field(min_length=1)
    kind: SourceKind = "other"
    uri: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class CreateSourceRequest(SourceSeed):
    pass


class KnowledgeSource(SourceSeed):
    id: str
    document_count: int = Field(default=0, alias="documentCount")
    chunk_count: int = Field(default=0, alias="chunkCount")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")

    model_config = {
        "populate_by_name": True,
    }


class IngestDocumentRequest(BaseModel):
    source_id: str | None = Field(default=None, alias="sourceId")
    source: SourceSeed | None = None
    title: str = Field(min_length=1)
    content: str = Field(min_length=20)
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"
    source_type: str | None = Field(default=None, alias="sourceType")
    source_uri: str | None = Field(default=None, alias="sourceUri")

    model_config = {
        "populate_by_name": True,
    }

    @model_validator(mode="after")
    def validate_source_ref(self) -> "IngestDocumentRequest":
        if self.source_id or self.source:
            return self
        raise ValueError("Either sourceId or source must be provided.")


class KnowledgeDocument(BaseModel):
    id: str
    source_id: str = Field(alias="sourceId")
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"
    checksum: str
    chunk_ids: list[str] = Field(default_factory=list, alias="chunkIds")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")

    model_config = {
        "populate_by_name": True,
    }


class KnowledgeChunk(BaseModel):
    id: str
    source_id: str = Field(alias="sourceId")
    document_id: str = Field(alias="documentId")
    document_title: str = Field(alias="documentTitle")
    ordinal: int
    content: str
    token_estimate: int = Field(alias="tokenEstimate")
    keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
    }


class IngestionJob(BaseModel):
    id: str
    source_id: str = Field(alias="sourceId")
    document_id: str = Field(alias="documentId")
    status: Literal["completed", "failed"] = "completed"
    documents_received: int = Field(alias="documentsReceived")
    chunks_created: int = Field(alias="chunksCreated")
    warnings: list[str] = Field(default_factory=list)
    created_at: str = Field(alias="createdAt")
    completed_at: str = Field(alias="completedAt")

    model_config = {
        "populate_by_name": True,
    }


class IngestionResponse(BaseModel):
    job: IngestionJob
    source: KnowledgeSource
    document: KnowledgeDocument
    chunks_created: int = Field(alias="chunksCreated")

    model_config = {
        "populate_by_name": True,
    }


class StarterCatalogItem(BaseModel):
    source: SourceSeed
    title: str = Field(min_length=1)
    content: str = Field(min_length=20)
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"


class StarterCatalog(BaseModel):
    documents: list[StarterCatalogItem] = Field(default_factory=list)


class BootstrapCatalogResponse(BaseModel):
    seeded_documents: int = Field(alias="seededDocuments")
    reused_documents: int = Field(alias="reusedDocuments")
    source_count: int = Field(alias="sourceCount")
    document_count: int = Field(alias="documentCount")
    chunk_count: int = Field(alias="chunkCount")

    model_config = {
        "populate_by_name": True,
    }


class FileImportPreviewRequest(BaseModel):
    directory: str | None = None
    glob_pattern: str = Field(default="**/*", alias="glob")
    max_files: int = Field(default=12, ge=1, le=100, alias="maxFiles")

    model_config = {
        "populate_by_name": True,
    }


class FileImportRequest(FileImportPreviewRequest):
    source_id: str | None = Field(default=None, alias="sourceId")
    source: SourceSeed | None = None
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"

    model_config = {
        "populate_by_name": True,
    }


class FileImportPreviewItem(BaseModel):
    path: str
    title: str
    extension: str
    size_bytes: int = Field(alias="sizeBytes")
    importable: bool = True
    note: str | None = None

    model_config = {
        "populate_by_name": True,
    }


class FileImportPreviewResponse(BaseModel):
    import_root: str = Field(alias="importRoot")
    directory: str
    glob_pattern: str = Field(alias="glob")
    matched_files: int = Field(alias="matchedFiles")
    importable_files: int = Field(alias="importableFiles")
    items: list[FileImportPreviewItem] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class FileImportResultItem(BaseModel):
    path: str
    title: str
    status: FileImportStatus
    document_id: str | None = Field(default=None, alias="documentId")
    chunks_created: int = Field(default=0, alias="chunksCreated")
    warning: str | None = None
    error: str | None = None

    model_config = {
        "populate_by_name": True,
    }


class FileImportResponse(BaseModel):
    import_root: str = Field(alias="importRoot")
    directory: str
    glob_pattern: str = Field(alias="glob")
    source: KnowledgeSource
    processed_files: int = Field(alias="processedFiles")
    imported_files: int = Field(alias="importedFiles")
    reused_files: int = Field(alias="reusedFiles")
    failed_files: int = Field(alias="failedFiles")
    results: list[FileImportResultItem] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class CountBucket(BaseModel):
    label: str
    count: int


class SourceSnapshot(BaseModel):
    source_id: str = Field(alias="sourceId")
    source_name: str = Field(alias="sourceName")
    kind: SourceKind = "other"
    document_count: int = Field(alias="documentCount")
    chunk_count: int = Field(alias="chunkCount")
    updated_at: str = Field(alias="updatedAt")
    tags: list[str] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class RecentIngestionActivity(BaseModel):
    job_id: str = Field(alias="jobId")
    source_id: str = Field(alias="sourceId")
    source_name: str = Field(alias="sourceName")
    document_id: str = Field(alias="documentId")
    document_title: str = Field(alias="documentTitle")
    status: Literal["completed", "failed"] = "completed"
    chunks_created: int = Field(alias="chunksCreated")
    completed_at: str = Field(alias="completedAt")
    warnings: list[str] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class KnowledgeOverviewResponse(BaseModel):
    counts: dict[str, int] = Field(default_factory=dict)
    average_chunks_per_document: float = Field(default=0.0, alias="averageChunksPerDocument")
    latest_ingestion_at: str | None = Field(default=None, alias="latestIngestionAt")
    sources_by_kind: list[CountBucket] = Field(default_factory=list, alias="sourcesByKind")
    top_tags: list[CountBucket] = Field(default_factory=list, alias="topTags")
    document_languages: list[CountBucket] = Field(default_factory=list, alias="documentLanguages")
    largest_sources: list[SourceSnapshot] = Field(default_factory=list, alias="largestSources")
    recent_ingestions: list[RecentIngestionActivity] = Field(
        default_factory=list,
        alias="recentIngestions",
    )

    model_config = {
        "populate_by_name": True,
    }


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20, alias="topK")
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    tags: list[str] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class SearchAppliedFilters(BaseModel):
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    tags: list[str] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class SearchSourceBreakdown(BaseModel):
    source_id: str = Field(alias="sourceId")
    source_name: str = Field(alias="sourceName")
    result_count: int = Field(alias="resultCount")
    best_score: float = Field(alias="bestScore")

    model_config = {
        "populate_by_name": True,
    }


class SearchResult(BaseModel):
    chunk: KnowledgeChunk
    source_name: str = Field(alias="sourceName")
    score: float
    match_reason: str = Field(alias="matchReason")

    model_config = {
        "populate_by_name": True,
    }


class SearchResponse(BaseModel):
    query: str
    total: int
    query_tokens: list[str] = Field(default_factory=list, alias="queryTokens")
    applied_filters: SearchAppliedFilters = Field(
        default_factory=lambda: SearchAppliedFilters(),
        alias="appliedFilters",
    )
    source_breakdown: list[SearchSourceBreakdown] = Field(
        default_factory=list,
        alias="sourceBreakdown",
    )
    tag_breakdown: list[CountBucket] = Field(default_factory=list, alias="tagBreakdown")
    results: list[SearchResult] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }
