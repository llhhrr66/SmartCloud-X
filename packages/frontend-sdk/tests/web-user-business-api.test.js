import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { ApiError } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
const {
  normalizeCompleteUploadRequest,
  normalizeUploadPolicyRequest
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-normalizers.js');
const {
  extractFileNameFromObjectKey
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-state.js');
const {
  createBillingApi,
  createCitationApi,
  createFileApi,
  createIcpApi,
  createOrderApi,
  createServiceDeskApi,
  createTicketApi,
  createWebUserBusinessApis
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-api.js');
const {
  mapBillingSummary,
  mapCitationDetail,
  mapFileRecord,
  mapIcpApplication,
  mapIcpMaterialCheckResult,
  mapOrderDetail,
  mapRefundRecord,
  mapServiceWorkspaceData,
  mapTicketDetail,
  mapUploadPolicy
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-mappers.js');

test('createBillingApi marks the dashboard degraded when only part of the workspace loads', async () => {
  const client = {
    async request(path) {
      if (path.includes('/billing/summary')) {
        return {
          total_amount: '128.00',
          currency: 'CNY',
          range: 'this_month'
        };
      }

      if (path.includes('/billing/details')) {
        throw new Error('details unavailable');
      }

      if (path.includes('/billing/invoices')) {
        return {
          items: [
            {
              invoice_no: 'inv_001',
              status: 'issued',
              amount: '128.00',
              billing_cycle: '2026-04',
              title: 'SmartCloud'
            }
          ]
        };
      }

      if (path.includes('/api/v1/orders')) {
        return {
          items: [
            {
              order_no: 'ord_001',
              product_type: 'GPU 云服务器',
              status: 'paid',
              amount: '599.00',
              created_at: '2026-04-16T00:00:00.000Z'
            }
          ]
        };
      }

      if (path.includes('/api/v1/tickets')) {
        throw new Error('tickets unavailable');
      }

      throw new Error(`unexpected path: ${path}`);
    }
  };

  const api = createBillingApi({ client });
  const dashboard = await api.getDashboard();

  assert.equal(dashboard.summary.totalAmount, '128.00');
  assert.equal(dashboard.invoices[0].invoiceNo, 'inv_001');
  assert.equal(dashboard.orders[0].orderNo, 'ord_001');
  assert.equal(dashboard.loadState.degraded, true);
  assert.deepEqual(dashboard.loadState.failedDomains, ['details', 'tickets']);
  assert.equal(dashboard.loadState.domainErrors.details.kind, 'server');
  assert.match(dashboard.loadState.domainErrors.details.message, /details unavailable/);
  assert.equal(dashboard.loadState.domainErrors.tickets.kind, 'server');
  assert.match(dashboard.loadState.domainErrors.tickets.message, /tickets unavailable/);
});

test('createBillingApi preserves structured domain error metadata for degraded sections', async () => {
  const api = createBillingApi({
    client: {
      async request(path) {
        if (path.includes('/billing/summary')) {
          throw new ApiError(
            'forbidden',
            403,
            'TOOL_HUB_CALLER_FORBIDDEN',
            {
              user_action_hint: {
                action: 'collect-auth-context',
                required_permissions: ['user:billing.read'],
                missing_auth_context: ['account_id']
              }
            },
            'req-billing-summary'
          );
        }

        if (path.includes('/billing/details')) {
          throw new ApiError('slow down', 429, 'RATE_LIMITED', undefined, 'req-billing-details', 1500);
        }

        return { items: [] };
      }
    }
  });

  const dashboard = await api.getDashboard();

  assert.equal(dashboard.loadState.degraded, true);
  assert.deepEqual(dashboard.loadState.failedDomains, ['summary', 'details']);
  assert.deepEqual(dashboard.loadState.domainErrors.summary, {
      kind: 'forbidden',
      message: 'forbidden (request id: req-billing-summary)',
      status: 403,
      code: 'TOOL_HUB_CALLER_FORBIDDEN',
      requestId: 'req-billing-summary',
      retryAfterMs: undefined,
      details: {
        missingFields: [],
        requiredPermissions: ['user:billing.read'],
        missingAuthContext: ['account_id']
      }
    });
  assert.deepEqual(dashboard.loadState.domainErrors.details, {
    kind: 'rate_limited',
    message: 'slow down (request id: req-billing-details)',
    status: 429,
    code: 'RATE_LIMITED',
    requestId: 'req-billing-details',
    retryAfterMs: 1500
  });
});

test('createBillingApi exposes a strict shared billing summary query path', async () => {
  const requestedPaths = [];

  const api = createBillingApi({
    client: {
      async request(path) {
        requestedPaths.push(path);
        const range = new URL(path, 'https://smartcloud.local').searchParams.get('range') ?? 'unknown';

        return {
          total_amount: '256.00',
          currency: 'CNY',
          range
        };
      }
    }
  });

  const explicitSummary = await api.getSummary({
    range: '  last_3_months  '
  });
  const fallbackSummary = await api.getSummary({
    range: '   '
  });

  assert.equal(explicitSummary.range, 'last_3_months');
  assert.equal(fallbackSummary.range, 'this_month');
  assert.deepEqual(requestedPaths, [
    '/api/v1/billing/summary?range=last_3_months',
    '/api/v1/billing/summary?range=this_month'
  ]);
});

test('createServiceDeskApi normalizes ticket creation payloads and fallback fields', async () => {
  let capturedInit = null;

  const api = createServiceDeskApi({
    client: {
      async request(path, init) {
        if (path === '/api/v1/tickets') {
          capturedInit = init;
          return {
            data: {
              ticket: {
                ticket_no: 'tic_001',
                status: 'open'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-ticket',
    now: () => '2026-04-16T00:00:00.000Z'
  });

  const ticket = await api.createTicket({
    subject: '  公网带宽异常  ',
    content: '  请协助核查峰值突发计费  ',
    priority: 'high',
    category: '  billing  ',
    attachments: [
      {
        fileId: ' file_001 ',
        fileName: ' bandwidth.csv ',
        mimeType: ' text/csv ',
        size: 128.8
      },
      {
        fileId: 'file_001',
        fileName: 'duplicate.csv',
        mimeType: 'text/plain',
        size: 64
      }
    ]
  });

  assert.equal(ticket.ticketNo, 'tic_001');
  assert.equal(ticket.subject, '公网带宽异常');
  assert.equal(ticket.content, '请协助核查峰值突发计费');
  assert.equal(ticket.category, 'billing');
  assert.equal(ticket.attachments.length, 1);
  assert.equal(ticket.attachments[0].fileId, 'file_001');
  assert.equal(ticket.attachments[0].fileName, 'bandwidth.csv');
  assert.equal(ticket.attachments[0].mimeType, 'text/csv');
  assert.equal(ticket.attachments[0].size, 128);
  assert.equal(ticket.createdAt, '2026-04-16T00:00:00.000Z');

  const headers = capturedInit.headers;
  assert.equal(headers['Idempotency-Key'], 'idem-ticket');
  assert.deepEqual(JSON.parse(capturedInit.body), {
    subject: '公网带宽异常',
    content: '请协助核查峰值突发计费',
    priority: 'high',
    category: 'billing',
    attachments: [
      {
        file_id: 'file_001'
      }
    ]
  });
});

test('createServiceDeskApi remembers newly created ICP applications', async () => {
  let rememberedApplication = null;
  let capturedInit = null;

  const api = createServiceDeskApi({
    client: {
      async request(path, init) {
        assert.equal(path, '/api/v1/icp/applications');
        capturedInit = init;
        return {
          data: {
            application: {
              application_no: 'ICP20260416001',
              status: 'submitted',
              current_step: 'waiting_review'
            }
          }
        };
      }
    },
    createIdempotencyKey: () => 'idem-icp',
    icpTrackingStore: {
      list: () => [],
      remember: (applicationNo) => {
        rememberedApplication = applicationNo;
      }
    },
    now: () => '2026-04-16T00:00:00.000Z'
  });

  const application = await api.createIcpApplication({
    subjectType: 'enterprise',
    domain: '  llm-demo.smartcloud.local  ',
    websiteName: '  SmartCloud 模型体验站  ',
    contacts: [' 李雷 138****0001 ', ' ', '李雷 138****0001'],
    materials: [
      {
        fileId: ' file_business_license_001 ',
        fileName: ' business-license.pdf ',
        type: ' business_license ',
        status: 'verified',
        required: true
      },
      {
        fileId: 'file_business_license_001',
        fileName: 'duplicate.pdf',
        type: 'business_license',
        status: 'uploaded',
        required: true
      }
    ]
  });

  assert.equal(application.applicationNo, 'ICP20260416001');
  assert.equal(application.domain, 'llm-demo.smartcloud.local');
  assert.equal(application.websiteName, 'SmartCloud 模型体验站');
  assert.deepEqual(application.contacts, ['李雷 138****0001']);
  assert.equal(application.materials.length, 1);
  assert.equal(application.materials[0].fileId, 'file_business_license_001');
  assert.equal(application.materials[0].fileName, 'business-license.pdf');
  assert.equal(application.materials[0].type, 'business_license');
  assert.equal(application.submittedAt, '2026-04-16T00:00:00.000Z');
  assert.equal(rememberedApplication, 'ICP20260416001');
  assert.deepEqual(JSON.parse(capturedInit.body), {
    subject_type: 'enterprise',
    domain: 'llm-demo.smartcloud.local',
    website_name: 'SmartCloud 模型体验站',
    contacts: ['李雷 138****0001'],
    materials: [
      {
        file_id: 'file_business_license_001',
        file_name: 'business-license.pdf',
        type: 'business_license',
        status: 'verified',
        required: true
      }
    ]
  });
});

test('shared detail adapters preserve requested identifiers and sparse citation fallback metadata', async () => {
  const serviceDeskApi = createServiceDeskApi({
    client: {
      async request(path) {
        if (path === '/api/v1/refunds/ref_sparse_001') {
          return {
            data: {
              refund: {
                order_no: 'ord_sparse_001',
                status: 'processing',
                requested_amount: '18.00',
                currency: 'CNY',
                created_at: '2026-04-16T00:00:00.000Z'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'unused'
  });

  const fileApi = createFileApi({
    client: {
      async request(path) {
        if (path === '/api/v1/files/file_sparse_001') {
          return {
            data: {
              file: {
                file_name: 'screenshot.png',
                size: 2048,
                mime_type: 'image/png'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'unused'
  });

  const citationApi = createCitationApi({
    client: {
      async request(path) {
        if (path === '/api/v1/citations/cite_sparse_001') {
          return {
            data: {
              citation: {
                title: '账单知识库',
                doc_id: 'doc_sparse_001',
                chunk_id: 'chunk_sparse_001'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    }
  });

  const refund = await serviceDeskApi.getRefundDetail('ref_sparse_001');
  const file = await fileApi.getFile('file_sparse_001');
  const citation = await citationApi.getCitationDetail('cite_sparse_001', {
    id: 'cite_sparse_001',
    sourceType: 'knowledge_base',
    snippet: '共享 SDK 回填的引用片段',
    versionNo: 'v3',
    score: 0.72
  });

  assert.equal(refund.refundNo, 'ref_sparse_001');
  assert.equal(file.fileId, 'file_sparse_001');
  assert.equal(file.fileName, 'screenshot.png');
  assert.equal(citation.id, 'cite_sparse_001');
  assert.equal(citation.sourceType, 'knowledge_base');
  assert.equal(citation.snippet, '共享 SDK 回填的引用片段');
  assert.equal(citation.versionNo, 'v3');
  assert.equal(citation.score, 0.72);
});

test('shared business adapters accept stricter surface-specific named resource aliases from live wrappers', async () => {
  const client = {
    async request(path) {
      if (path.startsWith('/api/v1/billing/details?')) {
        return {
          data: {
            billing_detail_page: {
              items: [
                {
                  statement_no: 'stmt_alias_001',
                  billing_cycle: '2026-04',
                  product_type: 'GPU 云服务器',
                  instance_id: 'ins_alias_001',
                  instance_name: 'gpu-alias-01',
                  amount: '256.00',
                  status: 'paid'
                }
              ],
              page: 1,
              page_size: 5,
              total: 1
            }
          }
        };
      }

      if (path === '/api/v1/orders/ord_alias_001') {
        return {
          data: {
            order_detail: {
              order: {
                order_no: 'ord_alias_001',
                product_type: 'GPU 云服务器',
                status: 'paid',
                amount: '599.00',
                created_at: '2026-04-16T00:00:00.000Z'
              },
              configuration_summary: ['GPU: 1 x 24GB']
            }
          }
        };
      }

      if (path === '/api/v1/refunds/ref_alias_001') {
        return {
          data: {
            refund_record: {
              refund_no: 'ref_alias_001',
              order_no: 'ord_alias_001',
              status: 'processing',
              requested_amount: '18.00',
              currency: 'CNY',
              created_at: '2026-04-16T01:00:00.000Z'
            }
          }
        };
      }

      if (path === '/api/v1/tickets/tic_alias_001') {
        return {
          data: {
            ticket_detail: {
              ticket: {
                ticket_no: 'tic_alias_001',
                subject: '别名包装测试',
                status: 'processing',
                category: 'billing',
                updated_at: '2026-04-16T02:00:00.000Z'
              },
              replies: [
                {
                  reply_no: 'reply_alias_001',
                  content: '已收到',
                  created_at: '2026-04-16T02:05:00.000Z',
                  operator_type: 'support'
                }
              ]
            }
          }
        };
      }

      if (path === '/api/v1/icp/materials/check') {
        return {
          data: {
            material_check_result: {
              passed: true,
              required_materials: ['business_license']
            }
          }
        };
      }

      if (path === '/api/v1/files/upload-policy') {
        return {
          data: {
            file_upload_policy: {
              file_id: 'file_alias_001',
              upload_url: 'https://upload.smartcloud.local/file_alias_001',
              form_fields: {
                key: 'uploads/file_alias_001/report.pdf'
              },
              object_key: 'uploads/file_alias_001/report.pdf',
              expire_at: '2026-04-16T03:00:00.000Z'
            }
          }
        };
      }

      if (path === '/api/v1/files/file_alias_001') {
        return {
          data: {
            file_record: {
              file_id: 'file_alias_001',
              file_name: 'report.pdf',
              size: 2048,
              mime_type: 'application/pdf'
            }
          }
        };
      }

      if (path === '/api/v1/citations/cite_alias_001') {
        return {
          data: {
            citation_detail: {
              citation_id: 'cite_alias_001',
              title: '账单说明',
              source_type: 'knowledge_base',
              doc_id: 'doc_alias_001',
              chunk_id: 'chunk_alias_001',
              snippet: '这是别名包装下的引用详情。'
            }
          }
        };
      }

      throw new Error(`unexpected path: ${path}`);
    }
  };

  const billingApi = createBillingApi({
    client,
    now: () => new Date('2026-04-16T00:00:00.000Z')
  });
  const serviceDeskApi = createServiceDeskApi({
    client,
    createIdempotencyKey: () => 'unused'
  });
  const fileApi = createFileApi({
    client,
    createIdempotencyKey: () => 'unused'
  });
  const citationApi = createCitationApi({ client });

  const billingDetails = await billingApi.listBillingDetails({ pageSize: 5 });
  const orderDetail = await serviceDeskApi.getOrderDetail('ord_alias_001');
  const refund = await serviceDeskApi.getRefundDetail('ref_alias_001');
  const ticketDetail = await serviceDeskApi.getTicketDetail('tic_alias_001');
  const icpCheck = await serviceDeskApi.checkIcpMaterials({
    subjectType: 'enterprise',
    materials: []
  });
  const uploadPolicy = await fileApi.getUploadPolicy({
    fileName: 'report.pdf',
    size: 2048,
    mimeType: 'application/pdf',
    bizType: 'research_export'
  });
  const file = await fileApi.getFile('file_alias_001');
  const citation = await citationApi.getCitationDetail('cite_alias_001');

  assert.equal(billingDetails.items[0].statementNo, 'stmt_alias_001');
  assert.equal(billingDetails.pageSize, 5);
  assert.equal(orderDetail.order.orderNo, 'ord_alias_001');
  assert.deepEqual(orderDetail.configurationSummary, ['GPU: 1 x 24GB']);
  assert.equal(refund.refundNo, 'ref_alias_001');
  assert.equal(ticketDetail.ticket.ticketNo, 'tic_alias_001');
  assert.equal(ticketDetail.replies[0].replyNo, 'reply_alias_001');
  assert.equal(icpCheck.passed, true);
  assert.deepEqual(icpCheck.requiredMaterials, ['business_license']);
  assert.equal(uploadPolicy.fileId, 'file_alias_001');
  assert.equal(uploadPolicy.formFields.key, 'uploads/file_alias_001/report.pdf');
  assert.equal(file.fileId, 'file_alias_001');
  assert.equal(file.fileName, 'report.pdf');
  assert.equal(citation.id, 'cite_alias_001');
  assert.equal(citation.snippet, '这是别名包装下的引用详情。');
});

test('createServiceDeskApi preserves tracked ICP identifiers when detail fallback payloads are sparse', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          throw new ApiError('list unavailable', 404, 'ORCH_AGENT_NOT_FOUND');
        }

        if (path === '/api/v1/icp/applications/ICP20260416088') {
          return {
            data: {
              application: {
                status: 'reviewing',
                current_step: 'operator_review',
                domain: 'tracked-fallback.smartcloud.local',
                website_name: 'Tracked Fallback',
                subject_type: 'enterprise',
                submitted_at: '2026-04-16T01:00:00.000Z'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'unused',
    icpTrackingStore: {
      list: () => ['ICP20260416088']
    }
  });

  const page = await api.listIcpApplicationPage();

  assert.equal(page.loadState.fallbackDomains?.includes('icp'), true);
  assert.equal(page.items[0].applicationNo, 'ICP20260416088');
  assert.equal(page.items[0].domain, 'tracked-fallback.smartcloud.local');
});

test('createServiceDeskApi prefers the live ICP list route and supplements missing tracked applications via detail fallback', async () => {
  const requestLog = [];

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        requestLog.push(path);

        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          return {
            items: [
              {
                application_no: 'ICP20260416001',
                status: 'reviewing',
                current_step: 'operator_review',
                domain: 'live.smartcloud.local',
                website_name: 'Live SmartCloud',
                subject_type: 'enterprise',
                submitted_at: '2026-04-16T01:00:00.000Z'
              }
            ],
            page: 1,
            page_size: 20,
            total: 1
          };
        }

        if (path === '/api/v1/icp/applications/ICP20260416077') {
          return {
            data: {
              application: {
                application_no: 'ICP20260416077',
                status: 'submitted',
                current_step: 'waiting_review',
                domain: 'tracked.smartcloud.local',
                website_name: 'Tracked SmartCloud',
                subject_type: 'enterprise',
                submitted_at: '2026-04-16T02:00:00.000Z'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-list',
    icpTrackingStore: {
      list: () => ['ICP20260416001', 'ICP20260416077']
    }
  });

  const applications = await api.listIcpApplications({ page: 1, pageSize: 20 });

  assert.deepEqual(
    applications.map((item) => item.applicationNo),
    ['ICP20260416077', 'ICP20260416001']
  );
  assert.deepEqual(requestLog, [
    '/api/v1/icp/applications?page=1&page_size=20',
    '/api/v1/icp/applications/ICP20260416077'
  ]);
});

test('createServiceDeskApi remembers ICP application ids learned from the live list route and reuses them during fallback', async () => {
  const trackedIds = [];
  let listCallCount = 0;

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          listCallCount += 1;

          if (listCallCount === 1) {
            return {
              items: [
                {
                  application_no: 'ICP20260416031',
                  status: 'reviewing',
                  current_step: 'operator_review',
                  domain: 'live-history.smartcloud.local',
                  website_name: 'Live History SmartCloud',
                  subject_type: 'enterprise',
                  submitted_at: '2026-04-16T03:00:00.000Z'
                }
              ],
              page: 1,
              page_size: 20,
              total: 1
            };
          }

          throw new Error('icp list temporarily unavailable');
        }

        if (path === '/api/v1/icp/applications/ICP20260416031') {
          return {
            data: {
              application: {
                application_no: 'ICP20260416031',
                status: 'approved',
                current_step: 'done',
                domain: 'live-history.smartcloud.local',
                website_name: 'Live History SmartCloud',
                subject_type: 'enterprise',
                approved_at: '2026-04-16T04:00:00.000Z'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-remember-live',
    icpTrackingStore: {
      list: () => [...trackedIds],
      remember: (applicationNo) => {
        if (!trackedIds.includes(applicationNo)) {
          trackedIds.push(applicationNo);
        }
      }
    }
  });

  const initialPage = await api.listIcpApplicationPage({ page: 1, pageSize: 20 });
  const fallbackPage = await api.listIcpApplicationPage({ page: 1, pageSize: 20 });

  assert.deepEqual(initialPage.items.map((item) => item.applicationNo), ['ICP20260416031']);
  assert.deepEqual(trackedIds, ['ICP20260416031']);
  assert.deepEqual(fallbackPage.items.map((item) => item.applicationNo), ['ICP20260416031']);
  assert.equal(fallbackPage.items[0].status, 'approved');
  assert.equal(fallbackPage.loadState.degraded, false);
  assert.deepEqual(fallbackPage.loadState.failedDomains, []);
  assert.deepEqual(fallbackPage.loadState.fallbackDomains, ['icp']);
});

test('createServiceDeskApi keeps successful later ICP pages backend-shaped instead of supplementing tracked history into them', async () => {
  const requestLog = [];

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        requestLog.push(path);

        if (path === '/api/v1/icp/applications?page=2&page_size=1') {
          return {
            items: [
              {
                application_no: 'ICP20260416022',
                status: 'submitted',
                current_step: 'waiting_review',
                domain: 'live-page-two.smartcloud.local',
                website_name: 'Live Page Two',
                subject_type: 'enterprise',
                submitted_at: '2026-04-16T02:00:00.000Z'
              }
            ],
            page: 2,
            page_size: 1,
            total: 3
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-live-page-two',
    icpTrackingStore: {
      list: () => ['ICP20260416009', 'ICP20260416022', 'ICP20260416033']
    }
  });

  const page = await api.listIcpApplicationPage({ page: 2, pageSize: 1 });

  assert.deepEqual(page.items.map((item) => item.applicationNo), ['ICP20260416022']);
  assert.equal(page.page, 2);
  assert.equal(page.pageSize, 1);
  assert.equal(page.total, 3);
  assert.equal(page.totalPages, 3);
  assert.equal(page.loadState.degraded, false);
  assert.deepEqual(page.loadState.failedDomains, []);
  assert.deepEqual(page.loadState.fallbackDomains, []);
  assert.deepEqual(requestLog, ['/api/v1/icp/applications?page=2&page_size=1']);
});

test('createServiceDeskApi paginates tracked ICP fallback results with the requested shared page contract', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path === '/api/v1/icp/applications?page=2&page_size=1') {
          throw new ApiError('icp list unavailable', 404, 'ICP_LIST_ROUTE_MISSING');
        }

        if (path === '/api/v1/icp/applications/ICP20260416011') {
          return {
            application_no: 'ICP20260416011',
            status: 'reviewing',
            current_step: 'operator_review',
            domain: 'tracked-1.smartcloud.local',
            website_name: 'Tracked One',
            subject_type: 'enterprise',
            submitted_at: '2026-04-16T01:00:00.000Z'
          };
        }

        if (path === '/api/v1/icp/applications/ICP20260416022') {
          return {
            application_no: 'ICP20260416022',
            status: 'submitted',
            current_step: 'waiting_review',
            domain: 'tracked-2.smartcloud.local',
            website_name: 'Tracked Two',
            subject_type: 'enterprise',
            submitted_at: '2026-04-16T03:00:00.000Z'
          };
        }

        if (path === '/api/v1/icp/applications/ICP20260416033') {
          return {
            application_no: 'ICP20260416033',
            status: 'approved',
            current_step: 'done',
            domain: 'tracked-3.smartcloud.local',
            website_name: 'Tracked Three',
            subject_type: 'enterprise',
            approved_at: '2026-04-16T02:00:00.000Z'
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-pagination-fallback',
    icpTrackingStore: {
      list: () => ['ICP20260416011', 'ICP20260416022', 'ICP20260416033']
    }
  });

  const page = await api.listIcpApplicationPage({ page: 2, pageSize: 1 });

  assert.deepEqual(page.items.map((item) => item.applicationNo), ['ICP20260416033']);
  assert.equal(page.page, 2);
  assert.equal(page.pageSize, 1);
  assert.equal(page.total, 3);
  assert.equal(page.totalPages, 3);
  assert.equal(page.loadState.degraded, false);
  assert.deepEqual(page.loadState.failedDomains, []);
  assert.deepEqual(page.loadState.fallbackDomains, ['icp']);
});

test('createServiceDeskApi treats structured ICP list rate limits as degradable fallback failures', async () => {
  const requestLog = [];

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        requestLog.push(path);

        if (path === '/api/v1/icp/applications?page=1&page_size=2') {
          throw new ApiError('rate limited', 429, 'RATE_LIMITED', undefined, 'req-icp-rate', 2500);
        }

        if (path === '/api/v1/icp/applications/ICP20260416101') {
          return {
            data: {
              application: {
                application_no: 'ICP20260416101',
                status: 'reviewing',
                current_step: 'operator_review',
                domain: 'tracked-rate-limit.smartcloud.local',
                website_name: 'Tracked Rate Limit',
                subject_type: 'enterprise',
                submitted_at: '2026-04-16T04:00:00.000Z'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-rate-limit',
    icpTrackingStore: {
      list: () => ['ICP20260416101']
    }
  });

  const page = await api.listIcpApplicationPage({ page: 1, pageSize: 2 });

  assert.deepEqual(requestLog, [
    '/api/v1/icp/applications?page=1&page_size=2',
    '/api/v1/icp/applications/ICP20260416101'
  ]);
  assert.deepEqual(page.items.map((item) => item.applicationNo), ['ICP20260416101']);
  assert.equal(page.page, 1);
  assert.equal(page.pageSize, 2);
  assert.equal(page.total, 1);
  assert.equal(page.totalPages, 1);
  assert.equal(page.loadState.degraded, false);
  assert.deepEqual(page.loadState.failedDomains, []);
  assert.deepEqual(page.loadState.fallbackDomains, ['icp']);
  assert.deepEqual(page.loadState.domainErrors?.icp, {
    kind: 'rate_limited',
    message: 'rate limited (request id: req-icp-rate)',
    status: 429,
    code: 'RATE_LIMITED',
    requestId: 'req-icp-rate',
    retryAfterMs: 2500
  });
});

test('createServiceDeskApi surfaces degraded ICP list metadata when the live route fails without tracked fallback data', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path === '/api/v1/icp/applications?page=2&page_size=5') {
          throw new Error('icp list unavailable');
        }

        if (path.startsWith('/api/v1/orders')) {
          return { items: [], page: 1, page_size: 10, total: 0 };
        }

        if (path.startsWith('/api/v1/refunds')) {
          return { items: [], page: 1, page_size: 10, total: 0 };
        }

        if (path.startsWith('/api/v1/tickets')) {
          return { items: [], page: 1, page_size: 10, total: 0 };
        }

        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          throw new Error('icp list unavailable');
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-empty-fallback',
    icpTrackingStore: {
      list: () => []
    }
  });

  const page = await api.listIcpApplicationPage({ page: 2, pageSize: 5 });
  const workspace = await api.getWorkspace();

  assert.deepEqual(page.items, []);
  assert.equal(page.page, 2);
  assert.equal(page.pageSize, 5);
  assert.equal(page.total, 0);
  assert.equal(page.totalPages, 0);
  assert.equal(page.loadState.degraded, true);
  assert.deepEqual(page.loadState.failedDomains, ['icp']);
  assert.deepEqual(page.loadState.fallbackDomains, []);
  assert.equal(workspace.loadState.degraded, true);
  assert.deepEqual(workspace.loadState.failedDomains, ['icp']);
  assert.deepEqual(workspace.loadState.fallbackDomains, []);
});

test('createOrderApi, createTicketApi, createIcpApi, and createWebUserBusinessApis expose reusable shared surface adapters', async () => {
  const requestLog = [];
  let rememberedApplication = null;
  const client = {
    async request(path, init) {
      requestLog.push({ path, init });

      if (path.startsWith('/api/v1/billing/details')) {
        return {
          items: []
        };
      }

      if (path === '/api/v1/orders?page=1&page_size=1') {
        return {
          items: [
            {
              order_no: 'ord_suite_001',
              product_type: 'GPU 云服务器',
              status: 'paid',
              amount: '599.00',
              created_at: '2026-04-16T00:00:00.000Z'
            }
          ]
        };
      }

      if (path === '/api/v1/tickets?page=1&page_size=1') {
        return {
          items: [
            {
              ticket_no: 'tic_suite_001',
              subject: 'Shared ticket suite',
              status: 'processing',
              category: 'billing',
              updated_at: '2026-04-16T00:30:00.000Z'
            }
          ]
        };
      }

      if (path === '/api/v1/files/upload-policy') {
        return {
          file_id: 'file_suite_001',
          upload_url: 'https://upload.smartcloud.local/file_suite_001',
          object_key: 'uploads/file_suite_001/demo.txt',
          expire_at: '2026-04-16T10:00:00.000Z'
        };
      }

      if (path === '/api/v1/icp/applications') {
        return {
          data: {
            application: {
              application_no: 'ICP20260416111',
              status: 'submitted',
              current_step: 'waiting_review'
            }
          }
        };
      }

      if (path === '/api/v1/citations/cite_suite_001') {
        return {
          citation_id: 'cite_suite_001',
          title: 'Shared Suite Citation',
          source_type: 'knowledge_base',
          doc_id: 'doc_suite_001',
          chunk_id: 'chunk_suite_001',
          snippet: 'suite citation preview'
        };
      }

      throw new Error(`unexpected path: ${path}`);
    }
  };
  const orderApi = createOrderApi({
    client,
    createIdempotencyKey: () => 'idem-order-wrapper'
  });
  const ticketApi = createTicketApi({
    client,
    createIdempotencyKey: () => 'idem-ticket-wrapper'
  });
  const icpApi = createIcpApi({
    client,
    createIdempotencyKey: () => 'idem-icp-wrapper',
    icpTrackingStore: {
      list: () => [],
      remember: (applicationNo) => {
        rememberedApplication = applicationNo;
      }
    }
  });

  const apis = createWebUserBusinessApis({
    client,
    createIdempotencyKey: (scope) => `idem:${scope}`,
    icpTrackingStore: {
      list: () => [],
      remember: (applicationNo) => {
        rememberedApplication = applicationNo;
      }
    },
    now: () => '2026-04-16T00:00:00.000Z',
    billingNow: () => new Date('2026-04-16T00:00:00.000Z')
  });

  const detailPage = await apis.billing.listBillingDetails({
    page: 1,
    pageSize: 1
  });
  const orderPage = await orderApi.listOrders({
    page: 1,
    pageSize: 1
  });
  const ticketPage = await ticketApi.listTickets({
    page: 1,
    pageSize: 1
  });
  const policy = await apis.files.getUploadPolicy({
    fileName: 'demo.txt',
    size: 128,
    mimeType: 'text/plain',
    bizType: 'chat_attachment'
  });
  const application = await icpApi.createIcpApplication({
    subjectType: 'enterprise',
    domain: 'suite.smartcloud.local',
    websiteName: 'Shared Suite Demo',
    contacts: ['李雷 138****0001'],
    materials: []
  });
  const citation = await apis.citations.getCitationDetail('cite_suite_001');

  assert.deepEqual(detailPage.items, []);
  assert.equal(orderPage.items[0].orderNo, 'ord_suite_001');
  assert.equal(ticketPage.items[0].ticketNo, 'tic_suite_001');
  assert.match(requestLog[0].path, /billing_cycle=2026-04/);
  assert.equal(requestLog[3].init.headers['Idempotency-Key'], 'idem:file-upload-policy');
  assert.equal(requestLog[4].init.headers['Idempotency-Key'], 'idem-icp-wrapper');
  assert.equal(policy.fileId, 'file_suite_001');
  assert.equal(application.applicationNo, 'ICP20260416111');
  assert.equal(rememberedApplication, 'ICP20260416111');
  assert.equal(citation.id, 'cite_suite_001');
  assert.equal(typeof apis.orders.getOrderDetail, 'function');
  assert.equal(typeof apis.tickets.replyTicket, 'function');
  assert.equal(typeof apis.icp.listIcpApplicationPage, 'function');
});

test('createServiceDeskApi preserves reply and refund fallback fields when mutation responses use wrapped resources', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path === '/api/v1/tickets/tic_001/replies') {
          return {
            success: true,
            data: {
              reply: {
                reply_no: 'reply_001',
                status: 'processing'
              }
            }
          };
        }

        if (path === '/api/v1/tickets/tic_001') {
          throw new Error('detail endpoint still catching up');
        }

        if (path === '/api/v1/orders/ord_001/refunds') {
          return {
            code: 0,
            message: 'ok',
            request_id: 'req-refund-create',
            timestamp: 1776297600000,
            data: {
              refund: {
                refund_no: 'ref_001',
                status: 'approved'
              }
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-mutation',
    now: () => '2026-04-16T00:00:00.000Z'
  });

  const reply = await api.replyTicket('tic_001', {
    content: '已补充监控截图，请继续核查。',
    attachments: [
      {
        fileId: 'file_reply_001',
        fileName: 'monitoring.png',
        mimeType: 'image/png',
        size: 512
      }
    ]
  });
  const refund = await api.createRefund({
    orderNo: 'ord_001',
    reason: '重复扣费',
    amount: '18.00',
    attachments: [
      {
        fileId: 'file_refund_001',
        fileName: 'refund-proof.pdf',
        mimeType: 'application/pdf',
        size: 256
      }
    ]
  });

  assert.equal(reply.replyNo, 'reply_001');
  assert.equal(reply.content, '已补充监控截图，请继续核查。');
  assert.equal(reply.operatorType, 'user');
  assert.equal(reply.status, 'processing');
  assert.equal(reply.attachments[0].fileId, 'file_reply_001');
  assert.equal(reply.createdAt, '2026-04-16T00:00:00.000Z');

  assert.equal(refund.refundNo, 'ref_001');
  assert.equal(refund.orderNo, 'ord_001');
  assert.equal(refund.requestedAmount, '18.00');
  assert.equal(refund.timeline[0].status, 'approved');
  assert.equal(refund.timeline[0].note, '重复扣费');
  assert.equal(refund.timeline[0].operatorType, 'user');
});

test('createServiceDeskApi normalizes direct list payloads in the shared workspace adapter', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          return [
            {
              order_no: 'ord_002',
              product_type: '对象存储',
              status: 'paid',
              amount: '199.00',
              created_at: '2026-04-16T00:00:00.000Z'
            }
          ];
        }

        if (path.startsWith('/api/v1/refunds')) {
          return [
            {
              refund_no: 'ref_002',
              order_no: 'ord_002',
              status: 'pending_review',
              requested_amount: '29.00',
              currency: 'CNY',
              created_at: '2026-04-16T01:00:00.000Z'
            }
          ];
        }

        if (path.startsWith('/api/v1/tickets')) {
          return [
            {
              ticket_no: 'tic_002',
              subject: '对象存储账单咨询',
              status: 'unknown_remote_status',
              category: 'billing',
              updated_at: '2026-04-16T02:00:00.000Z'
            }
          ];
        }

        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          return {
            items: [],
            page: 1,
            page_size: 20,
            total: 0
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-workspace',
    icpTrackingStore: {
      list: () => []
    }
  });

  const workspace = await api.getWorkspace();

  assert.equal(workspace.orders[0].orderNo, 'ord_002');
  assert.equal(workspace.refunds[0].refundNo, 'ref_002');
  assert.equal(workspace.tickets[0].ticketNo, 'tic_002');
  assert.equal(workspace.tickets[0].status, 'open');
  assert.equal(workspace.loadState?.degraded, false);
  assert.deepEqual(workspace.loadState?.failedDomains, []);
});

test('createServiceDeskApi falls back to tracked ICP detail history when the live list route is unavailable', async () => {
  const requestLog = [];

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        requestLog.push(path);

        if (path.startsWith('/api/v1/orders')) {
          return { items: [] };
        }

        if (path.startsWith('/api/v1/refunds')) {
          return { items: [] };
        }

        if (path.startsWith('/api/v1/tickets')) {
          return { items: [] };
        }

        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          throw new ApiError('icp list unavailable', 404, 'ICP_LIST_ROUTE_MISSING');
        }

        if (path === '/api/v1/icp/applications/ICP20260416088') {
          return {
            application_no: 'ICP20260416088',
            status: 'reviewing',
            current_step: 'operator_review',
            domain: 'fallback.smartcloud.local',
            website_name: 'Fallback SmartCloud',
            subject_type: 'enterprise',
            submitted_at: '2026-04-16T03:00:00.000Z'
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-fallback',
    icpTrackingStore: {
      list: () => ['ICP20260416088']
    }
  });

  const workspace = await api.getWorkspace();

  assert.deepEqual(
    requestLog,
    [
      '/api/v1/orders?page=1&page_size=10',
      '/api/v1/refunds?page=1&page_size=10',
      '/api/v1/tickets?page=1&page_size=10',
      '/api/v1/icp/applications?page=1&page_size=20',
      '/api/v1/icp/applications/ICP20260416088'
    ]
  );
  assert.equal(workspace.icpApplications[0].applicationNo, 'ICP20260416088');
  assert.equal(workspace.loadState?.degraded, false);
  assert.deepEqual(workspace.loadState?.failedDomains, []);
  assert.deepEqual(workspace.loadState?.fallbackDomains, ['icp']);
});

test('createServiceDeskApi does not bypass structured ICP list permission failures with tracked fallback', async () => {
  let detailRequests = 0;

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          return { items: [] };
        }

        if (path.startsWith('/api/v1/refunds')) {
          return { items: [] };
        }

        if (path.startsWith('/api/v1/tickets')) {
          return { items: [] };
        }

        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          throw new ApiError('forbidden', 403, 'TOOL_HUB_CALLER_FORBIDDEN');
        }

        if (path.startsWith('/api/v1/icp/applications/')) {
          detailRequests += 1;
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-icp-forbidden',
    icpTrackingStore: {
      list: () => ['ICP20260416099']
    }
  });

  const workspace = await api.getWorkspace();

  assert.equal(detailRequests, 0);
  assert.equal(workspace.loadState?.degraded, true);
  assert.deepEqual(workspace.loadState?.failedDomains, ['icp']);
  assert.deepEqual(workspace.loadState?.fallbackDomains, []);
  assert.deepEqual(workspace.loadState?.domainErrors?.icp, {
    kind: 'forbidden',
    message: 'forbidden',
    status: 403,
    code: 'TOOL_HUB_CALLER_FORBIDDEN',
    requestId: undefined,
    retryAfterMs: undefined
  });
});

test('shared workspace mapper accepts normalized shared DTO arrays plus wrapped ICP resources', () => {
  const workspace = mapServiceWorkspaceData({
    orders: [
      {
        orderNo: 'ord_shared_001',
        productType: '对象存储',
        status: 'paid',
        amount: '199.00',
        createdAt: '2026-04-16T00:00:00.000Z',
        eligibleForRefund: true
      }
    ],
    refunds: [
      {
        refundNo: 'ref_shared_001',
        orderNo: 'ord_shared_001',
        status: 'pending_review',
        requestedAmount: '29.00',
        currency: 'CNY',
        createdAt: '2026-04-16T01:00:00.000Z',
        timeline: []
      }
    ],
    tickets: [
      {
        ticketNo: 'tic_shared_001',
        subject: '共享 DTO 工单',
        status: 'processing',
        category: 'billing',
        updatedAt: '2026-04-16T02:00:00.000Z'
      }
    ],
    icpApplications: [
      {
        data: {
          application: {
            application_no: 'ICP20260416999',
            status: 'reviewing',
            current_step: 'operator_review',
            domain: 'shared.smartcloud.local',
            website_name: 'Shared Workspace Demo',
            subject_type: 'enterprise'
          }
        }
      }
    ]
  });

  assert.equal(workspace.orders[0].orderNo, 'ord_shared_001');
  assert.equal(workspace.orders[0].eligibleForRefund, true);
  assert.equal(workspace.refunds[0].refundNo, 'ref_shared_001');
  assert.equal(workspace.tickets[0].ticketNo, 'tic_shared_001');
  assert.equal(workspace.icpApplications[0].applicationNo, 'ICP20260416999');
  assert.equal(workspace.loadState?.degraded, false);
  assert.deepEqual(workspace.loadState?.failedDomains, []);
});

test('createServiceDeskApi marks the shared workspace degraded when only part of the aggregate loads', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          return {
            items: [
              {
                order_no: 'ord_partial_001',
                product_type: '对象存储',
                status: 'paid',
                amount: '199.00',
                created_at: '2026-04-16T00:00:00.000Z'
              }
            ]
          };
        }

        if (path.startsWith('/api/v1/refunds')) {
          throw new Error('refunds unavailable');
        }

        if (path.startsWith('/api/v1/tickets')) {
          return {
            items: [
              {
                ticket_no: 'tic_partial_001',
                subject: '对象存储工单',
                status: 'processing',
                category: 'order',
                updated_at: '2026-04-16T02:00:00.000Z'
              }
            ]
          };
        }

        if (path.startsWith('/api/v1/icp/applications/')) {
          throw new Error('icp unavailable');
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-workspace-partial',
    icpTrackingStore: {
      list: () => ['ICP20260416088']
    }
  });

  const workspace = await api.getWorkspace();

  assert.equal(workspace.orders[0].orderNo, 'ord_partial_001');
  assert.equal(workspace.tickets[0].ticketNo, 'tic_partial_001');
  assert.deepEqual(workspace.refunds, []);
  assert.deepEqual(workspace.icpApplications, []);
  assert.equal(workspace.loadState?.degraded, true);
  assert.deepEqual(workspace.loadState?.failedDomains, ['refunds', 'icp']);
});

test('createServiceDeskApi preserves structured 401/409/429 domain errors across partial workspace failures', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          throw new ApiError('session expired', 401, 'AUTH_UNAUTHORIZED', undefined, 'req-workspace-401');
        }

        if (path.startsWith('/api/v1/refunds')) {
          throw new ApiError(
            'refund still processing',
            409,
            'CHAT_CONVERSATION_RUNNING',
            {
              error_detail: {
                missing_fields: ['refund_no']
              }
            },
            'req-workspace-409'
          );
        }

        if (path.startsWith('/api/v1/tickets')) {
          throw new ApiError('slow down', 429, 'RATE_LIMITED', undefined, 'req-workspace-429', 2200);
        }

        if (path === '/api/v1/icp/applications?page=1&page_size=20') {
          return {
            items: [],
            page: 1,
            page_size: 20,
            total: 0
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-workspace-structured'
  });

  const workspace = await api.getWorkspace();

  assert.deepEqual(workspace.orders, []);
  assert.deepEqual(workspace.refunds, []);
  assert.deepEqual(workspace.tickets, []);
  assert.deepEqual(workspace.icpApplications, []);
  assert.equal(workspace.loadState?.degraded, true);
  assert.deepEqual(workspace.loadState?.failedDomains, ['orders', 'refunds', 'tickets']);
  assert.deepEqual(workspace.loadState?.fallbackDomains, []);
  assert.deepEqual(workspace.loadState?.domainErrors?.orders, {
    kind: 'unauthorized',
    message: 'session expired (request id: req-workspace-401)',
    status: 401,
    code: 'AUTH_UNAUTHORIZED',
    requestId: 'req-workspace-401',
    retryAfterMs: undefined
  });
  assert.deepEqual(workspace.loadState?.domainErrors?.refunds, {
    kind: 'conflict',
    message: 'refund still processing (request id: req-workspace-409)',
    status: 409,
    code: 'CHAT_CONVERSATION_RUNNING',
    requestId: 'req-workspace-409',
    retryAfterMs: undefined,
    details: {
      missingFields: ['refund_no'],
      requiredPermissions: [],
      missingAuthContext: []
    }
  });
  assert.deepEqual(workspace.loadState?.domainErrors?.tickets, {
    kind: 'rate_limited',
    message: 'slow down (request id: req-workspace-429)',
    status: 429,
    code: 'RATE_LIMITED',
    requestId: 'req-workspace-429',
    retryAfterMs: 2200
  });
});

test('createServiceDeskApi throws when every workspace domain fails instead of silently returning empty data', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          throw new Error('orders unavailable');
        }

        if (path.startsWith('/api/v1/refunds')) {
          throw new Error('refunds unavailable');
        }

        if (path.startsWith('/api/v1/tickets')) {
          throw new Error('tickets unavailable');
        }

        if (path.startsWith('/api/v1/icp/applications/')) {
          throw new Error('icp unavailable');
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-workspace-failed',
    icpTrackingStore: {
      list: () => ['ICP20260416099']
    }
  });

  await assert.rejects(api.getWorkspace(), /orders unavailable/);
});

test('createBillingApi clamps invalid shared page inputs and malformed billing cycles before transport', async () => {
  const requestedPaths = [];

  const api = createBillingApi({
    client: {
      async request(path) {
        requestedPaths.push(path);
        return { items: [] };
      }
    },
    now: () => new Date('2026-04-16T00:00:00.000Z')
  });

  await api.listBillingDetails({
    page: 0,
    pageSize: -5,
    billingCycle: '2026/04'
  });
  await api.listInvoices({
    page: Number.NaN,
    pageSize: 0
  });

  assert.equal(requestedPaths[0], '/api/v1/billing/details?page=1&page_size=10&billing_cycle=2026-04');
  assert.equal(requestedPaths[1], '/api/v1/billing/invoices?page=1&page_size=10');
});

test('shared business page adapters normalize alias list contracts and preserve pagination metadata', async () => {
  const billingApi = createBillingApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/billing/details')) {
          assert.match(path, /billing_cycle=2026-04/);
          assert.match(path, /page=2/);
          assert.match(path, /page_size=1/);
          return {
            records: [
              {
                statement_no: 'stmt_002',
                billing_cycle: '2026-04',
                product_type: 'GPU 云服务器',
                instance_id: 'ins_002',
                instance_name: 'gpu-02',
                amount: '88.00',
                status: 'paid'
              }
            ],
            total: '4',
            page: '2',
            pageSize: '1',
            totalPages: '4',
            sortOrder: 'DESC'
          };
        }

        if (path.startsWith('/api/v1/billing/invoices')) {
          return {
            data: {
              list: [
                {
                  invoice_no: 'inv_page_001',
                  status: 'issued',
                  amount: '88.00',
                  billing_cycle: '2026-04',
                  title: 'SmartCloud'
                }
              ],
              total: 1,
              page: 1,
              page_size: 1
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    now: () => new Date('2026-04-16T00:00:00.000Z')
  });

  const detailPage = await billingApi.listBillingDetails({
    page: 2,
    pageSize: 1
  });
  const invoicePage = await billingApi.listInvoices({
    page: 1,
    pageSize: 1
  });

  assert.equal(detailPage.items[0].statementNo, 'stmt_002');
  assert.equal(detailPage.page, 2);
  assert.equal(detailPage.pageSize, 1);
  assert.equal(detailPage.total, 4);
  assert.equal(detailPage.totalPages, 4);
  assert.equal(detailPage.sortOrder, 'desc');
  assert.equal(invoicePage.items[0].invoiceNo, 'inv_page_001');
  assert.equal(invoicePage.total, 1);
});

test('shared business page adapters honor ApiEnvelope meta pagination for billing detail arrays', async () => {
  const billingApi = createBillingApi({
    client: {
      async request(path) {
        assert.match(path, /page=3/);
        assert.match(path, /page_size=1/);

        return {
          success: true,
          data: [
            {
              statement_no: 'stmt_meta_001',
              billing_cycle: '2026-04',
              product_type: '对象存储',
              instance_id: 'ins_meta_001',
              instance_name: 'oss-meta-001',
              amount: '66.00',
              status: 'paid'
            }
          ],
          meta: {
            pagination: {
              page: '3',
              pageSize: '1',
              total: '6',
              total_pages: '6',
              sort_order: 'asc'
            }
          }
        };
      }
    },
    now: () => new Date('2026-04-16T00:00:00.000Z')
  });

  const detailPage = await billingApi.listBillingDetails({
    page: 3,
    pageSize: 1
  });

  assert.equal(detailPage.items[0].statementNo, 'stmt_meta_001');
  assert.equal(detailPage.page, 3);
  assert.equal(detailPage.pageSize, 1);
  assert.equal(detailPage.total, 6);
  assert.equal(detailPage.totalPages, 6);
  assert.equal(detailPage.sortOrder, 'asc');
});

test('createServiceDeskApi exposes shared order/refund/ticket page adapters for strict reuse', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          return {
            records: [
              {
                order_no: 'ord_page_001',
                product_type: '对象存储',
                status: 'paid',
                amount: '199.00',
                created_at: '2026-04-16T00:00:00.000Z'
              }
            ],
            total: 3,
            page: 2,
            page_size: 1
          };
        }

        if (path.startsWith('/api/v1/refunds')) {
          return {
            results: [
              {
                refund_no: 'ref_page_001',
                order_no: 'ord_page_001',
                status: 'pending_review',
                requested_amount: '29.00',
                currency: 'CNY',
                created_at: '2026-04-16T01:00:00.000Z'
              }
            ],
            total: 1,
            page: 1,
            page_size: 1
          };
        }

        if (path.startsWith('/api/v1/tickets')) {
          return {
            data: {
              list: [
                {
                  ticket_no: 'tic_page_001',
                  subject: '订单计费咨询',
                  status: 'processing',
                  category: 'order',
                  updated_at: '2026-04-16T02:00:00.000Z'
                }
              ],
              total: 1,
              page: 1,
              pageSize: 1
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-pages',
    icpTrackingStore: {
      list: () => []
    }
  });

  const orderPage = await api.listOrders({ page: 2, pageSize: 1 });
  const refundPage = await api.listRefunds({ page: 1, pageSize: 1 });
  const ticketPage = await api.listTickets({ page: 1, pageSize: 1 });

  assert.equal(orderPage.items[0].orderNo, 'ord_page_001');
  assert.equal(orderPage.page, 2);
  assert.equal(orderPage.total, 3);
  assert.equal(refundPage.items[0].refundNo, 'ref_page_001');
  assert.equal(ticketPage.items[0].ticketNo, 'tic_page_001');
  assert.equal(ticketPage.pageSize, 1);
});

test('createServiceDeskApi reads ticket pagination metadata from shared envelope meta', async () => {
  const api = createServiceDeskApi({
    client: {
      async request(path) {
        if (path.startsWith('/api/v1/orders')) {
          return {
            items: []
          };
        }

        if (path.startsWith('/api/v1/refunds')) {
          return {
            items: []
          };
        }

        if (path.startsWith('/api/v1/tickets')) {
          return {
            success: true,
            data: {
              list: [
                {
                  ticket_no: 'tic_meta_001',
                  subject: '共享分页元数据工单',
                  status: 'processing',
                  category: 'billing',
                  updated_at: '2026-04-16T02:00:00.000Z'
                }
              ]
            },
            meta: {
              page: '2',
              page_size: '1',
              total: '9',
              totalPages: '9',
              sortBy: 'updated_at',
              sort_order: 'DESC'
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-ticket-meta',
    icpTrackingStore: {
      list: () => []
    }
  });

  const ticketPage = await api.listTickets({ page: 2, pageSize: 1 });

  assert.equal(ticketPage.items[0].ticketNo, 'tic_meta_001');
  assert.equal(ticketPage.page, 2);
  assert.equal(ticketPage.pageSize, 1);
  assert.equal(ticketPage.total, 9);
  assert.equal(ticketPage.totalPages, 9);
  assert.equal(ticketPage.sortBy, 'updated_at');
  assert.equal(ticketPage.sortOrder, 'desc');
});
test('shared business mappers clamp invalid owned-business enum payloads to safe defaults', () => {
  const application = mapIcpApplication({
    application_no: 'ICP20260416009',
    status: 'unexpected_status',
    current_step: 'precheck',
    domain: 'demo.smartcloud.local',
    website_name: 'SmartCloud Demo',
    subject_type: 'corporate',
    materials: [
      {
        file_name: 'business-license.pdf',
        type: 'business_license',
        status: 'not_a_real_status',
        required: true
      }
    ]
  });
  const materialCheck = mapIcpMaterialCheckResult({
    passed: false,
    issues: [
      {
        field: 'business_license',
        severity: 'critical',
        message: 'invalid severity should fall back'
      }
    ]
  });
  const refund = mapRefundRecord({
    refund_no: 'ref_invalid',
    order_no: 'ord_invalid',
    status: 'not_a_real_status',
    requested_amount: '18.00',
    currency: 'CNY',
    created_at: '2026-04-16T00:00:00.000Z',
    timeline: [
      {
        status: 'wrong',
        at: '2026-04-16T00:05:00.000Z',
        operator_type: 'robot',
        note: 'invalid operator'
      }
    ]
  });
  const ticketDetail = mapTicketDetail({
    ticket_no: 'tic_invalid',
    subject: '异常工单',
    status: 'not_a_real_status',
    category: 'billing',
    updated_at: '2026-04-16T00:10:00.000Z',
    replies: [
      {
        reply_no: 'reply_invalid',
        content: 'invalid reply enum',
        created_at: '2026-04-16T00:11:00.000Z',
        operator_type: 'robot',
        status: 'not_a_real_status'
      }
    ]
  });

  assert.equal(application.status, 'submitted');
  assert.equal(application.subjectType, 'enterprise');
  assert.equal(application.materials[0].status, 'prepared');
  assert.equal(materialCheck.issues[0].severity, 'warning');
  assert.equal(refund.status, 'pending_review');
  assert.equal(refund.timeline[0].status, 'pending_review');
  assert.equal(refund.timeline[0].operatorType, 'system');
  assert.equal(ticketDetail.ticket.status, 'open');
  assert.equal(ticketDetail.replies[0].operatorType, 'user');
  assert.equal(ticketDetail.replies[0].status, undefined);
});

test('createFileApi and createCitationApi normalize owned frontend business contracts', async () => {
  const requestLog = [];

  const client = {
    async request(path, init) {
      requestLog.push({ path, init });

      if (path === '/api/v1/files/upload-policy') {
        return {
          file_id: 'file_001',
          upload_url: 'https://upload.smartcloud.local/file_001',
          form_fields: {
            policy: 'policy-001',
            max_size: 2048,
            secure: true
          },
          object_key: 'uploads/file_001/report.pdf',
          expire_at: '2026-04-16T10:00:00.000Z'
        };
      }

      if (path === '/api/v1/files/complete') {
        return {
          file_id: 'file_001',
          file_name: 'report.pdf',
          size: '2048',
          mime_type: 'application/pdf',
          scan_status: 'passed'
        };
      }

      if (path === '/api/v1/citations/cite_001') {
        return {
          citation_id: 'cite_001',
          title: '账单分析报告',
          source_type: 'knowledge_base',
          doc_id: 'doc_001',
          chunk_id: 'chunk_001',
          content_preview: '账单片段预览',
          score: '0.88'
        };
      }

      throw new Error(`unexpected path: ${path}`);
    }
  };

  const fileApi = createFileApi({
    client,
    createIdempotencyKey: () => 'idem-file'
  });
  const citationApi = createCitationApi({ client });

  const policy = await fileApi.getUploadPolicy({
    fileName: '  report.pdf  ',
    size: 2048.8,
    mimeType: '  application/pdf  ',
    bizType: 'research_export'
  });
  const file = await fileApi.completeUpload({
    fileId: '  file_001  ',
    objectKey: '  uploads/file_001/report.pdf  ',
    checksum: '  sha256:abc  ',
    size: 2048.8
  });
  const citation = await citationApi.getCitationDetail('cite_001');

  assert.deepEqual(policy.formFields, {
    policy: 'policy-001',
    max_size: '2048',
    secure: 'true'
  });
  assert.equal(file.fileId, 'file_001');
  assert.equal(file.scanStatus, 'passed');
  assert.equal(citation.snippet, '账单片段预览');
  assert.equal(citation.score, 0.88);
  assert.equal(requestLog[0].init.headers['Idempotency-Key'], 'idem-file');
  assert.deepEqual(JSON.parse(requestLog[0].init.body), {
    file_name: 'report.pdf',
    size: 2048,
    mime_type: 'application/pdf',
    biz_type: 'research_export'
  });
  assert.deepEqual(JSON.parse(requestLog[1].init.body), {
    file_id: 'file_001',
    object_key: 'uploads/file_001/report.pdf',
    checksum: 'sha256:abc',
    size: 2048
  });
});

test('createFileApi and createCitationApi preserve fallback context for partial wrapped resources', async () => {
  const requestLog = [];

  const client = {
    async request(path, init) {
      requestLog.push({ path, init });

      if (path === '/api/v1/files/complete') {
        return {
          data: {
            file: {
              file_id: 'file_partial_001',
              status: 'ready'
            }
          }
        };
      }

      if (path === '/api/v1/citations/cite_partial_001') {
        return {
          data: {
            detail: {
              snippet: 'partial citation preview',
              version_no: 'v2',
              score: '0.91'
            }
          }
        };
      }

      throw new Error(`unexpected path: ${path}`);
    }
  };

  const fileApi = createFileApi({
    client,
    createIdempotencyKey: () => 'idem-file-partial'
  });
  const citationApi = createCitationApi({ client });

  const file = await fileApi.completeUpload({
    fileId: 'file_partial_001',
    objectKey: 'uploads/file_partial_001/billing-evidence.pdf',
    checksum: 'sha256:def',
    size: 4096
  });
  const citation = await citationApi.getCitationDetail('cite_partial_001', {
    id: 'cite_partial_001',
    title: 'GPU 账单规则',
    sourceType: 'knowledge_base',
    docId: 'doc_citation_001',
    chunkId: 'chunk_citation_001',
    url: 'https://smartcloud.local/docs/billing'
  });

  assert.equal(file.fileId, 'file_partial_001');
  assert.equal(file.fileName, 'billing-evidence.pdf');
  assert.equal(file.size, 4096);
  assert.equal(file.status, 'ready');
  assert.equal(citation.id, 'cite_partial_001');
  assert.equal(citation.title, 'GPU 账单规则');
  assert.equal(citation.docId, 'doc_citation_001');
  assert.equal(citation.chunkId, 'chunk_citation_001');
  assert.equal(citation.url, 'https://smartcloud.local/docs/billing');
  assert.equal(citation.snippet, 'partial citation preview');
  assert.equal(citation.versionNo, 'v2');
  assert.equal(citation.score, 0.91);
  assert.equal(requestLog[0].init.headers['Idempotency-Key'], 'idem-file-partial');
});

test('shared file and citation mappers support thin dev-only shim reuse without local DTO drift', () => {
  const normalizedPolicyInput = normalizeUploadPolicyRequest({
    fileName: '  invoice-proof.png  ',
    size: 1024.6,
    mimeType: '  image/png  ',
    bizType: 'chat_attachment'
  });
  const normalizedCompleteInput = normalizeCompleteUploadRequest({
    fileId: ' file_mock_001 ',
    objectKey: ' mock/file_mock_001/invoice-proof.png ',
    checksum: ' sha256:mock ',
    size: 1024.6
  });

  const policy = mapUploadPolicy({
    fileId: 'file_mock_001',
    uploadUrl: 'https://smartcloud.local/mock/upload/file_mock_001',
    formFields: {
      key: `mock/file_mock_001/${normalizedPolicyInput.fileName}`,
      secure: true
    },
    objectKey: `mock/file_mock_001/${normalizedPolicyInput.fileName}`,
    expireAt: '2026-04-16T10:00:00.000Z'
  });
  const file = mapFileRecord({
    fileId: normalizedCompleteInput.fileId,
    fileName: extractFileNameFromObjectKey(normalizedCompleteInput.objectKey),
    size: normalizedCompleteInput.size,
    mimeType: 'application/octet-stream',
    status: 'ready',
    scanStatus: 'passed'
  });
  const citation = mapCitationDetail({
    id: 'cite_mock_001',
    title: '示例引用资料',
    sourceType: 'knowledge_base',
    docId: 'doc_mock_001',
    chunkId: 'chunk_mock_001',
    snippet: '这里展示引用片段与来源详情。',
    versionNo: 'v1',
    score: 0.66
  });

  assert.equal(policy.fileId, 'file_mock_001');
  assert.equal(policy.objectKey, 'mock/file_mock_001/invoice-proof.png');
  assert.deepEqual(policy.formFields, {
    key: 'mock/file_mock_001/invoice-proof.png',
    secure: 'true'
  });
  assert.equal(file.fileId, 'file_mock_001');
  assert.equal(file.fileName, 'invoice-proof.png');
  assert.equal(file.size, 1024);
  assert.equal(file.status, 'ready');
  assert.equal(file.scanStatus, 'passed');
  assert.equal(citation.id, 'cite_mock_001');
  assert.equal(citation.snippet, '这里展示引用片段与来源详情。');
  assert.equal(citation.versionNo, 'v1');
  assert.equal(citation.score, 0.66);
});

test('shared business mappers unwrap wrapped named-resource contracts across billing/order/icp/file/citation surfaces', () => {
  const summary = mapBillingSummary({
    data: {
      summary: {
        total_amount: '256.00',
        currency: 'CNY',
        range: 'this_month'
      }
    }
  });
  const detail = mapOrderDetail({
    detail: {
      order: {
        order_no: 'ord_wrapped_001',
        product_type: '云服务器',
        status: 'paid',
        amount: '256.00',
        created_at: '2026-04-16T00:00:00.000Z'
      },
      refunds: [
        {
          refund_no: 'ref_wrapped_001',
          order_no: 'ord_wrapped_001',
          status: 'pending_review',
          requested_amount: '56.00',
          currency: 'CNY',
          created_at: '2026-04-16T01:00:00.000Z'
        }
      ]
    }
  });
  const application = mapIcpApplication({
    data: {
      application: {
        application_no: 'ICP20260416088',
        status: 'reviewing',
        current_step: 'operator_review',
        domain: 'wrapped.smartcloud.local',
        website_name: 'Wrapped Demo',
        subject_type: 'enterprise',
        contacts: ['王工']
      }
    }
  });
  const policy = mapUploadPolicy({
    data: {
      policy: {
        file_id: 'file_wrapped_001',
        upload_url: 'https://upload.smartcloud.local/file_wrapped_001',
        object_key: 'uploads/file_wrapped_001/demo.txt',
        expire_at: '2026-04-16T10:00:00.000Z'
      }
    }
  });
  const file = mapFileRecord({
    file: {
      file_id: 'file_wrapped_001',
      file_name: 'demo.txt',
      size: '1024',
      mime_type: 'text/plain'
    }
  });
  const citation = mapCitationDetail({
    data: {
      citation: {
        citation_id: 'cite_wrapped_001',
        title: 'Wrapped Citation',
        source_type: 'knowledge_base',
        doc_id: 'doc_wrapped_001',
        chunk_id: 'chunk_wrapped_001',
        snippet: 'wrapped citation preview'
      }
    }
  });

  assert.equal(summary.totalAmount, '256.00');
  assert.equal(detail.order.orderNo, 'ord_wrapped_001');
  assert.equal(detail.refunds[0].refundNo, 'ref_wrapped_001');
  assert.equal(application.applicationNo, 'ICP20260416088');
  assert.equal(policy.fileId, 'file_wrapped_001');
  assert.equal(file.fileName, 'demo.txt');
  assert.equal(citation.id, 'cite_wrapped_001');
});

test('shared business mappers unwrap canonical and api-envelope wrappers across business contract surfaces', () => {
  const summary = mapBillingSummary({
    code: 0,
    message: 'ok',
    request_id: 'req-summary-envelope',
    timestamp: 1776297600000,
    data: {
      summary: {
        total_amount: '512.00',
        currency: 'CNY',
        range: 'this_month'
      }
    }
  });
  const detail = mapOrderDetail({
    success: true,
    requestId: 'req-order-envelope',
    data: {
      detail: {
        order: {
          order_no: 'ord_enveloped_001',
          product_type: 'GPU 云服务器',
          status: 'paid',
          amount: '512.00',
          created_at: '2026-04-16T00:00:00.000Z'
        }
      }
    }
  });
  const application = mapIcpApplication({
    code: 0,
    message: 'ok',
    request_id: 'req-icp-envelope',
    timestamp: 1776297600000,
    data: {
      application: {
        application_no: 'ICP20260416123',
        status: 'reviewing',
        current_step: 'operator_review',
        domain: 'enveloped.smartcloud.local',
        website_name: 'Envelope Demo',
        subject_type: 'enterprise'
      }
    }
  });
  const policy = mapUploadPolicy({
    success: true,
    requestId: 'req-policy-envelope',
    data: {
      policy: {
        file_id: 'file_enveloped_001',
        upload_url: 'https://upload.smartcloud.local/file_enveloped_001',
        object_key: 'uploads/file_enveloped_001/demo.txt',
        expire_at: '2026-04-16T10:00:00.000Z'
      }
    }
  });
  const file = mapFileRecord({
    code: 0,
    message: 'ok',
    request_id: 'req-file-envelope',
    timestamp: 1776297600000,
    data: {
      file: {
        file_id: 'file_enveloped_001',
        file_name: 'demo.txt',
        size: 2048,
        mime_type: 'text/plain'
      }
    }
  });
  const citation = mapCitationDetail({
    success: true,
    requestId: 'req-citation-envelope',
    data: {
      citation: {
        citation_id: 'cite_enveloped_001',
        title: 'Envelope Citation',
        source_type: 'knowledge_base',
        doc_id: 'doc_enveloped_001',
        chunk_id: 'chunk_enveloped_001',
        snippet: 'enveloped citation preview'
      }
    }
  });

  assert.equal(summary.totalAmount, '512.00');
  assert.equal(detail.order.orderNo, 'ord_enveloped_001');
  assert.equal(application.applicationNo, 'ICP20260416123');
  assert.equal(policy.fileId, 'file_enveloped_001');
  assert.equal(file.size, 2048);
  assert.equal(citation.id, 'cite_enveloped_001');
});

test('shared business mappers accept already-normalized shared DTO reuse across ICP/file/citation surfaces', () => {
  const application = mapIcpApplication({
    applicationNo: 'ICP20260416188',
    status: 'reviewing',
    currentStep: 'operator_review',
    domain: 'normalized.smartcloud.local',
    websiteName: 'Normalized Demo',
    subjectType: 'enterprise',
    contacts: ['王工'],
    materials: [],
    submittedAt: '2026-04-16T00:00:00.000Z'
  });
  const materialCheck = mapIcpMaterialCheckResult({
    passed: true,
    issues: [],
    requiredMaterials: ['business_license']
  });
  const policy = mapUploadPolicy({
    fileId: 'file_normalized_001',
    uploadUrl: 'https://upload.smartcloud.local/file_normalized_001',
    formFields: {
      policy: 'policy-001'
    },
    objectKey: 'uploads/file_normalized_001/demo.txt',
    expireAt: '2026-04-16T10:00:00.000Z'
  });
  const file = mapFileRecord({
    fileId: 'file_normalized_001',
    fileName: 'demo.txt',
    size: 2048,
    mimeType: 'text/plain',
    downloadUrl: 'https://download.smartcloud.local/file_normalized_001'
  });
  const citation = mapCitationDetail({
    id: 'cite_normalized_001',
    title: 'Normalized Citation',
    sourceType: 'knowledge_base',
    docId: 'doc_normalized_001',
    chunkId: 'chunk_normalized_001',
    snippet: 'normalized citation preview',
    versionNo: 'v2',
    score: 0.92
  });

  assert.equal(application.applicationNo, 'ICP20260416188');
  assert.equal(materialCheck.requiredMaterials[0], 'business_license');
  assert.equal(policy.objectKey, 'uploads/file_normalized_001/demo.txt');
  assert.equal(file.downloadUrl, 'https://download.smartcloud.local/file_normalized_001');
  assert.equal(citation.id, 'cite_normalized_001');
  assert.equal(citation.score, 0.92);
});

test('shared business adapters accept contract-style page query inputs with snake_case keys and numeric strings', async () => {
  const requestLog = [];
  const billingApi = createBillingApi({
    client: {
      async request(path) {
        requestLog.push(path);
        return {
          items: []
        };
      }
    },
    now: () => new Date('2026-04-16T00:00:00.000Z')
  });
  const icpApi = createIcpApi({
    client: {
      async request(path) {
        requestLog.push(path);
        return {
          items: [],
          page: 2,
          page_size: 1,
          total: 0
        };
      }
    },
    createIdempotencyKey: () => 'idem-query-input',
    icpTrackingStore: {
      list: () => []
    }
  });

  await billingApi.listBillingDetails({
    page: '2',
    page_size: '1',
    billing_cycle: '2026-03'
  });
  await icpApi.listIcpApplicationPage({
    page: '2',
    page_size: '1'
  });

  assert.deepEqual(requestLog, [
    '/api/v1/billing/details?page=2&page_size=1&billing_cycle=2026-03',
    '/api/v1/icp/applications?page=2&page_size=1'
  ]);
});
