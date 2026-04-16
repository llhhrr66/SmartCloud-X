import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  createBillingApi,
  createCitationApi,
  createFileApi,
  createServiceDeskApi
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-api.js');
const {
  mapBillingSummary,
  mapCitationDetail,
  mapFileRecord,
  mapIcpApplication,
  mapIcpMaterialCheckResult,
  mapOrderDetail,
  mapRefundRecord,
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
});

test('createServiceDeskApi normalizes ticket creation payloads and fallback fields', async () => {
  let capturedInit = null;

  const api = createServiceDeskApi({
    client: {
      async request(path, init) {
        if (path === '/api/v1/tickets') {
          capturedInit = init;
          return {
            ticket_no: 'tic_001',
            status: 'open'
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'idem-ticket',
    now: () => '2026-04-16T00:00:00.000Z'
  });

  const ticket = await api.createTicket({
    subject: '公网带宽异常',
    content: '请协助核查峰值突发计费',
    priority: 'high',
    category: 'billing',
    attachments: [
      {
        fileId: 'file_001',
        fileName: 'bandwidth.csv',
        mimeType: 'text/csv',
        size: 128
      }
    ]
  });

  assert.equal(ticket.ticketNo, 'tic_001');
  assert.equal(ticket.subject, '公网带宽异常');
  assert.equal(ticket.category, 'billing');
  assert.equal(ticket.attachments[0].fileId, 'file_001');
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

  const api = createServiceDeskApi({
    client: {
      async request(path) {
        assert.equal(path, '/api/v1/icp/applications');
        return {
          application_no: 'ICP20260416001',
          status: 'submitted',
          current_step: 'waiting_review'
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
    domain: 'llm-demo.smartcloud.local',
    websiteName: 'SmartCloud 模型体验站',
    contacts: ['李雷 138****0001'],
    materials: [
      {
        fileId: 'file_business_license_001',
        fileName: 'business-license.pdf',
        type: 'business_license',
        status: 'verified',
        required: true
      }
    ]
  });

  assert.equal(application.applicationNo, 'ICP20260416001');
  assert.equal(application.submittedAt, '2026-04-16T00:00:00.000Z');
  assert.equal(rememberedApplication, 'ICP20260416001');
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
            sortOrder: 'desc'
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
    fileName: 'report.pdf',
    size: 2048,
    mimeType: 'application/pdf',
    bizType: 'research_export'
  });
  const file = await fileApi.completeUpload({
    fileId: 'file_001',
    objectKey: 'uploads/file_001/report.pdf',
    checksum: 'sha256:abc',
    size: 2048
  });
  const citation = await citationApi.getCitationDetail('cite_001');

  assert.deepEqual(policy.formFields, {
    policy: 'policy-001',
    max_size: '2048',
    secure: 'true'
  });
  assert.equal(file.scanStatus, 'passed');
  assert.equal(citation.snippet, '账单片段预览');
  assert.equal(citation.score, 0.88);
  assert.equal(requestLog[0].init.headers['Idempotency-Key'], 'idem-file');
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
