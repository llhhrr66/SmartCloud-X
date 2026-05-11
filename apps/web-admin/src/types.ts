export type AdminPermission =
  | "admin:ops.read"
  | "admin:ops.write"
  | "admin:kb.read"
  | "admin:kb.write"
  | "admin:job.read"
  | "admin:marketing.read"
  | "admin:marketing.write"
  | string;

export interface AdminMenuItem {
  code: string;
  name: string;
  path: string;
  icon?: string | null;
  children?: AdminMenuItem[];
}

export interface AdminProfile {
  admin_id?: string;
  adminId?: string;
  name: string;
  roles: string[];
  permissions: AdminPermission[];
  menus: AdminMenuItem[];
}

export interface AdminSession {
  accessToken: string;
  refreshToken: string;
  admin: AdminProfile;
}

export interface DashboardSummary {
  conversation_count: number;
  error_count: number;
  active_alert_count: number;
  p95_latency_ms: number;
  total_cost: number | string;
}

export interface PageResult<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  total_pages?: number;
}

export interface KnowledgeBaseRecord {
  kb_id: string;
  code: string;
  name: string;
  scene: string;
  language: string;
  retrieval_mode: string;
  status: string;
  description?: string | null;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocumentRecord {
  id?: string;
  doc_id: string;
  sourceId?: string;
  source_id?: string;
  kb_id: string;
  title: string;
  status: string;
  parse_status: string;
  index_status: string;
  version_no: number;
  file_id?: string | null;
  source_type?: string | null;
  source_uri?: string | null;
  chunk_count: number;
  token_count: number;
  error_message?: string | null;
  indexed_at?: string | null;
}

export type DocumentRecord = KnowledgeDocumentRecord;

export interface KnowledgeChunkRecord {
  id?: string;
  chunk_id: string;
  documentId?: string;
  document_id?: string;
  documentTitle?: string;
  document_title?: string;
  ordinal?: number;
  doc_id: string;
  position: number;
  content?: string;
  content_preview: string;
  tokenEstimate?: number;
  token_count: number;
  keywords?: string[];
  score?: number | null;
  tags: string[];
  updated_at?: string | null;
}

export type ChunkRecord = KnowledgeChunkRecord;

export interface DocumentDetail {
  document: KnowledgeDocumentRecord;
  chunk_stats: {
    chunk_count: number;
    token_count: number;
    average_tokens_per_chunk: number;
    latest_job_id?: string | null;
  };
  error_message?: string | null;
}

export interface AdminJob {
  id?: string;
  job_id: string;
  sourceId?: string;
  source_id?: string;
  documentId?: string;
  document_id?: string;
  type: string;
  status: string;
  progress: number;
  documentsReceived?: number;
  documents_received?: number;
  chunksCreated?: number;
  chunks_created?: number;
  warnings?: string[];
  created_at: string;
  completedAt?: string | null;
  completed_at?: string | null;
  params?: Record<string, unknown> | null;
  result_file_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  finished_at?: string | null;
}

export type AdminAsyncJob = AdminJob;
export type IngestionJob = AdminJob;
export type AdminDocumentRecord = KnowledgeDocumentRecord;

export interface UploadRecord {
  upload_id: string;
  status: string;
  filename: string;
  bucket: string;
  object_key: string;
  file_id: string;
  resolved_file_id?: string | null;
  source_type: string;
  source_uri: string;
  content_type?: string | null;
  size_bytes?: number | null;
  checksum?: string | null;
  created_at: string;
  updated_at: string;
}

export interface SearchPreviewResult {
  query: string;
  queryTokens?: string[];
  sourceBreakdown?: Array<{
    sourceId: string;
    sourceName: string;
    resultCount: number;
    bestScore: number;
  }>;
  tagBreakdown?: Array<{ label: string; count: number }>;
  rewritten_query?: string | null;
  total: number;
  degraded: boolean;
  items: Array<{
    doc_id: string;
    chunk_id: string;
    kb_id?: string | null;
    title: string;
    score: number;
    content_preview: string;
    source_type?: string | null;
    tags: string[];
  }>;
  results?: Array<{
    chunk: {
      id: string;
      documentTitle: string;
      content: string;
    };
    sourceName: string;
    score: number;
    matchReason: string;
  }>;
}

export type KnowledgeSearchPayload = SearchPreviewResult;

export interface RetrievalDiagnosticResult {
  query?: string;
  rewritten_query?: string;
  total?: number;
  coverage?: Record<string, unknown>;
  sources?: unknown[];
  citations?: unknown[];
  [key: string]: unknown;
}

export interface AgentRecord {
  name: string;
  code: string;
  display_name: string;
  domain: string;
  description: string;
  supported_scenes: string[];
  tool_whitelist: string[];
  fallback_agent: string;
  max_tool_calls: number;
  enabled: boolean;
  timeout_seconds: number;
}

export interface MarketingCampaign {
  campaign_id: string;
  name: string;
  product_type: string;
  status: "published" | "draft" | "expired";
  start_at: string;
  end_at: string;
  landing_page_url: string;
  highlights: string[];
}

export interface AuditRecord {
  audit_id: string;
  operator_type: string;
  operator_id: string;
  resource_type: string;
  resource_id: string;
  action: string;
  reason: string;
  before_json?: Record<string, unknown> | null;
  after_json?: Record<string, unknown> | null;
  operator_ip?: string | null;
  created_at: string;
}

export type AdminAuditRecord = AuditRecord;

export interface HealthPayload {
  service?: string;
  status?: string;
  ready?: boolean;
  warnings?: string[];
  counts?: Record<string, string | number>;
  knowledgeServiceBaseUrl?: string;
  knowledgeServiceApiPrefix?: string;
  requestTimeoutMs?: string | number;
  dataPath?: string;
  starterCatalogPath?: string;
  auditPath?: string;
  importRoot?: string;
  maxImportFiles?: string | number;
  corsAllowedOrigins?: string[];
  upstream?: {
    status?: string;
    reachable?: boolean;
    ready?: boolean;
    latencyMs?: number;
    error?: string;
  };
  readinessChecks?: Array<{
    name: string;
    status: string;
    detail: string;
  }>;
  [key: string]: unknown;
}

export interface RuntimeSnapshot {
  overview?: Record<string, unknown>;
  integrations?: {
    pendingEvents?: number;
    outboxPath?: string;
    rawMirrorRoot?: string;
    eventCounters?: Record<string, number>;
    rawStorage: ConnectorStatus;
    metadataStore: ConnectorStatus;
    vectorStore: ConnectorStatus;
    bm25Store: ConnectorStatus;
    cache: ConnectorStatus;
    taskQueue: ConnectorStatus;
    recentEvents: RuntimeEvent[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface ConnectorStatus {
  backend: string;
  configured: boolean;
  target?: string;
  endpoint?: string;
}

export interface RuntimeEvent {
  eventId: string;
  operation: string;
  docId: string;
  status: string;
  queueName: string;
  chunkCount: number;
  createdAt: string;
  processorId?: string;
  attemptCount?: number;
  lastError?: string;
  vectorTarget?: string | null;
  bm25Target?: string | null;
  rawObject: {
    storageKind: string;
  };
  connectorResults?: Array<{
    connector: string;
    status: string;
  }>;
}

export type KnowledgeRuntimeSnapshot = RuntimeSnapshot;

export interface LegacySource {
  id?: string;
  sourceId?: string;
  source_id?: string;
  name: string;
  kind?: string;
  uri?: string;
  tags?: string[];
  [key: string]: unknown;
}

export type SourceRecord = LegacySource;

/** Full document content from knowledge-service, used by the document viewer. */
export interface KnowledgeDocumentContent {
  /** knowledge-service uses camelCase aliases: id, sourceId, createdAt, updatedAt */
  id: string;
  sourceId: string;
  title: string;
  content: string;
  tags?: string[];
  language?: string;
  checksum?: string;
  chunkIds?: string[];
  createdAt?: string | null;
  updatedAt?: string | null;
  /** Alternate snake_case keys that may appear in some API versions */
  doc_id?: string;
  kb_id?: string;
  source_type?: string | null;
  source_uri?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** FAQ document reference from L1 cache hit. */
export interface FaqDocumentRef {
  docId: string;
  title: string;
  url?: string;
}

/** Structured FAQ metadata returned alongside an L1 FAQ cache hit. */
export interface FaqMetadata {
  category?: string | null;
  prerequisites?: string[];
  documentRefs?: FaqDocumentRef[];
  relatedTopics?: string[];
  matchReason?: string | null;
  tokenSaved?: number;
}

export type KnowledgeOverview = {
  counts: Record<string, number>;
  averageChunksPerDocument: number;
  latestIngestionAt?: string | null;
  sourcesByKind: Array<{ label: string; count: number }>;
  topTags: Array<{ label: string; count: number }>;
  documentLanguages: Array<{ label: string; count: number }>;
  largestSources: Array<{
    sourceId: string;
    sourceName: string;
    kind: string;
    documentCount: number;
    chunkCount: number;
    updatedAt?: string;
    tags?: string[];
  }>;
  recentIngestions?: unknown[];
};

export type FileImportPreviewItem = {
  path: string;
  title: string;
  extension: string;
  sizeBytes: number;
  importable: boolean;
  note?: string | null;
};

export type FileImportPreviewPayload = {
  importRoot: string;
  directory: string;
  glob: string;
  matchedFiles: number;
  importableFiles: number;
  items: FileImportPreviewItem[];
};

export type FileImportPayload = {
  importRoot: string;
  directory: string;
  glob: string;
  source: LegacySource;
  processedFiles: number;
  importedFiles: number;
  reusedFiles: number;
  failedFiles: number;
  results: Array<{
    path: string;
    title: string;
    status: string;
    documentId?: string | null;
    chunksCreated?: number;
    warning?: string | null;
    error?: string | null;
  }>;
};

export type RetrievalCitation = {
  title?: string;
  documentTitle?: string;
  chunkId?: string;
  sourceName?: string;
  score?: number;
  content?: string;
  snippet?: string;
  reasoning?: string;
  [key: string]: unknown;
};

export type AdminDocumentDetailPayload = DocumentDetail;
