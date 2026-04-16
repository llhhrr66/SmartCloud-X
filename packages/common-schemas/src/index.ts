export interface ErrorInfo {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  retryable?: boolean;
}

export interface TraceContextSchema {
  requestId?: string;
  traceId: string;
  conversationId?: string | null;
  userId?: string | null;
  tenantId?: string | null;
  callerService?: string | null;
  toolCallId?: string | null;
  idempotencyKey?: string | null;
  operatorReason?: string | null;
  tags?: string[];
}

export interface PaginationMeta {
  page?: number;
  pageSize?: number;
  total?: number;
  nextCursor?: string;
  hasMore?: boolean;
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error';
  service: string;
  version?: string;
  timestamp?: string;
  checks?: Record<string, 'ok' | 'degraded' | 'error'>;
}

export interface RuntimeDependencyReadiness {
  ready: boolean;
  status: string;
  mode: 'transport-local' | 'http';
  service: string;
  httpStatus?: number;
  notReadyComponents?: string[];
  error?: string;
}

export interface RuntimeHealthStatus {
  status: 'ok' | 'degraded';
  service: string;
  degraded_components: string[];
  runtime: Record<string, unknown>;
}

export interface RuntimeReadinessStatus {
  status: 'ready' | 'not_ready';
  service: string;
  not_ready_components: string[];
  runtime: Record<string, unknown>;
}

export interface ServiceCallerContext {
  callerService: string;
  requestId: string;
  traceId: string;
  tenantId?: string;
  conversationId?: string;
  toolCallId?: string;
  idempotencyKey?: string;
  operatorReason?: string;
}

export interface ApiEnvelope<T = unknown> {
  success: boolean;
  data?: T | null;
  requestId?: string;
  trace?: TraceContextSchema;
  error?: ErrorInfo | null;
  meta?: Record<string, unknown> | null;
}

export interface CanonicalErrorDetail {
  type?: string;
  field?: string;
  reason?: string;
  details?: Record<string, unknown>;
}

export interface CanonicalSuccessEnvelope<T = unknown> {
  code: 0;
  message: string;
  data: T;
  request_id: string;
  timestamp: number;
}

export interface CanonicalErrorEnvelope {
  code: number;
  message: string;
  data?: null;
  error?: CanonicalErrorDetail;
  request_id: string;
  timestamp: number;
}

export type SortOrder = 'asc' | 'desc';

export interface OffsetPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages?: number;
  sort_by?: string;
  sort_order?: SortOrder;
}

export interface SseEventEnvelope<T = unknown> {
  event: string;
  data: T;
  id?: string;
  retry?: number;
}

export interface AdminDashboardSummaryData {
  conversation_count: number;
  error_count: number;
  active_alert_count: number;
  p95_latency_ms: number;
  total_cost: number;
  date_from?: string;
  date_to?: string;
}

export interface AdminKnowledgeBase {
  kb_id: string;
  code: string;
  name: string;
  scene: string;
  language: string;
  retrieval_mode: string;
  status: string;
  description?: string | null;
  document_count?: number;
  chunk_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface AdminKnowledgeBaseListData extends OffsetPagination {
  items: AdminKnowledgeBase[];
}

export interface AdminKnowledgeBaseUpdateRequest {
  name?: string;
  description?: string | null;
  retrieval_mode?: string;
  status?: 'ready' | 'disabled';
}

export interface AdminKnowledgeDocument {
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
  chunk_count?: number;
  token_count?: number;
  error_message?: string | null;
  indexed_at?: string | null;
}

export interface AdminKnowledgeChunkStats {
  chunk_count: number;
  token_count: number;
  average_tokens_per_chunk: number;
  latest_job_id?: string | null;
}

export interface AdminKnowledgeDocumentDetailData {
  document: AdminKnowledgeDocument;
  chunk_stats: AdminKnowledgeChunkStats;
  error_message?: string | null;
}

export interface AdminKnowledgeDocumentListData extends OffsetPagination {
  items: AdminKnowledgeDocument[];
}

export interface AdminKnowledgeChunk {
  chunk_id: string;
  doc_id: string;
  position: number;
  content_preview: string;
  token_count: number;
  score?: number;
  tags?: string[];
  updated_at?: string;
}

export interface AdminKnowledgeChunkListData extends OffsetPagination {
  items: AdminKnowledgeChunk[];
}

export interface AdminAsyncJob {
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

export interface AdminRetrievalSearchSource {
  doc_id: string;
  chunk_id: string;
  kb_id?: string;
  title: string;
  score: number;
  content_preview: string;
  source_type?: string;
  tags?: string[];
}

export interface AdminRetrievalSearchPreviewData {
  query: string;
  rewritten_query?: string;
  total: number;
  items: AdminRetrievalSearchSource[];
  degraded?: boolean;
}

export interface AdminRetrievalDiagnosticsData {
  query: string;
  rewritten_query?: string;
  sources: AdminRetrievalSearchSource[];
  coverage?: Record<string, unknown>;
  answerable?: boolean;
  debug?: Record<string, unknown>;
  notes?: string[];
}

export interface AdminAuditRecord {
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

export interface AdminAuditListData extends OffsetPagination {
  items: AdminAuditRecord[];
}

export interface AdminAgentRecord {
  name: AgentName;
  code: string;
  display_name: string;
  domain: string;
  description: string;
  supported_scenes?: SceneName[];
  tool_whitelist?: string[];
  fallback_agent?: string;
  max_tool_calls?: number;
  enabled?: boolean;
  timeout_seconds?: number;
}

export interface AdminAgentListData {
  items: AdminAgentRecord[];
  total: number;
}

export interface AdminAgentConfigUpdateRequest {
  enabled?: boolean;
  max_tool_calls?: number;
  fallback_agent?: string;
  timeout_seconds?: number;
}

export interface KnowledgeRuntimeSnapshot {
  exportedAt: string;
  service: string;
  dataPath: string;
  auditPath: string;
  importRoot: string;
  counts: Record<string, number>;
  overview: Record<string, unknown>;
  sources: Record<string, unknown>[];
  documents: Record<string, unknown>[];
  chunks: Record<string, unknown>[];
  ingestions: Record<string, unknown>[];
  knowledgeBases: AdminKnowledgeBase[];
  documentProfiles: Record<string, unknown>[];
  adminJobs: AdminAsyncJob[];
  recentAuditRecords: AdminAuditRecord[];
  integrations: Record<string, unknown>;
}

export interface OrchestratorStreamMetaEventData {
  conversation_id: string;
  message_id: string;
  trace_id?: string | null;
  agent: string;
}

export interface OrchestratorStreamReasoningEventData {
  agent: string;
  summary: string;
  step: number;
}

export interface OrchestratorStreamRetrievalSource {
  doc_id: string;
  chunk_id: string;
  score: number;
  title: string;
}

export interface OrchestratorStreamRetrievalEventData {
  query: string;
  top_k: number;
  sources: OrchestratorStreamRetrievalSource[];
}

export interface OrchestratorStreamToolCallEventData {
  tool_name: string;
  tool_call_id: string;
  status: string;
  arguments: Record<string, unknown>;
}

export interface OrchestratorStreamToolResultEventData {
  tool_name: string;
  tool_call_id: string;
  status: string;
  latency_ms: number;
  data_preview: Record<string, unknown>;
}

export interface OrchestratorStreamDeltaEventData {
  content: string;
}

export interface OrchestratorStreamCitationEntry {
  id: string;
  title: string;
  source_type: 'knowledge_base' | 'tool';
  doc_id: string;
  chunk_id: string;
}

export interface OrchestratorStreamCitationEventData {
  citations: OrchestratorStreamCitationEntry[];
}

export interface OrchestratorStreamUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export type ChatUsage = OrchestratorStreamUsage;

export interface OrchestratorStreamDoneEventData {
  finish_reason: string;
  usage: OrchestratorStreamUsage;
  next_action: string;
  pending_actions: string[];
}

export interface OrchestratorStreamEventRecord {
  event_id: string;
  sequence: number;
  event: 'meta' | 'reasoning' | 'retrieval' | 'tool_call' | 'tool_result' | 'delta' | 'citation' | 'done';
  data: Record<string, unknown>;
  created_at: string;
}

export interface OrchestratorStreamEventPage {
  conversation_id: string;
  message_id: string;
  items: OrchestratorStreamEventRecord[];
  next_event_id?: string | null;
  has_more: boolean;
}

export interface MarketingCampaign {
  campaign_id: string;
  name: string;
  product_type: string;
  status: 'published' | 'draft' | 'expired';
  start_at: string;
  end_at: string;
  landing_page_url?: string;
  highlights?: string[];
}

export interface MarketingCampaignListData extends OffsetPagination {
  items: MarketingCampaign[];
}

export interface MarketingCopyRequest {
  campaign_id: string;
  topic: string;
  audience: string;
  tone: 'professional' | 'growth' | 'launch';
  keywords?: string[];
}

export interface MarketingCopyResult {
  copy_id: string;
  campaign_id: string;
  campaign_name: string;
  topic: string;
  audience: string;
  tone: MarketingCopyRequest['tone'];
  headline: string;
  summary: string;
  body: string;
  call_to_action: string;
  keywords?: string[];
  landing_page_url?: string | null;
  created_at: string;
}

export interface MarketingCopyListData extends OffsetPagination {
  items: MarketingCopyResult[];
}

export interface PosterTask {
  task_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  campaign_id: string;
  campaign_name?: string;
  theme: string;
  slogan?: string;
  size: string;
  created_at: string;
  image_url?: string;
  error_message?: string;
  estimated_seconds?: number;
  updated_at?: string;
}

export interface PosterTaskCreateResponseData {
  task_id: string;
  status: PosterTask['status'];
  estimated_seconds: number;
}

export interface PosterTaskListData extends OffsetPagination {
  items: PosterTask[];
}

export interface PosterResultData {
  task_id: string;
  status: PosterTask['status'];
  result_ready: boolean;
  campaign_id: string;
  campaign_name?: string | null;
  theme: string;
  slogan?: string | null;
  size: string;
  image_url?: string | null;
  preview_url?: string | null;
  download_url?: string | null;
  mime_type?: string | null;
  generated_at?: string | null;
}

export interface PromotionLinkRequest {
  campaign_id: string;
  channel: string;
  source?: string | null;
  content_tag?: string | null;
}

export interface PromotionLinkResult {
  link_id: string;
  campaign_id: string;
  campaign_name: string;
  channel: string;
  short_url: string;
  landing_page_url: string;
  tracking_code: string;
  created_at: string;
  note: string;
}

export interface PromotionLinkListData extends OffsetPagination {
  items: PromotionLinkResult[];
}

export interface ResearchTask {
  task_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  topic: string;
  scope: string;
  depth: 'lite' | 'standard' | 'deep';
  output_format: 'markdown' | 'pdf';
  progress: number;
  created_at: string;
  summary?: string | null;
  report_file_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
  updated_at?: string | null;
}

export interface ResearchTaskCreateResponseData {
  task_id: string;
  status: ResearchTask['status'];
  estimated_minutes: number;
}

export interface ResearchTaskListData extends OffsetPagination {
  items: ResearchTask[];
}

export interface ResearchTaskStatusData {
  task_id: string;
  status: ResearchTask['status'];
  progress: number;
  created_at: string;
  updated_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  result_ready: boolean;
  report_file_id?: string | null;
}

export interface ResearchTaskResultData {
  task_id: string;
  status: ResearchTask['status'];
  result_ready: boolean;
  output_format: ResearchTask['output_format'];
  summary?: string | null;
  report_file_id?: string | null;
  download_url?: string | null;
  preview_text?: string | null;
  citations?: string[];
  generated_at?: string | null;
}

export interface AuthUserProfile {
  user_id: string;
  tenant_id: string;
  name: string;
  email: string;
  mobile: string;
  avatar_url?: string | null;
  locale: string;
  time_zone: string;
  permissions: string[];
}

export interface LoginRequest {
  login_type: 'password' | 'sms' | 'email_code';
  account: string;
  password?: string;
  sms_code?: string;
  email_code?: string;
  captcha_token?: string;
}

export interface LoginResponseData {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: AuthUserProfile;
}

export interface SendCodeRequest {
  scene: 'login' | 'reset_password';
  account: string;
  account_type: 'mobile' | 'email';
  captcha_token?: string;
}

export interface SendCodeResponseData {
  scene: SendCodeRequest['scene'];
  masked_account: string;
  expire_in: number;
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface RefreshTokenResponseData {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user?: AuthUserProfile;
}

export interface LogoutRequest {
  refresh_token?: string;
}

export interface UserProfileUpdateRequest {
  name?: string;
  avatar_url?: string;
  locale?: string;
  time_zone?: string;
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
  confirm_password: string;
}

export interface ForgotPasswordRequest {
  account: string;
  account_type: 'mobile' | 'email';
  verification_code: string;
}

export interface ForgotPasswordResponseData {
  challenge_id: string;
  expire_in: number;
}

export interface ResetPasswordRequest {
  challenge_id: string;
  account: string;
  verification_code: string;
  new_password: string;
  confirm_password: string;
}

export interface OperationStatusData {
  success: true;
}

export interface AdminMenuItem {
  code: string;
  name: string;
  path: string;
  icon?: string;
  children?: Array<Pick<AdminMenuItem, 'code' | 'name' | 'path' | 'icon'>>;
}

export interface AdminSessionProfile {
  admin_id: string;
  name: string;
  roles: string[];
  permissions: string[];
  menus: AdminMenuItem[];
}

export interface AdminLoginRequest {
  username: string;
  password: string;
  captcha_token: string;
}

export interface AdminLoginResponseData {
  access_token: string;
  refresh_token: string;
  admin: AdminSessionProfile;
}

export interface AdminActionConfirmationRequest {
  action: string;
  resource_scope: string;
  verification_method: 'password' | 'sms' | 'totp' | 'webauthn';
  verification_payload: Record<string, unknown>;
}

export interface AdminActionConfirmationResponseData {
  confirm_token: string;
  expired_at: string;
  action: string;
  resource_scope: string;
}

export interface InternalTokenValidationResponseData {
  subject_type: 'user' | 'admin' | 'service' | 'agent';
  subject_id: string;
  tenant_id?: string;
  roles: string[];
  permissions: string[];
  expired_at: string;
}

export interface PermissionCheckRequest {
  subject_type: InternalTokenValidationResponseData['subject_type'];
  subject_id: string;
  permissions: string[];
}

export interface PermissionCheckResponseData {
  allowed: boolean;
  denied_permissions: string[];
}

export interface InvalidateSubjectCacheRequest {
  subject_type: InternalTokenValidationResponseData['subject_type'];
  subject_ids: string[];
}

export interface InvalidateSubjectCacheResponseData {
  invalidated_subject_ids: string[];
}

export type AgentName =
  | 'product_tech_agent'
  | 'finance_order_agent'
  | 'icp_service_agent'
  | 'ops_marketing_agent'
  | 'deep_research_agent';

export type SceneName =
  | 'customer_service'
  | 'billing'
  | 'technical_support'
  | 'icp'
  | 'marketing'
  | 'research';

export type ConversationStatus = 'active' | 'running' | 'archived' | 'closed' | 'deleted';
export type MessageRole = 'user' | 'assistant' | 'system';
export type MessageType = 'user_input' | 'assistant_response' | 'event';
export type MessageStatus =
  | 'running'
  | 'completed'
  | 'handoff'
  | 'need_user_input'
  | 'failed'
  | 'cancelled';

export interface UserProfile {
  user_id?: string | null;
  roles?: string[];
  permissions?: string[];
  account_id?: string | null;
  tenant_id?: string;
  locale?: string;
  channel?: string;
  vip_level?: string;
}

export interface UserProfilePatch {
  user_id?: string | null;
  roles?: string[];
  permissions?: string[];
  account_id?: string | null;
  tenant_id?: string | null;
  locale?: string | null;
  channel?: string | null;
  vip_level?: string | null;
}

export interface SessionContext {
  latest_summary?: string | null;
  history_summary?: string | null;
  recent_messages?: Array<Record<string, unknown>>;
  active_products?: string[];
  open_ticket_id?: string | null;
  confirmed_tool_names?: string[];
  attributes?: Record<string, unknown>;
}

export interface RuntimeConstraints {
  must_cite?: boolean;
  allow_handoff?: boolean;
  max_tool_calls?: number;
}

export interface IntentSignal {
  label: string;
  score: number;
  matched_keywords?: string[];
}

export interface IntentSummary {
  domain: string;
  matched_domains?: string[];
  signals?: IntentSignal[];
  urgency?: 'low' | 'medium' | 'high';
  needs_human_handoff?: boolean;
  scene?: SceneName;
}

export interface RouteRequest {
  user_query: string;
  conversation_id: string;
  scene?: SceneName;
  user_profile?: UserProfile;
  session_context?: SessionContext;
  retrieval_required?: boolean | null;
  tool_candidates?: string[];
  preferred_agents?: AgentName[];
  constraints?: RuntimeConstraints;
}

export interface AgentTask {
  agent: AgentName;
  reason: string;
  requires_retrieval?: boolean;
  suggested_tools?: string[];
  handoff_step_id?: string | null;
  depends_on_tool_call_ids?: string[];
  session_context_inputs?: string[];
  session_context_outputs?: string[];
}

export interface AgentDescriptor {
  name: AgentName;
  code?: string;
  display_name?: string;
  domain: string;
  description?: string;
  version?: string;
  owner?: string;
  input_schema_version?: string;
  output_schema_version?: string;
  default_tools?: string[];
  supported_scenes?: SceneName[];
  allowed_tools?: string[];
  fallback_agent?: string;
  max_tool_calls?: number;
}

export type ToolOperation = 'preview' | 'execute';
export type ToolMode = 'query' | 'write';
export type ToolUserActionType =
  | 'clarify-tool-input'
  | 'collect-auth-context'
  | 'user-confirmation';

export interface ToolAuthRequirements {
  require_user_id?: boolean;
  require_account_id?: boolean;
  allowed_roles?: string[];
  required_permissions?: string[];
  confirmation_required?: boolean;
}

export interface ToolCompensationAction {
  action_name: string;
  description: string;
  payload?: Record<string, unknown>;
}

export interface ToolUserActionHint {
  action: ToolUserActionType;
  message: string;
  missing_fields?: string[];
  missing_payload_hints?: Record<string, string>;
  missing_auth_context?: string[];
  required_permissions?: string[];
  requires_account_context?: boolean;
  confirmation_required?: boolean;
  session_context_bindings?: Record<string, string[]>;
  user_profile_bindings?: Record<string, string[]>;
  confirm_tool_names?: string[];
}

export interface ToolExecutionContext {
  request_id?: string | null;
  trace_id?: string | null;
  conversation_id?: string | null;
  tenant_id?: string;
  user_id?: string | null;
  account_id?: string | null;
  roles?: string[];
  permissions?: string[];
  locale?: string;
  operator_type?: string;
  operator_id?: string | null;
  tool_call_id?: string | null;
  idempotency_key?: string | null;
  operator_reason?: string | null;
}

export interface ToolDefinition {
  name: string;
  capability: string;
  description: string;
  version?: string;
  tags?: string[];
  owner?: string;
  mode?: ToolMode;
  supported_operations?: ToolOperation[];
  input_schema?: Record<string, unknown>;
  input_schema_hint?: Record<string, unknown>;
  input_field_hints?: Record<string, string>;
  output_schema?: Record<string, unknown>;
  output_schema_hint?: Record<string, unknown>;
  session_context_bindings?: Record<string, string[]>;
  session_context_output_keys?: string[];
  prerequisite_tool_names?: string[];
  operation_required_fields?: Partial<Record<ToolOperation, string[]>>;
  auth_requirements?: ToolAuthRequirements;
  downstream_target?: string;
  provider?: string;
  timeout_ms?: number;
  idempotent?: boolean;
  idempotency_window_seconds?: number | null;
  high_risk?: boolean;
  cache_ttl_seconds?: number | null;
}

export type ToolPreflightStatus =
  | 'ready'
  | 'missing-tool'
  | 'missing-payload'
  | 'auth-required'
  | 'confirmation-required'
  | 'invalid-operation';

export interface ToolPreflightResult {
  tool_name: string;
  operation: ToolOperation;
  status: ToolPreflightStatus;
  ready: boolean;
  available: boolean;
  high_risk: boolean;
  tool_mode?: ToolMode;
  timeout_ms?: number;
  idempotent?: boolean;
  cache_ttl_seconds?: number | null;
  missing_payload_fields: string[];
  missing_payload_hints: Record<string, string>;
  missing_auth_context: string[];
  required_permissions: string[];
  requires_account_context: boolean;
  confirmation_required: boolean;
  session_context_bindings?: Record<string, string[]>;
  user_action_hint?: ToolUserActionHint | null;
}

export interface ToolPreflightResponse extends ToolPreflightResult {
  downstream_target: string;
  provider: string;
}

export interface ToolPlanItem {
  tool_call_id?: string;
  tool_name: string;
  assigned_agent: AgentName;
  operation?: ToolOperation;
  reason: string;
  payload?: Record<string, unknown>;
  required_payload_fields?: string[];
  missing_payload_fields?: string[];
  deferred_payload_fields?: string[];
  missing_payload_hints?: Record<string, string>;
  depends_on_tool_call_ids?: string[];
  session_context_input_keys?: string[];
  session_context_output_keys?: string[];
  readiness?: 'ready' | 'ready_after_dependencies' | 'needs_user_input';
  auth_required?: boolean;
  requires_account_context?: boolean;
  required_permissions?: string[];
  high_risk?: boolean;
  tool_mode?: ToolMode;
  timeout_ms?: number;
  idempotent?: boolean;
  cache_ttl_seconds?: number | null;
}

export interface HandoffStep {
  step_id: string;
  order: number;
  agent: AgentName;
  objective: string;
  depends_on?: string[];
  requires_retrieval?: boolean;
  tool_names?: string[];
  depends_on_tool_call_ids?: string[];
  session_context_inputs?: string[];
  session_context_outputs?: string[];
  exit_criteria?: string | null;
}

export interface ExecutionCheckpoint {
  name: string;
  description: string;
  status?: 'planned' | 'pending' | 'completed' | 'skipped' | 'failed';
}

export interface ExecutionEvent {
  sequence: number;
  event:
    | 'route_selected'
    | 'checkpoint_updated'
    | 'tool_call'
    | 'tool_result'
    | 'agent_result'
    | 'review_result'
    | 'compensation_result'
    | 'state_persisted';
  message: string;
  agent?: AgentName | null;
  tool_name?: string | null;
  data?: Record<string, unknown>;
}

export interface ResponseReviewIssue {
  code: string;
  severity: 'warning' | 'error';
  message: string;
}

export interface ResponseReview {
  status: 'approved' | 'warning' | 'blocked' | 'skipped';
  summary: string;
  issues: ResponseReviewIssue[];
  requires_escalation: boolean;
}

export interface AgentRouteRecord {
  step_id: string;
  order: number;
  agent: AgentName;
  objective: string;
  status?: string;
  handoff_received_from?: AgentName | null;
  handoff_to?: AgentName | null;
  handoff_reason?: string | null;
  action_required?: string | null;
  tool_names?: string[];
  tool_call_ids?: string[];
  tool_statuses?: string[];
  depends_on?: string[];
  depends_on_tool_call_ids?: string[];
  session_context_inputs?: string[];
  session_context_outputs?: string[];
  context_highlights?: Record<string, unknown>;
}

export interface SagaCompensationStep {
  saga_id: string;
  step_id: string;
  tool_name: string;
  compensation: ToolCompensationAction;
  status?: 'armed' | 'completed' | 'failed';
}

export interface SessionStateSnapshot {
  conversation_id: string;
  primary_agent: AgentName;
  current_agent?: AgentName | null;
  version?: number;
  session_context?: SessionContext;
  agent_routes?: AgentRouteRecord[];
  checkpoints?: ExecutionCheckpoint[];
  tool_results?: ToolInvocation[];
  tool_context?: ToolContextItem[];
  compensation_stack?: SagaCompensationStep[];
  events?: ExecutionEvent[];
  pending_actions?: string[];
  pending_user_actions?: PendingUserAction[];
  final_response_summary?: string | null;
  review?: ResponseReview | null;
  trace?: TraceContextSchema | null;
}

export interface CompensationExecutionRecord {
  step_id: string;
  tool_name: string;
  action_name: string;
  status: 'completed' | 'failed';
  success: boolean;
  message: string;
  data?: Record<string, unknown>;
  provider?: string | null;
  code?: number | null;
  retryable?: boolean;
  latency_ms?: number | null;
  error_detail?: Record<string, unknown>;
  idempotency_key?: string | null;
}

export interface SessionRollbackResponse {
  conversation_id: string;
  status: 'completed' | 'partial' | 'failed' | 'noop';
  compensated_steps: CompensationExecutionRecord[];
  state_snapshot: SessionStateSnapshot;
  trace?: TraceContextSchema | null;
}

export interface RouteDecision {
  primary_agent: AgentName;
  supporting_agents?: AgentName[];
  requires_retrieval?: boolean;
  requires_tools?: boolean;
  needs_human_handoff?: boolean;
  intent: IntentSummary;
  tasks?: AgentTask[];
  handoff_plan?: HandoffStep[];
  tool_plan?: ToolPlanItem[];
  checkpoints?: ExecutionCheckpoint[];
  summary: string;
}

export interface MessageRequest {
  user_query: string;
  message_id?: string;
  scene?: SceneName;
  user_profile?: UserProfile;
  session_context?: SessionContext;
  retrieval_context?: string[];
  attachments?: Array<Record<string, unknown>>;
  constraints?: RuntimeConstraints;
  trace?: TraceContextSchema | null;
}

export interface ToolInvocation {
  tool_name: string;
  tool_call_id?: string;
  operation: string;
  status: string;
  payload?: Record<string, unknown>;
  summary?: string | null;
  citations?: string[];
  auth_required?: boolean;
  success?: boolean | null;
  code?: number | null;
  retryable?: boolean;
  latency_ms?: number | null;
  compensation?: ToolCompensationAction | null;
  provider?: string | null;
  audit_tags?: string[];
  error_detail?: Record<string, unknown>;
  idempotency_key?: string | null;
  session_context_patch?: SessionContext;
  user_action_hint?: ToolUserActionHint | null;
}

export interface PendingUserAction {
  tool_name: string;
  tool_call_id: string;
  agent?: AgentName | null;
  action: ToolUserActionType;
  message: string;
  missing_fields?: string[];
  missing_payload_hints?: Record<string, string>;
  missing_auth_context?: string[];
  required_permissions?: string[];
  requires_account_context?: boolean;
  confirmation_required?: boolean;
  session_context_bindings?: Record<string, string[]>;
  user_profile_bindings?: Record<string, string[]>;
  confirm_tool_names?: string[];
}

export interface ToolContextItem {
  tool_name: string;
  tool_call_id: string;
  status: string;
  summary?: string | null;
  provider?: string | null;
  data?: Record<string, unknown>;
  patch_keys?: string[];
}

export type AgentExecutionRiskFlag =
  | 'missing_tool_input'
  | 'missing_auth_context'
  | 'confirmation_required'
  | 'idempotency_conflict'
  | 'tool_failure'
  | 'human_handoff_requested';

export interface AgentExecutionResult {
  agent: AgentName;
  status?:
    | 'planned'
    | 'completed'
    | 'needs-human'
    | 'success'
    | 'handoff'
    | 'need_user_input'
    | 'failed';
  reasoning_summary: string;
  tool_calls?: ToolInvocation[];
  citations?: string[];
  confidence?: number;
  final_answer?: string | null;
  handoff_received_from?: AgentName | null;
  next_agent?: AgentName | null;
  action_required?: string | null;
  risk_flags?: AgentExecutionRiskFlag[];
  trace_tags?: string[];
  handoff_reason?: string | null;
  handoff_payload?: Record<string, unknown>;
}

export interface OrchestratorResponse {
  conversation_id: string;
  route: RouteDecision;
  executions?: AgentExecutionResult[];
  next_action?: string;
  final_response_summary?: string | null;
  pending_actions?: string[];
  pending_user_actions?: PendingUserAction[];
  state_snapshot?: SessionStateSnapshot | null;
  review?: ResponseReview | null;
  trace?: TraceContextSchema | null;
}

export interface ConversationRecord {
  conversation_id: string;
  scene?: SceneName;
  status?: ConversationStatus;
  title?: string | null;
  current_agent?: AgentName | null;
  summary?: string | null;
  pending_actions?: string[];
  created_at: string;
  updated_at: string;
  last_message_at?: string | null;
  initial_context?: SessionContext;
  total_messages?: number;
}

export interface SessionCreateRequest {
  scene?: SceneName;
  title?: string | null;
  initial_context?: SessionContext;
}

export interface SessionUpdateRequest {
  title: string;
}

export interface SessionListResponse {
  items?: ConversationRecord[];
  total?: number;
  page?: number;
  page_size?: number;
}

export interface ChatMessageRecord {
  message_id: string;
  conversation_id: string;
  role: MessageRole;
  message_type: MessageType;
  status: MessageStatus;
  created_at: string;
  updated_at: string;
  parent_message_id?: string | null;
  agent_name?: string | null;
  content?: string | null;
  citations?: string[];
  tool_calls?: ToolInvocation[];
  finish_reason?: string | null;
  trace?: TraceContextSchema | null;
}

export interface SessionMessagesPage {
  items?: ChatMessageRecord[];
  next_cursor?: string | null;
  has_more?: boolean;
}

export interface StreamEventRecord {
  event_id: string;
  sequence: number;
  event: 'meta' | 'reasoning' | 'retrieval' | 'tool_call' | 'tool_result' | 'delta' | 'citation' | 'done';
  data: Record<string, unknown>;
  created_at: string;
}

export interface StreamEventPage {
  conversation_id: string;
  message_id: string;
  items?: StreamEventRecord[];
  next_event_id?: string | null;
  has_more: boolean;
}

export interface SessionRetryRequest {
  message_id: string;
  override_input?: string | null;
}

export interface SessionContinueRequest {
  message_id?: string | null;
  user_input?: string | null;
  field_values?: Record<string, unknown>;
  confirm_tool_names?: string[];
  session_context_patch?: Record<string, unknown>;
  user_profile_patch?: UserProfilePatch;
}

export interface SessionCancelRequest {
  message_id: string;
}

export interface SessionCancelResponse {
  conversation_id: string;
  message_id: string;
  status: 'cancelled';
  cancelled: true;
}

export interface SessionDeleteResponse {
  conversation_id: string;
  status: 'deleted';
  deleted: true;
}

export interface InternalChatUser {
  user_id: string;
  roles?: string[];
  permissions?: string[];
  account_id?: string | null;
  tenant_id?: string;
}

export interface InternalChatPayload {
  conversation_id: string;
  message_id: string;
  user_input: string;
  stream?: boolean;
  scene?: SceneName;
  session_context?: SessionContext;
  attachments?: Array<Record<string, unknown>>;
}

export interface InternalChatRequest {
  request_id: string;
  trace_id: string;
  tenant_id?: string;
  user: InternalChatUser;
  chat_request: InternalChatPayload;
}

export interface InternalChatResponse {
  conversation_id: string;
  message_id: string;
  status: 'success' | 'handoff' | 'need_user_input' | 'failed';
  agent_name: AgentName;
  route: RouteDecision;
  executions?: AgentExecutionResult[];
  final_answer: string;
  citations?: string[];
  tool_calls?: ToolInvocation[];
  next_agent?: AgentName | null;
  pending_actions?: string[];
  pending_user_actions?: PendingUserAction[];
  state_snapshot?: SessionStateSnapshot | null;
  review?: ResponseReview | null;
  trace?: TraceContextSchema | null;
}

export interface ChatCompletionRequest {
  conversation_id: string;
  message_id: string;
  user_input: string;
  stream?: boolean;
  scene?: SceneName | null;
  user_profile?: UserProfile;
  session_context?: SessionContext;
  attachments?: Array<Record<string, unknown>>;
  constraints?: RuntimeConstraints;
  context?: Record<string, unknown>;
  options?: Record<string, unknown>;
  context_control?: Record<string, unknown>;
  client_meta?: Record<string, unknown>;
  trace?: TraceContextSchema | null;
}

export interface ChatCompletionResponse {
  conversation_id: string;
  message_id: string;
  status: 'success' | 'handoff' | 'need_user_input' | 'failed';
  answer?: string;
  citations?: string[];
  tool_calls?: ToolInvocation[];
  pending_user_actions?: PendingUserAction[];
  usage?: ChatUsage;
  finish_reason?: string;
  response: OrchestratorResponse;
}

export interface ToolInvocationRequest {
  tool_name: string;
  operation?: ToolOperation;
  payload?: Record<string, unknown>;
  context?: ToolExecutionContext;
  trace?: TraceContextSchema | Record<string, unknown>;
}

export interface ToolExecutionResult {
  tool_name: string;
  operation: ToolOperation;
  status: string;
  summary: string;
  result?: Record<string, unknown>;
  citations?: string[];
  audit_tags?: string[];
  session_context_patch?: SessionContext;
  success?: boolean;
  code?: number;
  message?: string;
  retryable?: boolean;
  provider?: string;
  cache_ttl_seconds?: number | null;
  error_detail?: Record<string, unknown>;
  compensation?: ToolCompensationAction | null;
  idempotency_key?: string | null;
  user_action_hint?: ToolUserActionHint | null;
}

export type ToolDescriptor = ToolDefinition;

export interface ToolInvokeRequest extends Omit<ToolInvocationRequest, 'tool_name'> {}

export interface ToolInvokeResponse extends ToolExecutionResult {
  downstream_target?: string;
  auth_requirements?: ToolAuthRequirements;
}

export interface ToolCallOperator {
  type?: 'agent' | 'user' | 'admin' | 'system';
  id: string;
}

export interface ToolCallUserContext {
  user_id?: string | null;
  account_id?: string | null;
  permissions?: string[];
  roles?: string[];
  tenant_id?: string;
  locale?: string;
}

export interface ToolCallRequest {
  trace_id: string;
  conversation_id: string;
  tool_call_id: string;
  tool_name: string;
  operator: ToolCallOperator;
  user_context?: ToolCallUserContext;
  payload?: Record<string, unknown>;
  idempotency_key?: string | null;
  operation?: ToolOperation;
}

export interface ToolCallError {
  retryable?: boolean;
  provider?: string;
  details?: Record<string, unknown>;
}

export interface ToolCallResponse {
  success: boolean;
  code: number;
  message: string;
  status?: string;
  summary?: string;
  result?: Record<string, unknown>;
  citations?: string[];
  data?: Record<string, unknown>;
  audit_tags?: string[];
  session_context_patch?: SessionContext;
  tool_call_id: string;
  latency_ms: number;
  provider?: string;
  error?: ToolCallError | null;
  compensation?: ToolCompensationAction | null;
  idempotency_key?: string | null;
  attempts?: number;
  user_action_hint?: ToolUserActionHint | null;
}

export interface CompensationCallRequest {
  trace_id: string;
  conversation_id: string;
  compensation_id: string;
  action_name: string;
  operator: ToolCallOperator;
  payload?: Record<string, unknown>;
  idempotency_key?: string | null;
}

export interface CompensationCallResponse {
  success: boolean;
  code: number;
  message: string;
  data?: Record<string, unknown>;
  compensation_id: string;
  action_name: string;
  latency_ms: number;
  provider?: string;
  error?: ToolCallError | null;
  idempotency_key?: string | null;
  attempts?: number;
}

export interface ToolCallAuditRecord {
  tool_call_id: string;
  trace_id: string;
  conversation_id: string;
  tool_name: string;
  operation: ToolOperation;
  status:
    | 'success'
    | 'completed'
    | 'invalid-payload'
    | 'auth-required'
    | 'idempotency-conflict'
    | 'confirmation-required'
    | 'timeout'
    | 'failed';
  success: boolean;
  code: number;
  message: string;
  summary?: string;
  citations?: string[];
  provider?: string;
  retryable?: boolean;
  latency_ms: number;
  attempts?: number;
  tenant_id: string;
  operator: ToolCallOperator;
  user_context: ToolCallUserContext;
  idempotency_key?: string | null;
  audit_tags?: string[];
  operator_reason?: string | null;
  data_preview?: Record<string, unknown>;
  session_context_patch?: SessionContext;
  error?: ToolCallError | null;
  user_action_hint?: ToolUserActionHint | null;
  created_at: string;
  updated_at: string;
}

export interface McpToolsListResponse {
  tools?: ToolDescriptor[];
}

export interface OperatorContext {
  type?: 'agent' | 'user' | 'admin' | 'system';
  id: string;
}

export interface SubjectContext {
  user_id?: string | null;
  account_id?: string | null;
  tenant_id?: string;
  roles?: string[];
  permissions?: string[];
  locale?: string;
}

export interface BusinessToolExecuteRequest {
  operator: OperatorContext;
  subject?: SubjectContext;
  payload?: Record<string, unknown>;
  operation?: ToolOperation;
}

export interface BusinessToolExecuteResponse {
  success: boolean;
  code: number;
  message: string;
  tool_name?: string;
  operation?: ToolOperation;
  status?: string;
  summary?: string;
  result?: Record<string, unknown>;
  citations?: string[];
  data?: Record<string, unknown>;
  audit_tags?: string[];
  retryable?: boolean;
  cache_ttl_seconds?: number | null;
  provider?: string;
  error_detail?: Record<string, unknown>;
  compensation?: ToolCompensationAction | null;
  idempotency_key?: string | null;
  session_context_patch?: SessionContext;
  user_action_hint?: ToolUserActionHint | null;
}

export interface BusinessCompensationExecuteRequest {
  compensation_id: string;
  conversation_id: string;
  action_name: string;
  operator: OperatorContext;
  payload?: Record<string, unknown>;
}

export interface BusinessCompensationExecuteResponse {
  success: boolean;
  code: number;
  message: string;
  data?: Record<string, unknown>;
  compensation_id: string;
  action_name: string;
  latency_ms: number;
  retryable?: boolean;
  provider?: string;
  error_detail?: Record<string, unknown>;
  idempotency_key?: string | null;
}

export type FoundationErrorCode =
  | 'AUTH_INVALID_TOKEN'
  | 'AUTH_UNAUTHORIZED'
  | 'BUSINESS_TOOLS_CALLER_FORBIDDEN'
  | 'ORCH_AGENT_NOT_FOUND'
  | 'CHAT_CONVERSATION_ARCHIVED'
  | 'CHAT_CONVERSATION_NOT_FOUND'
  | 'CHAT_CONTINUATION_NOT_AVAILABLE'
  | 'CHAT_CONVERSATION_RUNNING'
  | 'CHAT_CONVERSATION_RESTORE_INVALID'
  | 'CHAT_MESSAGE_CANCELLED'
  | 'CHAT_MESSAGE_NOT_FOUND'
  | 'CHAT_MESSAGE_NOT_RUNNING'
  | 'CHAT_STREAM_EVENTS_NOT_FOUND'
  | 'IDEMPOTENCY_CONFLICT'
  | 'INTERNAL_ERROR'
  | 'KNOWLEDGE_SYNC_FAILED'
  | 'ORCH_CALLER_FORBIDDEN'
  | 'ORCH_ROUTE_FAILED'
  | 'ORCH_SESSION_STATE_NOT_FOUND'
  | 'ORCH_TOOL_AUTH_REQUIRED'
  | 'ORCH_TOOL_CALL_NOT_FOUND'
  | 'ORCH_TOOL_NOT_FOUND'
  | 'ORCH_TOOL_OPERATION_INVALID'
  | 'ORCH_TOOL_PAYLOAD_INVALID'
  | 'RAG_RETRIEVAL_UNAVAILABLE'
  | 'RATE_LIMITED'
  | 'SERVICE_UNAVAILABLE'
  | 'TOOL_HUB_CALLER_FORBIDDEN'
  | 'VALIDATION_ERROR';

export const foundationErrorCodes: FoundationErrorCode[] = [
  'AUTH_INVALID_TOKEN',
  'AUTH_UNAUTHORIZED',
  'BUSINESS_TOOLS_CALLER_FORBIDDEN',
  'ORCH_AGENT_NOT_FOUND',
  'CHAT_CONVERSATION_ARCHIVED',
  'CHAT_CONVERSATION_NOT_FOUND',
  'CHAT_CONTINUATION_NOT_AVAILABLE',
  'CHAT_CONVERSATION_RUNNING',
  'CHAT_CONVERSATION_RESTORE_INVALID',
  'CHAT_MESSAGE_CANCELLED',
  'CHAT_MESSAGE_NOT_FOUND',
  'CHAT_MESSAGE_NOT_RUNNING',
  'CHAT_STREAM_EVENTS_NOT_FOUND',
  'IDEMPOTENCY_CONFLICT',
  'INTERNAL_ERROR',
  'KNOWLEDGE_SYNC_FAILED',
  'ORCH_CALLER_FORBIDDEN',
  'ORCH_ROUTE_FAILED',
  'ORCH_SESSION_STATE_NOT_FOUND',
  'ORCH_TOOL_AUTH_REQUIRED',
  'ORCH_TOOL_CALL_NOT_FOUND',
  'ORCH_TOOL_NOT_FOUND',
  'ORCH_TOOL_OPERATION_INVALID',
  'ORCH_TOOL_PAYLOAD_INVALID',
  'RAG_RETRIEVAL_UNAVAILABLE',
  'RATE_LIMITED',
  'SERVICE_UNAVAILABLE',
  'TOOL_HUB_CALLER_FORBIDDEN',
  'VALIDATION_ERROR'
];

export const schemaRegistry = {
  common: {
    apiEnvelope: 'api-envelope.schema.json',
    errorInfo: 'error-info.schema.json',
    healthStatus: 'health-status.schema.json',
    paginationMeta: 'pagination-meta.schema.json',
    runtimeDependencyReadiness: 'runtime-dependency-readiness.schema.json',
    runtimeHealthStatus: 'runtime-health-status.schema.json',
    runtimeReadinessStatus: 'runtime-readiness-status.schema.json',
    serviceCallerContext: 'service-caller-context.schema.json',
    traceContext: 'trace-context.schema.json'
  },
  external: {
    canonicalErrorDetail: 'external/canonical-error-detail.schema.json',
    canonicalSuccessEnvelope: 'external/canonical-success-envelope.schema.json',
    canonicalErrorEnvelope: 'external/canonical-error-envelope.schema.json',
    offsetPagination: 'external/offset-pagination.schema.json',
    sseEventEnvelope: 'external/sse-event-envelope.schema.json',
    auth: {
      authUserProfile: 'external/auth/auth-user-profile.schema.json',
      loginRequest: 'external/auth/login-request.schema.json',
      loginResponseData: 'external/auth/login-response-data.schema.json',
      sendCodeRequest: 'external/auth/send-code-request.schema.json',
      sendCodeResponseData: 'external/auth/send-code-response-data.schema.json',
      refreshTokenRequest: 'external/auth/refresh-token-request.schema.json',
      refreshTokenResponseData: 'external/auth/refresh-token-response-data.schema.json',
      logoutRequest: 'external/auth/logout-request.schema.json',
      userProfileUpdateRequest: 'external/auth/user-profile-update-request.schema.json',
      changePasswordRequest: 'external/auth/change-password-request.schema.json',
      forgotPasswordRequest: 'external/auth/forgot-password-request.schema.json',
      forgotPasswordResponseData: 'external/auth/forgot-password-response-data.schema.json',
      resetPasswordRequest: 'external/auth/reset-password-request.schema.json',
      operationStatusData: 'external/auth/operation-status-data.schema.json'
    },
    admin: {
      adminAgentConfigUpdateRequest: 'external/admin/admin-agent-config-update-request.schema.json',
      adminAgentListData: 'external/admin/admin-agent-list-data.schema.json',
      adminAgentRecord: 'external/admin/admin-agent-record.schema.json',
      adminAuditRecord: 'external/admin/admin-audit-record.schema.json',
      adminAuditListData: 'external/admin/admin-audit-list-data.schema.json',
      adminMenuItem: 'external/admin/admin-menu-item.schema.json',
      adminSessionProfile: 'external/admin/admin-session-profile.schema.json',
      adminLoginRequest: 'external/admin/admin-login-request.schema.json',
      adminLoginResponseData: 'external/admin/admin-login-response-data.schema.json',
      adminActionConfirmationRequest: 'external/admin/admin-action-confirmation-request.schema.json',
      adminActionConfirmationResponseData: 'external/admin/admin-action-confirmation-response-data.schema.json',
      dashboardSummaryData: 'external/admin/dashboard-summary-data.schema.json',
      knowledgeBase: 'external/admin/knowledge-base.schema.json',
      knowledgeBaseListData: 'external/admin/knowledge-base-list-data.schema.json',
      knowledgeBaseUpdateRequest: 'external/admin/knowledge-base-update-request.schema.json',
      knowledgeChunkStats: 'external/admin/knowledge-chunk-stats.schema.json',
      knowledgeDocumentDetailData: 'external/admin/knowledge-document-detail-data.schema.json',
      knowledgeDocument: 'external/admin/knowledge-document.schema.json',
      knowledgeDocumentListData: 'external/admin/knowledge-document-list-data.schema.json',
      knowledgeChunk: 'external/admin/knowledge-chunk.schema.json',
      knowledgeChunkListData: 'external/admin/knowledge-chunk-list-data.schema.json',
      asyncJob: 'external/admin/async-job.schema.json',
      retrievalSearchSource: 'external/admin/retrieval-search-source.schema.json',
      retrievalSearchPreviewData: 'external/admin/retrieval-search-preview-data.schema.json',
      retrievalDiagnosticsData: 'external/admin/retrieval-diagnostics-data.schema.json'
    },
    user: {
      marketingCampaign: 'external/user/marketing-campaign.schema.json',
      marketingCampaignListData: 'external/user/marketing-campaign-list-data.schema.json',
      marketingCopyRequest: 'external/user/marketing-copy-request.schema.json',
      marketingCopyListData: 'external/user/marketing-copy-list-data.schema.json',
      marketingCopyResult: 'external/user/marketing-copy-result.schema.json',
      posterTask: 'external/user/poster-task.schema.json',
      posterTaskCreateResponseData: 'external/user/poster-task-create-response-data.schema.json',
      posterTaskListData: 'external/user/poster-task-list-data.schema.json',
      posterResultData: 'external/user/poster-result-data.schema.json',
      promotionLinkRequest: 'external/user/promotion-link-request.schema.json',
      promotionLinkListData: 'external/user/promotion-link-list-data.schema.json',
      promotionLinkResult: 'external/user/promotion-link-result.schema.json',
      researchTask: 'external/user/research-task.schema.json',
      researchTaskCreateResponseData: 'external/user/research-task-create-response-data.schema.json',
      researchTaskListData: 'external/user/research-task-list-data.schema.json',
      researchTaskStatusData: 'external/user/research-task-status-data.schema.json',
      researchTaskResultData: 'external/user/research-task-result-data.schema.json'
    }
  },
  internal: {
    auth: {
      tokenValidationResponseData: 'internal/auth/token-validation-response-data.schema.json',
      permissionCheckRequest: 'internal/auth/permission-check-request.schema.json',
      permissionCheckResponseData: 'internal/auth/permission-check-response-data.schema.json',
      invalidateSubjectCacheRequest: 'internal/auth/invalidate-subject-cache-request.schema.json',
      invalidateSubjectCacheResponseData: 'internal/auth/invalidate-subject-cache-response-data.schema.json'
    },
    orchestrator: {
      agentDescriptor: 'internal/orchestrator/agent-descriptor.schema.json',
      agentExecutionRiskFlag: 'internal/orchestrator/agent-execution-risk-flag.schema.json',
      agentExecutionResult: 'internal/orchestrator/agent-execution-result.schema.json',
      agentName: 'internal/orchestrator/agent-name.schema.json',
      agentRouteRecord: 'internal/orchestrator/agent-route-record.schema.json',
      agentTask: 'internal/orchestrator/agent-task.schema.json',
      chatUsage: 'internal/orchestrator/chat-usage.schema.json',
      chatCompletionRequest: 'internal/orchestrator/chat-completion-request.schema.json',
      chatCompletionResponse: 'internal/orchestrator/chat-completion-response.schema.json',
      chatMessageRecord: 'internal/orchestrator/chat-message-record.schema.json',
      conversationRecord: 'internal/orchestrator/conversation-record.schema.json',
      executionCheckpoint: 'internal/orchestrator/execution-checkpoint.schema.json',
      compensationExecutionRecord: 'internal/orchestrator/compensation-execution-record.schema.json',
      executionEvent: 'internal/orchestrator/execution-event.schema.json',
      handoffStep: 'internal/orchestrator/handoff-step.schema.json',
      intentSignal: 'internal/orchestrator/intent-signal.schema.json',
      intentSummary: 'internal/orchestrator/intent-summary.schema.json',
      internalChatPayload: 'internal/orchestrator/internal-chat-payload.schema.json',
      internalChatRequest: 'internal/orchestrator/internal-chat-request.schema.json',
      internalChatResponse: 'internal/orchestrator/internal-chat-response.schema.json',
      internalChatUser: 'internal/orchestrator/internal-chat-user.schema.json',
      messageRequest: 'internal/orchestrator/message-request.schema.json',
      orchestratorResponse: 'internal/orchestrator/orchestrator-response.schema.json',
      pendingUserAction: 'internal/orchestrator/pending-user-action.schema.json',
      responseReview: 'internal/orchestrator/response-review.schema.json',
      responseReviewIssue: 'internal/orchestrator/response-review-issue.schema.json',
      routeDecision: 'internal/orchestrator/route-decision.schema.json',
      routeRequest: 'internal/orchestrator/route-request.schema.json',
      runtimeConstraints: 'internal/orchestrator/runtime-constraints.schema.json',
      sagaCompensationStep: 'internal/orchestrator/saga-compensation-step.schema.json',
      sceneName: 'internal/orchestrator/scene-name.schema.json',
      sessionCreateRequest: 'internal/orchestrator/session-create-request.schema.json',
      sessionContext: 'internal/orchestrator/session-context.schema.json',
      sessionCancelRequest: 'internal/orchestrator/session-cancel-request.schema.json',
      sessionCancelResponse: 'internal/orchestrator/session-cancel-response.schema.json',
      sessionContinueRequest: 'internal/orchestrator/session-continue-request.schema.json',
      sessionDeleteResponse: 'internal/orchestrator/session-delete-response.schema.json',
      sessionListResponse: 'internal/orchestrator/session-list-response.schema.json',
      sessionMessagesPage: 'internal/orchestrator/session-messages-page.schema.json',
      sessionRetryRequest: 'internal/orchestrator/session-retry-request.schema.json',
      sessionRollbackResponse: 'internal/orchestrator/session-rollback-response.schema.json',
      sessionStateSnapshot: 'internal/orchestrator/session-state-snapshot.schema.json',
      sessionUpdateRequest: 'internal/orchestrator/session-update-request.schema.json',
      streamCitationEntry: 'internal/orchestrator/stream-citation-entry.schema.json',
      streamCitationEventData: 'internal/orchestrator/stream-citation-event-data.schema.json',
      streamDeltaEventData: 'internal/orchestrator/stream-delta-event-data.schema.json',
      streamDoneEventData: 'internal/orchestrator/stream-done-event-data.schema.json',
      streamEvent: 'internal/orchestrator/stream-event.schema.json',
      streamEventPage: 'internal/orchestrator/stream-event-page.schema.json',
      streamEventRecord: 'internal/orchestrator/stream-event-record.schema.json',
      streamMetaEventData: 'internal/orchestrator/stream-meta-event-data.schema.json',
      streamReasoningEventData: 'internal/orchestrator/stream-reasoning-event-data.schema.json',
      streamRetrievalEventData: 'internal/orchestrator/stream-retrieval-event-data.schema.json',
      streamRetrievalSource: 'internal/orchestrator/stream-retrieval-source.schema.json',
      streamToolCallEventData: 'internal/orchestrator/stream-tool-call-event-data.schema.json',
      streamToolResultEventData: 'internal/orchestrator/stream-tool-result-event-data.schema.json',
      streamUsage: 'internal/orchestrator/stream-usage.schema.json',
      toolContextItem: 'internal/orchestrator/tool-context-item.schema.json',
      toolInvocation: 'internal/orchestrator/tool-invocation.schema.json',
      toolPlanItem: 'internal/orchestrator/tool-plan-item.schema.json',
      userProfile: 'internal/orchestrator/user-profile.schema.json',
      userProfilePatch: 'internal/orchestrator/user-profile-patch.schema.json'
    },
    toolHub: {
      compensationCallRequest: 'internal/tool-hub/compensation-call-request.schema.json',
      compensationCallResponse: 'internal/tool-hub/compensation-call-response.schema.json',
      mcpToolsListResponse: 'internal/tool-hub/mcp-tools-list-response.schema.json',
      toolCallAuditRecord: 'internal/tool-hub/tool-call-audit-record.schema.json',
      toolAuthRequirements: 'internal/tool-hub/tool-auth-requirements.schema.json',
      toolCallError: 'internal/tool-hub/tool-call-error.schema.json',
      toolCallOperator: 'internal/tool-hub/tool-call-operator.schema.json',
      toolCallRequest: 'internal/tool-hub/tool-call-request.schema.json',
      toolCallResponse: 'internal/tool-hub/tool-call-response.schema.json',
      toolCallUserContext: 'internal/tool-hub/tool-call-user-context.schema.json',
      toolCompensationAction: 'internal/tool-hub/tool-compensation-action.schema.json',
      toolDefinition: 'internal/tool-hub/tool-definition.schema.json',
      toolDescriptor: 'internal/tool-hub/tool-descriptor.schema.json',
      toolExecutionContext: 'internal/tool-hub/tool-execution-context.schema.json',
      toolExecutionResult: 'internal/tool-hub/tool-execution-result.schema.json',
      toolInvocationRequest: 'internal/tool-hub/tool-invocation-request.schema.json',
      toolInvokeRequest: 'internal/tool-hub/tool-invoke-request.schema.json',
      toolInvokeResponse: 'internal/tool-hub/tool-invoke-response.schema.json',
      toolPreflightResult: 'internal/tool-hub/tool-preflight-result.schema.json',
      toolPreflightResponse: 'internal/tool-hub/tool-preflight-response.schema.json',
      toolUserActionHint: 'internal/tool-hub/tool-user-action-hint.schema.json',
      toolMode: 'internal/tool-hub/tool-mode.schema.json',
      toolOperation: 'internal/tool-hub/tool-operation.schema.json'
    },
    businessTools: {
      businessCompensationExecuteRequest: 'internal/business-tools/business-compensation-execute-request.schema.json',
      businessCompensationExecuteResponse: 'internal/business-tools/business-compensation-execute-response.schema.json',
      businessToolExecuteRequest: 'internal/business-tools/business-tool-execute-request.schema.json',
      businessToolExecuteResponse: 'internal/business-tools/business-tool-execute-response.schema.json',
      operatorContext: 'internal/business-tools/operator-context.schema.json',
      subjectContext: 'internal/business-tools/subject-context.schema.json'
    },
    knowledge: {
      knowledgeRuntimeSnapshot: 'internal/knowledge/knowledge-runtime-snapshot.schema.json'
    }
  },
  errors: {
    catalog: '../errors/error_codes.yaml'
  }
} as const;
