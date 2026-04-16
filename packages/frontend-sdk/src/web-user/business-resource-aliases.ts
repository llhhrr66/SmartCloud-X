export const billingSummaryResourceAliases = ['summary', 'billing_summary'] as const;
export const billingDetailPageResourceAliases = [
  'billing_details',
  'details',
  'billing_detail_page'
] as const;
export const invoiceRecordResourceAliases = ['invoice', 'invoice_record'] as const;
export const invoiceRecordPageResourceAliases = ['invoices', 'invoice_records'] as const;
export const orderRecordResourceAliases = ['order', 'order_record'] as const;
export const orderRecordPageResourceAliases = ['orders', 'order_records'] as const;
export const refundRecordResourceAliases = ['refund', 'refund_record'] as const;
export const refundRecordPageResourceAliases = ['refunds', 'refund_records'] as const;
export const orderDetailResourceAliases = ['detail', 'order_detail'] as const;
export const ticketRecordResourceAliases = ['ticket', 'ticket_record'] as const;
export const ticketRecordPageResourceAliases = ['tickets', 'ticket_records'] as const;
export const ticketReplyResourceAliases = ['reply', 'ticket_reply'] as const;
export const ticketDetailResourceAliases = ['detail', 'ticket_detail'] as const;
export const icpMaterialCheckResultResourceAliases = [
  'check_result',
  'material_check',
  'material_check_result',
  'icp_material_check_result'
] as const;
export const icpApplicationResourceAliases = ['application', 'icp_application'] as const;
export const icpApplicationPageResourceAliases = ['applications', 'icp_applications'] as const;
export const fileUploadPolicyResourceAliases = [
  'policy',
  'upload_policy',
  'file_upload_policy'
] as const;
export const fileRecordResourceAliases = ['file', 'file_record'] as const;
export const citationDetailResourceAliases = ['citation', 'detail', 'citation_detail'] as const;

export function withOwnedCommonResourceKeys<TAlias extends readonly string[]>(
  aliases: TAlias
): readonly [...TAlias, 'result', 'record'] {
  return [...aliases, 'result', 'record'];
}

export const billingSummaryResourceKeys = withOwnedCommonResourceKeys(
  billingSummaryResourceAliases
);
export const billingDetailPageResourceKeys = withOwnedCommonResourceKeys(
  billingDetailPageResourceAliases
);
export const invoiceRecordResourceKeys = withOwnedCommonResourceKeys(
  invoiceRecordResourceAliases
);
export const invoiceRecordPageResourceKeys = withOwnedCommonResourceKeys(
  invoiceRecordPageResourceAliases
);
export const orderRecordResourceKeys = withOwnedCommonResourceKeys(orderRecordResourceAliases);
export const orderRecordPageResourceKeys = withOwnedCommonResourceKeys(
  orderRecordPageResourceAliases
);
export const refundRecordResourceKeys = withOwnedCommonResourceKeys(
  refundRecordResourceAliases
);
export const refundRecordPageResourceKeys = withOwnedCommonResourceKeys(
  refundRecordPageResourceAliases
);
export const orderDetailResourceKeys = withOwnedCommonResourceKeys(orderDetailResourceAliases);
export const ticketRecordResourceKeys = withOwnedCommonResourceKeys(
  ticketRecordResourceAliases
);
export const ticketRecordPageResourceKeys = withOwnedCommonResourceKeys(
  ticketRecordPageResourceAliases
);
export const ticketReplyResourceKeys = withOwnedCommonResourceKeys(
  ticketReplyResourceAliases
);
export const ticketDetailResourceKeys = withOwnedCommonResourceKeys(
  ticketDetailResourceAliases
);
export const icpMaterialCheckResultResourceKeys = withOwnedCommonResourceKeys(
  icpMaterialCheckResultResourceAliases
);
export const icpApplicationResourceKeys = withOwnedCommonResourceKeys(
  icpApplicationResourceAliases
);
export const icpApplicationPageResourceKeys = withOwnedCommonResourceKeys(
  icpApplicationPageResourceAliases
);
export const fileUploadPolicyResourceKeys = withOwnedCommonResourceKeys(
  fileUploadPolicyResourceAliases
);
export const fileRecordResourceKeys = withOwnedCommonResourceKeys(fileRecordResourceAliases);
export const citationDetailResourceKeys = withOwnedCommonResourceKeys(
  citationDetailResourceAliases
);
