import { createApiClient, type FrontendApiClient } from '../core/http';
import {
  mapAdminDiagnosticPayload,
  mapAdminSearchPreviewPayload
} from './mappers';
import type {
  AdminAsyncJob,
  AdminAuditListPayload,
  AdminDiagnosticInput,
  AdminDiagnosticPayload,
  AdminDocumentDetailPayload,
  AdminDocumentListPayload,
  AdminDocumentRecord,
  AdminSearchPreviewInput,
  AdminSearchPreviewPayload,
  AnswerPayload,
  BootstrapCatalogInput,
  BootstrapPayload,
  ChunkRecord,
  CreateKnowledgeBaseInput,
  CreateKnowledgeDocumentInput,
  DocumentRecord,
  FetchKnowledgeAuditRecordsQuery,
  FileImportPayload,
  FileImportPreviewPayload,
  HealthPayload,
  ImportFilesInput,
  IngestDocumentInput,
  IngestionJob,
  IngestionResult,
  KnowledgeBaseListPayload,
  KnowledgeBaseRecord,
  KnowledgeOverview,
  KnowledgeRuntimeSnapshot,
  KnowledgeSearchPayload,
  RagCapabilities,
  ReindexKnowledgeDocumentInput,
  RetrievalDiagnosticPayload,
  SourceRecord,
  UpdateKnowledgeBaseInput
} from './types';

export interface WebAdminApiConfig {
  knowledgeBaseUrl: string;
  ragBaseUrl: string;
  requestTimeoutMs?: number;
  callerService?: string;
  operatorReasonHeaderName?: string;
  fetchFn?: typeof fetch;
}

export function serviceRoot(apiBaseUrl: string): string {
  if (/^[a-zA-Z][a-zA-Z\d+.-]*:\/\//.test(apiBaseUrl)) {
    return new URL(apiBaseUrl).origin;
  }

  return '';
}

function createAdminClient(apiBaseUrl: string, config: WebAdminApiConfig): FrontendApiClient {
  return createApiClient({
    baseUrl: apiBaseUrl,
    requestTimeoutMs: config.requestTimeoutMs ?? 30_000,
    fetchFn: config.fetchFn,
    buildHeaders: ({ init }) => {
      const headers = new Headers(init.headers);
      if (!headers.has('X-Caller-Service')) {
        headers.set('X-Caller-Service', config.callerService ?? 'web-admin');
      }
      return headers;
    },
    requestIdPrefix: config.callerService ?? 'web-admin'
  });
}

function buildFilters(sourceIds: string[], tags: string[]) {
  if (sourceIds.length === 0 && tags.length === 0) {
    return undefined;
  }

  return {
    sourceIds,
    tags
  };
}

function buildOperatorReasonHeaders(config: WebAdminApiConfig, operatorReason: string): HeadersInit {
  return {
    [config.operatorReasonHeaderName ?? 'X-Operator-Reason']: operatorReason
  };
}

function buildPathWithQuery(
  path: string,
  query: Record<string, string | undefined>
): string {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') {
      params.set(key, value);
    }
  }

  const encoded = params.toString();
  return encoded ? `${path}?${encoded}` : path;
}

export function createWebAdminApi(config: WebAdminApiConfig) {
  const knowledgeClient = createAdminClient(config.knowledgeBaseUrl, config);
  const ragClient = createAdminClient(config.ragBaseUrl, config);
  const rootClient = createAdminClient(serviceRoot(config.knowledgeBaseUrl), config);
  const ragRootClient = createAdminClient(serviceRoot(config.ragBaseUrl), config);

  return {
    fetchKnowledgeHealth(): Promise<HealthPayload> {
      return rootClient.request<HealthPayload>('/healthz');
    },

    fetchRagHealth(): Promise<HealthPayload> {
      return ragRootClient.request<HealthPayload>('/healthz');
    },

    fetchRagCapabilities(): Promise<RagCapabilities> {
      return ragRootClient.request<RagCapabilities>('/api/rag/v1/capabilities');
    },

    fetchKnowledgeSnapshot(auditLimit = 20): Promise<KnowledgeRuntimeSnapshot> {
      const params = new URLSearchParams({ auditLimit: String(auditLimit) });
      return rootClient.request<KnowledgeRuntimeSnapshot>(`/api/knowledge/v1/snapshot?${params.toString()}`);
    },

    fetchSources(): Promise<SourceRecord[]> {
      return knowledgeClient.request<SourceRecord[]>('/sources');
    },

    fetchDocuments(): Promise<DocumentRecord[]> {
      return knowledgeClient.request<DocumentRecord[]>('/documents');
    },

    fetchChunks(documentId?: string): Promise<ChunkRecord[]> {
      return knowledgeClient.request<ChunkRecord[]>(
        buildPathWithQuery('/chunks', {
          documentId
        })
      );
    },

    fetchIngestions(): Promise<IngestionJob[]> {
      return knowledgeClient.request<IngestionJob[]>('/ingestions');
    },

    fetchOverview(): Promise<KnowledgeOverview> {
      return knowledgeClient.request<KnowledgeOverview>('/overview');
    },

    bootstrapCatalog(input: BootstrapCatalogInput): Promise<BootstrapPayload> {
      return knowledgeClient.request<BootstrapPayload>('/catalog:bootstrap', {
        method: 'POST',
        headers: buildOperatorReasonHeaders(config, input.operatorReason)
      });
    },

    previewImportFiles(directory: string, glob = '**/*', maxFiles = 12): Promise<FileImportPreviewPayload> {
      return knowledgeClient.request<FileImportPreviewPayload>(
        buildPathWithQuery('/imports:preview', {
          directory: directory.trim() || undefined,
          glob,
          maxFiles: String(maxFiles)
        })
      );
    },

    importFiles(input: ImportFilesInput): Promise<FileImportPayload> {
      return knowledgeClient.request<FileImportPayload>('/files:ingest', {
        method: 'POST',
        body: JSON.stringify({
          directory: input.directory || undefined,
          glob: input.glob,
          maxFiles: input.maxFiles ?? 12,
          sourceId: input.sourceId || undefined,
          source: input.sourceId
            ? undefined
            : {
                name: input.sourceName,
                kind: input.sourceKind,
                uri: input.sourceUri || undefined,
                description: input.sourceDescription || undefined,
                tags: input.sourceTags
              },
          tags: input.tags
        })
      });
    },

    searchKnowledge(query: string, topK = 5, sourceIds: string[] = [], tags: string[] = []): Promise<KnowledgeSearchPayload> {
      return knowledgeClient.request<KnowledgeSearchPayload>('/search', {
        method: 'POST',
        body: JSON.stringify({
          query,
          topK,
          sourceIds,
          tags
        })
      });
    },

    ingestDocument(input: IngestDocumentInput): Promise<IngestionResult> {
      return knowledgeClient.request<IngestionResult>('/documents:ingest', {
        method: 'POST',
        body: JSON.stringify({
          sourceId: input.sourceId || undefined,
          source: input.sourceId
            ? undefined
            : {
                name: input.sourceName,
                kind: input.sourceKind,
                uri: input.sourceUri || undefined,
                description: input.sourceDescription || undefined,
                tags: input.sourceTags
              },
          title: input.title,
          content: input.content,
          tags: input.tags
        })
      });
    },

    diagnose(query: string, topK = 5, sourceIds: string[] = [], tags: string[] = []): Promise<RetrievalDiagnosticPayload> {
      return ragClient.request<RetrievalDiagnosticPayload>('/diagnose', {
        method: 'POST',
        body: JSON.stringify({
          query,
          topK,
          filters: buildFilters(sourceIds, tags)
        })
      });
    },

    answer(query: string, topK = 5, sourceIds: string[] = [], tags: string[] = []): Promise<AnswerPayload> {
      return ragClient.request<AnswerPayload>('/answer', {
        method: 'POST',
        body: JSON.stringify({
          query,
          topK,
          style: 'detailed',
          filters: buildFilters(sourceIds, tags)
        })
      });
    },

    fetchKnowledgeBases(): Promise<KnowledgeBaseListPayload> {
      return rootClient.request<KnowledgeBaseListPayload>('/api/v1/admin/knowledge-bases?page=1&page_size=100');
    },

    createKnowledgeBase(input: CreateKnowledgeBaseInput): Promise<KnowledgeBaseRecord> {
      return rootClient.request<KnowledgeBaseRecord>('/api/v1/admin/knowledge-bases', {
        method: 'POST',
        headers: buildOperatorReasonHeaders(config, input.operatorReason),
        body: JSON.stringify({
          name: input.name,
          code: input.code,
          scene: input.scene,
          language: input.language,
          retrieval_mode: input.retrievalMode,
          embedding_model: input.embeddingModel,
          description: input.description || undefined
        })
      });
    },

    updateKnowledgeBase(input: UpdateKnowledgeBaseInput): Promise<KnowledgeBaseRecord> {
      return rootClient.request<KnowledgeBaseRecord>(`/api/v1/admin/knowledge-bases/${input.knowledgeBaseId}`, {
        method: 'PATCH',
        headers: buildOperatorReasonHeaders(config, input.operatorReason),
        body: JSON.stringify({
          name: input.name,
          description: input.description || undefined,
          retrieval_mode: input.retrievalMode,
          status: input.status
        })
      });
    },

    fetchKnowledgeBaseDocuments(knowledgeBaseId: string): Promise<AdminDocumentListPayload> {
      return rootClient.request<AdminDocumentListPayload>(`/api/v1/admin/knowledge-bases/${knowledgeBaseId}/documents?page=1&page_size=100`);
    },

    createKnowledgeDocument(input: CreateKnowledgeDocumentInput): Promise<AdminDocumentRecord> {
      return rootClient.request<AdminDocumentRecord>(`/api/v1/admin/knowledge-bases/${input.knowledgeBaseId}/documents`, {
        method: 'POST',
        headers: buildOperatorReasonHeaders(config, input.operatorReason),
        body: JSON.stringify({
          file_id: input.fileId,
          title: input.title,
          tags: input.tags,
          source_type: input.sourceType,
          source_uri: input.sourceUri || undefined
        })
      });
    },

    fetchKnowledgeDocumentDetail(documentId: string): Promise<AdminDocumentDetailPayload> {
      return rootClient.request<AdminDocumentDetailPayload>(`/api/v1/admin/knowledge-documents/${documentId}`);
    },

    reindexKnowledgeDocument(input: ReindexKnowledgeDocumentInput): Promise<AdminAsyncJob> {
      return rootClient.request<AdminAsyncJob>(`/api/v1/admin/knowledge-documents/${input.documentId}/reindex`, {
        method: 'POST',
        headers: buildOperatorReasonHeaders(config, input.operatorReason),
        body: JSON.stringify({
          force: true,
          confirm_token: input.confirmToken
        })
      });
    },

    fetchAdminJob(jobId: string): Promise<AdminAsyncJob> {
      return rootClient.request<AdminAsyncJob>(`/api/v1/admin/jobs/${jobId}`);
    },

    fetchKnowledgeAuditRecords(input?: FetchKnowledgeAuditRecordsQuery): Promise<AdminAuditListPayload> {
      return knowledgeClient.request<AdminAuditListPayload>(
        buildPathWithQuery('/admin/audit-records', {
          page: String(input?.page ?? 1),
          pageSize: String(input?.pageSize ?? 20),
          resourceType: input?.resourceType,
          action: input?.action,
          operatorId: input?.operatorId
        })
      );
    },

    searchKnowledgeAdminPreview(input: AdminSearchPreviewInput): Promise<AdminSearchPreviewPayload> {
      return rootClient
        .request<unknown>('/api/v1/admin/retrieval/search-preview', {
          method: 'POST',
          body: JSON.stringify({
            query: input.query,
            kb_id: input.knowledgeBaseId || undefined,
            top_k: input.topK ?? 5,
            tags: input.tags ?? []
          })
        })
        .then(mapAdminSearchPreviewPayload);
    },

    diagnoseAdminRetrieval(input: AdminDiagnosticInput): Promise<AdminDiagnosticPayload> {
      return ragRootClient
        .request<unknown>('/api/v1/admin/retrieval/diagnostics', {
          method: 'POST',
          body: JSON.stringify({
            query: input.query,
            kb_id: input.knowledgeBaseId || undefined,
            top_k: input.topK ?? 5,
            include_citations: input.includeCitations ?? true
          })
        })
        .then(mapAdminDiagnosticPayload);
    }
  };
}
