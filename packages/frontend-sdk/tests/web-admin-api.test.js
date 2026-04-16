import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { createWebAdminApi } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-admin/api.js');

test('createWebAdminApi exposes shared root-level admin helpers', async () => {
  const requests = [];

  const api = createWebAdminApi({
    knowledgeBaseUrl: 'http://localhost:8030/api/knowledge/v1',
    ragBaseUrl: 'http://localhost:8040/api/rag/v1',
    callerService: 'web-admin',
    operatorReasonHeaderName: 'X-Operator-Reason',
    fetchFn: async (url, init) => {
      requests.push({
        url: String(url),
        method: init?.method ?? 'GET',
        headers: Object.fromEntries(new Headers(init?.headers).entries()),
        body: init?.body ? JSON.parse(String(init.body)) : null
      });

      if (String(url).endsWith('/api/rag/v1/capabilities')) {
        return new Response(
          JSON.stringify({
            code: 0,
            data: {
              rewrite: 'hybrid',
              retrieval: 'vector+bm25',
              rerank: 'enabled',
              answering: 'grounded',
              diagnostics: 'enabled'
            }
          }),
          {
            status: 200,
            headers: {
              'content-type': 'application/json'
            }
          }
        );
      }

      if (String(url).includes('/api/knowledge/v1/snapshot')) {
        return new Response(
          JSON.stringify({
            code: 0,
            data: {
              exportedAt: '2026-04-16T00:00:00.000Z',
              service: 'knowledge-service',
              dataPath: '/data',
              auditPath: '/audit',
              importRoot: '/imports',
              counts: {},
              overview: {},
              sources: [],
              documents: [],
              chunks: [],
              ingestions: [],
              knowledgeBases: [],
              documentProfiles: [],
              adminJobs: [],
              recentAuditRecords: [],
              integrations: {
                rawStorage: { backend: 'minio', configured: true },
                metadataStore: { backend: 'mysql', configured: true },
                vectorStore: { backend: 'qdrant', configured: true },
                bm25Store: { backend: 'opensearch', configured: true },
                cache: { backend: 'redis', configured: true },
                taskQueue: { backend: 'celery', configured: true },
                outboxPath: '/outbox',
                rawMirrorRoot: '/mirror',
                pendingEvents: 0,
                recentEvents: []
              }
            }
          }),
          {
            status: 200,
            headers: {
              'content-type': 'application/json'
            }
          }
        );
      }

      return new Response(
        JSON.stringify({
          code: 0,
          data: {
            kb_id: 'kb_001',
            name: '运维知识库',
            code: 'ops',
            scene: 'customer_service',
            language: 'zh-CN',
            retrieval_mode: 'hybrid',
            embedding_model: 'text-embedding-3-large',
            status: 'active',
            description: 'baseline'
          }
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json'
          }
        }
      );
    }
  });

  const capabilities = await api.fetchRagCapabilities();
  const snapshot = await api.fetchKnowledgeSnapshot(25);
  const knowledgeBase = await api.updateKnowledgeBase({
    knowledgeBaseId: 'kb_001',
    name: '运维知识库',
    description: 'baseline',
    retrievalMode: 'hybrid',
    status: 'active',
    operatorReason: 'sync shared sdk'
  });

  assert.equal(capabilities.retrieval, 'vector+bm25');
  assert.equal(snapshot.service, 'knowledge-service');
  assert.equal(knowledgeBase.kb_id, 'kb_001');
  assert.equal(requests[0].url, 'http://localhost:8040/api/rag/v1/capabilities');
  assert.equal(requests[1].url, 'http://localhost:8030/api/knowledge/v1/snapshot?auditLimit=25');
  assert.equal(requests[2].headers['x-operator-reason'], 'sync shared sdk');
  assert.equal(requests[2].body.retrieval_mode, 'hybrid');
});
