import { appEnv } from '../../config/env';
import { createIdempotencyKey } from '../../lib/request-meta';
import { listTaskIds, rememberTask } from '../../lib/task-registry';
import type {
  CheckIcpMaterialsRequest,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  IcpApplication,
  IcpMaterialCheckResult,
  OrderDetail,
  ReplyTicketRequest,
  RefundRecord,
  ServiceWorkspaceData,
  TicketDetail,
  TicketReply,
  TicketRecord
} from '../../types/domain';
import { createServiceDeskApi } from '../../shared-sdk';
import { apiClient } from '../client';
import {
  mockCheckIcpMaterials,
  mockCreateIcpApplication,
  mockCreateRefund,
  mockCreateTicket,
  mockGetOrderDetail,
  mockGetRefundDetail,
  mockGetServiceWorkspace,
  mockGetTicketDetail,
  mockListIcpApplications,
  mockReplyTicket
} from '../mock';

const liveServiceDeskService = createServiceDeskApi({
  client: apiClient,
  createIdempotencyKey,
  icpTrackingStore: {
    list: () => listTaskIds('icp'),
    remember: (applicationNo) => rememberTask('icp', applicationNo)
  }
});

export const serviceDeskService = {
  async getWorkspace(): Promise<ServiceWorkspaceData> {
    if (appEnv.useMockApi) {
      return mockGetServiceWorkspace();
    }

    return liveServiceDeskService.getWorkspace();
  },

  async listIcpApplications(): Promise<IcpApplication[]> {
    if (appEnv.useMockApi) {
      return mockListIcpApplications();
    }

    return liveServiceDeskService.listIcpApplications();
  },

  async getTicketDetail(ticketNo: string): Promise<TicketDetail> {
    if (appEnv.useMockApi) {
      return mockGetTicketDetail(ticketNo);
    }

    return liveServiceDeskService.getTicketDetail(ticketNo);
  },

  async getOrderDetail(orderNo: string): Promise<OrderDetail> {
    if (appEnv.useMockApi) {
      return mockGetOrderDetail(orderNo);
    }

    return liveServiceDeskService.getOrderDetail(orderNo);
  },

  async getRefundDetail(refundNo: string): Promise<RefundRecord> {
    if (appEnv.useMockApi) {
      return mockGetRefundDetail(refundNo);
    }

    return liveServiceDeskService.getRefundDetail(refundNo);
  },

  async createTicket(input: CreateTicketRequest): Promise<TicketRecord> {
    if (appEnv.useMockApi) {
      return mockCreateTicket(input);
    }

    return liveServiceDeskService.createTicket(input);
  },

  async replyTicket(ticketNo: string, input: ReplyTicketRequest): Promise<TicketReply> {
    if (appEnv.useMockApi) {
      return mockReplyTicket(ticketNo, input);
    }

    return liveServiceDeskService.replyTicket(ticketNo, input);
  },

  async createRefund(input: CreateRefundRequest): Promise<RefundRecord> {
    if (appEnv.useMockApi) {
      return mockCreateRefund(input);
    }

    return liveServiceDeskService.createRefund(input);
  },

  async checkIcpMaterials(input: CheckIcpMaterialsRequest): Promise<IcpMaterialCheckResult> {
    if (appEnv.useMockApi) {
      return mockCheckIcpMaterials(input);
    }

    return liveServiceDeskService.checkIcpMaterials(input);
  },

  async createIcpApplication(input: CreateIcpApplicationRequest): Promise<IcpApplication> {
    if (appEnv.useMockApi) {
      return mockCreateIcpApplication(input);
    }

    return liveServiceDeskService.createIcpApplication(input);
  }
};
