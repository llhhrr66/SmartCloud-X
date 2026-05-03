import {
  buildMarketingCopyResultFromGenerateResponse,
  buildPosterTaskFromCreateResponse,
  mapMarketingCampaign,
  mapMarketingCopyResult,
  mapPosterTask,
  toCreatePosterTaskRequestBody,
  toMarketingCopyRequestBody,
  type CreatePosterTaskRequest,
  type MarketingCampaign,
  type MarketingCopyRequest,
  type MarketingCopyResult,
  type PosterTask,
} from "@smartcloud-x/frontend-sdk/web-user";

import { apiClient } from "./sdk";
import { createIdempotencyKey } from "./request-meta";

interface PaginatedResp<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

function pickItems(data: any): any[] {
  return Array.isArray(data?.items) ? data.items
       : Array.isArray(data?.list)  ? data.list
       : Array.isArray(data?.data?.items) ? data.data.items
       : [];
}

function pickPage(data: any, fallback: { page: number; pageSize: number }): { total: number; page: number; pageSize: number } {
  const root = data?.data ?? data ?? {};
  const meta = root?.meta?.pagination ?? root?.pagination ?? {};
  return {
    total: Number(root.total ?? meta.total ?? pickItems(data).length),
    page: Number(root.page ?? meta.page ?? fallback.page),
    pageSize: Number(root.page_size ?? root.pageSize ?? meta.page_size ?? meta.pageSize ?? fallback.pageSize),
  };
}

export const marketingService = {
  async listCampaigns(page = 1, pageSize = 12): Promise<PaginatedResp<MarketingCampaign>> {
    const data = await apiClient.request<any>(`/api/v1/marketing/campaigns?page=${page}&page_size=${pageSize}`);
    const items = pickItems(data).map(mapMarketingCampaign);
    return { items, ...pickPage(data, { page, pageSize }) };
  },

  async listPosterTasks(page = 1, pageSize = 12): Promise<PaginatedResp<PosterTask>> {
    const data = await apiClient.request<any>(`/api/v1/marketing/posters?page=${page}&page_size=${pageSize}`);
    const items = pickItems(data).map(mapPosterTask);
    return { items, ...pickPage(data, { page, pageSize }) };
  },

  async getPosterTask(taskId: string): Promise<PosterTask> {
    const data = await apiClient.request<any>(`/api/v1/marketing/posters/${encodeURIComponent(taskId)}`);
    return mapPosterTask(data);
  },

  async generateCopy(input: MarketingCopyRequest): Promise<MarketingCopyResult> {
    const data = await apiClient.request<any>("/api/v1/marketing/copy/generate", {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("marketing-copy", [input.campaignId, input.topic, input.audience, input.tone, input.keywords.join(",")]),
      },
      body: JSON.stringify(toMarketingCopyRequestBody(input)),
    });
    return buildMarketingCopyResultFromGenerateResponse(data, input);
  },

  async createPosterTask(input: CreatePosterTaskRequest): Promise<PosterTask> {
    const data = await apiClient.request<any>("/api/v1/marketing/posters", {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("marketing-poster", [input.campaignId, input.theme, input.slogan, input.size]),
      },
      body: JSON.stringify(toCreatePosterTaskRequestBody(input)),
    });
    return buildPosterTaskFromCreateResponse(data, input);
  },
};
