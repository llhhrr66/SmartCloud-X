import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  applyCreatedTicketToWorkspace,
  applyIcpApplicationToWorkspace,
  applyRefundToWorkspace,
  applyTicketReplyToDetail,
  applyTicketReplyToWorkspace,
  buildIcpApplicationListResult,
  buildChatAttachmentFromFileRecord,
  buildIcpMaterialFromFileRecord,
  buildOrderDetailFallback,
  buildSharedWorkspaceLoadState,
  extractFileNameFromObjectKey,
  mergeOrderDetailWithRefunds,
  paginateBusinessItems,
  resolveSharedLoadStateRetryAfterMs,
  selectSharedLoadStateDomains,
  sortRefundRecordsByCreatedAt,
  upsertChatAttachment,
  upsertIcpMaterial
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-state.js');

test('extractFileNameFromObjectKey trims and resolves the leaf name for shared upload fallbacks', () => {
  assert.equal(
    extractFileNameFromObjectKey(' uploads/file_001/ billing-evidence.pdf '),
    'billing-evidence.pdf'
  );
  assert.equal(
    extractFileNameFromObjectKey('billing-evidence.pdf'),
    'billing-evidence.pdf'
  );
  assert.equal(extractFileNameFromObjectKey('   '), '');
});

test('paginateBusinessItems keeps shared page contracts aligned for numeric-string and contract-style queries', () => {
  const page = paginateBusinessItems(
    [
      { applicationNo: 'ICP20260416001' },
      { applicationNo: 'ICP20260416002' },
      { applicationNo: 'ICP20260416003' }
    ],
    {
      page: '2',
      page_size: '1'
    },
    {
      total: 5,
      sortBy: 'submitted_at',
      sortOrder: 'desc'
    }
  );

  assert.deepEqual(page.items, [{ applicationNo: 'ICP20260416002' }]);
  assert.equal(page.page, 2);
  assert.equal(page.pageSize, 1);
  assert.equal(page.total, 5);
  assert.equal(page.totalPages, 5);
  assert.equal(page.sortBy, 'submitted_at');
  assert.equal(page.sortOrder, 'desc');
});

test('shared load-state helpers filter visible domains and surface retry-after metadata for thin page shims', () => {
  const loadState = buildSharedWorkspaceLoadState({
    failedDomains: ['tickets', 'icp', 'tickets'],
    fallbackDomains: ['icp', 'icp'],
    domainErrors: {
      tickets: {
        kind: 'rate_limited',
        message: 'tickets slow down',
        retryAfterMs: 1200
      },
      icp: {
        kind: 'rate_limited',
        message: 'icp slow down',
        retryAfterMs: 2400
      }
    }
  });

  assert.deepEqual(
    selectSharedLoadStateDomains(loadState, ['orders', 'tickets', 'icp']),
    ['tickets', 'icp']
  );
  assert.deepEqual(
    selectSharedLoadStateDomains(loadState, ['orders', 'icp'], 'fallback'),
    ['icp']
  );
  assert.equal(resolveSharedLoadStateRetryAfterMs(loadState, ['orders', 'tickets']), 1200);
  assert.equal(resolveSharedLoadStateRetryAfterMs(loadState, ['icp']), 2400);
  assert.equal(resolveSharedLoadStateRetryAfterMs(loadState), 1200);
  assert.equal(resolveSharedLoadStateRetryAfterMs(loadState, ['orders']), undefined);
});

test('shared ICP page-result helper keeps fallback and degraded metadata aligned for live and dev-only adapters', () => {
  const errorInfo = {
    kind: 'rate_limited',
    message: 'icp slow down',
    status: 429,
    code: 'RATE_LIMITED',
    requestId: 'req-icp-rate',
    retryAfterMs: 2400
  };

  const degradedPage = buildIcpApplicationListResult(
    {
      items: [
        {
          applicationNo: 'ICP20260416001',
          status: 'reviewing',
          currentStep: 'operator_review',
          domain: 'demo.smartcloud.local',
          websiteName: 'SmartCloud Demo',
          subjectType: 'enterprise',
          contacts: [],
          materials: []
        }
      ],
      page: 1,
      pageSize: 20,
      total: 1
    },
    {
      degraded: true,
      fallbackUsed: true,
      errorInfo
    }
  );
  const cleanPage = buildIcpApplicationListResult({
    items: [],
    page: 1,
    pageSize: 20,
    total: 0,
    totalPages: 0
  });

  assert.deepEqual(degradedPage.loadState, {
    degraded: true,
    failedDomains: ['icp'],
    fallbackDomains: ['icp'],
    domainErrors: {
      icp: errorInfo
    }
  });
  assert.deepEqual(cleanPage.loadState, {
    degraded: false,
    failedDomains: [],
    fallbackDomains: []
  });
});

test('shared order detail helpers merge fallback refunds without dropping detailed timeline data', () => {
  const detail = {
    order: {
      orderNo: 'ord_001',
      productType: 'GPU 云服务器',
      status: 'paid',
      amount: '199.00',
      createdAt: '2026-04-16T00:00:00.000Z'
    },
    configurationSummary: ['A100 x1'],
    refunds: [
      {
        refundNo: 'ref_001',
        orderNo: 'ord_001',
        status: 'approved',
        requestedAmount: '18.00',
        currency: 'CNY',
        createdAt: '2026-04-16T01:00:00.000Z',
        timeline: [
          {
            status: 'approved',
            at: '2026-04-16T02:00:00.000Z',
            operatorType: 'finance',
            note: 'approved by finance'
          }
        ]
      }
    ]
  };
  const fallbackRefunds = [
    {
      refundNo: 'ref_001',
      orderNo: 'ord_001',
      status: 'processing',
      requestedAmount: '18.00',
      currency: 'CNY',
      createdAt: '2026-04-16T01:00:00.000Z',
      approvedAmount: '18.00',
      timeline: []
    },
    {
      refundNo: 'ref_002',
      orderNo: 'ord_001',
      status: 'pending_review',
      requestedAmount: '29.00',
      currency: 'CNY',
      createdAt: '2026-04-16T03:00:00.000Z',
      timeline: []
    }
  ];

  const mergedDetail = mergeOrderDetailWithRefunds(detail, fallbackRefunds);
  const fallbackOnlyDetail = buildOrderDetailFallback(detail.order, fallbackRefunds);

  assert.equal(mergedDetail.configurationSummary[0], 'A100 x1');
  assert.equal(mergedDetail.refunds.length, 2);
  assert.equal(mergedDetail.refunds[0].refundNo, 'ref_002');
  assert.equal(mergedDetail.refunds[1].refundNo, 'ref_001');
  assert.equal(mergedDetail.refunds[1].approvedAmount, '18.00');
  assert.equal(mergedDetail.refunds[1].timeline[0].note, 'approved by finance');
  assert.equal(fallbackOnlyDetail?.refunds[0].refundNo, 'ref_002');
  assert.equal(buildOrderDetailFallback(null, fallbackRefunds), null);
  assert.deepEqual(
    sortRefundRecordsByCreatedAt(fallbackRefunds).map((item) => item.refundNo),
    ['ref_002', 'ref_001']
  );
});

test('shared ticket workspace helper upserts created tickets and keeps newest items first', () => {
  const workspace = {
    orders: [],
    refunds: [],
    tickets: [
      {
        ticketNo: 'tic_existing',
        subject: '旧工单',
        status: 'open',
        category: 'billing',
        updatedAt: '2026-04-16T01:00:00.000Z'
      },
      {
        ticketNo: 'tic_same',
        subject: '历史版本',
        status: 'open',
        category: 'billing',
        updatedAt: '2026-04-16T00:00:00.000Z'
      }
    ],
    icpApplications: []
  };
  const createdTicket = {
    ticketNo: 'tic_same',
    subject: '新工单版本',
    status: 'processing',
    category: 'technical_support',
    updatedAt: '2026-04-16T03:00:00.000Z'
  };

  const nextWorkspace = applyCreatedTicketToWorkspace(workspace, createdTicket);

  assert.deepEqual(
    nextWorkspace.tickets.map((item) => item.ticketNo),
    ['tic_same', 'tic_existing']
  );
  assert.equal(nextWorkspace.tickets[0].subject, '新工单版本');
  assert.equal(nextWorkspace.tickets[0].category, 'technical_support');
});

test('shared ticket reply helpers update detail and workspace state without duplicate replies', () => {
  const reply = {
    replyNo: 'reply_002',
    content: '已补充截图',
    createdAt: '2026-04-16T03:00:00.000Z',
    operatorType: 'user',
    status: 'processing'
  };
  const detail = {
    ticket: {
      ticketNo: 'tic_001',
      subject: '公网带宽异常',
      status: 'open',
      category: 'billing',
      updatedAt: '2026-04-16T01:00:00.000Z'
    },
    replies: [
      {
        replyNo: 'reply_002',
        content: '旧内容',
        createdAt: '2026-04-16T03:00:00.000Z',
        operatorType: 'user'
      },
      {
        replyNo: 'reply_001',
        content: '首条回复',
        createdAt: '2026-04-16T02:00:00.000Z',
        operatorType: 'support'
      }
    ]
  };
  const workspace = {
    orders: [],
    refunds: [],
    tickets: [
      {
        ticketNo: 'tic_001',
        subject: '公网带宽异常',
        status: 'open',
        category: 'billing',
        updatedAt: '2026-04-16T01:00:00.000Z'
      }
    ],
    icpApplications: []
  };

  const nextDetail = applyTicketReplyToDetail(detail, 'tic_001', reply);
  const nextWorkspace = applyTicketReplyToWorkspace(workspace, 'tic_001', reply);

  assert.equal(nextDetail?.ticket.status, 'processing');
  assert.equal(nextDetail?.ticket.updatedAt, '2026-04-16T03:00:00.000Z');
  assert.deepEqual(
    nextDetail?.replies.map((item) => item.replyNo),
    ['reply_001', 'reply_002']
  );
  assert.equal(nextDetail?.replies[1].content, '已补充截图');
  assert.equal(nextWorkspace.tickets[0].status, 'processing');
  assert.equal(nextWorkspace.tickets[0].updatedAt, '2026-04-16T03:00:00.000Z');
});

test('shared refund workspace helper marks the order as non-refundable and dedupes refunds', () => {
  const workspace = {
    orders: [
      {
        orderNo: 'ord_001',
        productType: '对象存储',
        status: 'paid',
        amount: '99.00',
        createdAt: '2026-04-16T00:00:00.000Z',
        eligibleForRefund: true
      }
    ],
    refunds: [
      {
        refundNo: 'ref_001',
        orderNo: 'ord_001',
        status: 'pending_review',
        requestedAmount: '18.00',
        currency: 'CNY',
        createdAt: '2026-04-16T01:00:00.000Z',
        timeline: []
      }
    ],
    tickets: [],
    icpApplications: [],
    loadState: {
      degraded: true,
      failedDomains: ['tickets']
    }
  };
  const refund = {
    refundNo: 'ref_001',
    orderNo: 'ord_001',
    status: 'approved',
    requestedAmount: '18.00',
    currency: 'CNY',
    createdAt: '2026-04-16T02:00:00.000Z',
    timeline: []
  };

  const nextWorkspace = applyRefundToWorkspace(workspace, refund);

  assert.equal(nextWorkspace.refunds.length, 1);
  assert.equal(nextWorkspace.refunds[0].status, 'approved');
  assert.equal(nextWorkspace.orders[0].eligibleForRefund, false);
  assert.deepEqual(nextWorkspace.loadState, workspace.loadState);
});

test('shared ICP workspace helper prepends created applications and replaces older duplicates', () => {
  const workspace = {
    orders: [],
    refunds: [],
    tickets: [],
    icpApplications: [
      {
        applicationNo: 'ICP20260416001',
        status: 'reviewing',
        currentStep: 'operator_review',
        domain: 'old.smartcloud.local',
        websiteName: 'Old Demo',
        subjectType: 'enterprise',
        contacts: [],
        materials: []
      }
    ]
  };
  const application = {
    applicationNo: 'ICP20260416001',
    status: 'approved',
    currentStep: 'done',
    domain: 'new.smartcloud.local',
    websiteName: 'New Demo',
    subjectType: 'enterprise',
    contacts: ['李雷'],
    materials: []
  };

  const nextWorkspace = applyIcpApplicationToWorkspace(workspace, application);

  assert.equal(nextWorkspace.icpApplications.length, 1);
  assert.equal(nextWorkspace.icpApplications[0].status, 'approved');
  assert.equal(nextWorkspace.icpApplications[0].domain, 'new.smartcloud.local');
});

test('shared upload-state helpers normalize file records into reusable attachment and ICP material state', () => {
  const file = {
    fileId: 'file_001',
    fileName: 'license.pdf',
    mimeType: 'application/pdf',
    size: 2048
  };

  const attachment = buildChatAttachmentFromFileRecord(file);
  const material = buildIcpMaterialFromFileRecord(file, 'business_license');
  const nextAttachments = upsertChatAttachment(
    [
      {
        fileId: 'file_existing',
        fileName: 'existing.png',
        mimeType: 'image/png',
        size: 128
      },
      {
        fileId: 'file_001',
        fileName: 'older-name.pdf',
        mimeType: 'application/pdf',
        size: 1024
      }
    ],
    attachment
  );
  const nextMaterials = upsertIcpMaterial(
    [
      {
        fileId: 'file_existing',
        fileName: 'existing.pdf',
        type: 'domain_certificate',
        status: 'verified',
        required: true
      },
      {
        fileId: 'file_001',
        fileName: 'older-license.pdf',
        type: 'business_license',
        status: 'prepared',
        required: true
      }
    ],
    material
  );

  assert.deepEqual(attachment, {
    fileId: 'file_001',
    fileName: 'license.pdf',
    mimeType: 'application/pdf',
    size: 2048
  });
  assert.deepEqual(material, {
    fileId: 'file_001',
    fileName: 'license.pdf',
    type: 'business_license',
    status: 'uploaded',
    required: true
  });
  assert.deepEqual(
    nextAttachments.map((item) => item.fileId),
    ['file_001', 'file_existing']
  );
  assert.equal(nextAttachments[0].fileName, 'license.pdf');
  assert.deepEqual(
    nextMaterials.map((item) => item.fileId),
    ['file_001', 'file_existing']
  );
  assert.equal(nextMaterials[0].fileName, 'license.pdf');
  assert.equal(nextMaterials[0].type, 'business_license');
});
