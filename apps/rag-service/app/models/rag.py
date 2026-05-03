from pydantic import BaseModel, Field, model_serializer


class CountBucket(BaseModel):
    label: str
    count: int


class SourceBreakdown(BaseModel):
    source_id: str = Field(alias="sourceId")
    source_name: str = Field(alias="sourceName")
    hit_count: int = Field(alias="hitCount")
    best_score: float = Field(alias="bestScore")

    model_config = {
        "populate_by_name": True,
    }


class RetrievalFilters(BaseModel):
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    tags: list[str] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class ConversationMessage(BaseModel):
    role: str | None = None
    content: str = ""


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20, alias="topK")
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    conversation_id: str | None = Field(default=None, alias="conversationId")
    conversation_context: list[ConversationMessage] = Field(default_factory=list, alias="conversationContext")

    model_config = {
        "populate_by_name": True,
    }


class AnswerRequest(RetrieveRequest):
    style: str = "brief"


class KnowledgeChunkRecord(BaseModel):
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


class KnowledgeSearchCandidate(BaseModel):
    chunk: KnowledgeChunkRecord
    source_name: str = Field(alias="sourceName")
    score: float
    match_reason: str = Field(alias="matchReason")

    model_config = {
        "populate_by_name": True,
    }


class KnowledgeSearchPayload(BaseModel):
    query: str
    total: int
    results: list[KnowledgeSearchCandidate] = Field(default_factory=list)


class RetrievalCitation(BaseModel):
    citation_id: str = Field(alias="citationId")
    chunk_id: str = Field(alias="chunkId")
    source_id: str = Field(alias="sourceId")
    source_name: str = Field(alias="sourceName")
    document_id: str = Field(alias="documentId")
    document_title: str = Field(alias="documentTitle")
    snippet: str
    score: float
    backend_used: str = Field(alias="backendUsed")
    reasoning: str

    model_config = {
        "populate_by_name": True,
    }


class RetrievalSource(BaseModel):
    source_id: str = Field(alias="sourceId")
    source_type: str = Field(default="knowledge_base", alias="sourceType")
    title: str
    doc_id: str | None = Field(default=None, alias="docId")
    chunk_id: str | None = Field(default=None, alias="chunkId")
    score: float | None = None
    uri: str | None = None
    snippet: str | None = None
    backend_used: str | None = Field(default=None, alias="backendUsed")
    domain: str | None = None

    model_config = {
        "populate_by_name": True,
    }


class RetrieveResponseCitationItem(BaseModel):
    id: str
    title: str
    source_type: str = Field(alias="source_type")
    doc_id: str | None = None
    chunk_id: str | None = None

    model_config = {
        "populate_by_name": True,
    }


class ContextBuildResult(BaseModel):
    context_text: str = Field(alias="contextText")
    token_estimate: int = Field(alias="tokenEstimate")
    included_count: int = Field(alias="includedCount")
    truncated_count: int = Field(alias="truncatedCount")

    model_config = {
        "populate_by_name": True,
    }


class RetrieveResponse(BaseModel):
    query: str
    rewritten_query: str = Field(alias="rewrittenQuery")
    strategy: str = "hybrid-baseline"
    backend_used: str = Field(default="local-keyword", alias="backendUsed")
    citations: list[RetrievalCitation] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list, alias="coverageNotes")
    degraded: bool = False
    degradation_note: str | None = Field(default=None, alias="degradationNote")
    sources: list[RetrievalSource] = Field(default_factory=list)
    context: ContextBuildResult | None = None

    model_config = {
        "populate_by_name": True,
    }

    @model_serializer(mode="wrap")
    def serialize_model(self, handler):
        payload = handler(self)
        payload["citations"] = [
            {
                "id": item.chunk_id or item.source_id,
                "title": item.title,
                "source_type": item.source_type,
                "doc_id": item.doc_id,
                "chunk_id": item.chunk_id,
            }
            for item in self.sources
        ]
        return payload


class RetrievalDiagnosticResponse(BaseModel):
    query: str
    rewritten_query: str = Field(alias="rewrittenQuery")
    expanded_terms: list[str] = Field(default_factory=list, alias="expandedTerms")
    query_terms: list[str] = Field(default_factory=list, alias="queryTerms")
    unmatched_terms: list[str] = Field(default_factory=list, alias="unmatchedTerms")
    requested_top_k: int = Field(alias="requestedTopK")
    applied_filters: RetrievalFilters = Field(alias="appliedFilters")
    candidate_count: int = Field(alias="candidateCount")
    strategy: str = "hybrid-baseline"
    backend_used: str = Field(default="local-keyword", alias="backendUsed")
    source_breakdown: list[SourceBreakdown] = Field(default_factory=list, alias="sourceBreakdown")
    tag_breakdown: list[CountBucket] = Field(default_factory=list, alias="tagBreakdown")
    citations: list[RetrievalCitation] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list, alias="coverageNotes")
    degraded: bool = False

    model_config = {
        "populate_by_name": True,
    }


class AnswerResponse(BaseModel):
    query: str
    rewritten_query: str = Field(alias="rewrittenQuery")
    backend_used: str = Field(default="local-keyword", alias="backendUsed")
    answer: str
    citations: list[RetrievalCitation] = Field(default_factory=list)
    coverage_notes: list[str] = Field(default_factory=list, alias="coverageNotes")
    degraded: bool = False
    context: ContextBuildResult | None = None

    model_config = {
        "populate_by_name": True,
    }


class QueryRewriteResult(BaseModel):
    original_query: str = Field(alias="originalQuery")
    rewritten_query: str = Field(alias="rewrittenQuery")
    expanded_terms: list[str] = Field(default_factory=list, alias="expandedTerms")
    context_terms: list[str] = Field(default_factory=list, alias="contextTerms")

    model_config = {
        "populate_by_name": True,
    }
