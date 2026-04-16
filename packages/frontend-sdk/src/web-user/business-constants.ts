import type {
  BillingSummaryRange,
  FileLifecycleStatus,
  FileScanStatus,
  IcpApplicationStatus,
  IcpMaterialType,
  RefundStatus,
  TicketCategory,
  TicketPriority,
  TicketStatus,
  UploadBizType
} from './business-types';

export const knownBillingSummaryRanges = [
  'this_month',
  'last_month',
  'last_3_months'
] as const satisfies readonly BillingSummaryRange[];

export type KnownBillingSummaryRange = (typeof knownBillingSummaryRanges)[number];

export function isKnownBillingSummaryRange(
  value: string | null | undefined
): value is KnownBillingSummaryRange {
  return (
    typeof value === 'string' &&
    (knownBillingSummaryRanges as readonly string[]).includes(value)
  );
}

export const knownTicketPriorities = [
  'low',
  'medium',
  'high',
  'urgent'
] as const satisfies readonly TicketPriority[];

export type KnownTicketPriority = (typeof knownTicketPriorities)[number];

export function isKnownTicketPriority(
  value: string | null | undefined
): value is KnownTicketPriority {
  return (
    typeof value === 'string' &&
    (knownTicketPriorities as readonly string[]).includes(value)
  );
}

export const knownTicketCategories = [
  'technical_support',
  'billing',
  'order',
  'icp'
] as const satisfies readonly TicketCategory[];

export type KnownTicketCategory = (typeof knownTicketCategories)[number];

export function isKnownTicketCategory(
  value: string | null | undefined
): value is KnownTicketCategory {
  return (
    typeof value === 'string' &&
    (knownTicketCategories as readonly string[]).includes(value)
  );
}

export const knownTicketStatuses = [
  'open',
  'processing',
  'resolved',
  'closed'
] as const satisfies readonly TicketStatus[];

export type KnownTicketStatus = (typeof knownTicketStatuses)[number];

export function isKnownTicketStatus(
  value: string | null | undefined
): value is KnownTicketStatus {
  return (
    typeof value === 'string' &&
    (knownTicketStatuses as readonly string[]).includes(value)
  );
}

export const knownRefundStatuses = [
  'pending_review',
  'approved',
  'rejected',
  'processing',
  'completed',
  'failed',
  'cancelled'
] as const satisfies readonly RefundStatus[];

export type KnownRefundStatus = (typeof knownRefundStatuses)[number];

export function isKnownRefundStatus(
  value: string | null | undefined
): value is KnownRefundStatus {
  return (
    typeof value === 'string' &&
    (knownRefundStatuses as readonly string[]).includes(value)
  );
}

export const knownIcpApplicationStatuses = [
  'materials_pending',
  'submitted',
  'reviewing',
  'approved',
  'rejected'
] as const satisfies readonly IcpApplicationStatus[];

export type KnownIcpApplicationStatus = (typeof knownIcpApplicationStatuses)[number];

export function isKnownIcpApplicationStatus(
  value: string | null | undefined
): value is KnownIcpApplicationStatus {
  return (
    typeof value === 'string' &&
    (knownIcpApplicationStatuses as readonly string[]).includes(value)
  );
}

export const knownIcpMaterialTypes = [
  'business_license',
  'domain_certificate',
  'website_responsible_id',
  'personal_id'
] as const satisfies readonly IcpMaterialType[];

export type KnownIcpMaterialType = (typeof knownIcpMaterialTypes)[number];

export function isKnownIcpMaterialType(
  value: string | null | undefined
): value is KnownIcpMaterialType {
  return (
    typeof value === 'string' &&
    (knownIcpMaterialTypes as readonly string[]).includes(value)
  );
}

export const knownUploadBizTypes = [
  'chat_attachment',
  'icp_material',
  'research_export',
  'avatar'
] as const satisfies readonly UploadBizType[];

export type KnownUploadBizType = (typeof knownUploadBizTypes)[number];

export function isKnownUploadBizType(
  value: string | null | undefined
): value is KnownUploadBizType {
  return (
    typeof value === 'string' &&
    (knownUploadBizTypes as readonly string[]).includes(value)
  );
}

export const knownFileLifecycleStatuses = [
  'pending',
  'ready',
  'expired',
  'deleted'
] as const satisfies readonly FileLifecycleStatus[];

export type KnownFileLifecycleStatus = (typeof knownFileLifecycleStatuses)[number];

export function isKnownFileLifecycleStatus(
  value: string | null | undefined
): value is KnownFileLifecycleStatus {
  return (
    typeof value === 'string' &&
    (knownFileLifecycleStatuses as readonly string[]).includes(value)
  );
}

export const knownFileScanStatuses = [
  'pending',
  'passed',
  'failed'
] as const satisfies readonly FileScanStatus[];

export type KnownFileScanStatus = (typeof knownFileScanStatuses)[number];

export function isKnownFileScanStatus(
  value: string | null | undefined
): value is KnownFileScanStatus {
  return (
    typeof value === 'string' &&
    (knownFileScanStatuses as readonly string[]).includes(value)
  );
}
