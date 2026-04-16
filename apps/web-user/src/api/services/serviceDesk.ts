import { appEnv } from '../../config/env';
import type {
  CheckIcpMaterialsRequest,
  CreateIcpApplicationRequest,
  CreateRefundRequest,
  CreateTicketRequest,
  IcpApplication,
  IcpApplicationListQuery,
  IcpApplicationListResult,
  IcpMaterialCheckResult,
  OrderDetail,
  ReplyTicketRequest,
  RefundRecord,
  ServiceWorkspaceData,
  TicketDetail,
  TicketReply,
  TicketRecord
} from '../../types/domain';
import { buildIcpApplicationListResult, paginateBusinessItems } from '../../shared-sdk';
import { liveBusinessApis } from '../business-sdk';
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

export const serviceDeskService = {
  async getWorkspace(): Promise<ServiceWorkspaceData> {
    if (appEnv.useMockApi) {
      return mockGetServiceWorkspace();
    }

    return liveBusinessApis.serviceDesk.getWorkspace();
  },

  async listIcpApplications(query: IcpApplicationListQuery = {}): Promise<IcpApplication[]> {
    if (appEnv.useMockApi) {
      return paginateBusinessItems(await mockListIcpApplications(), query).items;
    }

    return liveBusinessApis.icp.listIcpApplications(query);
  },

  async listIcpApplicationPage(
    query: IcpApplicationListQuery = {}
  ): Promise<IcpApplicationListResult> {
    if (appEnv.useMockApi) {
      return buildIcpApplicationListResult(
        paginateBusinessItems(await mockListIcpApplications(), query)
      );
    }

    return liveBusinessApis.icp.listIcpApplicationPage(query);
  },

  async getTicketDetail(ticketNo: string): Promise<TicketDetail> {
    if (appEnv.useMockApi) {
      return mockGetTicketDetail(ticketNo);
    }

    return liveBusinessApis.tickets.getTicketDetail(ticketNo);
  },

  async getOrderDetail(orderNo: string): Promise<OrderDetail> {
    if (appEnv.useMockApi) {
      return mockGetOrderDetail(orderNo);
    }

    return liveBusinessApis.orders.getOrderDetail(orderNo);
  },

  async getRefundDetail(refundNo: string): Promise<RefundRecord> {
    if (appEnv.useMockApi) {
      return mockGetRefundDetail(refundNo);
    }

    return liveBusinessApis.orders.getRefundDetail(refundNo);
  },

  async createTicket(input: CreateTicketRequest): Promise<TicketRecord> {
    if (appEnv.useMockApi) {
      return mockCreateTicket(input);
    }

    return liveBusinessApis.tickets.createTicket(input);
  },

  async replyTicket(ticketNo: string, input: ReplyTicketRequest): Promise<TicketReply> {
    if (appEnv.useMockApi) {
      return mockReplyTicket(ticketNo, input);
    }

    return liveBusinessApis.tickets.replyTicket(ticketNo, input);
  },

  async createRefund(input: CreateRefundRequest): Promise<RefundRecord> {
    if (appEnv.useMockApi) {
      return mockCreateRefund(input);
    }

    return liveBusinessApis.orders.createRefund(input);
  },

  async checkIcpMaterials(input: CheckIcpMaterialsRequest): Promise<IcpMaterialCheckResult> {
    if (appEnv.useMockApi) {
      return mockCheckIcpMaterials(input);
    }

    return liveBusinessApis.icp.checkIcpMaterials(input);
  },

  async createIcpApplication(input: CreateIcpApplicationRequest): Promise<IcpApplication> {
    if (appEnv.useMockApi) {
      return mockCreateIcpApplication(input);
    }

    return liveBusinessApis.icp.createIcpApplication(input);
  }
};
