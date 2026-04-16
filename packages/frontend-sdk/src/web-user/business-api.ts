import type {
  BillingDashboard,
  BillingDetailItem,
  BillingDetailListQuery,
  BillingDetailPage,
  BusinessPageQuery,
  CheckIcpMaterialsRequest,
  CitationDetail,
  CompleteUploadRequest,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  FileRecord,
  IcpApplication,
  IcpMaterialCheckResult,
  InvoiceRecord,
  InvoiceRecordPage,
  OrderDetail,
  OrderListQuery,
  OrderRecord,
  OrderRecordPage,
  RefundListQuery,
  RefundRecord,
  RefundRecordPage,
  ReplyTicketRequest,
  ServiceWorkspaceData,
  TicketDetail,
  TicketListQuery,
  TicketRecord,
  TicketRecordPage,
  TicketReply,
  UploadPolicy,
  UploadPolicyRequest
} from './business-types';
import type { FrontendApiClient } from '../core/http';
import {
  buildBillingDashboard,
  mapBillingDetailPage,
  mapCitationDetail,
  mapFileRecord,
  mapIcpApplication,
  mapIcpMaterialCheckResult,
  mapInvoiceRecordPage,
  mapOrderDetail,
  mapOrderRecordPage,
  mapRefundRecord,
  mapRefundRecordPage,
  mapServiceWorkspaceData,
  mapTicketDetail,
  mapTicketRecordPage,
  mapTicketRecord,
  mapTicketReply,
  mapUploadPolicy,
  toCheckIcpMaterialsRequestBody,
  toCompleteUploadRequestBody,
  toCreateIcpApplicationRequestBody,
  toCreateRefundRequestBody,
  toCreateTicketRequestBody,
  toReplyTicketRequestBody,
  toUploadPolicyRequestBody
} from './business-mappers';
import type {
  BillingDetailItemContract,
  BillingSummaryContract,
  CitationDetailContract,
  FileRecordContract,
  FileUploadPolicyContract,
  IcpApplicationContract,
  IcpMaterialCheckResultContract,
  InvoiceRecordContract,
  OrderDetailContract,
  OrderRecordContract,
  OwnedNamedResourceInput,
  OwnedOffsetPageInput,
  RefundRecordContract,
  TicketDetailContract,
  TicketRecordContract,
  TicketReplyContract
} from './business-contracts';

export interface RequestClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export interface CreateBillingApiOptions {
  client: RequestClient | FrontendApiClient;
  now?: () => Date;
}

function currentBillingCycle(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

function buildBusinessPagePath(
  path: string,
  query: BusinessPageQuery,
  extras: Record<string, string | undefined> = {}
): string {
  const params = new URLSearchParams();
  params.set('page', String(query.page ?? 1));
  params.set('page_size', String(query.pageSize ?? 10));

  for (const [key, value] of Object.entries(extras)) {
    if (value !== undefined && value !== '') {
      params.set(key, value);
    }
  }

  return `${path}?${params.toString()}`;
}

export function createBillingApi(options: CreateBillingApiOptions) {
  async function listBillingDetails(
    query: BillingDetailListQuery = {}
  ): Promise<BillingDetailPage> {
    const billingCycle = query.billingCycle ?? currentBillingCycle(options.now ? options.now() : new Date());
    const data = await options.client.request<OwnedOffsetPageInput<BillingDetailItemContract>>(
      buildBusinessPagePath('/api/v1/billing/details', query, {
        billing_cycle: billingCycle
      })
    );
    return mapBillingDetailPage(data);
  }

  async function listInvoices(
    query: BusinessPageQuery = {}
  ): Promise<InvoiceRecordPage> {
    const data = await options.client.request<OwnedOffsetPageInput<InvoiceRecordContract>>(
      buildBusinessPagePath('/api/v1/billing/invoices', query)
    );
    return mapInvoiceRecordPage(data);
  }

  async function listOrders(
    query: OrderListQuery = {}
  ): Promise<OrderRecordPage> {
    const data = await options.client.request<OwnedOffsetPageInput<OrderRecordContract>>(
      buildBusinessPagePath('/api/v1/orders', query)
    );
    return mapOrderRecordPage(data);
  }

  async function listTickets(
    query: TicketListQuery = {}
  ): Promise<TicketRecordPage> {
    const data = await options.client.request<OwnedOffsetPageInput<TicketRecordContract>>(
      buildBusinessPagePath('/api/v1/tickets', query)
    );
    return mapTicketRecordPage(data);
  }

  return {
    listBillingDetails,

    listInvoices,

    listOrders,

    listTickets,

    async getDashboard(): Promise<BillingDashboard> {
      const [summaryResult, detailsResult, invoicesResult, ordersResult, ticketsResult] = await Promise.allSettled([
        options.client.request<OwnedNamedResourceInput<BillingSummaryContract, 'summary'>>(
          '/api/v1/billing/summary?range=this_month'
        ),
        listBillingDetails({ page: 1, pageSize: 5 }),
        listInvoices({ page: 1, pageSize: 5 }),
        listOrders({ page: 1, pageSize: 5 }),
        listTickets({ page: 1, pageSize: 5 })
      ]);

      const failedDomains: string[] = [];

      if (summaryResult.status === 'rejected') {
        failedDomains.push('summary');
      }
      if (detailsResult.status === 'rejected') {
        failedDomains.push('details');
      }
      if (invoicesResult.status === 'rejected') {
        failedDomains.push('invoices');
      }
      if (ordersResult.status === 'rejected') {
        failedDomains.push('orders');
      }
      if (ticketsResult.status === 'rejected') {
        failedDomains.push('tickets');
      }

      if (failedDomains.length === 5) {
        const firstFailure = [summaryResult, detailsResult, invoicesResult, ordersResult, ticketsResult].find(
          (item): item is PromiseRejectedResult => item.status === 'rejected'
        );
        throw firstFailure?.reason instanceof Error ? firstFailure.reason : new Error('加载账单工作区失败');
      }

      return buildBillingDashboard({
        summary: summaryResult.status === 'fulfilled' ? summaryResult.value : undefined,
        details: detailsResult.status === 'fulfilled' ? detailsResult.value.items : undefined,
        invoices: invoicesResult.status === 'fulfilled' ? invoicesResult.value.items : undefined,
        orders: ordersResult.status === 'fulfilled' ? ordersResult.value.items : undefined,
        tickets: ticketsResult.status === 'fulfilled' ? ticketsResult.value.items : undefined,
        failedDomains
      });
    }
  };
}

export interface IcpTrackingStore {
  list(): string[];
  remember?(applicationNo: string): void;
}

export interface CreateServiceDeskApiOptions {
  client: RequestClient | FrontendApiClient;
  createIdempotencyKey: (scope: string, parts: unknown[]) => string;
  icpTrackingStore?: IcpTrackingStore;
  now?: () => string;
}

export function createServiceDeskApi(options: CreateServiceDeskApiOptions) {
  const now = () => (options.now ? options.now() : new Date().toISOString());

  async function getIcpApplication(applicationNo: string): Promise<IcpApplication> {
    const data = await options.client.request<
      OwnedNamedResourceInput<IcpApplicationContract, 'application' | 'icp_application'>
    >(`/api/v1/icp/applications/${encodeURIComponent(applicationNo)}`);
    return mapIcpApplication(data);
  }

  async function listIcpApplications(): Promise<IcpApplication[]> {
    const applicationIds = options.icpTrackingStore?.list() ?? [];
    if (!applicationIds.length) {
      return [];
    }

    const settled = await Promise.allSettled(applicationIds.map((applicationNo) => getIcpApplication(applicationNo)));
    return settled
      .filter((item): item is PromiseFulfilledResult<IcpApplication> => item.status === 'fulfilled')
      .map((item) => item.value)
      .sort(
        (left, right) =>
          new Date(right.submittedAt ?? right.approvedAt ?? 0).getTime() -
          new Date(left.submittedAt ?? left.approvedAt ?? 0).getTime()
      );
  }

  async function getTicketDetail(ticketNo: string): Promise<TicketDetail> {
    const data = await options.client.request<OwnedNamedResourceInput<TicketDetailContract, 'detail'>>(
      `/api/v1/tickets/${encodeURIComponent(ticketNo)}`
    );
    return mapTicketDetail(data, ticketNo);
  }

  async function listOrders(
    query: OrderListQuery = {}
  ): Promise<OrderRecordPage> {
    const data = await options.client.request<OwnedOffsetPageInput<OrderRecordContract>>(
      buildBusinessPagePath('/api/v1/orders', query)
    );
    return mapOrderRecordPage(data);
  }

  async function listRefunds(
    query: RefundListQuery = {}
  ): Promise<RefundRecordPage> {
    const data = await options.client.request<OwnedOffsetPageInput<RefundRecordContract>>(
      buildBusinessPagePath('/api/v1/refunds', query)
    );
    return mapRefundRecordPage(data);
  }

  async function listTickets(
    query: TicketListQuery = {}
  ): Promise<TicketRecordPage> {
    const data = await options.client.request<OwnedOffsetPageInput<TicketRecordContract>>(
      buildBusinessPagePath('/api/v1/tickets', query)
    );
    return mapTicketRecordPage(data);
  }

  return {
    listOrders,

    listRefunds,

    listTickets,

    async getWorkspace(): Promise<ServiceWorkspaceData> {
      const [ordersResult, refundsResult, ticketsResult, icpResult] = await Promise.allSettled([
        listOrders({ page: 1, pageSize: 10 }),
        listRefunds({ page: 1, pageSize: 10 }),
        listTickets({ page: 1, pageSize: 10 }),
        listIcpApplications()
      ]);

      return mapServiceWorkspaceData({
        orders: ordersResult.status === 'fulfilled' ? ordersResult.value.items : undefined,
        refunds: refundsResult.status === 'fulfilled' ? refundsResult.value.items : undefined,
        tickets: ticketsResult.status === 'fulfilled' ? ticketsResult.value.items : undefined,
        icpApplications: icpResult.status === 'fulfilled' ? icpResult.value : []
      });
    },

    listIcpApplications,

    getTicketDetail,

    async getOrderDetail(orderNo: string): Promise<OrderDetail> {
      const data = await options.client.request<OwnedNamedResourceInput<OrderDetailContract, 'detail'>>(
        `/api/v1/orders/${encodeURIComponent(orderNo)}`
      );
      return mapOrderDetail(data, orderNo);
    },

    async getRefundDetail(refundNo: string): Promise<RefundRecord> {
      const data = await options.client.request<OwnedNamedResourceInput<RefundRecordContract, 'refund'>>(
        `/api/v1/refunds/${encodeURIComponent(refundNo)}`
      );
      return mapRefundRecord(data);
    },

    async createTicket(input: CreateTicketRequest): Promise<TicketRecord> {
      const timestamp = now();
      const data = await options.client.request<OwnedNamedResourceInput<TicketRecordContract, 'ticket'>>(
        '/api/v1/tickets',
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('ticket-create', [
              input.subject,
              input.content,
              input.priority,
              input.category,
              input.attachments.map((item) => item.fileId)
            ])
          },
          body: JSON.stringify(toCreateTicketRequestBody(input))
        }
      );

      return mapTicketRecord({
        ...(typeof data === 'object' && data !== null ? data : {}),
        subject: input.subject,
        content: input.content,
        category: input.category,
        priority: input.priority,
        attachments: input.attachments.map((item) => ({
          file_id: item.fileId,
          file_name: item.fileName,
          mime_type: item.mimeType,
          size: item.size
        })),
        created_at: timestamp,
        updated_at: timestamp
      });
    },

    async replyTicket(ticketNo: string, input: ReplyTicketRequest): Promise<TicketReply> {
      const data = await options.client.request<OwnedNamedResourceInput<TicketReplyContract, 'reply'>>(
        `/api/v1/tickets/${encodeURIComponent(ticketNo)}/replies`,
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('ticket-reply', [
              ticketNo,
              input.content,
              input.attachments.map((item) => item.fileId)
            ])
          },
          body: JSON.stringify(toReplyTicketRequestBody(input))
        }
      );

      try {
        const detail = await getTicketDetail(ticketNo);
        const replyId =
          typeof data === 'object' && data !== null && 'reply_no' in data
            ? String((data as { reply_no?: unknown }).reply_no ?? '')
            : typeof data === 'object' && data !== null && 'replyNo' in data
              ? String((data as { replyNo?: unknown }).replyNo ?? '')
              : '';
        const matchedReply = detail.replies.find((item) => item.replyNo === replyId) ?? detail.replies.at(-1);
        if (matchedReply) {
          return matchedReply;
        }
      } catch {
        // fall back to the immediate POST response when the detail endpoint lags
      }

      return mapTicketReply({
        ...(typeof data === 'object' && data !== null ? data : {}),
        content: input.content,
        attachments: input.attachments.map((item) => ({
          file_id: item.fileId,
          file_name: item.fileName,
          mime_type: item.mimeType,
          size: item.size
        })),
        created_at: now(),
        operator_type: 'user'
      });
    },

    async createRefund(input: CreateRefundRequest): Promise<RefundRecord> {
      const timestamp = now();
      const data = await options.client.request<OwnedNamedResourceInput<RefundRecordContract, 'refund'>>(
        `/api/v1/orders/${encodeURIComponent(input.orderNo)}/refunds`,
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('refund-create', [
              input.orderNo,
              input.amount,
              input.reason,
              input.attachments.map((item) => item.fileId)
            ])
          },
          body: JSON.stringify(toCreateRefundRequestBody(input))
        }
      );

      return mapRefundRecord({
        ...(typeof data === 'object' && data !== null ? data : {}),
        order_no: input.orderNo,
        requested_amount: input.amount,
        created_at: timestamp,
        currency: 'CNY',
        timeline: [
          {
            status:
              typeof data === 'object' && data !== null && 'status' in data
                ? (data as { status?: RefundRecord['status'] }).status ?? 'pending_review'
                : 'pending_review',
            at: timestamp,
            operator_type: 'user',
            note: input.reason
          }
        ]
      });
    },

    async checkIcpMaterials(input: CheckIcpMaterialsRequest): Promise<IcpMaterialCheckResult> {
      const data = await options.client.request<
        OwnedNamedResourceInput<IcpMaterialCheckResultContract, 'check_result'>
      >('/api/v1/icp/materials/check', {
        method: 'POST',
        body: JSON.stringify(toCheckIcpMaterialsRequestBody(input))
      });

      return mapIcpMaterialCheckResult(data);
    },

    async createIcpApplication(input: CreateIcpApplicationRequest): Promise<IcpApplication> {
      const data = await options.client.request<
        OwnedNamedResourceInput<IcpApplicationContract, 'application' | 'icp_application'>
      >('/api/v1/icp/applications', {
        method: 'POST',
        headers: {
          'Idempotency-Key': options.createIdempotencyKey('icp-application', [
            input.subjectType,
            input.domain,
            input.websiteName,
            input.contacts,
            input.materials.map((item) => [item.fileId, item.type, item.required])
          ])
        },
        body: JSON.stringify(toCreateIcpApplicationRequestBody(input))
      });

      const application = mapIcpApplication({
        ...(typeof data === 'object' && data !== null ? data : {}),
        subject_type: input.subjectType,
        domain: input.domain,
        website_name: input.websiteName,
        contacts: input.contacts,
        materials: input.materials.map((item) => ({
          file_id: item.fileId,
          file_name: item.fileName,
          type: item.type,
          status: item.status,
          required: item.required
        })),
        submitted_at: now()
      });

      options.icpTrackingStore?.remember?.(application.applicationNo);
      return application;
    }
  };
}

export interface CreateFileApiOptions {
  client: RequestClient | FrontendApiClient;
  createIdempotencyKey: (scope: string, parts: unknown[]) => string;
}

export function createFileApi(options: CreateFileApiOptions) {
  return {
    async getUploadPolicy(input: UploadPolicyRequest): Promise<UploadPolicy> {
      const data = await options.client.request<
        OwnedNamedResourceInput<FileUploadPolicyContract, 'policy' | 'upload_policy'>
      >('/api/v1/files/upload-policy', {
        method: 'POST',
        headers: {
          'Idempotency-Key': options.createIdempotencyKey('file-upload-policy', [
            input.bizType,
            input.fileName,
            input.size,
            input.mimeType
          ])
        },
        body: JSON.stringify(toUploadPolicyRequestBody(input))
      });

      return mapUploadPolicy(data);
    },

    async completeUpload(input: CompleteUploadRequest): Promise<FileRecord> {
      const data = await options.client.request<OwnedNamedResourceInput<FileRecordContract, 'file'>>(
        '/api/v1/files/complete',
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('file-complete', [
              input.fileId,
              input.objectKey,
              input.checksum,
              input.size
            ])
          },
          body: JSON.stringify(toCompleteUploadRequestBody(input))
        }
      );

      return mapFileRecord(data);
    },

    async getFile(fileId: string): Promise<FileRecord> {
      const data = await options.client.request<OwnedNamedResourceInput<FileRecordContract, 'file'>>(
        `/api/v1/files/${encodeURIComponent(fileId)}`
      );
      return mapFileRecord(data);
    },

    async deleteFile(fileId: string): Promise<{ success: true }> {
      await options.client.request(`/api/v1/files/${encodeURIComponent(fileId)}`, {
        method: 'DELETE'
      });

      return { success: true };
    }
  };
}

export interface CreateCitationApiOptions {
  client: RequestClient | FrontendApiClient;
}

export function createCitationApi(options: CreateCitationApiOptions) {
  return {
    async getCitationDetail(citationId: string): Promise<CitationDetail> {
      const data = await options.client.request<
        OwnedNamedResourceInput<CitationDetailContract, 'citation' | 'detail'>
      >(`/api/v1/citations/${encodeURIComponent(citationId)}`);
      return mapCitationDetail(data);
    }
  };
}
