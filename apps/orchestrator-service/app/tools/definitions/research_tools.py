from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..registry import ToolDefinition

# ——————————————————————————————————————
# input / output schemas
# ——————————————————————————————————————


class SearchInput(BaseModel):
    query: str = Field(..., min_length=1)
    source: str = Field(default="all", description="data source: web, internal, all")
    max_results: int = Field(default=10, ge=1, le=100)


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


class SearchOutput(BaseModel):
    results: list[SearchResult] = Field(default_factory=list)
    total: int = 0
    took_ms: float = 0


class AnalyzeInput(BaseModel):
    content: str = Field(..., min_length=1)
    analysis_type: str = Field(default="summary", description="summary | sentiment | qa | extract")
    options: dict[str, Any] = Field(default_factory=dict)


class AnalyzeOutput(BaseModel):
    analysis: dict[str, Any] = Field(default_factory=dict)


class ResearchQueryInput(BaseModel):
    topic: str = Field(..., min_length=1)
    depth: str = Field(default="basic", description="basic | standard | deep")


class ResearchQueryOutput(BaseModel):
    report: str
    sources: int = 0


# ——————————————————————————————————————
# tool definitions
# ——————————————————————————————————————

research_tools: list[ToolDefinition] = [
    ToolDefinition(
        name="search",
        description="search across internal and external data sources",
        input_schema=SearchInput,
        output_schema=SearchOutput,
        is_readonly=True,
        allowed_roles=["research", "admin"],
    ),
    ToolDefinition(
        name="analyze",
        description="analyze content with specified analysis type",
        input_schema=AnalyzeInput,
        output_schema=AnalyzeOutput,
        is_readonly=True,
        allowed_roles=["research", "admin"],
    ),
    ToolDefinition(
        name="research_query",
        description="perform deep research on a topic",
        input_schema=ResearchQueryInput,
        output_schema=ResearchQueryOutput,
        is_readonly=True,
        allowed_roles=["research", "admin"],
    ),
]
