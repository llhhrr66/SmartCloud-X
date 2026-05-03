import {
  buildResearchTaskFromCreateResponse,
  mapResearchTask,
  toCreateResearchTaskRequestBody,
  type CreateResearchTaskRequest,
  type ResearchTask,
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

export const researchService = {
  async listTasks(page = 1, pageSize = 12): Promise<PaginatedResp<ResearchTask>> {
    const data = await apiClient.request<any>(`/api/v1/research/tasks?page=${page}&page_size=${pageSize}`);
    const items = pickItems(data).map(mapResearchTask);
    return { items, ...pickPage(data, { page, pageSize }) };
  },

  async getTask(taskId: string): Promise<ResearchTask> {
    const data = await apiClient.request<any>(`/api/v1/research/tasks/${encodeURIComponent(taskId)}`);
    return mapResearchTask(data);
  },

  async createTask(input: CreateResearchTaskRequest): Promise<ResearchTask> {
    const data = await apiClient.request<any>("/api/v1/research/tasks", {
      method: "POST",
      headers: {
        "Idempotency-Key": createIdempotencyKey("research-task", [input.topic, input.scope, input.depth, input.outputFormat]),
      },
      body: JSON.stringify(toCreateResearchTaskRequestBody(input)),
    });
    return buildResearchTaskFromCreateResponse(data, input);
  },
};
