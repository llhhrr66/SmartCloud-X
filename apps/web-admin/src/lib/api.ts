import {
  createWebAdminApi
} from '../shared-sdk';

const knowledgeBaseUrl =
  import.meta.env.VITE_KNOWLEDGE_SERVICE_BASE_URL ??
  'http://localhost:8030/api/knowledge/v1';
const ragBaseUrl =
  import.meta.env.VITE_RAG_SERVICE_BASE_URL ?? 'http://localhost:8040/api/rag/v1';
const operatorReasonHeaderName =
  import.meta.env.VITE_OPERATOR_REASON_HEADER ?? 'X-Operator-Reason';
const callerService = 'web-admin';
const requestTimeoutMs = 30_000;

const adminApi = createWebAdminApi({
  knowledgeBaseUrl,
  ragBaseUrl,
  callerService,
  operatorReasonHeaderName,
  requestTimeoutMs
});

export const {
  fetchKnowledgeHealth,
  fetchRagHealth,
  fetchRagCapabilities,
  fetchKnowledgeSnapshot,
  fetchKnowledgeBases,
  createKnowledgeBase,
  updateKnowledgeBase,
  fetchKnowledgeBaseDocuments,
  createKnowledgeDocument,
  fetchKnowledgeDocumentDetail,
  reindexKnowledgeDocument,
  fetchAdminJob,
  fetchKnowledgeAuditRecords,
  fetchSources,
  fetchDocuments,
  fetchChunks,
  fetchIngestions,
  fetchOverview,
  bootstrapCatalog,
  previewImportFiles,
  importFiles,
  searchKnowledge,
  searchKnowledgeAdminPreview,
  ingestDocument,
  diagnoseAdminRetrieval,
  diagnose,
  answer
} = adminApi;
