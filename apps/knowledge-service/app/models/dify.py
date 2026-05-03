from pydantic import BaseModel, Field


class DifyRetrievalSetting(BaseModel):
    top_k: int = Field(ge=1, le=20, alias="top_k")
    score_threshold: float = Field(ge=0, le=1, alias="score_threshold")


class DifyMetadataFilterCondition(BaseModel):
    name: list[str] = Field(min_length=1)
    comparison_operator: str = Field(min_length=1)
    value: str | None = None


class DifyMetadataCondition(BaseModel):
    logical_operator: str = "and"
    conditions: list[DifyMetadataFilterCondition] = Field(default_factory=list)


class DifyExternalKnowledgeRequest(BaseModel):
    knowledge_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    retrieval_setting: DifyRetrievalSetting
    metadata_condition: DifyMetadataCondition | None = None


class DifyExternalKnowledgeRecord(BaseModel):
    content: str
    score: float
    title: str
    metadata: dict[str, object] = Field(default_factory=dict)


class DifyExternalKnowledgeResponse(BaseModel):
    records: list[DifyExternalKnowledgeRecord] = Field(default_factory=list)
