import type {
  BillingDashboard,
  BillingDashboardLoadDomain,
  BillingDetailItem,
  BillingDetailListQueryInput,
  BillingDetailPage,
  BillingSummary,
  BillingSummaryQueryInput,
  BusinessPageQueryInput,
  CheckIcpMaterialsRequest,
  CitationDetail,
  CompleteUploadRequest,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  FileRecord,
  IcpApplication,
  IcpApplicationPage,
  IcpApplicationListResult,
  IcpApplicationListQueryInput,
  IcpMaterialCheckResult,
  InvoiceRecord,
  InvoiceRecordPage,
  OrderDetail,
  OrderListQueryInput,
  OrderRecord,
  OrderRecordPage,
  RefundListQueryInput,
  RefundRecord,
  RefundRecordPage,
  ReplyTicketRequest,
  ServiceWorkspaceLoadDomain,
  ServiceWorkspaceData,
  SharedDomainErrorInfo,
  TicketDetail,
  TicketListQueryInput,
  TicketRecord,
  TicketRecordPage,
  TicketReply,
  UploadPolicy,
  UploadPolicyRequest
} from './business-types';
import type { FrontendApiClient } from '../core/http';
import { asRecord, isRecord } from '../core/utils';
import type { Citation } from './types';
import {
  normalizeBillingDetailListQuery,
  normalizeBillingSummaryQuery,
  normalizeBusinessPageQuery,
  normalizeCompleteUploadRequest,
  normalizeCreateIcpApplicationRequest,
  normalizeCreateRefundRequest,
  normalizeCreateTicketRequest,
  normalizeReplyTicketRequest,
  normalizeUploadPolicyRequest
} from './business-normalizers';
import {
  buildIcpApplicationListResult,
  extractFileNameFromObjectKey,
  paginateBusinessItems
} from './business-state';
import {
  buildBillingDashboard,
  mapBillingDetailPage,
  mapBillingSummary,
  mapCitationDetail,
  mapFileRecord,
  mapIcpApplication,
  mapIcpApplicationPage,
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
import {
  citationDetailResourceKeys,
  fileRecordResourceKeys,
  icpApplicationResourceKeys,
  refundRecordResourceKeys,
  ticketRecordResourceKeys,
  ticketReplyResourceKeys
} from './business-resource-aliases';
import type {
  BillingDetailPageResponseContract,
  IcpApplicationPageResponseContract,
  BillingSummaryResponseContract,
  CitationDetailResponseContract,
  FileRecordResponseContract,
  FileUploadPolicyResponseContract,
  IcpApplicationResponseContract,
  IcpMaterialCheckResultResponseContract,
  InvoiceRecordPageResponseContract,
  OrderDetailResponseContract,
  OwnedBusinessPageQueryContract,
  OrderRecordPageResponseContract,
  OwnedNamedResourceInput,
  RefundRecordPageResponseContract,
  RefundRecordResponseContract,
  TicketDetailResponseContract,
  TicketRecordPageResponseContract,
  TicketRecordResponseContract,
  TicketReplyResponseContract
} from './business-contracts';
import { ApiError, classifyApiError, describeApiError } from '../core/envelope';

export interface RequestClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export const webUserBusinessRoutes = {
  billingSummary: '/api/v1/billing/summary',
  billingDetails: '/api/v1/billing/details',
  billingInvoices: '/api/v1/billing/invoices',
  orders: '/api/v1/orders',
  orderDetail: (orderNo: string) => `/api/v1/orders/${encodeURIComponent(orderNo)}`,
  orderRefunds: (orderNo: string) => `/api/v1/orders/${encodeURIComponent(orderNo)}/refunds`,
  refunds: '/api/v1/refunds',
  refundDetail: (refundNo: string) => `/api/v1/refunds/${encodeURIComponent(refundNo)}`,
  tickets: '/api/v1/tickets',
  ticketDetail: (ticketNo: string) => `/api/v1/tickets/${encodeURIComponent(ticketNo)}`,
  ticketReplies: (ticketNo: string) => `/api/v1/tickets/${encodeURIComponent(ticketNo)}/replies`,
  icpMaterialsCheck: '/api/v1/icp/materials/check',
  icpApplications: '/api/v1/icp/applications',
  icpApplicationDetail: (applicationNo: string) =>
    `/api/v1/icp/applications/${encodeURIComponent(applicationNo)}`,
  filesUploadPolicy: '/api/v1/files/upload-policy',
  filesComplete: '/api/v1/files/complete',
  fileDetail: (fileId: string) => `/api/v1/files/${encodeURIComponent(fileId)}`,
  citationDetail: (citationId: string) => `/api/v1/citations/${encodeURIComponent(citationId)}`
} as const;

export interface CreateBillingApiOptions {
  client: RequestClient | FrontendApiClient;
  now?: () => Date;
}

function buildDomainErrorMap<TDomain extends string>(
  entries: Array<readonly [TDomain, SharedDomainErrorInfo | undefined]>
): Partial<Record<TDomain, SharedDomainErrorInfo>> | undefined {
  const filtered = entries.filter(
    (entry): entry is readonly [TDomain, SharedDomainErrorInfo] => entry[1] !== undefined
  );

  if (!filtered.length) {
    return undefined;
  }

  return Object.fromEntries(filtered) as Partial<Record<TDomain, SharedDomainErrorInfo>>;
}

export interface BillingApi {
  getSummary(query?: BillingSummaryQueryInput): Promise<BillingSummary>;
  listBillingDetails(query?: BillingDetailListQueryInput): Promise<BillingDetailPage>;
  listInvoices(query?: BusinessPageQueryInput): Promise<InvoiceRecordPage>;
  listOrders(query?: OrderListQueryInput): Promise<OrderRecordPage>;
  listTickets(query?: TicketListQueryInput): Promise<TicketRecordPage>;
  getDashboard(): Promise<BillingDashboard>;
}

function buildBusinessQueryPath(
  path: string,
  query: Record<string, string | number | undefined>
): string {
  const params = new URLSearchParams();

  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '') {
      params.set(key, String(value));
    }
  }

  return params.size ? `${path}?${params.toString()}` : path;
}

function buildBusinessPagePath(
  path: string,
  query: Required<OwnedBusinessPageQueryContract>,
  extras: Record<string, string | undefined> = {}
): string {
  return buildBusinessQueryPath(path, {
    page: query.page,
    page_size: query.page_size,
    ...extras
  });
}

function mergeNamedResourceFallback<TContract, TName extends string>(
  value: OwnedNamedResourceInput<TContract, TName>,
  keys: readonly (TName | 'result' | 'record')[],
  fallback: Record<string, unknown>
): OwnedNamedResourceInput<TContract, TName> {
  const record = asRecord(value);

  for (const key of keys) {
    if (isRecord(record[key])) {
      return {
        ...record,
        [key]: {
          ...fallback,
          ...asRecord(record[key])
        }
      } as OwnedNamedResourceInput<TContract, TName>;
    }
  }

  if (isRecord(record.data)) {
    const dataRecord = asRecord(record.data);

    for (const key of keys) {
      if (isRecord(dataRecord[key])) {
        return {
          ...record,
          data: {
            ...dataRecord,
            [key]: {
              ...fallback,
              ...asRecord(dataRecord[key])
            }
          }
        } as OwnedNamedResourceInput<TContract, TName>;
      }
    }

    return {
      ...record,
      data: {
        ...fallback,
        ...dataRecord
      }
    } as OwnedNamedResourceInput<TContract, TName>;
  }

  return {
    ...fallback,
    ...record
  } as OwnedNamedResourceInput<TContract, TName>;
}

export function createBillingApi(options: CreateBillingApiOptions): BillingApi {
  async function getSummary(
    query: BillingSummaryQueryInput = {}
  ): Promise<BillingSummary> {
    const normalizedQuery = normalizeBillingSummaryQuery(query);
    const data = await options.client.request<BillingSummaryResponseContract>(
      buildBusinessQueryPath(webUserBusinessRoutes.billingSummary, {
        range: normalizedQuery.range
      })
    );
    return mapBillingSummary(data);
  }

  async function listBillingDetails(
    query: BillingDetailListQueryInput = {}
  ): Promise<BillingDetailPage> {
    const normalizedQuery = normalizeBillingDetailListQuery(
      query,
      options.now ? options.now() : new Date()
    );
    const data = await options.client.request<BillingDetailPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.billingDetails, normalizedQuery, {
        billing_cycle: normalizedQuery.billing_cycle
      })
    );
    return mapBillingDetailPage(data);
  }

  async function listInvoices(
    query: BusinessPageQueryInput = {}
  ): Promise<InvoiceRecordPage> {
    const data = await options.client.request<InvoiceRecordPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.billingInvoices, normalizeBusinessPageQuery(query))
    );
    return mapInvoiceRecordPage(data);
  }

  async function listOrders(
    query: OrderListQueryInput = {}
  ): Promise<OrderRecordPage> {
    const data = await options.client.request<OrderRecordPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.orders, normalizeBusinessPageQuery(query))
    );
    return mapOrderRecordPage(data);
  }

  async function listTickets(
    query: TicketListQueryInput = {}
  ): Promise<TicketRecordPage> {
    const data = await options.client.request<TicketRecordPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.tickets, normalizeBusinessPageQuery(query))
    );
    return mapTicketRecordPage(data);
  }

  return {
    getSummary,

    listBillingDetails,

    listInvoices,

    listOrders,

    listTickets,

    async getDashboard(): Promise<BillingDashboard> {
      const [summaryResult, detailsResult, invoicesResult, ordersResult, ticketsResult] = await Promise.allSettled([
        getSummary(),
        listBillingDetails({ page: 1, pageSize: 5 }),
        listInvoices({ page: 1, pageSize: 5 }),
        listOrders({ page: 1, pageSize: 5 }),
        listTickets({ page: 1, pageSize: 5 })
      ]);

      const failedDomains: BillingDashboardLoadDomain[] = [];

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

      const domainErrors = buildDomainErrorMap<BillingDashboardLoadDomain>([
        [
          'summary',
          summaryResult.status === 'rejected'
            ? describeApiError(summaryResult.reason, '加载账单汇总失败')
            : undefined
        ],
        [
          'details',
          detailsResult.status === 'rejected'
            ? describeApiError(detailsResult.reason, '加载账单明细失败')
            : undefined
        ],
        [
          'invoices',
          invoicesResult.status === 'rejected'
            ? describeApiError(invoicesResult.reason, '加载发票列表失败')
            : undefined
        ],
        [
          'orders',
          ordersResult.status === 'rejected'
            ? describeApiError(ordersResult.reason, '加载订单列表失败')
            : undefined
        ],
        [
          'tickets',
          ticketsResult.status === 'rejected'
            ? describeApiError(ticketsResult.reason, '加载工单列表失败')
            : undefined
        ]
      ]);

      return buildBillingDashboard({
        summary: summaryResult.status === 'fulfilled' ? summaryResult.value : undefined,
        details: detailsResult.status === 'fulfilled' ? detailsResult.value.items : undefined,
        invoices: invoicesResult.status === 'fulfilled' ? invoicesResult.value.items : undefined,
        orders: ordersResult.status === 'fulfilled' ? ordersResult.value.items : undefined,
        tickets: ticketsResult.status === 'fulfilled' ? ticketsResult.value.items : undefined,
        failedDomains,
        domainErrors
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

export interface ServiceDeskApi {
  listOrders(query?: OrderListQueryInput): Promise<OrderRecordPage>;
  listRefunds(query?: RefundListQueryInput): Promise<RefundRecordPage>;
  listTickets(query?: TicketListQueryInput): Promise<TicketRecordPage>;
  getWorkspace(): Promise<ServiceWorkspaceData>;
  listIcpApplicationPage(query?: IcpApplicationListQueryInput): Promise<IcpApplicationListResult>;
  listIcpApplications(query?: IcpApplicationListQueryInput): Promise<IcpApplication[]>;
  getTicketDetail(ticketNo: string): Promise<TicketDetail>;
  getOrderDetail(orderNo: string): Promise<OrderDetail>;
  getRefundDetail(refundNo: string): Promise<RefundRecord>;
  createTicket(input: CreateTicketRequest): Promise<TicketRecord>;
  replyTicket(ticketNo: string, input: ReplyTicketRequest): Promise<TicketReply>;
  createRefund(input: CreateRefundRequest): Promise<RefundRecord>;
  checkIcpMaterials(input: CheckIcpMaterialsRequest): Promise<IcpMaterialCheckResult>;
  createIcpApplication(input: CreateIcpApplicationRequest): Promise<IcpApplication>;
}

export interface OrderApi {
  listOrders(query?: OrderListQueryInput): Promise<OrderRecordPage>;
  listRefunds(query?: RefundListQueryInput): Promise<RefundRecordPage>;
  getOrderDetail(orderNo: string): Promise<OrderDetail>;
  getRefundDetail(refundNo: string): Promise<RefundRecord>;
  createRefund(input: CreateRefundRequest): Promise<RefundRecord>;
}

export interface TicketApi {
  listTickets(query?: TicketListQueryInput): Promise<TicketRecordPage>;
  getTicketDetail(ticketNo: string): Promise<TicketDetail>;
  createTicket(input: CreateTicketRequest): Promise<TicketRecord>;
  replyTicket(ticketNo: string, input: ReplyTicketRequest): Promise<TicketReply>;
}

export interface IcpApi {
  listIcpApplicationPage(query?: IcpApplicationListQueryInput): Promise<IcpApplicationListResult>;
  listIcpApplications(query?: IcpApplicationListQueryInput): Promise<IcpApplication[]>;
  checkIcpMaterials(input: CheckIcpMaterialsRequest): Promise<IcpMaterialCheckResult>;
  createIcpApplication(input: CreateIcpApplicationRequest): Promise<IcpApplication>;
}

interface IcpApplicationLoadResult {
  applications?: IcpApplication[];
  page: IcpApplicationListResult;
  failed: boolean;
  fallbackUsed: boolean;
  errorInfo?: SharedDomainErrorInfo;
}

export function createServiceDeskApi(options: CreateServiceDeskApiOptions): ServiceDeskApi {
  const now = () => (options.now ? options.now() : new Date().toISOString());

  function sortIcpApplicationsByUpdatedAt(applications: IcpApplication[]): IcpApplication[] {
    return [...applications].sort(
      (left, right) =>
        new Date(right.submittedAt ?? right.approvedAt ?? 0).getTime() -
        new Date(left.submittedAt ?? left.approvedAt ?? 0).getTime()
    );
  }

  function mergeIcpApplications(
    primary: IcpApplication[],
    secondary: IcpApplication[]
  ): IcpApplication[] {
    const merged = new Map<string, IcpApplication>();

    for (const application of secondary) {
      merged.set(application.applicationNo, application);
    }

    for (const application of primary) {
      const existing = merged.get(application.applicationNo);
      merged.set(application.applicationNo, existing ? { ...existing, ...application } : application);
    }

    return sortIcpApplicationsByUpdatedAt([...merged.values()]);
  }

  function shouldFallbackToTrackedIcpApplications(error: unknown): boolean {
    if (error instanceof Error && !(error instanceof ApiError)) {
      return true;
    }

    const kind = classifyApiError(error);
    return (
      kind === 'not_found' ||
      kind === 'server' ||
      kind === 'timeout' ||
      kind === 'rate_limited' ||
      kind === 'unknown'
    );
  }

  function rememberIcpApplications(applications: IcpApplication[]): IcpApplication[] {
    for (const application of applications) {
      options.icpTrackingStore?.remember?.(application.applicationNo);
    }

    return applications;
  }

  function createEmptyIcpApplicationPage(query: IcpApplicationListQueryInput = {}) {
    const normalizedQuery = normalizeBusinessPageQuery(query);
    return {
      items: [],
      page: normalizedQuery.page,
      pageSize: normalizedQuery.page_size,
      total: 0,
      totalPages: 0
    };
  }

  async function getIcpApplication(applicationNo: string): Promise<IcpApplication> {
    const data = await options.client.request<IcpApplicationResponseContract>(
      webUserBusinessRoutes.icpApplicationDetail(applicationNo)
    );
    return rememberIcpApplications([
      mapIcpApplication(
        mergeNamedResourceFallback(
          data,
          icpApplicationResourceKeys,
          {
            application_no: applicationNo
          }
        )
      )
    ])[0];
  }

  async function loadTrackedIcpApplications(
    applicationIds: string[],
    query: IcpApplicationListQueryInput = {}
  ): Promise<IcpApplicationLoadResult> {
    if (!applicationIds.length) {
      return {
        applications: [],
        page: buildIcpApplicationListResult(createEmptyIcpApplicationPage(query)),
        failed: false,
        fallbackUsed: false
      };
    }

    const settled = await Promise.allSettled(applicationIds.map((applicationNo) => getIcpApplication(applicationNo)));
    const applications = sortIcpApplicationsByUpdatedAt(
      settled
      .filter((item): item is PromiseFulfilledResult<IcpApplication> => item.status === 'fulfilled')
      .map((item) => item.value)
    );
    const hadFailures = settled.some((item) => item.status === 'rejected');
    const firstRejected = settled.find(
      (item): item is PromiseRejectedResult => item.status === 'rejected'
    );
    const errorInfo = firstRejected
      ? describeApiError(firstRejected.reason, '加载 ICP 申请详情失败')
      : undefined;

    return {
      applications,
      page: buildIcpApplicationListResult(
        paginateBusinessItems(applications, query),
        {
          degraded: hadFailures,
          fallbackUsed: true,
          errorInfo
        }
      ),
      failed: hadFailures && applications.length === 0,
      fallbackUsed: true,
      errorInfo
    };
  }

  async function listIcpApplications(query: IcpApplicationListQueryInput = {}): Promise<IcpApplication[]> {
    const result = await loadIcpApplicationPage(query);
    return result.page.items;
  }

  async function listLiveIcpApplicationPage(
    query: IcpApplicationListQueryInput = {}
  ): Promise<IcpApplicationPage> {
    const data = await options.client.request<IcpApplicationPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.icpApplications, normalizeBusinessPageQuery(query))
    );

    const page = mapIcpApplicationPage(data);
    return {
      ...page,
      items: rememberIcpApplications(page.items)
    };
  }

  async function loadIcpApplicationPage(
    query: IcpApplicationListQueryInput = {}
  ): Promise<IcpApplicationLoadResult> {
    const normalizedQuery = normalizeBusinessPageQuery(query);
    const pageQuery: IcpApplicationListQueryInput = {
      page: normalizedQuery.page,
      pageSize: normalizedQuery.page_size
    };
    const applicationIds = options.icpTrackingStore?.list() ?? [];
    const canSupplementLivePage = normalizedQuery.page <= 1;

    try {
      const livePage = await listLiveIcpApplicationPage(pageQuery);
      if (!canSupplementLivePage || !applicationIds.length) {
        return {
          page: buildIcpApplicationListResult(livePage),
          failed: false,
          fallbackUsed: false
        };
      }

      const missingTrackedIds = applicationIds.filter(
        (applicationNo) => !livePage.items.some((item) => item.applicationNo === applicationNo)
      );

      if (!missingTrackedIds.length) {
        return {
          page: buildIcpApplicationListResult(livePage),
          failed: false,
          fallbackUsed: false
        };
      }

      const trackedResult = await loadTrackedIcpApplications(missingTrackedIds, pageQuery);
      const mergedApplications = mergeIcpApplications(livePage.items, trackedResult.applications ?? []);
      const mergedTotal = Math.max(livePage.total, mergedApplications.length);

      return {
        applications: mergedApplications,
        page: buildIcpApplicationListResult(
          paginateBusinessItems(mergedApplications, pageQuery, {
            total: mergedTotal
          }),
          {
            degraded: trackedResult.page.loadState.degraded,
            fallbackUsed: true,
            errorInfo: trackedResult.errorInfo
          }
        ),
        failed: trackedResult.failed,
        fallbackUsed: trackedResult.fallbackUsed,
        errorInfo: trackedResult.errorInfo
      };
    } catch (error) {
      const liveErrorInfo = describeApiError(error, '加载 ICP 申请列表失败');

      if (!shouldFallbackToTrackedIcpApplications(error)) {
        throw error;
      }

      if (!applicationIds.length) {
        return {
          applications: [],
          page: buildIcpApplicationListResult(createEmptyIcpApplicationPage(pageQuery), {
            degraded: true,
            fallbackUsed: false,
            errorInfo: liveErrorInfo
          }),
          failed: true,
          fallbackUsed: false,
          errorInfo: liveErrorInfo
        };
      }

      const trackedResult = await loadTrackedIcpApplications(applicationIds, pageQuery);

      return {
        ...trackedResult,
        page: buildIcpApplicationListResult(trackedResult.page, {
          degraded: trackedResult.page.loadState.degraded,
          fallbackUsed: true,
          errorInfo: trackedResult.errorInfo ?? liveErrorInfo
        }),
        fallbackUsed: true,
        errorInfo: trackedResult.errorInfo ?? liveErrorInfo
      };
    }
  }

  async function getTicketDetail(ticketNo: string): Promise<TicketDetail> {
    const data = await options.client.request<TicketDetailResponseContract>(
      webUserBusinessRoutes.ticketDetail(ticketNo)
    );
    return mapTicketDetail(data, ticketNo);
  }

  async function listOrders(
    query: OrderListQueryInput = {}
  ): Promise<OrderRecordPage> {
    const data = await options.client.request<OrderRecordPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.orders, normalizeBusinessPageQuery(query))
    );
    return mapOrderRecordPage(data);
  }

  async function listRefunds(
    query: RefundListQueryInput = {}
  ): Promise<RefundRecordPage> {
    const data = await options.client.request<RefundRecordPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.refunds, normalizeBusinessPageQuery(query))
    );
    return mapRefundRecordPage(data);
  }

  async function listTickets(
    query: TicketListQueryInput = {}
  ): Promise<TicketRecordPage> {
    const data = await options.client.request<TicketRecordPageResponseContract>(
      buildBusinessPagePath(webUserBusinessRoutes.tickets, normalizeBusinessPageQuery(query))
    );
    return mapTicketRecordPage(data);
  }

  return {
    listOrders,

    listRefunds,

    listTickets,

    async getWorkspace(): Promise<ServiceWorkspaceData> {
      const [ordersResult, refundsResult, ticketsResult, icpLoadResult] = await Promise.allSettled([
        listOrders({ page: 1, pageSize: 10 }),
        listRefunds({ page: 1, pageSize: 10 }),
        listTickets({ page: 1, pageSize: 10 }),
        loadIcpApplicationPage({ page: 1, pageSize: 20 })
      ]);

      const failedDomains: ServiceWorkspaceLoadDomain[] = [];

      if (ordersResult.status === 'rejected') {
        failedDomains.push('orders');
      }
      if (refundsResult.status === 'rejected') {
        failedDomains.push('refunds');
      }
      if (ticketsResult.status === 'rejected') {
        failedDomains.push('tickets');
      }
      if (
        icpLoadResult.status === 'rejected' ||
        (icpLoadResult.status === 'fulfilled' && icpLoadResult.value.page.loadState.degraded)
      ) {
        failedDomains.push('icp');
      }

      if (failedDomains.length === 4) {
        const firstFailure = [ordersResult, refundsResult, ticketsResult, icpLoadResult].find(
          (item): item is PromiseRejectedResult => item.status === 'rejected'
        );
        throw firstFailure?.reason instanceof Error ? firstFailure.reason : new Error('加载服务工作区失败');
      }

      const domainErrors = buildDomainErrorMap<ServiceWorkspaceLoadDomain>([
        [
          'orders',
          ordersResult.status === 'rejected'
            ? describeApiError(ordersResult.reason, '加载订单列表失败')
            : undefined
        ],
        [
          'refunds',
          refundsResult.status === 'rejected'
            ? describeApiError(refundsResult.reason, '加载退款列表失败')
            : undefined
        ],
        [
          'tickets',
          ticketsResult.status === 'rejected'
            ? describeApiError(ticketsResult.reason, '加载工单列表失败')
            : undefined
        ],
        [
          'icp',
          icpLoadResult.status === 'rejected'
            ? describeApiError(icpLoadResult.reason, '加载 ICP 申请失败')
            : icpLoadResult.value.page.loadState.domainErrors?.icp
        ]
      ]);

      return mapServiceWorkspaceData({
        orders: ordersResult.status === 'fulfilled' ? ordersResult.value.items : undefined,
        refunds: refundsResult.status === 'fulfilled' ? refundsResult.value.items : undefined,
        tickets: ticketsResult.status === 'fulfilled' ? ticketsResult.value.items : undefined,
        icpApplications: icpLoadResult.status === 'fulfilled' ? icpLoadResult.value.page.items : [],
        failedDomains,
        fallbackDomains:
          icpLoadResult.status === 'fulfilled' && icpLoadResult.value.fallbackUsed ? ['icp'] : [],
        domainErrors
      });
    },

    async listIcpApplicationPage(
      query: IcpApplicationListQueryInput = {}
    ): Promise<IcpApplicationListResult> {
      const result = await loadIcpApplicationPage(query);
      return result.page;
    },

    listIcpApplications,

    getTicketDetail,

    async getOrderDetail(orderNo: string): Promise<OrderDetail> {
      const data = await options.client.request<OrderDetailResponseContract>(
        webUserBusinessRoutes.orderDetail(orderNo)
      );
      return mapOrderDetail(data, orderNo);
    },

    async getRefundDetail(refundNo: string): Promise<RefundRecord> {
      const data = await options.client.request<RefundRecordResponseContract>(
        webUserBusinessRoutes.refundDetail(refundNo)
      );
      return mapRefundRecord(
        mergeNamedResourceFallback(data, refundRecordResourceKeys, {
          refund_no: refundNo
        })
      );
    },

    async createTicket(input: CreateTicketRequest): Promise<TicketRecord> {
      const normalizedInput = normalizeCreateTicketRequest(input);
      const requestBody = toCreateTicketRequestBody(normalizedInput);
      const timestamp = now();
      const data = await options.client.request<TicketRecordResponseContract>(
        webUserBusinessRoutes.tickets,
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('ticket-create', [
              normalizedInput.subject,
              normalizedInput.content,
              normalizedInput.priority,
              normalizedInput.category,
              normalizedInput.attachments.map((item) => item.fileId)
            ])
          },
          body: JSON.stringify(requestBody)
        }
      );

      return mapTicketRecord(mergeNamedResourceFallback(data, ticketRecordResourceKeys, {
        subject: normalizedInput.subject,
        content: normalizedInput.content,
        category: normalizedInput.category,
        priority: normalizedInput.priority,
        attachments: normalizedInput.attachments.map((item) => ({
          file_id: item.fileId,
          file_name: item.fileName,
          mime_type: item.mimeType,
          size: item.size
        })),
        created_at: timestamp,
        updated_at: timestamp
      }));
    },

    async replyTicket(ticketNo: string, input: ReplyTicketRequest): Promise<TicketReply> {
      const normalizedInput = normalizeReplyTicketRequest(input);
      const requestBody = toReplyTicketRequestBody(normalizedInput);
      const timestamp = now();
      const data = await options.client.request<TicketReplyResponseContract>(
        webUserBusinessRoutes.ticketReplies(ticketNo),
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('ticket-reply', [
              ticketNo,
              normalizedInput.content,
              normalizedInput.attachments.map((item) => item.fileId)
            ])
          },
          body: JSON.stringify(requestBody)
        }
      );
      const immediateReply = mapTicketReply(
        mergeNamedResourceFallback(data, ticketReplyResourceKeys, {
          content: normalizedInput.content,
          attachments: normalizedInput.attachments.map((item) => ({
            file_id: item.fileId,
            file_name: item.fileName,
            mime_type: item.mimeType,
            size: item.size
          })),
          created_at: timestamp,
          operator_type: 'user'
        })
      );

      try {
        const detail = await getTicketDetail(ticketNo);
        const matchedReply =
          detail.replies.find((item) => item.replyNo === immediateReply.replyNo) ?? detail.replies.at(-1);
        if (matchedReply) {
          return matchedReply;
        }
      } catch {
        // fall back to the immediate POST response when the detail endpoint lags
      }

      return immediateReply;
    },

    async createRefund(input: CreateRefundRequest): Promise<RefundRecord> {
      const normalizedInput = normalizeCreateRefundRequest(input);
      const requestBody = toCreateRefundRequestBody(normalizedInput);
      const timestamp = now();
      const data = await options.client.request<RefundRecordResponseContract>(
        webUserBusinessRoutes.orderRefunds(normalizedInput.orderNo),
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('refund-create', [
              normalizedInput.orderNo,
              normalizedInput.amount,
              normalizedInput.reason,
              normalizedInput.attachments.map((item) => item.fileId)
            ])
          },
          body: JSON.stringify(requestBody)
        }
      );
      const refundStatus = mapRefundRecord(data).status;

      return mapRefundRecord(mergeNamedResourceFallback(data, ['refund', 'result', 'record'], {
        order_no: normalizedInput.orderNo,
        requested_amount: normalizedInput.amount,
        created_at: timestamp,
        currency: 'CNY',
        timeline: [
          {
            status: refundStatus,
            at: timestamp,
            operator_type: 'user',
            note: normalizedInput.reason
          }
        ]
      }));
    },

    async checkIcpMaterials(input: CheckIcpMaterialsRequest): Promise<IcpMaterialCheckResult> {
      const data = await options.client.request<IcpMaterialCheckResultResponseContract>(webUserBusinessRoutes.icpMaterialsCheck, {
        method: 'POST',
        body: JSON.stringify(toCheckIcpMaterialsRequestBody(input))
      });

      return mapIcpMaterialCheckResult(data);
    },

    async createIcpApplication(input: CreateIcpApplicationRequest): Promise<IcpApplication> {
      const normalizedInput = normalizeCreateIcpApplicationRequest(input);
      const requestBody = toCreateIcpApplicationRequestBody(normalizedInput);
      const data = await options.client.request<IcpApplicationResponseContract>(webUserBusinessRoutes.icpApplications, {
        method: 'POST',
        headers: {
          'Idempotency-Key': options.createIdempotencyKey('icp-application', [
            normalizedInput.subjectType,
            normalizedInput.domain,
            normalizedInput.websiteName,
            normalizedInput.contacts,
            normalizedInput.materials.map((item) => [item.fileId, item.type, item.required])
          ])
        },
        body: JSON.stringify(requestBody)
      });

      const application = mapIcpApplication(
        mergeNamedResourceFallback(data, icpApplicationResourceKeys, {
          subject_type: normalizedInput.subjectType,
          domain: normalizedInput.domain,
          website_name: normalizedInput.websiteName,
          contacts: normalizedInput.contacts,
          materials: normalizedInput.materials.map((item) => ({
            file_id: item.fileId,
            file_name: item.fileName,
            type: item.type,
            status: item.status,
            required: item.required
          })),
          submitted_at: now()
        })
      );

      rememberIcpApplications([application]);
      return application;
    }
  };
}

function createOrderApiFromServiceDesk(serviceDesk: ServiceDeskApi): OrderApi {
  return {
    listOrders: (query) => serviceDesk.listOrders(query),
    listRefunds: (query) => serviceDesk.listRefunds(query),
    getOrderDetail: (orderNo) => serviceDesk.getOrderDetail(orderNo),
    getRefundDetail: (refundNo) => serviceDesk.getRefundDetail(refundNo),
    createRefund: (input) => serviceDesk.createRefund(input)
  };
}

function createTicketApiFromServiceDesk(serviceDesk: ServiceDeskApi): TicketApi {
  return {
    listTickets: (query) => serviceDesk.listTickets(query),
    getTicketDetail: (ticketNo) => serviceDesk.getTicketDetail(ticketNo),
    createTicket: (input) => serviceDesk.createTicket(input),
    replyTicket: (ticketNo, input) => serviceDesk.replyTicket(ticketNo, input)
  };
}

function createIcpApiFromServiceDesk(serviceDesk: ServiceDeskApi): IcpApi {
  return {
    listIcpApplicationPage: (query) => serviceDesk.listIcpApplicationPage(query),
    listIcpApplications: (query) => serviceDesk.listIcpApplications(query),
    checkIcpMaterials: (input) => serviceDesk.checkIcpMaterials(input),
    createIcpApplication: (input) => serviceDesk.createIcpApplication(input)
  };
}

export function createOrderApi(options: CreateServiceDeskApiOptions): OrderApi {
  return createOrderApiFromServiceDesk(createServiceDeskApi(options));
}

export function createTicketApi(options: CreateServiceDeskApiOptions): TicketApi {
  return createTicketApiFromServiceDesk(createServiceDeskApi(options));
}

export function createIcpApi(options: CreateServiceDeskApiOptions): IcpApi {
  return createIcpApiFromServiceDesk(createServiceDeskApi(options));
}

export interface CreateFileApiOptions {
  client: RequestClient | FrontendApiClient;
  createIdempotencyKey: (scope: string, parts: unknown[]) => string;
}

export interface FileApi {
  getUploadPolicy(input: UploadPolicyRequest): Promise<UploadPolicy>;
  completeUpload(input: CompleteUploadRequest): Promise<FileRecord>;
  getFile(fileId: string): Promise<FileRecord>;
  deleteFile(fileId: string): Promise<{ success: true }>;
}

export function createFileApi(options: CreateFileApiOptions): FileApi {
  return {
    async getUploadPolicy(input: UploadPolicyRequest): Promise<UploadPolicy> {
      const normalizedInput = normalizeUploadPolicyRequest(input);
      const requestBody = toUploadPolicyRequestBody(normalizedInput);
      const data = await options.client.request<FileUploadPolicyResponseContract>(webUserBusinessRoutes.filesUploadPolicy, {
        method: 'POST',
        headers: {
          'Idempotency-Key': options.createIdempotencyKey('file-upload-policy', [
            normalizedInput.bizType,
            normalizedInput.fileName,
            normalizedInput.size,
            normalizedInput.mimeType
          ])
        },
        body: JSON.stringify(requestBody)
      });

      return mapUploadPolicy(data);
    },

    async completeUpload(input: CompleteUploadRequest): Promise<FileRecord> {
      const normalizedInput = normalizeCompleteUploadRequest(input);
      const requestBody = toCompleteUploadRequestBody(normalizedInput);
      const data = await options.client.request<FileRecordResponseContract>(
        webUserBusinessRoutes.filesComplete,
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('file-complete', [
              normalizedInput.fileId,
              normalizedInput.objectKey,
              normalizedInput.checksum,
              normalizedInput.size
            ])
          },
          body: JSON.stringify(requestBody)
        }
      );

      return mapFileRecord(
        mergeNamedResourceFallback(data, fileRecordResourceKeys, {
          file_id: normalizedInput.fileId,
          file_name: extractFileNameFromObjectKey(normalizedInput.objectKey),
          size: normalizedInput.size
        })
      );
    },

    async getFile(fileId: string): Promise<FileRecord> {
      const data = await options.client.request<FileRecordResponseContract>(
        webUserBusinessRoutes.fileDetail(fileId)
      );
      return mapFileRecord(
        mergeNamedResourceFallback(data, fileRecordResourceKeys, {
          file_id: fileId
        })
      );
    },

    async deleteFile(fileId: string): Promise<{ success: true }> {
      await options.client.request(webUserBusinessRoutes.fileDetail(fileId), {
        method: 'DELETE'
      });

      return { success: true };
    }
  };
}

export interface CreateCitationApiOptions {
  client: RequestClient | FrontendApiClient;
}

export interface CitationApi {
  getCitationDetail(
    citationId: string,
    fallback?: Citation | Partial<CitationDetail>
  ): Promise<CitationDetail>;
}

export interface CreateWebUserBusinessApisOptions {
  client: RequestClient | FrontendApiClient;
  createIdempotencyKey: (scope: string, parts: unknown[]) => string;
  icpTrackingStore?: IcpTrackingStore;
  now?: () => string;
  billingNow?: () => Date;
}

export interface WebUserBusinessApis {
  billing: BillingApi;
  serviceDesk: ServiceDeskApi;
  orders: OrderApi;
  tickets: TicketApi;
  icp: IcpApi;
  files: FileApi;
  citations: CitationApi;
}

export function createCitationApi(options: CreateCitationApiOptions): CitationApi {
  return {
    async getCitationDetail(
      citationId: string,
      fallback?: Citation | Partial<CitationDetail>
    ): Promise<CitationDetail> {
      const fallbackDetail = fallback as Partial<CitationDetail> | undefined;
      const data = await options.client.request<CitationDetailResponseContract>(
        webUserBusinessRoutes.citationDetail(citationId)
      );
      return mapCitationDetail(
        mergeNamedResourceFallback(data, citationDetailResourceKeys, {
          citation_id: fallback?.id ?? citationId,
          title: fallback?.title,
          source_type: fallback?.sourceType,
          doc_id: fallback?.docId,
          chunk_id: fallback?.chunkId,
          url: fallback?.url,
          snippet: fallbackDetail?.snippet,
          version_no: fallbackDetail?.versionNo,
          score: fallbackDetail?.score
        })
      );
    }
  };
}

export function createWebUserBusinessApis(
  options: CreateWebUserBusinessApisOptions
): WebUserBusinessApis {
  const serviceDesk = createServiceDeskApi({
    client: options.client,
    createIdempotencyKey: options.createIdempotencyKey,
    icpTrackingStore: options.icpTrackingStore,
    now: options.now
  });

  return {
    billing: createBillingApi({
      client: options.client,
      now: options.billingNow
    }),
    serviceDesk,
    orders: createOrderApiFromServiceDesk(serviceDesk),
    tickets: createTicketApiFromServiceDesk(serviceDesk),
    icp: createIcpApiFromServiceDesk(serviceDesk),
    files: createFileApi({
      client: options.client,
      createIdempotencyKey: options.createIdempotencyKey
    }),
    citations: createCitationApi({
      client: options.client
    })
  };
}
