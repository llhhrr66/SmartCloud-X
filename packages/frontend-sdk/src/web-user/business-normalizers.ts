import type {
  BillingDetailListQueryContract,
  BillingSummaryQueryContract,
  CheckIcpMaterialsRequestContract,
  CompleteUploadRequestContract,
  CreateIcpApplicationRequestContract,
  CreateRefundRequestContract,
  CreateTicketRequestContract,
  IcpMaterialItemContract,
  OwnedBusinessPageQueryContract,
  ReplyTicketRequestContract,
  TicketAttachmentReferenceContract,
  UploadPolicyRequestContract
} from './business-contracts';
import type {
  BillingDetailListQueryInput,
  BillingSummaryQueryInput,
  BusinessPageQueryInput,
  CheckIcpMaterialsRequest,
  CompleteUploadRequest,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  IcpMaterialItem,
  ReplyTicketRequest,
  UploadPolicyRequest
} from './business-types';
import type { ChatAttachment } from './types';

function normalizeTrimmedString(value: string | undefined, fallback = ''): string {
  if (typeof value !== 'string') {
    return fallback;
  }

  const trimmed = value.trim();
  return trimmed || fallback;
}

function normalizeOptionalTrimmedString(value: string | undefined): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }

  const trimmed = value.trim();
  return trimmed || undefined;
}

function normalizeNonNegativeInteger(value: number | string | undefined, fallback = 0): number {
  const normalizedValue =
    typeof value === 'string'
      ? value.trim()
        ? Number(value.trim())
        : undefined
      : value;

  if (!Number.isFinite(normalizedValue)) {
    return fallback;
  }

  return Math.max(Math.trunc(normalizedValue ?? fallback), 0);
}

function normalizePositiveInteger(value: number | string | undefined, fallback: number): number {
  const normalized = normalizeNonNegativeInteger(value, fallback);
  return normalized >= 1 ? normalized : fallback;
}

function normalizeAttachmentReference(
  attachment: ChatAttachment
): ChatAttachment | null {
  const fileId = normalizeOptionalTrimmedString(attachment.fileId);
  if (!fileId) {
    return null;
  }

  return {
    fileId,
    fileName: normalizeTrimmedString(attachment.fileName, fileId),
    mimeType: normalizeTrimmedString(attachment.mimeType, 'application/octet-stream'),
    size: normalizeNonNegativeInteger(attachment.size)
  };
}

export function normalizeChatAttachments(attachments: ChatAttachment[]): ChatAttachment[] {
  const normalized: ChatAttachment[] = [];
  const seenFileIds = new Set<string>();

  for (const attachment of attachments) {
    const nextAttachment = normalizeAttachmentReference(attachment);
    if (!nextAttachment || seenFileIds.has(nextAttachment.fileId)) {
      continue;
    }

    seenFileIds.add(nextAttachment.fileId);
    normalized.push(nextAttachment);
  }

  return normalized;
}

export function toAttachmentReferenceContracts(
  attachments: ChatAttachment[]
): TicketAttachmentReferenceContract[] {
  return normalizeChatAttachments(attachments).map((item) => ({
    file_id: item.fileId
  }));
}

function resolveIcpMaterialIdentity(item: Pick<IcpMaterialItem, 'fileId' | 'fileName' | 'type'>): string {
  if (item.fileId) {
    return item.fileId;
  }

  return `${item.type}:${item.fileName}`;
}

export function normalizeIcpMaterialItem(input: IcpMaterialItem): IcpMaterialItem {
  return {
    fileId: normalizeOptionalTrimmedString(input.fileId),
    fileName: normalizeTrimmedString(input.fileName, 'unknown'),
    type: normalizeTrimmedString(input.type, 'unknown_material'),
    status: input.status,
    required: Boolean(input.required)
  };
}

export function normalizeIcpMaterials(materials: IcpMaterialItem[]): IcpMaterialItem[] {
  const normalized: IcpMaterialItem[] = [];
  const seenKeys = new Set<string>();

  for (const material of materials) {
    const nextMaterial = normalizeIcpMaterialItem(material);
    const key = resolveIcpMaterialIdentity(nextMaterial);
    if (seenKeys.has(key)) {
      continue;
    }

    seenKeys.add(key);
    normalized.push(nextMaterial);
  }

  return normalized;
}

function toIcpMaterialContract(item: IcpMaterialItem): IcpMaterialItemContract {
  const normalizedItem = normalizeIcpMaterialItem(item);
  return {
    file_id: normalizedItem.fileId,
    file_name: normalizedItem.fileName,
    type: normalizedItem.type,
    status: normalizedItem.status,
    required: normalizedItem.required
  };
}

export function normalizeBusinessPageQuery(
  query: BusinessPageQueryInput = {}
): Required<OwnedBusinessPageQueryContract> {
  return {
    page: normalizePositiveInteger(query.page, 1),
    page_size: normalizePositiveInteger(query.pageSize ?? query.page_size, 10)
  };
}

export function normalizeBillingCycle(
  value: string | undefined,
  now = new Date()
): string {
  const trimmed = normalizeOptionalTrimmedString(value);
  if (trimmed && /^\d{4}-(0[1-9]|1[0-2])$/.test(trimmed)) {
    return trimmed;
  }

  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

export function normalizeBillingDetailListQuery(
  query: BillingDetailListQueryInput = {},
  now = new Date()
): Required<BillingDetailListQueryContract> {
  return {
    ...normalizeBusinessPageQuery(query),
    billing_cycle: normalizeBillingCycle(query.billingCycle ?? query.billing_cycle, now)
  };
}

export function normalizeBillingSummaryQuery(
  query: BillingSummaryQueryInput = {}
): Required<BillingSummaryQueryContract> {
  return {
    range: normalizeOptionalTrimmedString(query.range) ?? 'this_month'
  };
}

export function normalizeCreateTicketRequest(
  input: CreateTicketRequest
): CreateTicketRequest {
  return {
    subject: normalizeTrimmedString(input.subject),
    content: normalizeTrimmedString(input.content),
    priority: input.priority,
    category: normalizeTrimmedString(input.category, 'general'),
    attachments: normalizeChatAttachments(input.attachments)
  };
}

export function normalizeReplyTicketRequest(
  input: ReplyTicketRequest
): ReplyTicketRequest {
  return {
    content: normalizeTrimmedString(input.content),
    attachments: normalizeChatAttachments(input.attachments)
  };
}

export function normalizeCreateRefundRequest(
  input: CreateRefundRequest
): CreateRefundRequest {
  return {
    orderNo: normalizeTrimmedString(input.orderNo),
    reason: normalizeTrimmedString(input.reason),
    amount: normalizeTrimmedString(input.amount, '0'),
    attachments: normalizeChatAttachments(input.attachments)
  };
}

export function normalizeCheckIcpMaterialsRequest(
  input: CheckIcpMaterialsRequest
): CheckIcpMaterialsRequest {
  return {
    subjectType: input.subjectType,
    materials: normalizeIcpMaterials(input.materials)
  };
}

export function normalizeCreateIcpApplicationRequest(
  input: CreateIcpApplicationRequest
): CreateIcpApplicationRequest {
  const contacts = input.contacts
    .map((item) => normalizeOptionalTrimmedString(item))
    .filter((item): item is string => Boolean(item));
  const dedupedContacts = [...new Set(contacts)];

  return {
    subjectType: input.subjectType,
    domain: normalizeTrimmedString(input.domain),
    websiteName: normalizeTrimmedString(input.websiteName),
    contacts: dedupedContacts,
    materials: normalizeIcpMaterials(input.materials)
  };
}

export function normalizeUploadPolicyRequest(
  input: UploadPolicyRequest
): UploadPolicyRequest {
  return {
    fileName: normalizeTrimmedString(input.fileName),
    size: normalizeNonNegativeInteger(input.size),
    mimeType: normalizeTrimmedString(input.mimeType, 'application/octet-stream'),
    bizType: input.bizType
  };
}

export function normalizeCompleteUploadRequest(
  input: CompleteUploadRequest
): CompleteUploadRequest {
  return {
    fileId: normalizeTrimmedString(input.fileId),
    objectKey: normalizeTrimmedString(input.objectKey),
    checksum: normalizeTrimmedString(input.checksum),
    size: normalizeNonNegativeInteger(input.size)
  };
}

export function toCreateTicketRequestContract(
  input: CreateTicketRequest
): CreateTicketRequestContract {
  const normalized = normalizeCreateTicketRequest(input);
  return {
    subject: normalized.subject,
    content: normalized.content,
    priority: normalized.priority,
    category: normalized.category,
    attachments: toAttachmentReferenceContracts(normalized.attachments)
  };
}

export function toReplyTicketRequestContract(
  input: ReplyTicketRequest
): ReplyTicketRequestContract {
  const normalized = normalizeReplyTicketRequest(input);
  return {
    content: normalized.content,
    attachments: toAttachmentReferenceContracts(normalized.attachments)
  };
}

export function toCreateRefundRequestContract(
  input: CreateRefundRequest
): CreateRefundRequestContract {
  const normalized = normalizeCreateRefundRequest(input);
  return {
    reason: normalized.reason,
    amount: normalized.amount,
    attachments: toAttachmentReferenceContracts(normalized.attachments)
  };
}

export function toCheckIcpMaterialsRequestContract(
  input: CheckIcpMaterialsRequest
): CheckIcpMaterialsRequestContract {
  const normalized = normalizeCheckIcpMaterialsRequest(input);
  return {
    subject_type: normalized.subjectType,
    materials: normalized.materials.map(toIcpMaterialContract)
  };
}

export function toCreateIcpApplicationRequestContract(
  input: CreateIcpApplicationRequest
): CreateIcpApplicationRequestContract {
  const normalized = normalizeCreateIcpApplicationRequest(input);
  return {
    subject_type: normalized.subjectType,
    domain: normalized.domain,
    website_name: normalized.websiteName,
    contacts: normalized.contacts,
    materials: normalized.materials.map(toIcpMaterialContract)
  };
}

export function toUploadPolicyRequestContract(
  input: UploadPolicyRequest
): UploadPolicyRequestContract {
  const normalized = normalizeUploadPolicyRequest(input);
  return {
    file_name: normalized.fileName,
    size: normalized.size,
    mime_type: normalized.mimeType,
    biz_type: normalized.bizType
  };
}

export function toCompleteUploadRequestContract(
  input: CompleteUploadRequest
): CompleteUploadRequestContract {
  const normalized = normalizeCompleteUploadRequest(input);
  return {
    file_id: normalized.fileId,
    object_key: normalized.objectKey,
    checksum: normalized.checksum,
    size: normalized.size
  };
}
