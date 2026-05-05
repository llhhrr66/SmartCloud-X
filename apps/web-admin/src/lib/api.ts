import type {
  AdminJob,
  AdminProfile,
  AdminSession,
  AgentRecord,
  AuditRecord,
  DashboardSummary,
  DocumentDetail,
  FaqMetadata,
  HealthPayload,
  KnowledgeBaseRecord,
  KnowledgeChunkRecord,
  KnowledgeDocumentContent,
  KnowledgeDocumentRecord,
  LegacySource,
  MarketingCampaign,
  PageResult,
  RetrievalDiagnosticResult,
  RuntimeSnapshot,
  SearchPreviewResult,
  UploadRecord,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/";
const SESSION_KEY = "smartcloud-x:web-admin:admin-session";
const REQUEST_TIMEOUT_MS = Number(import.meta.env.VITE_REQUEST_TIMEOUT_MS ?? 30_000);

function joinUrl(base: string, path: string): string {
  if (!base || base === "/") return path;
  return `${base.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function unwrap<T>(payload: unknown): T {
  if (isRecord(payload) && "data" in payload) return payload.data as T;
  return payload as T;
}

function errorMessage(payload: unknown, fallback: string): string {
  if (isRecord(payload)) {
    if (typeof payload.message === "string") return payload.message;
    if (isRecord(payload.detail) && typeof payload.detail.message === "string") return payload.detail.message;
    if (typeof payload.detail === "string") return payload.detail;
    if (isRecord(payload.error) && typeof payload.error.message === "string") return payload.error.message;
  }
  return fallback;
}

async function parseResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

class AdminApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.payload = payload;
  }
}

function sessionFromStorage(): AdminSession | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    return raw ? (JSON.parse(raw) as AdminSession) : null;
  } catch {
    return null;
  }
}

function saveSession(session: AdminSession): void {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

function clearSession(): void {
  window.localStorage.removeItem(SESSION_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const headers = new Headers(init.headers);
  const session = sessionFromStorage();

  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (session?.accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${session.accessToken}`);
  }
  if (!headers.has("X-Caller-Service")) headers.set("X-Caller-Service", "web-admin");
  if (!headers.has("X-Request-Id")) headers.set("X-Request-Id", `web-admin-${Date.now()}-${Math.random().toString(16).slice(2)}`);

  try {
    const response = await fetch(joinUrl(API_BASE_URL, path), {
      ...init,
      headers,
      signal: init.signal ?? controller.signal,
    });
    const payload = await parseResponse(response);
    if (!response.ok) throw new AdminApiError(errorMessage(payload, `HTTP ${response.status}`), response.status, payload);
    return unwrap<T>(payload);
  } finally {
    window.clearTimeout(timeout);
  }
}

function query(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") sp.set(key, String(value));
  });
  const text = sp.toString();
  return text ? `?${text}` : "";
}

function toSession(payload: unknown): AdminSession {
  const record = unwrap<Record<string, unknown>>(payload);
  return {
    accessToken: String(record.access_token ?? record.accessToken ?? ""),
    refreshToken: String(record.refresh_token ?? record.refreshToken ?? ""),
    admin: (record.admin ?? record) as AdminProfile,
  };
}

export const adminSession = {
  get: sessionFromStorage,
  set: saveSession,
  clear: clearSession,
  hasPermission(permission: string): boolean {
    return Boolean(sessionFromStorage()?.admin.permissions.includes(permission));
  },
};

export const adminApi = {
  async login(username: string, password: string): Promise<AdminSession> {
    const payload = await request<unknown>("/api/v1/admin/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    const session = toSession(payload);
    saveSession(session);
    return session;
  },

  async me(): Promise<AdminProfile> {
    const admin = await request<AdminProfile>("/api/v1/admin/auth/me");
    const current = sessionFromStorage();
    if (current) saveSession({ ...current, admin });
    return admin;
  },

  logout(): void {
    clearSession();
  },

  createConfirmation(action: string, resourceScope: string, password: string) {
    return request<{ confirm_token: string; expired_at: string; action: string; resource_scope: string }>(
      "/api/v1/admin/auth/action-confirmations",
      {
        method: "POST",
        body: JSON.stringify({
          action,
          resource_scope: resourceScope,
          verification_method: "password",
          verification_payload: { password },
        }),
      },
    );
  },

  dashboard() {
    return request<DashboardSummary>("/api/v1/admin/dashboard/summary");
  },

  knowledgeBases() {
    return request<PageResult<KnowledgeBaseRecord>>("/api/v1/admin/knowledge-bases?page=1&page_size=100");
  },

  createKnowledgeBase(input: Partial<KnowledgeBaseRecord> & { embedding_model: string; operatorReason: string }) {
    return request<KnowledgeBaseRecord>("/api/v1/admin/knowledge-bases", {
      method: "POST",
      headers: { "X-Operator-Reason": input.operatorReason },
      body: JSON.stringify({
        name: input.name,
        code: input.code,
        scene: input.scene,
        language: input.language,
        retrieval_mode: input.retrieval_mode,
        embedding_model: input.embedding_model,
        description: input.description || undefined,
      }),
    });
  },

  updateKnowledgeBase(kbId: string, input: Partial<KnowledgeBaseRecord> & { operatorReason: string }) {
    return request<KnowledgeBaseRecord>(`/api/v1/admin/knowledge-bases/${encodeURIComponent(kbId)}`, {
      method: "PATCH",
      headers: { "X-Operator-Reason": input.operatorReason },
      body: JSON.stringify({
        name: input.name,
        description: input.description,
        retrieval_mode: input.retrieval_mode,
        status: input.status,
      }),
    });
  },

  documents(kbId: string) {
    return request<PageResult<KnowledgeDocumentRecord>>(`/api/v1/admin/knowledge-bases/${encodeURIComponent(kbId)}/documents?page=1&page_size=100`);
  },

  createDocument(kbId: string, input: { file_id: string; title: string; tags: string[]; source_type: string; source_uri?: string; operatorReason: string }) {
    return request<KnowledgeDocumentRecord>(`/api/v1/admin/knowledge-bases/${encodeURIComponent(kbId)}/documents`, {
      method: "POST",
      headers: { "X-Operator-Reason": input.operatorReason },
      body: JSON.stringify(input),
    });
  },

  documentDetail(docId: string) {
    return request<DocumentDetail>(`/api/v1/admin/knowledge-documents/${encodeURIComponent(docId)}`);
  },

  documentChunks(docId: string) {
    return request<PageResult<KnowledgeChunkRecord>>(`/api/v1/admin/knowledge-documents/${encodeURIComponent(docId)}/chunks?page=1&page_size=100`);
  },

  /** Fetch full document content (including content field) from knowledge-service. */
  fetchDocumentContent(docId: string) {
    return request<KnowledgeDocumentContent>(`/api/knowledge/v1/documents/${encodeURIComponent(docId)}`);
  },

  /** L1 FAQ cache match — returns structured answer or miss. */
  faqMatch(query: string) {
    return request<{ matched: boolean; answer?: string | null; matchReason?: string | null; tokenSaved?: number; category?: string | null; prerequisites?: string[]; documentRefs?: Array<{ docId: string; title: string }>; relatedTopics?: string[] }>("/api/rag/v1/faq/match", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
  },

  reindexDocument(docId: string, confirmToken: string, operatorReason: string) {
    return request<AdminJob>(`/api/v1/admin/knowledge-documents/${encodeURIComponent(docId)}/reindex`, {
      method: "POST",
      headers: { "X-Operator-Reason": operatorReason },
      body: JSON.stringify({ force: true, confirm_token: confirmToken }),
    });
  },

  job(jobId: string) {
    return request<AdminJob>(`/api/v1/admin/jobs/${encodeURIComponent(jobId)}`);
  },

  initUpload(filename: string, contentType: string, operatorReason: string) {
    return request<UploadRecord>("/api/v1/admin/files/uploads", {
      method: "POST",
      headers: { "X-Operator-Reason": operatorReason },
      body: JSON.stringify({ filename, content_type: contentType || undefined }),
    });
  },

  uploadContent(uploadId: string, file: File, operatorReason: string) {
    return request<UploadRecord>(`/api/v1/admin/files/uploads/${encodeURIComponent(uploadId)}/content`, {
      method: "PUT",
      headers: { "Content-Type": file.type || "application/octet-stream", "X-Operator-Reason": operatorReason },
      body: file,
    });
  },

  completeUpload(uploadId: string, operatorReason: string) {
    return request<UploadRecord>(`/api/v1/admin/files/uploads/${encodeURIComponent(uploadId)}:complete`, {
      method: "POST",
      headers: { "X-Operator-Reason": operatorReason },
    });
  },

  previewImports(directory: string, glob = "**/*") {
    return request<Record<string, unknown>>(`/api/knowledge/v1/imports:preview${query({ directory, glob })}`);
  },

  importFiles(input: Record<string, unknown>) {
    return request<Record<string, unknown>>("/api/knowledge/v1/files:ingest", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  sources() {
    return request<LegacySource[]>("/api/knowledge/v1/sources");
  },

  searchPreview(input: { query: string; kb_id?: string; top_k?: number; tags?: string[] }) {
    return request<SearchPreviewResult>("/api/v1/admin/retrieval/search-preview", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  retrievalDiagnostics(input: { query: string; kb_id?: string; top_k?: number; include_citations?: boolean }) {
    return request<RetrievalDiagnosticResult>("/api/v1/admin/retrieval/diagnostics", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  ragCapabilities() {
    return request<Record<string, unknown>>("/api/rag/v1/capabilities");
  },

  ragAnswer(input: Record<string, unknown>) {
    return request<Record<string, unknown>>("/api/rag/v1/answer", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  agents() {
    return request<{ items: AgentRecord[]; total: number }>("/api/v1/admin/agents");
  },

  updateAgent(agentCode: string, input: Partial<Pick<AgentRecord, "enabled" | "max_tool_calls" | "fallback_agent" | "timeout_seconds">>) {
    return request<AgentRecord>(`/api/v1/admin/agents/${encodeURIComponent(agentCode)}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },

  campaigns(status?: string) {
    return request<PageResult<MarketingCampaign>>(`/api/v1/admin/marketing/campaigns${query({ page: 1, page_size: 100, status })}`);
  },

  saveCampaign(input: Partial<MarketingCampaign>) {
    const isUpdate = Boolean(input.campaign_id);
    return request<MarketingCampaign>(
      isUpdate ? `/api/v1/admin/marketing/campaigns/${encodeURIComponent(input.campaign_id!)}` : "/api/v1/admin/marketing/campaigns",
      {
        method: isUpdate ? "PUT" : "POST",
        body: JSON.stringify(input),
      },
    );
  },

  deleteCampaign(campaignId: string) {
    return request<Record<string, unknown>>(`/api/v1/admin/marketing/campaigns/${encodeURIComponent(campaignId)}`, { method: "DELETE" });
  },

  auditRecords(filters: { resourceType?: string; action?: string; operatorId?: string } = {}) {
    return request<PageResult<AuditRecord>>(`/api/knowledge/v1/admin/audit-records${query({ page: 1, pageSize: 100, ...filters })}`);
  },

  overview() {
    return request<Record<string, unknown>>("/api/knowledge/v1/overview");
  },

  snapshot() {
    return request<RuntimeSnapshot>("/api/knowledge/v1/snapshot?auditLimit=20");
  },

  knowledgeHealth() {
    return request<HealthPayload>("/healthz");
  },

  listLlmProviders() {
    return request<unknown>("/api/v1/admin/llm-providers");
  },

  createLlmProvider(input: { name: string; api_key: string; api_url: string; model_name: string; provider_type: string; is_active: boolean }) {
    return request<unknown>("/api/v1/admin/llm-providers", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  updateLlmProvider(providerId: string, input: Record<string, unknown>) {
    return request<unknown>(`/api/v1/admin/llm-providers/${encodeURIComponent(providerId)}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    });
  },

  deleteLlmProvider(providerId: string) {
    return request<unknown>(`/api/v1/admin/llm-providers/${encodeURIComponent(providerId)}`, { method: "DELETE" });
  },

  testLlmProvider(input: { api_key: string; api_url: string; model_name?: string }) {
    return request<{ success: boolean; message: string; model_id: string | null; latency_ms: number | null }>("/api/v1/admin/llm-providers/test", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  fetchLlmProviderModels(input: { api_key: string; api_url: string }) {
    return request<{ success: boolean; message: string; models: string[] }>("/api/v1/admin/llm-providers/models", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },
};

export { AdminApiError };
