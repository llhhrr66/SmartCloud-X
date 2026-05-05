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
  doc_id: string;
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

export interface KnowledgeChunkRecord {
  chunk_id: string;
  doc_id: string;
  position: number;
  content_preview: string;
  token_count: number;
  score?: number | null;
  tags: string[];
  updated_at?: string | null;
}

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
  job_id: string;
  type: string;
  status: string;
  progress: number;
  created_at: string;
  params?: Record<string, unknown> | null;
  result_file_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
  finished_at?: string | null;
}

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
}

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

export interface HealthPayload {
  service?: string;
  status?: string;
  ready?: boolean;
  warnings?: string[];
  [key: string]: unknown;
}

export interface RuntimeSnapshot {
  overview?: Record<string, unknown>;
  integrations?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface LegacySource {
  sourceId?: string;
  source_id?: string;
  name: string;
  kind?: string;
  uri?: string;
  tags?: string[];
  [key: string]: unknown;
}

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
