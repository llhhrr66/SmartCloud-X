from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..registry import ToolDefinition

# ——————————————————————————————————————
# input / output schemas
# ——————————————————————————————————————


class SearchDocumentsInput(BaseModel):
    query: str = Field(..., min_length=1, description="search query")
    knowledge_base_id: str = Field(default="default", description="knowledge base id")
    top_k: int = Field(default=5, ge=1, le=50, description="max results")


class SearchDocumentsOutput(BaseModel):
    results: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0


class ImportDocumentInput(BaseModel):
    knowledge_base_id: str = Field(..., min_length=1)
    source_url: str | None = None
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportDocumentOutput(BaseModel):
    document_id: str
    status: str = "imported"


class ListKnowledgeBasesInput(BaseModel):
    pass


class KnowledgeBaseInfo(BaseModel):
    id: str
    name: str
    document_count: int = 0


class ListKnowledgeBasesOutput(BaseModel):
    items: list[KnowledgeBaseInfo] = Field(default_factory=list)


# ——————————————————————————————————————
# tool definitions
# ——————————————————————————————————————

knowledge_tools: list[ToolDefinition] = [
    ToolDefinition(
        name="search_documents",
        description="search documents in a knowledge base",
        input_schema=SearchDocumentsInput,
        output_schema=SearchDocumentsOutput,
        is_readonly=True,
        allowed_roles=["research", "marketing", "admin"],
    ),
    ToolDefinition(
        name="import_document",
        description="import a document into a knowledge base",
        input_schema=ImportDocumentInput,
        output_schema=ImportDocumentOutput,
        is_readonly=False,
        allowed_roles=["admin"],
    ),
    ToolDefinition(
        name="list_knowledge_bases",
        description="list all available knowledge bases",
        input_schema=ListKnowledgeBasesInput,
        output_schema=ListKnowledgeBasesOutput,
        is_readonly=True,
        allowed_roles=["research", "marketing", "admin"],
    ),
]
