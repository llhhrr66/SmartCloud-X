import type {
  ApiEnvelope,
  CanonicalSuccessEnvelope,
  OffsetPagination,
  PaginationMeta
} from '@smartcloud-x/common-schemas';
import {
  billingDetailPageResourceAliases,
  billingSummaryResourceAliases,
  citationDetailResourceAliases,
  fileRecordResourceAliases,
  fileUploadPolicyResourceAliases,
  icpApplicationPageResourceAliases,
  icpApplicationResourceAliases,
  icpMaterialCheckResultResourceAliases,
  invoiceRecordPageResourceAliases,
  invoiceRecordResourceAliases,
  orderDetailResourceAliases,
  orderRecordPageResourceAliases,
  orderRecordResourceAliases,
  refundRecordPageResourceAliases,
  refundRecordResourceAliases,
  ticketDetailResourceAliases,
  ticketRecordPageResourceAliases,
  ticketRecordResourceAliases,
  ticketReplyResourceAliases
} from './business-resource-aliases';
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

export interface OwnedBusinessPaginationMetaContract
  extends Partial<OffsetPagination>,
    Partial<PaginationMeta> {
  pagination?: Partial<OffsetPagination> | Partial<PaginationMeta>;
}

export type OwnedBusinessEnvelope<T> =
  | ApiEnvelope<T>
  | CanonicalSuccessEnvelope<T>
  | {
      data: T;
      meta?: OwnedBusinessPaginationMetaContract | null;
    };

export type OwnedNamedResourceRecord<T, TName extends string> = Partial<
  Record<TName | 'result' | 'record', T>
> & {
  data?: T | Partial<Record<TName | 'result' | 'record', T>>;
};

export type OwnedNamedResourceInput<T, TName extends string> =
  | T
  | OwnedNamedResourceRecord<T, TName>
  | OwnedBusinessEnvelope<T | OwnedNamedResourceRecord<T, TName>>;

export interface OwnedOffsetPage<T> extends Partial<OffsetPagination> {
  items?: T[];
  list?: T[];
  records?: T[];
  results?: T[];
  data?: OwnedOffsetPage<T> | T[];
  meta?: OwnedBusinessPaginationMetaContract | null;
}

export type OwnedOffsetPageInput<T> =
  | T[]
  | OwnedOffsetPage<T>
  | OwnedBusinessEnvelope<OwnedOffsetPage<T> | T[]>;

export type OwnedNamedOffsetPageRecord<T, TName extends string> = Partial<
  Record<TName | 'result' | 'record', OwnedOffsetPage<T> | T[]>
> & {
  data?:
    | OwnedOffsetPage<T>
    | T[]
    | Partial<Record<TName | 'result' | 'record', OwnedOffsetPage<T> | T[]>>;
  meta?: OwnedBusinessPaginationMetaContract | null;
};

export type OwnedNamedOffsetPageInput<T, TName extends string> =
  | OwnedOffsetPage<T>
  | T[]
  | OwnedNamedOffsetPageRecord<T, TName>
  | OwnedBusinessEnvelope<
      OwnedOffsetPage<T> | T[] | OwnedNamedOffsetPageRecord<T, TName>
    >;

export interface OwnedBusinessPageQueryContract {
  page?: number;
  page_size?: number;
}

export interface BillingDetailListQueryContract extends OwnedBusinessPageQueryContract {
  billing_cycle?: string;
}

export interface BillingSummaryQueryContract {
  range?: string;
}

export type OrderListQueryContract = OwnedBusinessPageQueryContract;
export type RefundListQueryContract = OwnedBusinessPageQueryContract;
export type TicketListQueryContract = OwnedBusinessPageQueryContract;
export type IcpApplicationListQueryContract = OwnedBusinessPageQueryContract;

export interface BillingTopProductContract {
  product_type: string;
  amount: string;
  ratio: number;
}

export interface BillingTopInstanceContract {
  instance_id: string;
  instance_name: string;
  amount: string;
}

export interface BillingSummaryContract {
  total_amount: string;
  currency: string;
  range: BillingSummaryRange;
  top_products?: BillingTopProductContract[];
  top_instances?: BillingTopInstanceContract[];
}

export interface BillingDetailItemContract {
  statement_no: string;
  billing_cycle: string;
  product_type: string;
  instance_id: string;
  instance_name: string;
  amount: string;
  status: string;
}

export type BillingDetailPageContract = OwnedOffsetPage<BillingDetailItemContract>;

export interface InvoiceRecordContract {
  invoice_no: string;
  status: string;
  amount: string;
  billing_cycle: string;
  title: string;
}

export type InvoiceRecordPageContract = OwnedOffsetPage<InvoiceRecordContract>;

export interface OrderRecordContract {
  order_no: string;
  product_type: string;
  status: string;
  amount: string;
  created_at: string;
  eligible_for_refund?: boolean;
}

export type OrderRecordPageContract = OwnedOffsetPage<OrderRecordContract>;

export interface RefundTimelineEntryContract {
  status: RefundStatus;
  at: string;
  operator_type: 'user' | 'system' | 'finance';
  note: string;
}

export interface RefundRecordContract {
  refund_no: string;
  order_no: string;
  status: RefundStatus;
  requested_amount: string;
  currency: string;
  created_at: string;
  approved_amount?: string;
  reject_reason?: string;
  finished_at?: string;
  timeline?: RefundTimelineEntryContract[];
}

export type RefundRecordPageContract = OwnedOffsetPage<RefundRecordContract>;

export interface OrderDetailContract {
  order: OrderRecordContract;
  instance_name?: string;
  region?: string;
  billing_mode?: string;
  renew_type?: string;
  service_period?: string;
  pay_time?: string;
  configuration_summary?: string[];
  refunds?: RefundRecordContract[];
}

export interface TicketAttachmentContract {
  file_id: string;
  file_name: string;
  mime_type?: string;
  size?: number;
}

export interface TicketRecordContract {
  ticket_no: string;
  subject: string;
  status: TicketStatus;
  category: TicketCategory;
  priority?: TicketPriority;
  content?: string;
  created_at?: string;
  updated_at: string;
  sla_minutes?: number;
  attachments?: TicketAttachmentContract[];
}

export type TicketRecordPageContract = OwnedOffsetPage<TicketRecordContract>;

export interface TicketReplyContract {
  reply_no: string;
  content: string;
  created_at: string;
  operator_type: 'user' | 'support' | 'system';
  attachments?: TicketAttachmentContract[];
  status?: TicketStatus;
}

export interface TicketDetailContract {
  ticket: TicketRecordContract;
  replies?: TicketReplyContract[];
}

export interface IcpMaterialItemContract {
  file_id?: string;
  file_name: string;
  type: IcpMaterialType;
  status: 'prepared' | 'uploaded' | 'verified' | 'missing';
  required: boolean;
}

export interface IcpMaterialCheckIssueContract {
  field: string;
  severity: 'warning' | 'error';
  message: string;
}

export interface IcpMaterialCheckResultContract {
  passed: boolean;
  issues?: IcpMaterialCheckIssueContract[];
  required_materials?: string[];
}

export interface IcpApplicationContract {
  application_no: string;
  status: IcpApplicationStatus;
  current_step: string;
  domain: string;
  website_name: string;
  subject_type: 'enterprise' | 'individual';
  reject_reason?: string;
  contacts?: string[];
  materials?: IcpMaterialItemContract[];
  submitted_at?: string;
  approved_at?: string;
}

export type IcpApplicationPageContract = OwnedOffsetPage<IcpApplicationContract>;

export interface FileUploadPolicyContract {
  file_id: string;
  upload_url: string;
  form_fields?: Record<string, string | number | boolean>;
  object_key: string;
  expire_at: string;
}

export interface FileRecordContract {
  file_id: string;
  file_name: string;
  size: number;
  mime_type: string;
  download_url?: string;
  expires_at?: string;
  status?: FileLifecycleStatus;
  scan_status?: FileScanStatus;
}

export interface CitationDetailContract {
  citation_id: string;
  title: string;
  source_type: string;
  doc_id: string;
  chunk_id: string;
  url?: string;
  snippet: string;
  version_no?: string;
  score?: number;
}

export type BillingSummaryInputContract = OwnedNamedResourceInput<
  BillingSummaryContract,
  (typeof billingSummaryResourceAliases)[number]
>;
export type BillingDetailPageInputContract = OwnedNamedOffsetPageInput<
  BillingDetailItemContract,
  (typeof billingDetailPageResourceAliases)[number]
>;
export type InvoiceRecordInputContract = OwnedNamedResourceInput<
  InvoiceRecordContract,
  (typeof invoiceRecordResourceAliases)[number]
>;
export type InvoiceRecordPageInputContract = OwnedNamedOffsetPageInput<
  InvoiceRecordContract,
  (typeof invoiceRecordPageResourceAliases)[number]
>;
export type OrderRecordInputContract = OwnedNamedResourceInput<
  OrderRecordContract,
  (typeof orderRecordResourceAliases)[number]
>;
export type OrderRecordPageInputContract = OwnedNamedOffsetPageInput<
  OrderRecordContract,
  (typeof orderRecordPageResourceAliases)[number]
>;
export type RefundRecordInputContract = OwnedNamedResourceInput<
  RefundRecordContract,
  (typeof refundRecordResourceAliases)[number]
>;
export type RefundRecordPageInputContract = OwnedNamedOffsetPageInput<
  RefundRecordContract,
  (typeof refundRecordPageResourceAliases)[number]
>;
export type OrderDetailInputContract = OwnedNamedResourceInput<
  OrderDetailContract,
  (typeof orderDetailResourceAliases)[number]
>;
export type TicketRecordInputContract = OwnedNamedResourceInput<
  TicketRecordContract,
  (typeof ticketRecordResourceAliases)[number]
>;
export type TicketRecordPageInputContract = OwnedNamedOffsetPageInput<
  TicketRecordContract,
  (typeof ticketRecordPageResourceAliases)[number]
>;
export type TicketReplyInputContract = OwnedNamedResourceInput<
  TicketReplyContract,
  (typeof ticketReplyResourceAliases)[number]
>;
export type TicketDetailInputContract = OwnedNamedResourceInput<
  TicketDetailContract,
  (typeof ticketDetailResourceAliases)[number]
>;
export type IcpMaterialCheckResultInputContract = OwnedNamedResourceInput<
  IcpMaterialCheckResultContract,
  (typeof icpMaterialCheckResultResourceAliases)[number]
>;
export type IcpApplicationInputContract = OwnedNamedResourceInput<
  IcpApplicationContract,
  (typeof icpApplicationResourceAliases)[number]
>;
export type IcpApplicationPageInputContract = OwnedNamedOffsetPageInput<
  IcpApplicationContract,
  (typeof icpApplicationPageResourceAliases)[number]
>;
export type FileUploadPolicyInputContract = OwnedNamedResourceInput<
  FileUploadPolicyContract,
  (typeof fileUploadPolicyResourceAliases)[number]
>;
export type FileRecordInputContract = OwnedNamedResourceInput<
  FileRecordContract,
  (typeof fileRecordResourceAliases)[number]
>;
export type CitationDetailInputContract = OwnedNamedResourceInput<
  CitationDetailContract,
  (typeof citationDetailResourceAliases)[number]
>;

export interface TicketAttachmentReferenceContract {
  file_id: string;
}

export interface CreateTicketRequestContract {
  subject: string;
  content: string;
  priority: TicketPriority;
  category: string;
  attachments: TicketAttachmentReferenceContract[];
}

export interface ReplyTicketRequestContract {
  content: string;
  attachments: TicketAttachmentReferenceContract[];
}

export interface CreateRefundRequestContract {
  reason: string;
  amount: string;
  attachments: TicketAttachmentReferenceContract[];
}

export interface CheckIcpMaterialsRequestContract {
  subject_type: 'enterprise' | 'individual';
  materials: IcpMaterialItemContract[];
}

export interface CreateIcpApplicationRequestContract {
  subject_type: 'enterprise' | 'individual';
  domain: string;
  website_name: string;
  contacts: string[];
  materials: IcpMaterialItemContract[];
}

export interface UploadPolicyRequestContract {
  file_name: string;
  size: number;
  mime_type: string;
  biz_type: UploadBizType;
}

export interface CompleteUploadRequestContract {
  file_id: string;
  object_key: string;
  checksum: string;
  size: number;
}

export type BillingSummaryResponseContract = BillingSummaryInputContract;
export type BillingDetailPageResponseContract = BillingDetailPageInputContract;
export type InvoiceRecordPageResponseContract = InvoiceRecordPageInputContract;
export type OrderRecordPageResponseContract = OrderRecordPageInputContract;
export type RefundRecordPageResponseContract = RefundRecordPageInputContract;
export type OrderDetailResponseContract = OrderDetailInputContract;
export type TicketRecordResponseContract = TicketRecordInputContract;
export type TicketRecordPageResponseContract = TicketRecordPageInputContract;
export type TicketReplyResponseContract = TicketReplyInputContract;
export type TicketDetailResponseContract = TicketDetailInputContract;
export type RefundRecordResponseContract = RefundRecordInputContract;
export type IcpMaterialCheckResultResponseContract = IcpMaterialCheckResultInputContract;
export type IcpApplicationResponseContract = IcpApplicationInputContract;
export type IcpApplicationPageResponseContract = IcpApplicationPageInputContract;
export type FileUploadPolicyResponseContract = FileUploadPolicyInputContract;
export type FileRecordResponseContract = FileRecordInputContract;
export type CitationDetailResponseContract = CitationDetailInputContract;
