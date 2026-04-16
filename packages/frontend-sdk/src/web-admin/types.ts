import type {
  AdminAsyncJob as ContractAdminAsyncJob,
  AdminKnowledgeBase as ContractAdminKnowledgeBase,
  AdminKnowledgeBaseListData as ContractAdminKnowledgeBaseListData,
  AdminKnowledgeDocument as ContractAdminKnowledgeDocument,
  AdminKnowledgeDocumentDetailData as ContractAdminKnowledgeDocumentDetailData,
  AdminKnowledgeDocumentListData as ContractAdminKnowledgeDocumentListData,
  AdminRetrievalDiagnosticsData as ContractAdminRetrievalDiagnosticsData,
  AdminRetrievalSearchPreviewData as ContractAdminRetrievalSearchPreviewData,
  AdminRetrievalSearchSource as ContractAdminRetrievalSearchSource
} from '@smartcloud-x/common-schemas';

export type HealthReadinessCheck = {
  name: string;
  status: string;
  detail: string;
};

export type HealthUpstreamPayload = {
  url: string;
  reachable: boolean;
  ready: boolean;
  status: string;
  latencyMs?: number;
  error?: string;
};

export type HealthPayload = {
  status: string;
  service: string;
  ready?: boolean;
  readinessChecks?: HealthReadinessCheck[];
  warnings?: string[];
  upstream?: HealthUpstreamPayload;
  counts?: Record<string, number>;
  dataPath?: string;
  auditPath?: string;
  starterCatalogPath?: string;
  importRoot?: string;
  maxImportFiles?: number;
  knowledgeServiceBaseUrl?: string;
  knowledgeServiceApiPrefix?: string;
  requestTimeoutMs?: number;
  corsAllowedOrigins?: string[];
};

export type SourceRecord = {
  id: string;
  name: string;
  kind: string;
  description?: string | null;
  tags: string[];
  documentCount: number;
  chunkCount: number;
  createdAt: string;
  updatedAt: string;
};

export type DocumentRecord = {
  id: string;
  sourceId: string;
  title: string;
  content: string;
  tags: string[];
  language: string;
  checksum: string;
  chunkIds: string[];
  createdAt: string;
  updatedAt: string;
};

export type ChunkRecord = {
  id: string;
  sourceId: string;
  documentId: string;
  documentTitle: string;
  ordinal: number;
  content: string;
  tokenEstimate: number;
  keywords: string[];
  tags: string[];
  createdAt: string;
};

export type IngestionJob = {
  id: string;
  sourceId: string;
  documentId: string;
  status: string;
  documentsReceived: number;
  chunksCreated: number;
  warnings: string[];
  createdAt: string;
  completedAt: string;
};

export type IngestionResult = {
  job: IngestionJob;
  source: SourceRecord;
  chunksCreated: number;
  document: {
    id: string;
    title: string;
  };
};

export type BootstrapPayload = {
  seededDocuments: number;
  reusedDocuments: number;
  sourceCount: number;
  documentCount: number;
  chunkCount: number;
};

export type CountBucket = {
  label: string;
  count: number;
};

export type SourceSnapshot = {
  sourceId: string;
  sourceName: string;
  kind: string;
  documentCount: number;
  chunkCount: number;
  updatedAt: string;
  tags: string[];
};

export type KnowledgeOverview = {
  counts: Record<string, number>;
  averageChunksPerDocument: number;
  latestIngestionAt?: string | null;
  sourcesByKind: CountBucket[];
  topTags: CountBucket[];
  documentLanguages: CountBucket[];
  largestSources: SourceSnapshot[];
  recentIngestions: Array<{
    jobId: string;
    sourceId: string;
    sourceName: string;
    documentId: string;
    documentTitle: string;
    status: string;
    chunksCreated: number;
    completedAt: string;
    warnings: string[];
  }>;
};

export type RetrievalCitation = {
  chunkId: string;
  sourceId: string;
  sourceName: string;
  documentId: string;
  documentTitle: string;
  snippet: string;
  score: number;
  reasoning: string;
};

export type RetrievalFiltersPayload = {
  sourceIds: string[];
  tags: string[];
};

export type RetrievalPayload = {
  query: string;
  rewrittenQuery: string;
  strategy: string;
  citations: RetrievalCitation[];
  coverageNotes: string[];
  degraded: boolean;
};

export type RetrievalDiagnosticPayload = RetrievalPayload & {
  expandedTerms: string[];
  queryTerms: string[];
  unmatchedTerms: string[];
  requestedTopK: number;
  appliedFilters: RetrievalFiltersPayload;
  candidateCount: number;
  sourceBreakdown: Array<{
    sourceId: string;
    sourceName: string;
    hitCount: number;
    bestScore: number;
  }>;
  tagBreakdown: CountBucket[];
};

export type AnswerPayload = RetrievalPayload & {
  answer: string;
};

export type KnowledgeSearchSourceBreakdown = {
  sourceId: string;
  sourceName: string;
  resultCount: number;
  bestScore: number;
};

export type KnowledgeSearchPayload = {
  query: string;
  total: number;
  queryTokens: string[];
  appliedFilters: RetrievalFiltersPayload;
  sourceBreakdown: KnowledgeSearchSourceBreakdown[];
  tagBreakdown: CountBucket[];
  results: Array<{
    sourceName: string;
    score: number;
    matchReason: string;
    chunk: {
      id: string;
      sourceId: string;
      documentId: string;
      documentTitle: string;
      ordinal: number;
      content: string;
      tokenEstimate: number;
      keywords: string[];
      tags: string[];
      createdAt: string;
    };
  }>;
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

export type FileImportResultItem = {
  path: string;
  title: string;
  status: 'imported' | 'reused' | 'failed';
  documentId?: string | null;
  chunksCreated: number;
  warning?: string | null;
  error?: string | null;
};

export type FileImportPayload = {
  importRoot: string;
  directory: string;
  glob: string;
  source: SourceRecord;
  processedFiles: number;
  importedFiles: number;
  reusedFiles: number;
  failedFiles: number;
  results: FileImportResultItem[];
};

export type ImportFilesInput = {
  directory: string;
  glob: string;
  maxFiles?: number;
  sourceId?: string;
  sourceName: string;
  sourceKind: string;
  sourceUri?: string;
  sourceDescription?: string;
  sourceTags: string[];
  tags: string[];
};

export type IngestDocumentInput = {
  sourceId?: string;
  sourceName: string;
  sourceKind: string;
  sourceUri?: string;
  sourceDescription?: string;
  sourceTags: string[];
  title: string;
  content: string;
  tags: string[];
};

export type CreateKnowledgeBaseInput = {
  name: string;
  code: string;
  scene: string;
  language: string;
  retrievalMode: string;
  embeddingModel: string;
  description?: string;
  operatorReason: string;
};

export type CreateKnowledgeDocumentInput = {
  knowledgeBaseId: string;
  fileId: string;
  title: string;
  tags: string[];
  sourceType: string;
  operatorReason: string;
  sourceUri?: string;
};

export type ReindexKnowledgeDocumentInput = {
  documentId: string;
  confirmToken: string;
  operatorReason: string;
};

export type BootstrapCatalogInput = {
  operatorReason: string;
};

export type AdminSearchPreviewInput = {
  query: string;
  topK?: number;
  knowledgeBaseId?: string;
  tags?: string[];
};

export type AdminDiagnosticInput = {
  query: string;
  topK?: number;
  knowledgeBaseId?: string;
  includeCitations?: boolean;
};

export type KnowledgeBaseRecord = ContractAdminKnowledgeBase;
export type KnowledgeBaseListPayload = ContractAdminKnowledgeBaseListData;
export type AdminDocumentRecord = ContractAdminKnowledgeDocument;
export type AdminDocumentListPayload = ContractAdminKnowledgeDocumentListData;
export type AdminDocumentDetailPayload = ContractAdminKnowledgeDocumentDetailData;
export type AdminDocumentChunkStats = ContractAdminKnowledgeDocumentDetailData['chunk_stats'];
export type AdminAsyncJob = ContractAdminAsyncJob;
export type ContractAdminSearchPreviewPayload = ContractAdminRetrievalSearchPreviewData;
export type ContractAdminDiagnosticPayload = ContractAdminRetrievalDiagnosticsData;
export type ContractAdminRetrievalSource = ContractAdminRetrievalSearchSource;

export type AdminSearchPreviewItem = {
  docId: string;
  chunkId: string;
  kbId?: string | null;
  title: string;
  score: number;
  contentPreview: string;
  sourceType?: string | null;
  tags: string[];
};

export type AdminSearchPreviewPayload = {
  query: string;
  rewrittenQuery?: string | null;
  total: number;
  items: AdminSearchPreviewItem[];
  degraded: boolean;
};

export type AdminDiagnosticSource = AdminSearchPreviewItem;

export type AdminDiagnosticCoverage = {
  candidateCount: number;
  sourceBreakdown: Array<{
    sourceId: string;
    sourceName: string;
    hitCount: number;
    bestScore: number;
  }>;
  tagBreakdown: CountBucket[];
  unmatchedTerms: string[];
  degraded: boolean;
};

export type AdminDiagnosticDebug = {
  expandedTerms: string[];
  queryTerms: string[];
  appliedFilters: RetrievalFiltersPayload;
  citations: RetrievalCitation[];
};

export type AdminDiagnosticPayload = {
  query: string;
  rewrittenQuery: string;
  sources: AdminDiagnosticSource[];
  coverage: AdminDiagnosticCoverage;
  answerable: boolean;
  debug: AdminDiagnosticDebug;
  notes: string[];
};

export type AdminAuditRecord = {
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
};

export type FetchKnowledgeAuditRecordsQuery = {
  page?: number;
  pageSize?: number;
  resourceType?: string;
  action?: string;
  operatorId?: string;
};

export type AdminAuditListPayload = {
  items: AdminAuditRecord[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  sort_by: string;
  sort_order: 'asc' | 'desc';
};

export type RagCapabilities = {
  rewrite: string;
  retrieval: string;
  rerank: string;
  answering: string;
  diagnostics: string;
  cache?: string;
};

export type RuntimeConnectorStatus = {
  backend: string;
  configured: boolean;
  endpoint?: string | null;
  target?: string | null;
  notes?: string[];
};

export type RawObjectMirrorRecord = {
  docId: string;
  kbId?: string | null;
  sourceId: string;
  storageKind: string;
  bucket?: string | null;
  objectKey: string;
  mirrorPath: string;
  checksum: string;
  contentType: string;
  sizeBytes: number;
  sourceType?: string | null;
  sourceUri?: string | null;
  createdAt: string;
};

export type IndexingConnectorResult = {
  connector: string;
  backend: string;
  status: string;
  target?: string | null;
  detail?: string | null;
  itemCount?: number | null;
  attemptedAt: string;
};

export type IndexingOutboxEvent = {
  eventId: string;
  eventType: string;
  operation: string;
  status: string;
  queueName: string;
  docId: string;
  kbId?: string | null;
  sourceId: string;
  jobId?: string | null;
  chunkCount: number;
  warnings: string[];
  rawObject: RawObjectMirrorRecord;
  metadataTarget?: string | null;
  vectorTarget?: string | null;
  bm25Target?: string | null;
  cacheNamespace?: string | null;
  createdAt: string;
  attemptCount?: number;
  processorId?: string | null;
  reservedAt?: string | null;
  completedAt?: string | null;
  lastError?: string | null;
  connectorResults?: IndexingConnectorResult[];
};

export type KnowledgeRuntimeIntegrations = {
  rawStorage: RuntimeConnectorStatus;
  metadataStore: RuntimeConnectorStatus;
  vectorStore: RuntimeConnectorStatus;
  bm25Store: RuntimeConnectorStatus;
  cache: RuntimeConnectorStatus;
  taskQueue: RuntimeConnectorStatus;
  outboxPath: string;
  rawMirrorRoot: string;
  pendingEvents: number;
  eventCounters?: Record<string, number>;
  recentEvents: IndexingOutboxEvent[];
};

export type KnowledgeRuntimeSnapshot = {
  exportedAt: string;
  service: string;
  dataPath: string;
  auditPath: string;
  importRoot: string;
  counts: Record<string, number>;
  overview: Record<string, unknown>;
  sources: unknown[];
  documents: Array<{ id: string }>;
  chunks: unknown[];
  ingestions: unknown[];
  knowledgeBases: Array<{ kb_id: string; name: string; status: string }>;
  documentProfiles: unknown[];
  adminJobs: unknown[];
  recentAuditRecords: Array<{ audit_id: string; action: string; resource_type: string }>;
  integrations: KnowledgeRuntimeIntegrations;
};

export type UpdateKnowledgeBaseInput = {
  knowledgeBaseId: string;
  name: string;
  description?: string;
  retrievalMode: string;
  status: string;
  operatorReason: string;
};
