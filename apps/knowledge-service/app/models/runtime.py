from pydantic import BaseModel, Field


class RuntimeConnectorStatus(BaseModel):
    backend: str
    configured: bool
    status: str | None = None
    endpoint: str | None = None
    target: str | None = None
    notes: list[str] = Field(default_factory=list)


class RawObjectMirrorRecord(BaseModel):
    doc_id: str = Field(alias="docId")
    kb_id: str | None = Field(default=None, alias="kbId")
    source_id: str = Field(alias="sourceId")
    storage_kind: str = Field(alias="storageKind")
    bucket: str | None = None
    object_key: str = Field(alias="objectKey")
    mirror_path: str = Field(alias="mirrorPath")
    checksum: str
    content_type: str = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes")
    source_type: str | None = Field(default=None, alias="sourceType")
    source_uri: str | None = Field(default=None, alias="sourceUri")
    created_at: str = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
    }


class ConnectorWriteResult(BaseModel):
    connector: str
    backend: str
    status: str
    target: str | None = None
    detail: str | None = None
    item_count: int | None = Field(default=None, alias="itemCount")
    attempted_at: str = Field(alias="attemptedAt")

    model_config = {
        "populate_by_name": True,
    }


class IndexingOutboxEvent(BaseModel):
    event_id: str = Field(alias="eventId")
    event_type: str = Field(alias="eventType")
    operation: str
    status: str
    queue_name: str = Field(alias="queueName")
    doc_id: str = Field(alias="docId")
    kb_id: str | None = Field(default=None, alias="kbId")
    source_id: str = Field(alias="sourceId")
    job_id: str | None = Field(default=None, alias="jobId")
    chunk_count: int = Field(alias="chunkCount")
    warnings: list[str] = Field(default_factory=list)
    raw_object: RawObjectMirrorRecord = Field(alias="rawObject")
    metadata_target: str | None = Field(default=None, alias="metadataTarget")
    vector_target: str | None = Field(default=None, alias="vectorTarget")
    bm25_target: str | None = Field(default=None, alias="bm25Target")
    cache_namespace: str | None = Field(default=None, alias="cacheNamespace")
    attempt_count: int = Field(default=0, alias="attemptCount")
    processor_id: str | None = Field(default=None, alias="processorId")
    reserved_at: str | None = Field(default=None, alias="reservedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")
    last_error: str | None = Field(default=None, alias="lastError")
    connector_results: list[ConnectorWriteResult] = Field(
        default_factory=list,
        alias="connectorResults",
    )
    created_at: str = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
    }


class KnowledgeRuntimeIntegrations(BaseModel):
    raw_storage: RuntimeConnectorStatus = Field(alias="rawStorage")
    metadata_store: RuntimeConnectorStatus = Field(alias="metadataStore")
    vector_store: RuntimeConnectorStatus = Field(alias="vectorStore")
    bm25_store: RuntimeConnectorStatus = Field(alias="bm25Store")
    dify_external_knowledge: RuntimeConnectorStatus = Field(alias="difyExternalKnowledge")
    dify_dataset_sync: RuntimeConnectorStatus = Field(alias="difyDatasetSync")
    cache: RuntimeConnectorStatus
    task_queue: RuntimeConnectorStatus = Field(alias="taskQueue")
    outbox_path: str = Field(alias="outboxPath")
    raw_mirror_root: str = Field(alias="rawMirrorRoot")
    pending_events: int = Field(alias="pendingEvents")
    event_counters: dict[str, int] = Field(default_factory=dict, alias="eventCounters")
    recent_events: list[IndexingOutboxEvent] = Field(default_factory=list, alias="recentEvents")

    model_config = {
        "populate_by_name": True,
    }
