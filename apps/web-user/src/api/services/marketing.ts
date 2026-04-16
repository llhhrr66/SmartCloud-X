import type {
  CreatePosterTaskRequest,
  MarketingCampaign,
  MarketingCopyRequest,
  MarketingCopyResult,
  PosterTask
} from '../../types/domain';
import { appEnv } from '../../config/env';
import { createIdempotencyKey } from '../../lib/request-meta';
import { listTaskIds, rememberTask } from '../../lib/task-registry';
import {
  buildMarketingCopyResultFromGenerateResponse,
  buildPosterTaskFromCreateResponse,
  mapMarketingCampaign,
  mapPosterTask,
  toCreatePosterTaskRequestBody,
  toMarketingCopyRequestBody
} from '../../shared-sdk';
import { apiClient } from '../client';
import {
  mockCreatePosterTask,
  mockGenerateMarketingCopy,
  mockListCampaigns,
  mockListPosterTasks
} from '../mock';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function resolveCollectionItems(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) {
    return value.filter(isRecord);
  }

  if (!isRecord(value)) {
    return [];
  }

  const candidates = [value.items, value.tasks, value.list, value.results];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate.filter(isRecord);
    }
  }

  if (Array.isArray(value.data)) {
    return value.data.filter(isRecord);
  }

  if (isRecord(value.data)) {
    return resolveCollectionItems(value.data);
  }

  return [];
}

function sortPosterTasks(tasks: PosterTask[]): PosterTask[] {
  return [...tasks].sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
}

async function listTrackedPosterTasks(taskIds: string[]): Promise<PosterTask[]> {
  if (!taskIds.length) {
    return [];
  }

  const settled = await Promise.allSettled(taskIds.map((taskId) => getPosterTask(taskId)));
  return settled
    .filter((item): item is PromiseFulfilledResult<PosterTask> => item.status === 'fulfilled')
    .map((item) => item.value);
}

function mergePosterTasks(primary: PosterTask[], secondary: PosterTask[]): PosterTask[] {
  return sortPosterTasks([
    ...primary,
    ...secondary.filter((task) => !primary.some((item) => item.taskId === task.taskId))
  ]);
}

async function getPosterTask(taskId: string): Promise<PosterTask> {
  if (appEnv.useMockApi) {
    const tasks = await mockListPosterTasks();
    const task = tasks.find((item) => item.taskId === taskId);
    if (!task) {
      throw new Error('海报任务不存在');
    }
    return task;
  }

  const data = await apiClient.request<Record<string, unknown>>(`/api/v1/marketing/posters/${taskId}`);
  return mapPosterTask(data);
}

async function listLivePosterTasks(): Promise<PosterTask[]> {
  const data = await apiClient.request<Record<string, unknown>>(
    '/api/v1/marketing/posters?page=1&page_size=20&sort_by=updated_at&sort_order=desc'
  );

  return sortPosterTasks(resolveCollectionItems(data).map(mapPosterTask));
}

export const marketingService = {
  async listCampaigns(): Promise<MarketingCampaign[]> {
    if (appEnv.useMockApi) {
      return mockListCampaigns();
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/marketing/campaigns?page=1&page_size=20');
    return Array.isArray(data.items) ? data.items.map(mapMarketingCampaign) : [];
  },

  async generateCopy(input: MarketingCopyRequest): Promise<MarketingCopyResult> {
    if (appEnv.useMockApi) {
      return mockGenerateMarketingCopy(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/marketing/copy/generate', {
      method: 'POST',
      body: JSON.stringify(toMarketingCopyRequestBody(input))
    });

    return buildMarketingCopyResultFromGenerateResponse(data, input);
  },

  async listPosterTasks(): Promise<PosterTask[]> {
    if (appEnv.useMockApi) {
      return mockListPosterTasks();
    }

    const trackedTaskIds = listTaskIds('poster');

    try {
      const liveTasks = await listLivePosterTasks();
      const missingTrackedIds = trackedTaskIds.filter((taskId) => !liveTasks.some((item) => item.taskId === taskId));
      if (!missingTrackedIds.length) {
        return liveTasks;
      }

      const trackedTasks = await listTrackedPosterTasks(missingTrackedIds);
      return mergePosterTasks(liveTasks, trackedTasks);
    } catch (error) {
      if (!trackedTaskIds.length) {
        throw error;
      }

      return sortPosterTasks(await listTrackedPosterTasks(trackedTaskIds));
    }
  },

  async getPosterTask(taskId: string): Promise<PosterTask> {
    return getPosterTask(taskId);
  },

  async createPosterTask(input: CreatePosterTaskRequest): Promise<PosterTask> {
    if (appEnv.useMockApi) {
      return mockCreatePosterTask(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/marketing/posters', {
      method: 'POST',
      headers: {
        'Idempotency-Key': createIdempotencyKey('marketing-poster', [
          input.campaignId,
          input.theme,
          input.slogan,
          input.size
        ])
      },
      body: JSON.stringify(toCreatePosterTaskRequestBody(input))
    });

    const task = buildPosterTaskFromCreateResponse(data, input);
    rememberTask('poster', task.taskId);
    return task;
  }
};
