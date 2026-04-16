import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildCitationDetailFallback,
  buildCompletedUploadFileRecordFallback,
  buildStoredFileRecordFallback,
  buildUploadPolicyFallback
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-fallbacks.js');
const {
  isKnownBillingSummaryRange,
  isKnownFileLifecycleStatus,
  isKnownFileScanStatus,
  isKnownIcpApplicationStatus,
  isKnownIcpMaterialType,
  isKnownRefundStatus,
  isKnownTicketCategory,
  isKnownTicketPriority,
  isKnownTicketStatus,
  isKnownUploadBizType,
  knownBillingSummaryRanges,
  knownFileLifecycleStatuses,
  knownFileScanStatuses,
  knownIcpApplicationStatuses,
  knownIcpMaterialTypes,
  knownRefundStatuses,
  knownTicketCategories,
  knownTicketPriorities,
  knownTicketStatuses,
  knownUploadBizTypes
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/business-constants.js');

test('shared business constants expose reusable known route enums and guards for thin app adoption', () => {
  assert.deepEqual(knownBillingSummaryRanges, ['this_month', 'last_month', 'last_3_months']);
  assert.deepEqual(knownTicketPriorities, ['low', 'medium', 'high', 'urgent']);
  assert.deepEqual(knownTicketCategories, ['technical_support', 'billing', 'order', 'icp']);
  assert.deepEqual(knownTicketStatuses, ['open', 'processing', 'resolved', 'closed']);
  assert.deepEqual(knownRefundStatuses, [
    'pending_review',
    'approved',
    'rejected',
    'processing',
    'completed',
    'failed',
    'cancelled'
  ]);
  assert.deepEqual(knownIcpApplicationStatuses, [
    'materials_pending',
    'submitted',
    'reviewing',
    'approved',
    'rejected'
  ]);
  assert.deepEqual(knownIcpMaterialTypes, [
    'business_license',
    'domain_certificate',
    'website_responsible_id',
    'personal_id'
  ]);
  assert.deepEqual(knownUploadBizTypes, [
    'chat_attachment',
    'icp_material',
    'research_export',
    'avatar'
  ]);
  assert.deepEqual(knownFileLifecycleStatuses, ['pending', 'ready', 'expired', 'deleted']);
  assert.deepEqual(knownFileScanStatuses, ['pending', 'passed', 'failed']);

  assert.equal(isKnownBillingSummaryRange('last_3_months'), true);
  assert.equal(isKnownBillingSummaryRange('custom_window'), false);
  assert.equal(isKnownTicketPriority('high'), true);
  assert.equal(isKnownTicketPriority('p1'), false);
  assert.equal(isKnownTicketCategory('billing'), true);
  assert.equal(isKnownTicketCategory('research'), false);
  assert.equal(isKnownTicketStatus('processing'), true);
  assert.equal(isKnownTicketStatus('paused'), false);
  assert.equal(isKnownRefundStatus('completed'), true);
  assert.equal(isKnownRefundStatus('refunding'), false);
  assert.equal(isKnownIcpApplicationStatus('reviewing'), true);
  assert.equal(isKnownIcpApplicationStatus('queued'), false);
  assert.equal(isKnownIcpMaterialType('business_license'), true);
  assert.equal(isKnownIcpMaterialType('passport'), false);
  assert.equal(isKnownUploadBizType('icp_material'), true);
  assert.equal(isKnownUploadBizType('poster_asset'), false);
  assert.equal(isKnownFileLifecycleStatus('ready'), true);
  assert.equal(isKnownFileLifecycleStatus('archived'), false);
  assert.equal(isKnownFileScanStatus('passed'), true);
  assert.equal(isKnownFileScanStatus('quarantined'), false);
});

test('shared business fallback builders keep file and citation dev shims aligned with shared SDK contracts', () => {
  const policy = buildUploadPolicyFallback({
    fileId: 'file_mock_001',
    apiBaseUrl: 'https://smartcloud.local/api',
    input: {
      fileName: '  invoice-proof.png  ',
      size: 1024.6,
      mimeType: ' image/png ',
      bizType: 'chat_attachment'
    },
    formFields: {
      secure: true
    },
    expireAt: '2026-04-16T10:00:00.000Z'
  });
  const completedFile = buildCompletedUploadFileRecordFallback({
    input: {
      fileId: ' file_mock_001 ',
      objectKey: ' mock/file_mock_001/invoice-proof.png ',
      checksum: ' sha256:mock ',
      size: 1024.6
    },
    status: 'ready',
    scanStatus: 'passed'
  });
  const storedFile = buildStoredFileRecordFallback({
    fileId: 'file_mock_002',
    downloadUrl: 'https://smartcloud.local/mock/files/file_mock_002',
    expiresAt: '2026-04-16T10:00:00.000Z'
  });
  const citation = buildCitationDetailFallback({
    citationId: 'cite_mock_001',
    fallback: {
      title: '示例引用资料',
      sourceType: 'knowledge_base',
      docId: 'doc_mock_001',
      chunkId: 'chunk_mock_001'
    },
    snippet: '这里展示引用片段与来源详情。',
    versionNo: 'v1',
    score: 0.66
  });

  assert.equal(policy.fileId, 'file_mock_001');
  assert.equal(policy.uploadUrl, 'https://smartcloud.local/api/mock/upload/file_mock_001');
  assert.equal(policy.objectKey, 'mock/file_mock_001/invoice-proof.png');
  assert.deepEqual(policy.formFields, {
    key: 'mock/file_mock_001/invoice-proof.png',
    secure: 'true'
  });
  assert.equal(policy.expireAt, '2026-04-16T10:00:00.000Z');

  assert.equal(completedFile.fileId, 'file_mock_001');
  assert.equal(completedFile.fileName, 'invoice-proof.png');
  assert.equal(completedFile.size, 1024);
  assert.equal(completedFile.mimeType, 'application/octet-stream');
  assert.equal(completedFile.status, 'ready');
  assert.equal(completedFile.scanStatus, 'passed');

  assert.equal(storedFile.fileId, 'file_mock_002');
  assert.equal(storedFile.fileName, 'file_mock_002.txt');
  assert.equal(storedFile.downloadUrl, 'https://smartcloud.local/mock/files/file_mock_002');
  assert.equal(storedFile.expiresAt, '2026-04-16T10:00:00.000Z');

  assert.equal(citation.id, 'cite_mock_001');
  assert.equal(citation.title, '示例引用资料');
  assert.equal(citation.sourceType, 'knowledge_base');
  assert.equal(citation.docId, 'doc_mock_001');
  assert.equal(citation.chunkId, 'chunk_mock_001');
  assert.equal(citation.snippet, '这里展示引用片段与来源详情。');
  assert.equal(citation.versionNo, 'v1');
  assert.equal(citation.score, 0.66);
});
