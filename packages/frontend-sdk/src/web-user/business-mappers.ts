import {
  asRecord,
  getBoolean,
  getNumber,
  getOptionalBoolean,
  getOptionalNumber,
  getOptionalString,
  getString,
  getStringArray,
  isRecord
} from '../core/utils';
import type {
  BillingDashboard,
  BillingDetailItem,
  BillingSummary,
  CheckIcpMaterialsRequest,
  CitationDetail,
  CompleteUploadRequest,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  FileRecord,
  IcpApplication,
  IcpMaterialCheckIssue,
  IcpMaterialCheckResult,
  IcpMaterialItem,
  InvoiceRecord,
  OrderDetail,
  OrderRecord,
  OwnedOffsetPageResult,
  RefundRecord,
  RefundTimelineEntry,
  ReplyTicketRequest,
  ServiceWorkspaceData,
  TicketDetail,
  TicketReply,
  TicketRecord,
  UploadPolicy,
  UploadPolicyRequest
} from './business-types';
import type { ChatAttachment } from './types';
import type {
  BillingDetailPageContract,
  BillingSummaryContract,
  CheckIcpMaterialsRequestContract,
  CitationDetailContract,
  CompleteUploadRequestContract,
  CreateIcpApplicationRequestContract,
  CreateRefundRequestContract,
  CreateTicketRequestContract,
  FileRecordContract,
  FileUploadPolicyContract,
  IcpApplicationContract,
  IcpMaterialCheckResultContract,
  IcpMaterialItemContract,
  InvoiceRecordPageContract,
  InvoiceRecordContract,
  OwnedNamedResourceInput,
  OwnedOffsetPageInput,
  OrderDetailContract,
  OrderRecordPageContract,
  OrderRecordContract,
  RefundRecordPageContract,
  RefundRecordContract,
  RefundTimelineEntryContract,
  ReplyTicketRequestContract,
  TicketAttachmentContract,
  TicketRecordPageContract,
  TicketDetailContract,
  TicketRecordContract,
  TicketReplyContract,
  UploadPolicyRequestContract
} from './business-contracts';

const TICKET_PRIORITIES = ['low', 'medium', 'high', 'urgent'] as const;
const TICKET_STATUSES = ['open', 'processing', 'resolved', 'closed'] as const;
const REFUND_STATUSES = [
  'pending_review',
  'approved',
  'rejected',
  'processing',
  'completed',
  'failed',
  'cancelled'
] as const;
const ICP_APPLICATION_STATUSES = [
  'materials_pending',
  'submitted',
  'reviewing',
  'approved',
  'rejected'
] as const;
const REFUND_OPERATOR_TYPES = ['user', 'system', 'finance'] as const;
const TICKET_REPLY_OPERATOR_TYPES = ['user', 'support', 'system'] as const;
const ICP_SUBJECT_TYPES = ['enterprise', 'individual'] as const;
const ICP_MATERIAL_STATUSES = ['prepared', 'uploaded', 'verified', 'missing'] as const;
const ICP_ISSUE_SEVERITIES = ['warning', 'error'] as const;

function getEnumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  fallback: T
): T {
  return typeof value === 'string' && allowed.includes(value as T) ? (value as T) : fallback;
}

function getOptionalEnumValue<T extends string>(
  value: unknown,
  allowed: readonly T[]
): T | undefined {
  return typeof value === 'string' && allowed.includes(value as T) ? (value as T) : undefined;
}

function hasOffsetPageItems(record: Record<string, unknown>): boolean {
  return (
    Array.isArray(record.items) ||
    Array.isArray(record.list) ||
    Array.isArray(record.records) ||
    Array.isArray(record.results)
  );
}

function extractOffsetPageItems<TContract>(
  record: Record<string, unknown>
): Array<unknown | TContract> {
  if (Array.isArray(record.items)) {
    return record.items;
  }

  if (Array.isArray(record.list)) {
    return record.list;
  }

  if (Array.isArray(record.records)) {
    return record.records;
  }

  if (Array.isArray(record.results)) {
    return record.results;
  }

  if (Array.isArray(record.data)) {
    return record.data;
  }

  if (isRecord(record.data)) {
    return extractOffsetPageItems(asRecord(record.data));
  }

  return [];
}

function resolveOffsetPageRecord(value: unknown): Record<string, unknown> | undefined {
  if (Array.isArray(value)) {
    return undefined;
  }

  const record = asRecord(value);
  if (hasOffsetPageItems(record)) {
    return record;
  }

  if (isRecord(record.data) && hasOffsetPageItems(record.data)) {
    return asRecord(record.data);
  }

  return record;
}

function selectNestedResourceRecord(
  record: Record<string, unknown>,
  keys: readonly string[]
): Record<string, unknown> | undefined {
  for (const key of keys) {
    if (isRecord(record[key])) {
      return asRecord(record[key]);
    }
  }

  return undefined;
}

function resolveResourceRecord(
  value: unknown,
  keys: readonly string[]
): Record<string, unknown> {
  const record = asRecord(value);
  const directNested = selectNestedResourceRecord(record, keys);
  if (directNested) {
    return directNested;
  }

  if (isRecord(record.data)) {
    const dataRecord = asRecord(record.data);
    const nestedDataRecord = selectNestedResourceRecord(dataRecord, keys);
    if (nestedDataRecord) {
      return nestedDataRecord;
    }

    return dataRecord;
  }

  return record;
}

function mapOffsetPage<TContract, TResponse>(
  value: unknown | { items?: TContract[] } | TContract[],
  mapper: (item: unknown | TContract) => TResponse
): OwnedOffsetPageResult<TResponse> {
  if (Array.isArray(value)) {
    return {
      items: value.map(mapper),
      page: 1,
      pageSize: value.length,
      total: value.length
    };
  }

  const pageRecord = resolveOffsetPageRecord(value) ?? asRecord(value);
  const items = extractOffsetPageItems<TContract>(pageRecord);

  return {
    items: items.map(mapper),
    page: getNumber(pageRecord, ['page'], 1),
    pageSize: getNumber(pageRecord, ['page_size', 'pageSize'], items.length),
    total: getNumber(pageRecord, ['total'], items.length),
    totalPages: getOptionalNumber(pageRecord, ['total_pages', 'totalPages']),
    sortBy: getOptionalString(pageRecord, ['sort_by', 'sortBy']),
    sortOrder: getOptionalEnumValue(pageRecord.sort_order ?? pageRecord.sortOrder, ['asc', 'desc'])
  };
}

function nowIso(): string {
  return new Date().toISOString();
}

export function mapSupportAttachment(value: unknown): ChatAttachment {
  const record = asRecord(value as TicketAttachmentContract | Record<string, unknown>);
  return {
    fileId: getString(record, ['file_id', 'fileId'], 'file_unknown'),
    fileName: getString(record, ['file_name', 'fileName'], 'unknown'),
    mimeType: getString(record, ['mime_type', 'mimeType'], 'application/octet-stream'),
    size: getNumber(record, ['size'])
  };
}

export function mapInvoiceRecord(
  value: OwnedNamedResourceInput<InvoiceRecordContract, 'invoice'>
): InvoiceRecord {
  const record = resolveResourceRecord(value, ['invoice', 'result', 'record']);
  return {
    invoiceNo: getString(record, ['invoice_no', 'invoiceNo'], 'inv_unknown'),
    status: getString(record, ['status'], 'unknown'),
    amount: getString(record, ['amount'], '0'),
    billingCycle: getString(record, ['billing_cycle', 'billingCycle'], '-'),
    title: getString(record, ['title'], '-')
  };
}

export function mapInvoiceRecordPage(
  value: OwnedOffsetPageInput<InvoiceRecordContract> | InvoiceRecordPageContract
): OwnedOffsetPageResult<InvoiceRecord> {
  return mapOffsetPage(value, mapInvoiceRecord);
}

export function mapOrderRecord(
  value: OwnedNamedResourceInput<OrderRecordContract, 'order'>
): OrderRecord {
  const record = resolveResourceRecord(value, ['order', 'result', 'record']);
  return {
    orderNo: getString(record, ['order_no', 'orderNo'], 'ord_unknown'),
    productType: getString(record, ['product_type', 'productType'], '-'),
    status: getString(record, ['status'], 'unknown'),
    amount: getString(record, ['amount'], '0'),
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso()),
    eligibleForRefund: getOptionalBoolean(record, ['eligible_for_refund', 'eligibleForRefund'])
  };
}

export function mapOrderRecordPage(
  value: OwnedOffsetPageInput<OrderRecordContract> | OrderRecordPageContract
): OwnedOffsetPageResult<OrderRecord> {
  return mapOffsetPage(value, mapOrderRecord);
}

export function mapRefundTimelineEntry(
  value: unknown | RefundTimelineEntryContract
): RefundTimelineEntry {
  const record = asRecord(value);
  return {
    status: getEnumValue(record.status, REFUND_STATUSES, 'pending_review'),
    at: getString(record, ['at'], nowIso()),
    operatorType: getEnumValue(
      getOptionalString(record, ['operator_type', 'operatorType']),
      REFUND_OPERATOR_TYPES,
      'system'
    ),
    note: getString(record, ['note'])
  };
}

export function mapRefundRecord(
  value: OwnedNamedResourceInput<RefundRecordContract, 'refund'>
): RefundRecord {
  const record = resolveResourceRecord(value, ['refund', 'result', 'record']);
  return {
    refundNo: getString(record, ['refund_no', 'refundNo'], 'ref_unknown'),
    orderNo: getString(record, ['order_no', 'orderNo'], 'ord_unknown'),
    status: getEnumValue(record.status, REFUND_STATUSES, 'pending_review'),
    requestedAmount: getString(record, ['requested_amount', 'requestedAmount'], '0'),
    currency: getString(record, ['currency'], 'CNY'),
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso()),
    approvedAmount: getOptionalString(record, ['approved_amount', 'approvedAmount']),
    rejectReason: getOptionalString(record, ['reject_reason', 'rejectReason']),
    finishedAt: getOptionalString(record, ['finished_at', 'finishedAt']),
    timeline: Array.isArray(record.timeline) ? record.timeline.map(mapRefundTimelineEntry) : []
  };
}

export function mapRefundRecordPage(
  value: OwnedOffsetPageInput<RefundRecordContract> | RefundRecordPageContract
): OwnedOffsetPageResult<RefundRecord> {
  return mapOffsetPage(value, mapRefundRecord);
}

export function mapOrderDetail(
  value: OwnedNamedResourceInput<OrderDetailContract, 'detail'>,
  fallbackOrderNo?: string
): OrderDetail {
  const record = resolveResourceRecord(value, ['detail', 'result', 'record']);
  const orderRecord = isRecord(record.order) ? record.order : record;

  return {
    order: mapOrderRecord({
      ...orderRecord,
      order_no: orderRecord.order_no ?? orderRecord.orderNo ?? fallbackOrderNo
    }),
    instanceName: getOptionalString(record, ['instance_name', 'instanceName']),
    region:
      getOptionalString(record, ['region']) ??
      getOptionalString(asRecord(orderRecord), ['region']),
    billingMode: getOptionalString(record, ['billing_mode', 'billingMode']),
    renewType: getOptionalString(record, ['renew_type', 'renewType']),
    servicePeriod: getOptionalString(record, ['service_period', 'servicePeriod']),
    payTime: getOptionalString(record, ['pay_time', 'payTime']),
    configurationSummary: getStringArray(record.configuration_summary ?? record.configurationSummary),
    refunds: Array.isArray(record.refunds) ? record.refunds.map(mapRefundRecord) : []
  };
}

export function mapTicketRecord(
  value: OwnedNamedResourceInput<TicketRecordContract, 'ticket'>
): TicketRecord {
  const record = resolveResourceRecord(value, ['ticket', 'result', 'record']);
  return {
    ticketNo: getString(record, ['ticket_no', 'ticketNo'], 'tic_unknown'),
    subject: getString(record, ['subject'], '-'),
    status: getEnumValue(record.status, TICKET_STATUSES, 'open'),
    category: getString(record, ['category'], 'general'),
    priority: getOptionalEnumValue(record.priority, TICKET_PRIORITIES),
    content: getOptionalString(record, ['content']),
    createdAt: getOptionalString(record, ['created_at', 'createdAt']),
    updatedAt: getString(record, ['updated_at', 'updatedAt'], nowIso()),
    slaMinutes: getOptionalNumber(record, ['sla_minutes', 'slaMinutes']),
    attachments: Array.isArray(record.attachments) ? record.attachments.map(mapSupportAttachment) : undefined
  };
}

export function mapTicketRecordPage(
  value: OwnedOffsetPageInput<TicketRecordContract> | TicketRecordPageContract
): OwnedOffsetPageResult<TicketRecord> {
  return mapOffsetPage(value, mapTicketRecord);
}

export function mapTicketReply(
  value: OwnedNamedResourceInput<TicketReplyContract, 'reply'>
): TicketReply {
  const record = resolveResourceRecord(value, ['reply', 'result', 'record']);
  return {
    replyNo: getString(record, ['reply_no', 'replyNo'], 'reply_unknown'),
    content: getString(record, ['content']),
    createdAt: getString(record, ['created_at', 'createdAt'], nowIso()),
    operatorType: getEnumValue(
      getOptionalString(record, ['operator_type', 'operatorType']),
      TICKET_REPLY_OPERATOR_TYPES,
      'user'
    ),
    attachments: Array.isArray(record.attachments) ? record.attachments.map(mapSupportAttachment) : undefined,
    status: getOptionalEnumValue(record.status, TICKET_STATUSES)
  };
}

export function mapTicketDetail(
  value: OwnedNamedResourceInput<TicketDetailContract, 'detail'>,
  fallbackTicketNo?: string
): TicketDetail {
  const record = resolveResourceRecord(value, ['detail', 'result', 'record']);
  const ticketRecord = isRecord(record.ticket) ? record.ticket : record;

  return {
    ticket: mapTicketRecord({
      ...ticketRecord,
      ticket_no: ticketRecord.ticket_no ?? ticketRecord.ticketNo ?? fallbackTicketNo
    }),
    replies: Array.isArray(record.replies) ? record.replies.map(mapTicketReply) : []
  };
}

export function mapBillingSummary(
  value: OwnedNamedResourceInput<BillingSummaryContract, 'summary'>
): BillingSummary {
  const record = resolveResourceRecord(value, ['summary', 'result', 'record']);
  const topProducts = Array.isArray(record.top_products)
    ? record.top_products
    : Array.isArray(record.topProducts)
      ? record.topProducts
      : [];
  const topInstances = Array.isArray(record.top_instances)
    ? record.top_instances
    : Array.isArray(record.topInstances)
      ? record.topInstances
      : [];

  return {
    totalAmount: getString(record, ['total_amount', 'totalAmount'], '0'),
    currency: getString(record, ['currency'], 'CNY'),
    range: getString(record, ['range'], 'this_month'),
    topProducts: topProducts.map((item) => {
          const product = asRecord(item);
          return {
            productType: getString(product, ['product_type', 'productType'], '-'),
            amount: getString(product, ['amount'], '0'),
            ratio: getNumber(product, ['ratio'])
          };
        }),
    topInstances: topInstances.map((item) => {
          const instance = asRecord(item);
          return {
            instanceId: getString(instance, ['instance_id', 'instanceId'], '-'),
            instanceName: getString(instance, ['instance_name', 'instanceName'], '-'),
            amount: getString(instance, ['amount'], '0')
          };
        })
  };
}

export function mapBillingDetailPage(
  value: OwnedOffsetPageInput<BillingDetailItemContract> | BillingDetailPageContract
): OwnedOffsetPageResult<BillingDetailItem> {
  return mapOffsetPage(value, (item) => {
    const detail = asRecord(item);
    return {
      statementNo: getString(detail, ['statement_no', 'statementNo'], '-'),
      billingCycle: getString(detail, ['billing_cycle', 'billingCycle'], '-'),
      productType: getString(detail, ['product_type', 'productType'], '-'),
      instanceId: getString(detail, ['instance_id', 'instanceId'], '-'),
      instanceName: getString(detail, ['instance_name', 'instanceName'], '-'),
      amount: getString(detail, ['amount'], '0'),
      status: getString(detail, ['status'], 'unknown')
    };
  });
}

export function mapBillingDetailItems(
  value: OwnedOffsetPageInput<BillingDetailItemContract> | BillingDetailPageContract
): BillingDetailItem[] {
  return mapBillingDetailPage(value).items;
}

export function mapIcpMaterialItem(value: unknown | IcpMaterialItemContract): IcpMaterialItem {
  const record = asRecord(value);
  return {
    fileId: getOptionalString(record, ['file_id', 'fileId']),
    fileName: getString(record, ['file_name', 'fileName'], 'unknown'),
    type: getString(record, ['type'], 'unknown_material'),
    status: getEnumValue(record.status, ICP_MATERIAL_STATUSES, 'prepared'),
    required: getBoolean(record, ['required'])
  };
}

export function mapIcpMaterialCheckIssue(value: unknown): IcpMaterialCheckIssue {
  const record = asRecord(value);
  return {
    field: getString(record, ['field'], 'unknown'),
    severity: getEnumValue(record.severity, ICP_ISSUE_SEVERITIES, 'warning'),
    message: getString(record, ['message'])
  };
}

export function mapIcpMaterialCheckResult(
  value: OwnedNamedResourceInput<IcpMaterialCheckResultContract, 'check_result'>
): IcpMaterialCheckResult {
  const record = resolveResourceRecord(value, ['check_result', 'result', 'record']);
  return {
    passed: getBoolean(record, ['passed']),
    issues: Array.isArray(record.issues) ? record.issues.map(mapIcpMaterialCheckIssue) : [],
    requiredMaterials: Array.isArray(record.required_materials)
      ? record.required_materials.map((item) => String(item))
      : Array.isArray(record.requiredMaterials)
        ? record.requiredMaterials.map((item) => String(item))
        : []
  };
}

export function mapIcpApplication(
  value: OwnedNamedResourceInput<IcpApplicationContract, 'application' | 'icp_application'>
): IcpApplication {
  const record = resolveResourceRecord(value, ['application', 'icp_application', 'result', 'record']);
  return {
    applicationNo: getString(record, ['application_no', 'applicationNo'], 'ICP_UNKNOWN'),
    status: getEnumValue(record.status, ICP_APPLICATION_STATUSES, 'submitted'),
    currentStep: getString(record, ['current_step', 'currentStep'], 'waiting_review'),
    domain: getString(record, ['domain']),
    websiteName: getString(record, ['website_name', 'websiteName']),
    subjectType: getEnumValue(
      getOptionalString(record, ['subject_type', 'subjectType']),
      ICP_SUBJECT_TYPES,
      'enterprise'
    ),
    rejectReason: getOptionalString(record, ['reject_reason', 'rejectReason']),
    contacts: getStringArray(record.contacts),
    materials: Array.isArray(record.materials) ? record.materials.map(mapIcpMaterialItem) : [],
    submittedAt: getOptionalString(record, ['submitted_at', 'submittedAt']),
    approvedAt: getOptionalString(record, ['approved_at', 'approvedAt'])
  };
}

export function mapServiceWorkspaceData(
  input: {
    orders?: unknown;
    refunds?: unknown;
    tickets?: unknown;
    icpApplications?: unknown;
  }
): ServiceWorkspaceData {
  const ordersRecord = asRecord(input.orders);
  const refundsRecord = asRecord(input.refunds);
  const ticketsRecord = asRecord(input.tickets);

  return {
    orders: mapOrderRecordPage(input.orders ?? ordersRecord).items,
    refunds: mapRefundRecordPage(input.refunds ?? refundsRecord).items,
    tickets: mapTicketRecordPage(input.tickets ?? ticketsRecord).items,
    icpApplications: Array.isArray(input.icpApplications) ? input.icpApplications.map(mapIcpApplication) : []
  };
}

export function mapFileRecord(
  value: OwnedNamedResourceInput<FileRecordContract, 'file'>
): FileRecord {
  const record = resolveResourceRecord(value, ['file', 'result', 'record']);
  return {
    fileId: getString(record, ['file_id', 'fileId'], 'file_unknown'),
    fileName: getString(record, ['file_name', 'fileName'], 'unknown'),
    size: getNumber(record, ['size']),
    mimeType: getString(record, ['mime_type', 'mimeType'], 'application/octet-stream'),
    downloadUrl: getOptionalString(record, ['download_url', 'downloadUrl']),
    expiresAt: getOptionalString(record, ['expires_at', 'expiresAt']),
    status: getOptionalString(record, ['status']),
    scanStatus: getOptionalString(record, ['scan_status', 'scanStatus'])
  };
}

export function mapUploadPolicy(
  value: OwnedNamedResourceInput<FileUploadPolicyContract, 'policy' | 'upload_policy'>
): UploadPolicy {
  const record = resolveResourceRecord(value, ['policy', 'upload_policy', 'result', 'record']);
  const formFields = isRecord(record.form_fields)
    ? Object.fromEntries(Object.entries(record.form_fields).map(([key, item]) => [key, String(item)]))
    : isRecord(record.formFields)
      ? Object.fromEntries(Object.entries(record.formFields).map(([key, item]) => [key, String(item)]))
      : {};

  return {
    fileId: getString(record, ['file_id', 'fileId'], 'file_unknown'),
    uploadUrl: getString(record, ['upload_url', 'uploadUrl']),
    formFields,
    objectKey: getString(record, ['object_key', 'objectKey']),
    expireAt: getString(record, ['expire_at', 'expireAt'], nowIso())
  };
}

export function mapCitationDetail(
  value: OwnedNamedResourceInput<CitationDetailContract, 'citation' | 'detail'>
): CitationDetail {
  const record = resolveResourceRecord(value, ['citation', 'detail', 'result', 'record']);
  return {
    id: getString(record, ['citation_id', 'id'], 'cite_unknown'),
    title: getString(record, ['title'], '引用资料'),
    sourceType: getString(record, ['source_type', 'sourceType'], 'knowledge_base'),
    docId: getString(record, ['doc_id', 'docId']),
    chunkId: getString(record, ['chunk_id', 'chunkId']),
    url: getOptionalString(record, ['url']),
    snippet: getString(record, ['snippet', 'content_preview', 'contentPreview'], '引用片段待接入'),
    versionNo: getOptionalString(record, ['version_no', 'versionNo']),
    score: getOptionalNumber(record, ['score'])
  };
}

function mapAttachmentReferences(attachments: ChatAttachment[]) {
  return attachments.map((item) => ({
    file_id: item.fileId
  }));
}

export function toCreateTicketRequestBody(input: CreateTicketRequest): CreateTicketRequestContract {
  return {
    subject: input.subject,
    content: input.content,
    priority: input.priority,
    category: input.category,
    attachments: mapAttachmentReferences(input.attachments)
  };
}

export function toReplyTicketRequestBody(input: ReplyTicketRequest): ReplyTicketRequestContract {
  return {
    content: input.content,
    attachments: mapAttachmentReferences(input.attachments)
  };
}

export function toCreateRefundRequestBody(input: CreateRefundRequest): CreateRefundRequestContract {
  return {
    reason: input.reason,
    amount: input.amount,
    attachments: mapAttachmentReferences(input.attachments)
  };
}

function toIcpMaterialContract(item: IcpMaterialItem): IcpMaterialItemContract {
  return {
    file_id: item.fileId,
    file_name: item.fileName,
    type: item.type,
    status: item.status,
    required: item.required
  };
}

export function toCheckIcpMaterialsRequestBody(
  input: CheckIcpMaterialsRequest
): CheckIcpMaterialsRequestContract {
  return {
    subject_type: input.subjectType,
    materials: input.materials.map(toIcpMaterialContract)
  };
}

export function toCreateIcpApplicationRequestBody(
  input: CreateIcpApplicationRequest
): CreateIcpApplicationRequestContract {
  return {
    subject_type: input.subjectType,
    domain: input.domain,
    website_name: input.websiteName,
    contacts: input.contacts,
    materials: input.materials.map(toIcpMaterialContract)
  };
}

export function toUploadPolicyRequestBody(input: UploadPolicyRequest): UploadPolicyRequestContract {
  return {
    file_name: input.fileName,
    size: input.size,
    mime_type: input.mimeType,
    biz_type: input.bizType
  };
}

export function toCompleteUploadRequestBody(input: CompleteUploadRequest): CompleteUploadRequestContract {
  return {
    file_id: input.fileId,
    object_key: input.objectKey,
    checksum: input.checksum,
    size: input.size
  };
}

export function buildBillingDashboard(input: {
  summary?: unknown;
  details?: unknown;
  invoices?: unknown;
  orders?: unknown;
  tickets?: unknown;
  failedDomains?: string[];
}): BillingDashboard {
  const failedDomains = input.failedDomains ?? [];

  return {
    summary: mapBillingSummary(input.summary),
    details: mapBillingDetailPage(input.details).items,
    invoices: mapInvoiceRecordPage(input.invoices as InvoiceRecordPageContract | unknown).items,
    orders: mapOrderRecordPage(input.orders as OrderRecordPageContract | unknown).items,
    tickets: mapTicketRecordPage(input.tickets as TicketRecordPageContract | unknown).items,
    loadState: {
      degraded: failedDomains.length > 0,
      failedDomains
    }
  };
}
