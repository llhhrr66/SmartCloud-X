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
  BillingDashboardLoadDomain,
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
  IcpApplicationPage,
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
  ServiceWorkspaceLoadDomain,
  ServiceWorkspaceData,
  SharedDomainErrorInfo,
  TicketDetail,
  TicketReply,
  TicketRecord,
  UploadPolicy,
  UploadPolicyRequest
} from './business-types';
import type { ChatAttachment } from './types';
import {
  toCheckIcpMaterialsRequestContract,
  toCompleteUploadRequestContract,
  toCreateIcpApplicationRequestContract,
  toCreateRefundRequestContract,
  toCreateTicketRequestContract,
  toReplyTicketRequestContract,
  toUploadPolicyRequestContract
} from './business-normalizers';
import { buildSharedWorkspaceLoadState } from './business-state';
import type {
  BillingDetailPageInputContract,
  BillingDetailItemContract,
  BillingDetailPageContract,
  BillingSummaryInputContract,
  BillingSummaryContract,
  CheckIcpMaterialsRequestContract,
  CitationDetailInputContract,
  CitationDetailContract,
  CompleteUploadRequestContract,
  CreateIcpApplicationRequestContract,
  CreateRefundRequestContract,
  CreateTicketRequestContract,
  FileRecordInputContract,
  FileRecordContract,
  FileUploadPolicyInputContract,
  FileUploadPolicyContract,
  IcpApplicationInputContract,
  IcpApplicationPageInputContract,
  IcpApplicationPageContract,
  IcpApplicationContract,
  IcpMaterialCheckResultInputContract,
  IcpMaterialCheckResultContract,
  InvoiceRecordInputContract,
  InvoiceRecordPageInputContract,
  IcpMaterialItemContract,
  InvoiceRecordPageContract,
  InvoiceRecordContract,
  OwnedBusinessPaginationMetaContract,
  OwnedOffsetPageInput,
  OrderDetailInputContract,
  OrderDetailContract,
  OrderRecordInputContract,
  OrderRecordPageInputContract,
  OrderRecordPageContract,
  OrderRecordContract,
  RefundRecordInputContract,
  RefundRecordPageInputContract,
  RefundRecordPageContract,
  RefundRecordContract,
  RefundTimelineEntryContract,
  ReplyTicketRequestContract,
  TicketAttachmentContract,
  TicketDetailInputContract,
  TicketRecordInputContract,
  TicketRecordPageInputContract,
  TicketReplyInputContract,
  TicketRecordPageContract,
  TicketDetailContract,
  TicketRecordContract,
  TicketReplyContract,
  UploadPolicyRequestContract
} from './business-contracts';
import {
  billingDetailPageResourceKeys,
  billingSummaryResourceKeys,
  citationDetailResourceKeys,
  fileRecordResourceKeys,
  fileUploadPolicyResourceKeys,
  icpApplicationPageResourceKeys,
  icpApplicationResourceKeys,
  icpMaterialCheckResultResourceKeys,
  invoiceRecordPageResourceKeys,
  invoiceRecordResourceKeys,
  orderDetailResourceKeys,
  orderRecordPageResourceKeys,
  orderRecordResourceKeys,
  refundRecordPageResourceKeys,
  refundRecordResourceKeys,
  ticketDetailResourceKeys,
  ticketRecordPageResourceKeys,
  ticketRecordResourceKeys,
  ticketReplyResourceKeys
} from './business-resource-aliases';

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

function normalizeSortOrder(value: unknown): 'asc' | 'desc' | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }

  const normalized = value.trim().toLowerCase();
  return normalized === 'asc' || normalized === 'desc' ? normalized : undefined;
}

function hasDirectOffsetPageItems(record: Record<string, unknown>): boolean {
  return (
    Array.isArray(record.items) ||
    Array.isArray(record.list) ||
    Array.isArray(record.records) ||
    Array.isArray(record.results) ||
    Array.isArray(record.data)
  );
}

function hasOffsetPageItems(record: Record<string, unknown>): boolean {
  if (hasDirectOffsetPageItems(record)) {
    return true;
  }

  return isRecord(record.data) ? hasDirectOffsetPageItems(asRecord(record.data)) : false;
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

function selectNestedOffsetPageValue(
  record: Record<string, unknown>,
  keys: readonly string[]
): Record<string, unknown> | unknown[] | undefined {
  for (const key of keys) {
    const nestedValue = record[key];
    if (Array.isArray(nestedValue)) {
      return nestedValue;
    }

    if (!isRecord(nestedValue)) {
      continue;
    }

    const nestedRecord = asRecord(nestedValue);
    if (hasOffsetPageItems(nestedRecord) || extractPaginationMetaRecord(nestedRecord)) {
      return nestedRecord;
    }
  }

  return undefined;
}

function resolveOffsetPageSource(
  value: unknown,
  keys: readonly string[] = []
): Record<string, unknown> | unknown[] | undefined {
  if (Array.isArray(value)) {
    return value;
  }

  const record = asRecord(value);
  if (hasOffsetPageItems(record)) {
    return record;
  }

  const directNested = selectNestedOffsetPageValue(record, keys);
  if (directNested) {
    return directNested;
  }

  if (Array.isArray(record.data)) {
    return record.data;
  }

  if (isRecord(record.data) && hasOffsetPageItems(record.data)) {
    return asRecord(record.data);
  }

  if (isRecord(record.data)) {
    const nestedDataValue = selectNestedOffsetPageValue(asRecord(record.data), keys);
    if (nestedDataValue) {
      return nestedDataValue;
    }
  }

  return record;
}

function extractPaginationMetaRecord(
  record: Record<string, unknown>
): Record<string, unknown> | undefined {
  const directPagination = isRecord(record.pagination)
    ? asRecord(record.pagination as OwnedBusinessPaginationMetaContract)
    : undefined;
  const meta = isRecord(record.meta)
    ? asRecord(record.meta as OwnedBusinessPaginationMetaContract)
    : undefined;
  const nestedPagination = meta && isRecord(meta.pagination)
    ? asRecord(meta.pagination)
    : undefined;

  if (meta && nestedPagination) {
    return {
      ...meta,
      ...nestedPagination
    };
  }

  return nestedPagination ?? meta ?? directPagination;
}

function mergeOffsetPageMetaRecords(
  primary?: Record<string, unknown>,
  secondary?: Record<string, unknown>
): Record<string, unknown> | undefined {
  if (primary && secondary) {
    return {
      ...secondary,
      ...primary
    };
  }

  return primary ?? secondary;
}

function resolveOffsetPageMetaRecord(
  value: unknown,
  keys: readonly string[] = []
): Record<string, unknown> | undefined {
  if (Array.isArray(value)) {
    return undefined;
  }

  const record = asRecord(value);
  const pageSource = resolveOffsetPageSource(value, keys);
  const pageMeta =
    pageSource && !Array.isArray(pageSource)
      ? extractPaginationMetaRecord(pageSource)
      : undefined;
  const dataMeta = isRecord(record.data) ? extractPaginationMetaRecord(asRecord(record.data)) : undefined;
  const directMeta = extractPaginationMetaRecord(record);

  return mergeOffsetPageMetaRecords(pageMeta, mergeOffsetPageMetaRecords(dataMeta, directMeta));
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
  mapper: (item: unknown | TContract) => TResponse,
  resourceKeys: readonly string[] = []
): OwnedOffsetPageResult<TResponse> {
  if (Array.isArray(value)) {
    return {
      items: value.map(mapper),
      page: 1,
      pageSize: value.length,
      total: value.length
    };
  }

  const pageSource = resolveOffsetPageSource(value, resourceKeys);
  const pageMetaRecord = resolveOffsetPageMetaRecord(value, resourceKeys) ?? {};
  const pageRecord = pageSource && !Array.isArray(pageSource) ? pageSource : asRecord(value);
  const items = Array.isArray(pageSource)
    ? pageSource
    : extractOffsetPageItems<TContract>(pageRecord);
  const page = getNumber(pageRecord, ['page'], getNumber(pageMetaRecord, ['page'], 1));
  const pageSize = getNumber(
    pageRecord,
    ['page_size', 'pageSize'],
    getNumber(pageMetaRecord, ['page_size', 'pageSize'], items.length)
  );
  const total = getNumber(pageRecord, ['total'], getNumber(pageMetaRecord, ['total'], items.length));
  const totalPages =
    getOptionalNumber(pageRecord, ['total_pages', 'totalPages']) ??
    getOptionalNumber(pageMetaRecord, ['total_pages', 'totalPages']) ??
    (pageSize > 0 ? Math.ceil(total / pageSize) : undefined);

  return {
    items: items.map(mapper),
    page,
    pageSize,
    total,
    totalPages,
    sortBy:
      getOptionalString(pageRecord, ['sort_by', 'sortBy']) ??
      getOptionalString(pageMetaRecord, ['sort_by', 'sortBy']),
    sortOrder:
      normalizeSortOrder(pageRecord.sort_order ?? pageRecord.sortOrder) ??
      normalizeSortOrder(pageMetaRecord.sort_order ?? pageMetaRecord.sortOrder)
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
  value: InvoiceRecordInputContract | InvoiceRecord
): InvoiceRecord {
  const record = resolveResourceRecord(value, invoiceRecordResourceKeys);
  return {
    invoiceNo: getString(record, ['invoice_no', 'invoiceNo'], 'inv_unknown'),
    status: getString(record, ['status'], 'unknown'),
    amount: getString(record, ['amount'], '0'),
    billingCycle: getString(record, ['billing_cycle', 'billingCycle'], '-'),
    title: getString(record, ['title'], '-')
  };
}

export function mapInvoiceRecordPage(
  value:
    | OwnedOffsetPageInput<InvoiceRecordContract | InvoiceRecord>
    | InvoiceRecordPageInputContract
    | InvoiceRecordPageContract
    | InvoiceRecord[]
): OwnedOffsetPageResult<InvoiceRecord> {
  return mapOffsetPage(value, (item) =>
    mapInvoiceRecord(item as InvoiceRecordInputContract | InvoiceRecord)
  , invoiceRecordPageResourceKeys);
}

export function mapOrderRecord(
  value: OrderRecordInputContract | OrderRecord
): OrderRecord {
  const record = resolveResourceRecord(value, orderRecordResourceKeys);
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
  value:
    | OwnedOffsetPageInput<OrderRecordContract | OrderRecord>
    | OrderRecordPageInputContract
    | OrderRecordPageContract
    | OrderRecord[]
): OwnedOffsetPageResult<OrderRecord> {
  return mapOffsetPage(value, (item) =>
    mapOrderRecord(item as OrderRecordInputContract | OrderRecord)
  , orderRecordPageResourceKeys);
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
  value: RefundRecordInputContract | RefundRecord
): RefundRecord {
  const record = resolveResourceRecord(value, refundRecordResourceKeys);
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
  value:
    | OwnedOffsetPageInput<RefundRecordContract | RefundRecord>
    | RefundRecordPageInputContract
    | RefundRecordPageContract
    | RefundRecord[]
): OwnedOffsetPageResult<RefundRecord> {
  return mapOffsetPage(value, (item) =>
    mapRefundRecord(item as RefundRecordInputContract | RefundRecord)
  , refundRecordPageResourceKeys);
}

export function mapOrderDetail(
  value: OrderDetailInputContract,
  fallbackOrderNo?: string
): OrderDetail {
  const record = resolveResourceRecord(value, orderDetailResourceKeys);
  const orderRecord = isRecord(record.order) ? record.order : record;

  return {
    order: mapOrderRecord(
      {
        ...orderRecord,
        order_no: getOptionalString(orderRecord, ['order_no', 'orderNo']) ?? fallbackOrderNo ?? 'ord_unknown'
      } as OrderRecordInputContract
    ),
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
  value: TicketRecordInputContract | TicketRecord
): TicketRecord {
  const record = resolveResourceRecord(value, ticketRecordResourceKeys);
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
  value:
    | OwnedOffsetPageInput<TicketRecordContract | TicketRecord>
    | TicketRecordPageInputContract
    | TicketRecordPageContract
    | TicketRecord[]
): OwnedOffsetPageResult<TicketRecord> {
  return mapOffsetPage(value, (item) =>
    mapTicketRecord(item as TicketRecordInputContract | TicketRecord)
  , ticketRecordPageResourceKeys);
}

export function mapTicketReply(
  value: TicketReplyInputContract
): TicketReply {
  const record = resolveResourceRecord(value, ticketReplyResourceKeys);
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
  value: TicketDetailInputContract,
  fallbackTicketNo?: string
): TicketDetail {
  const record = resolveResourceRecord(value, ticketDetailResourceKeys);
  const ticketRecord = isRecord(record.ticket) ? record.ticket : record;

  return {
    ticket: mapTicketRecord(
      {
        ...ticketRecord,
        ticket_no: getOptionalString(ticketRecord, ['ticket_no', 'ticketNo']) ?? fallbackTicketNo ?? 'tic_unknown'
      } as TicketRecordInputContract
    ),
    replies: Array.isArray(record.replies) ? record.replies.map(mapTicketReply) : []
  };
}

export function mapBillingSummary(
  value: BillingSummaryInputContract | BillingSummary
): BillingSummary {
  const record = resolveResourceRecord(value, billingSummaryResourceKeys);
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
  value:
    | OwnedOffsetPageInput<BillingDetailItemContract | BillingDetailItem>
    | BillingDetailPageInputContract
    | BillingDetailPageContract
    | BillingDetailItem[]
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
  }, billingDetailPageResourceKeys);
}

export function mapBillingDetailItems(
  value:
    | OwnedOffsetPageInput<BillingDetailItemContract | BillingDetailItem>
    | BillingDetailPageInputContract
    | BillingDetailPageContract
    | BillingDetailItem[]
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
  value:
    | IcpMaterialCheckResultInputContract
    | IcpMaterialCheckResult
): IcpMaterialCheckResult {
  const record = resolveResourceRecord(value, icpMaterialCheckResultResourceKeys);
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
  value:
    | IcpApplicationInputContract
    | IcpApplication
): IcpApplication {
  const record = resolveResourceRecord(value, icpApplicationResourceKeys);
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

export function mapIcpApplicationPage(
  value:
    | OwnedOffsetPageInput<IcpApplicationContract | IcpApplication>
    | IcpApplicationPageInputContract
    | IcpApplicationPageContract
    | Array<IcpApplicationInputContract | IcpApplication>
): IcpApplicationPage {
  return mapOffsetPage(value, (item) =>
    mapIcpApplication(item as IcpApplicationInputContract | IcpApplication)
  , icpApplicationPageResourceKeys);
}

export function mapServiceWorkspaceData(
  input: {
    orders?: OwnedOffsetPageInput<OrderRecordContract | OrderRecord> | OrderRecord[];
    refunds?: OwnedOffsetPageInput<RefundRecordContract | RefundRecord> | RefundRecord[];
    tickets?: OwnedOffsetPageInput<TicketRecordContract | TicketRecord> | TicketRecord[];
    icpApplications?:
      | OwnedOffsetPageInput<IcpApplicationContract | IcpApplication>
      | Array<IcpApplicationInputContract | IcpApplication>;
    failedDomains?: ServiceWorkspaceLoadDomain[];
    fallbackDomains?: ServiceWorkspaceLoadDomain[];
    domainErrors?: Partial<Record<ServiceWorkspaceLoadDomain, SharedDomainErrorInfo>>;
  }
): ServiceWorkspaceData {
  const failedDomains = input.failedDomains ?? [];
  const fallbackDomains = input.fallbackDomains ?? [];
  const domainErrors = input.domainErrors;

  return {
    orders: mapOrderRecordPage(input.orders ?? []).items,
    refunds: mapRefundRecordPage(input.refunds ?? []).items,
    tickets: mapTicketRecordPage(input.tickets ?? []).items,
    icpApplications: mapIcpApplicationPage(input.icpApplications ?? []).items,
    loadState: buildSharedWorkspaceLoadState<ServiceWorkspaceLoadDomain>({
      failedDomains,
      fallbackDomains,
      domainErrors
    })
  };
}

export function mapFileRecord(
  value: FileRecordInputContract | FileRecord
): FileRecord {
  const record = resolveResourceRecord(value, fileRecordResourceKeys);
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
  value:
    | FileUploadPolicyInputContract
    | UploadPolicy
): UploadPolicy {
  const record = resolveResourceRecord(value, fileUploadPolicyResourceKeys);
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
  value:
    | CitationDetailInputContract
    | CitationDetail
): CitationDetail {
  const record = resolveResourceRecord(value, citationDetailResourceKeys);
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

export function toCreateTicketRequestBody(input: CreateTicketRequest): CreateTicketRequestContract {
  return toCreateTicketRequestContract(input);
}

export function toReplyTicketRequestBody(input: ReplyTicketRequest): ReplyTicketRequestContract {
  return toReplyTicketRequestContract(input);
}

export function toCreateRefundRequestBody(input: CreateRefundRequest): CreateRefundRequestContract {
  return toCreateRefundRequestContract(input);
}

export function toCheckIcpMaterialsRequestBody(
  input: CheckIcpMaterialsRequest
): CheckIcpMaterialsRequestContract {
  return toCheckIcpMaterialsRequestContract(input);
}

export function toCreateIcpApplicationRequestBody(
  input: CreateIcpApplicationRequest
): CreateIcpApplicationRequestContract {
  return toCreateIcpApplicationRequestContract(input);
}

export function toUploadPolicyRequestBody(input: UploadPolicyRequest): UploadPolicyRequestContract {
  return toUploadPolicyRequestContract(input);
}

export function toCompleteUploadRequestBody(input: CompleteUploadRequest): CompleteUploadRequestContract {
  return toCompleteUploadRequestContract(input);
}

export function buildBillingDashboard(input: {
  summary?: BillingSummaryInputContract | BillingSummary;
  details?: BillingDetailPageInputContract | BillingDetailItem[];
  invoices?: OwnedOffsetPageInput<InvoiceRecordContract | InvoiceRecord> | InvoiceRecord[];
  orders?: OwnedOffsetPageInput<OrderRecordContract | OrderRecord> | OrderRecord[];
  tickets?: OwnedOffsetPageInput<TicketRecordContract | TicketRecord> | TicketRecord[];
  failedDomains?: BillingDashboardLoadDomain[];
  domainErrors?: Partial<Record<BillingDashboardLoadDomain, SharedDomainErrorInfo>>;
}): BillingDashboard {
  const failedDomains = input.failedDomains ?? [];
  const domainErrors = input.domainErrors;

  return {
    summary: mapBillingSummary(
      input.summary ?? {
        totalAmount: '0',
        currency: 'CNY',
        range: 'this_month',
        topProducts: [],
        topInstances: []
      }
    ),
    details: mapBillingDetailPage(input.details ?? []).items,
    invoices: mapInvoiceRecordPage(input.invoices ?? []).items,
    orders: mapOrderRecordPage(input.orders ?? []).items,
    tickets: mapTicketRecordPage(input.tickets ?? []).items,
    loadState: buildSharedWorkspaceLoadState<BillingDashboardLoadDomain>({
      failedDomains,
      domainErrors
    })
  };
}
