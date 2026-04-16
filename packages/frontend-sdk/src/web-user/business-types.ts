import type { SortOrder } from '@smartcloud-x/common-schemas';
import type { ChatAttachment, Citation } from './types';

export type TicketPriority = 'low' | 'medium' | 'high' | 'urgent';
export type TicketStatus = 'open' | 'processing' | 'resolved' | 'closed';
export type RefundStatus =
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled';
export type IcpApplicationStatus =
  | 'materials_pending'
  | 'submitted'
  | 'reviewing'
  | 'approved'
  | 'rejected';
export type UploadBizType = 'chat_attachment' | 'icp_material' | 'research_export' | 'avatar';

export interface BusinessPageQuery {
  page?: number;
  pageSize?: number;
}

export interface BillingDetailListQuery extends BusinessPageQuery {
  billingCycle?: string;
}

export interface OrderListQuery extends BusinessPageQuery {}

export interface RefundListQuery extends BusinessPageQuery {}

export interface TicketListQuery extends BusinessPageQuery {}

export interface OwnedOffsetPageResult<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages?: number;
  sortBy?: string;
  sortOrder?: SortOrder;
}

export interface BillingTopProduct {
  productType: string;
  amount: string;
  ratio: number;
}

export interface BillingTopInstance {
  instanceId: string;
  instanceName: string;
  amount: string;
}

export interface BillingSummary {
  totalAmount: string;
  currency: string;
  range: string;
  topProducts: BillingTopProduct[];
  topInstances: BillingTopInstance[];
}

export interface BillingDetailItem {
  statementNo: string;
  billingCycle: string;
  productType: string;
  instanceId: string;
  instanceName: string;
  amount: string;
  status: string;
}

export interface InvoiceRecord {
  invoiceNo: string;
  status: string;
  amount: string;
  billingCycle: string;
  title: string;
}

export interface OrderRecord {
  orderNo: string;
  productType: string;
  status: string;
  amount: string;
  createdAt: string;
  eligibleForRefund?: boolean;
}

export interface RefundTimelineEntry {
  status: RefundStatus;
  at: string;
  operatorType: 'user' | 'system' | 'finance';
  note: string;
}

export interface RefundRecord {
  refundNo: string;
  orderNo: string;
  status: RefundStatus;
  requestedAmount: string;
  currency: string;
  createdAt: string;
  approvedAmount?: string;
  rejectReason?: string;
  finishedAt?: string;
  timeline: RefundTimelineEntry[];
}

export interface OrderDetail {
  order: OrderRecord;
  instanceName?: string;
  region?: string;
  billingMode?: string;
  renewType?: string;
  servicePeriod?: string;
  payTime?: string;
  configurationSummary: string[];
  refunds: RefundRecord[];
}

export interface TicketRecord {
  ticketNo: string;
  subject: string;
  status: TicketStatus;
  category: string;
  priority?: TicketPriority;
  content?: string;
  createdAt?: string;
  updatedAt: string;
  slaMinutes?: number;
  attachments?: ChatAttachment[];
}

export interface TicketReply {
  replyNo: string;
  content: string;
  createdAt: string;
  operatorType: 'user' | 'support' | 'system';
  attachments?: ChatAttachment[];
  status?: TicketStatus;
}

export interface TicketDetail {
  ticket: TicketRecord;
  replies: TicketReply[];
}

export type BillingDetailPage = OwnedOffsetPageResult<BillingDetailItem>;
export type InvoiceRecordPage = OwnedOffsetPageResult<InvoiceRecord>;
export type OrderRecordPage = OwnedOffsetPageResult<OrderRecord>;
export type RefundRecordPage = OwnedOffsetPageResult<RefundRecord>;
export type TicketRecordPage = OwnedOffsetPageResult<TicketRecord>;

export interface BillingDashboard {
  summary: BillingSummary;
  details: BillingDetailItem[];
  invoices: InvoiceRecord[];
  orders: OrderRecord[];
  tickets: TicketRecord[];
  loadState?: {
    degraded: boolean;
    failedDomains: string[];
  };
}

export interface CreateTicketRequest {
  subject: string;
  content: string;
  priority: TicketPriority;
  category: string;
  attachments: ChatAttachment[];
}

export interface ReplyTicketRequest {
  content: string;
  attachments: ChatAttachment[];
}

export interface CreateRefundRequest {
  orderNo: string;
  reason: string;
  amount: string;
  attachments: ChatAttachment[];
}

export interface IcpMaterialItem {
  fileId?: string;
  fileName: string;
  type: string;
  status: 'prepared' | 'uploaded' | 'verified' | 'missing';
  required: boolean;
}

export interface IcpMaterialCheckIssue {
  field: string;
  severity: 'warning' | 'error';
  message: string;
}

export interface IcpMaterialCheckResult {
  passed: boolean;
  issues: IcpMaterialCheckIssue[];
  requiredMaterials: string[];
}

export interface CheckIcpMaterialsRequest {
  subjectType: 'enterprise' | 'individual';
  materials: IcpMaterialItem[];
}

export interface CreateIcpApplicationRequest {
  subjectType: 'enterprise' | 'individual';
  domain: string;
  websiteName: string;
  contacts: string[];
  materials: IcpMaterialItem[];
}

export interface IcpApplication {
  applicationNo: string;
  status: IcpApplicationStatus;
  currentStep: string;
  domain: string;
  websiteName: string;
  subjectType: 'enterprise' | 'individual';
  rejectReason?: string;
  contacts: string[];
  materials: IcpMaterialItem[];
  submittedAt?: string;
  approvedAt?: string;
}

export interface ServiceWorkspaceData {
  orders: OrderRecord[];
  refunds: RefundRecord[];
  tickets: TicketRecord[];
  icpApplications: IcpApplication[];
}

export interface UploadPolicyRequest {
  fileName: string;
  size: number;
  mimeType: string;
  bizType: UploadBizType;
}

export interface UploadPolicy {
  fileId: string;
  uploadUrl: string;
  formFields: Record<string, string>;
  objectKey: string;
  expireAt: string;
}

export interface CompleteUploadRequest {
  fileId: string;
  objectKey: string;
  checksum: string;
  size: number;
}

export interface FileRecord {
  fileId: string;
  fileName: string;
  size: number;
  mimeType: string;
  downloadUrl?: string;
  expiresAt?: string;
  status?: string;
  scanStatus?: string;
}

export interface CitationDetail extends Citation {
  snippet: string;
  versionNo?: string;
  score?: number;
}
