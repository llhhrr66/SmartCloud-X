import type { SortOrder } from '@smartcloud-x/common-schemas';
import type {
  BusinessPageQueryInput,
  FileRecord,
  IcpApplication,
  IcpApplicationListResult,
  IcpMaterialItem,
  OwnedOffsetPageResult,
  OrderDetail,
  OrderRecord,
  RefundRecord,
  SharedDomainErrorInfo,
  SharedWorkspaceLoadState,
  ServiceWorkspaceData,
  TicketDetail,
  TicketRecord,
  TicketReply,
  TicketStatus
} from './business-types';
import { normalizeBusinessPageQuery } from './business-normalizers';
import type { ChatAttachment } from './types';

function getCreatedAtTimestamp(value: { createdAt: string }): number {
  return new Date(value.createdAt).getTime();
}

export function extractFileNameFromObjectKey(objectKey: string): string {
  const trimmed = objectKey.trim();
  if (!trimmed) {
    return '';
  }

  const segments = trimmed
    .split('/')
    .map((segment) => segment.trim())
    .filter(Boolean);

  return segments.at(-1) ?? trimmed;
}

function getTicketUpdatedTimestamp(ticket: TicketRecord): number {
  return new Date(ticket.updatedAt ?? ticket.createdAt ?? 0).getTime();
}

function matchesIcpMaterial(
  left: Pick<IcpMaterialItem, 'fileId' | 'fileName' | 'type'>,
  right: Pick<IcpMaterialItem, 'fileId' | 'fileName' | 'type'>
): boolean {
  if (left.fileId && right.fileId) {
    return left.fileId === right.fileId;
  }

  return left.fileName === right.fileName && left.type === right.type;
}

function sortTicketRepliesByCreatedAt(replies: TicketReply[]): TicketReply[] {
  return [...replies].sort(
    (left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime()
  );
}

function mergeRefundRecord(base: RefundRecord, override: RefundRecord): RefundRecord {
  return {
    ...base,
    ...override,
    timeline: override.timeline.length ? override.timeline : base.timeline
  };
}

function resolveTicketStatusAfterReply(
  currentStatus: TicketStatus,
  replyStatus?: TicketReply['status']
): TicketStatus {
  return replyStatus ?? (currentStatus === 'open' ? 'processing' : currentStatus);
}

function dedupeDomains<TDomain extends string>(
  domains: readonly TDomain[] | undefined
): TDomain[] | undefined {
  return domains ? [...new Set(domains)] : undefined;
}

export function buildSharedWorkspaceLoadState<TDomain extends string>(options: {
  failedDomains?: readonly TDomain[];
  fallbackDomains?: readonly TDomain[];
  domainErrors?: Partial<Record<TDomain, SharedDomainErrorInfo>>;
} = {}): SharedWorkspaceLoadState<TDomain> {
  const failedDomains = dedupeDomains(options.failedDomains) ?? [];
  const fallbackDomains = dedupeDomains(options.fallbackDomains);

  return {
    degraded: failedDomains.length > 0,
    failedDomains,
    ...(fallbackDomains ? { fallbackDomains } : {}),
    ...(options.domainErrors ? { domainErrors: options.domainErrors } : {})
  };
}

export function selectSharedLoadStateDomains<
  TDomain extends string,
  TVisibleDomain extends TDomain
>(
  loadState: SharedWorkspaceLoadState<TDomain> | null | undefined,
  visibleDomains: readonly TVisibleDomain[],
  kind: 'failed' | 'fallback' = 'failed'
): TVisibleDomain[] {
  const domains = kind === 'fallback' ? loadState?.fallbackDomains ?? [] : loadState?.failedDomains ?? [];

  return domains.filter(
    (domain): domain is TVisibleDomain => visibleDomains.includes(domain as TVisibleDomain)
  );
}

export function resolveSharedLoadStateRetryAfterMs<TDomain extends string>(
  loadState: SharedWorkspaceLoadState<TDomain> | null | undefined,
  domains?: readonly TDomain[]
): number | undefined {
  const orderedDomains = domains?.length
    ? domains
    : [...new Set([...(loadState?.failedDomains ?? []), ...(loadState?.fallbackDomains ?? [])])];

  for (const domain of orderedDomains) {
    const retryAfterMs = loadState?.domainErrors?.[domain]?.retryAfterMs;
    if (typeof retryAfterMs === 'number' && Number.isFinite(retryAfterMs) && retryAfterMs >= 0) {
      return retryAfterMs;
    }
  }

  return undefined;
}

export function paginateBusinessItems<T>(
  items: T[],
  query: BusinessPageQueryInput = {},
  options: {
    total?: number;
    sortBy?: string;
    sortOrder?: SortOrder;
  } = {}
): OwnedOffsetPageResult<T> {
  const normalizedQuery = normalizeBusinessPageQuery(query);
  const total = Math.max(options.total ?? items.length, items.length);
  const startIndex = Math.max(normalizedQuery.page - 1, 0) * normalizedQuery.page_size;

  return {
    items: items.slice(startIndex, startIndex + normalizedQuery.page_size),
    page: normalizedQuery.page,
    pageSize: normalizedQuery.page_size,
    total,
    totalPages: total === 0 ? 0 : Math.ceil(total / normalizedQuery.page_size),
    sortBy: options.sortBy,
    sortOrder: options.sortOrder
  };
}

export function buildIcpApplicationListResult(
  page: OwnedOffsetPageResult<IcpApplication>,
  options: {
    degraded?: boolean;
    fallbackUsed?: boolean;
    errorInfo?: SharedDomainErrorInfo;
  } = {}
): IcpApplicationListResult {
  return {
    ...page,
    loadState: buildSharedWorkspaceLoadState<'icp'>({
      failedDomains: options.degraded ? ['icp'] : [],
      fallbackDomains: options.fallbackUsed ? ['icp'] : [],
      domainErrors: options.errorInfo
        ? {
            icp: options.errorInfo
          }
        : undefined
    })
  };
}

export function buildChatAttachmentFromFileRecord(file: FileRecord): ChatAttachment {
  return {
    fileId: file.fileId,
    fileName: file.fileName,
    mimeType: file.mimeType,
    size: file.size
  };
}

export function upsertChatAttachment(
  attachments: ChatAttachment[],
  attachment: ChatAttachment
): ChatAttachment[] {
  return [attachment, ...attachments.filter((item) => item.fileId !== attachment.fileId)];
}

export function buildIcpMaterialFromFileRecord(
  file: FileRecord,
  type: IcpMaterialItem['type'],
  options: Partial<Pick<IcpMaterialItem, 'required' | 'status'>> = {}
): IcpMaterialItem {
  return {
    fileId: file.fileId,
    fileName: file.fileName,
    type,
    status: options.status ?? 'uploaded',
    required: options.required ?? true
  };
}

export function upsertIcpMaterial(
  materials: IcpMaterialItem[],
  material: IcpMaterialItem
): IcpMaterialItem[] {
  return [
    material,
    ...materials.filter((item) => !matchesIcpMaterial(item, material))
  ];
}

export function sortRefundRecordsByCreatedAt(refunds: RefundRecord[]): RefundRecord[] {
  return [...refunds].sort((left, right) => getCreatedAtTimestamp(right) - getCreatedAtTimestamp(left));
}

export function mergeRefundRecords(
  primary: RefundRecord[],
  secondary: RefundRecord[]
): RefundRecord[] {
  const merged = new Map<string, RefundRecord>();

  for (const refund of secondary) {
    merged.set(refund.refundNo, refund);
  }

  for (const refund of primary) {
    const existing = merged.get(refund.refundNo);
    merged.set(refund.refundNo, existing ? mergeRefundRecord(existing, refund) : refund);
  }

  return sortRefundRecordsByCreatedAt([...merged.values()]);
}

export function buildOrderDetailFallback(
  order: OrderRecord | null | undefined,
  refunds: RefundRecord[]
): OrderDetail | null {
  if (!order) {
    return null;
  }

  return {
    order,
    configurationSummary: [],
    refunds: sortRefundRecordsByCreatedAt(refunds)
  };
}

export function mergeOrderDetailWithRefunds(
  detail: OrderDetail,
  fallbackRefunds: RefundRecord[]
): OrderDetail {
  return {
    ...detail,
    refunds: mergeRefundRecords(detail.refunds, fallbackRefunds)
  };
}

export function sortTicketRecordsByUpdatedAt(tickets: TicketRecord[]): TicketRecord[] {
  return [...tickets].sort((left, right) => getTicketUpdatedTimestamp(right) - getTicketUpdatedTimestamp(left));
}

export function applyCreatedTicketToWorkspace(
  workspace: ServiceWorkspaceData,
  ticket: TicketRecord
): ServiceWorkspaceData {
  return {
    ...workspace,
    tickets: sortTicketRecordsByUpdatedAt([
      ticket,
      ...workspace.tickets.filter((item) => item.ticketNo !== ticket.ticketNo)
    ])
  };
}

export function applyTicketReplyToDetail(
  detail: TicketDetail | null,
  ticketNo: string,
  reply: TicketReply
): TicketDetail | null {
  if (!detail || detail.ticket.ticketNo !== ticketNo) {
    return detail;
  }

  return {
    ticket: {
      ...detail.ticket,
      status: resolveTicketStatusAfterReply(detail.ticket.status, reply.status),
      updatedAt: reply.createdAt
    },
    replies: sortTicketRepliesByCreatedAt([
      ...detail.replies.filter((item) => item.replyNo !== reply.replyNo),
      reply
    ])
  };
}

export function applyTicketReplyToWorkspace(
  workspace: ServiceWorkspaceData,
  ticketNo: string,
  reply: TicketReply
): ServiceWorkspaceData {
  return {
    ...workspace,
    tickets: sortTicketRecordsByUpdatedAt(
      workspace.tickets.map((item) =>
        item.ticketNo === ticketNo
          ? {
              ...item,
              status: resolveTicketStatusAfterReply(item.status, reply.status),
              updatedAt: reply.createdAt
            }
          : item
      )
    )
  };
}

export function applyRefundToWorkspace(
  workspace: ServiceWorkspaceData,
  refund: RefundRecord
): ServiceWorkspaceData {
  return {
    ...workspace,
    refunds: sortRefundRecordsByCreatedAt([
      refund,
      ...workspace.refunds.filter((item) => item.refundNo !== refund.refundNo)
    ]),
    orders: workspace.orders.map((item) =>
      item.orderNo === refund.orderNo
        ? {
            ...item,
            eligibleForRefund: false
          }
        : item
    )
  };
}

export function applyIcpApplicationToWorkspace(
  workspace: ServiceWorkspaceData,
  application: IcpApplication
): ServiceWorkspaceData {
  return {
    ...workspace,
    icpApplications: [
      application,
      ...workspace.icpApplications.filter((item) => item.applicationNo !== application.applicationNo)
    ]
  };
}
