import type { CreateResearchTaskRequest, ResearchTask } from '../../types/domain';
import { appEnv } from '../../config/env';
import { createIdempotencyKey } from '../../lib/request-meta';
import { listTaskIds, rememberTask } from '../../lib/task-registry';
import {
  buildResearchTaskFromCreateResponse,
  mapResearchTask,
  toCreateResearchTaskRequestBody
} from '../../shared-sdk';
import { apiClient } from '../client';
import { mockCreateResearchTask, mockListResearchTasks } from '../mock';

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

function sortResearchTasks(tasks: ResearchTask[]): ResearchTask[] {
  return [...tasks].sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
}

async function listTrackedResearchTasks(taskIds: string[]): Promise<ResearchTask[]> {
  if (!taskIds.length) {
    return [];
  }

  const settled = await Promise.allSettled(taskIds.map((taskId) => getResearchTask(taskId)));
  return settled
    .filter((item): item is PromiseFulfilledResult<ResearchTask> => item.status === 'fulfilled')
    .map((item) => item.value);
}

function mergeResearchTasks(primary: ResearchTask[], secondary: ResearchTask[]): ResearchTask[] {
  return sortResearchTasks([
    ...primary,
    ...secondary.filter((task) => !primary.some((item) => item.taskId === task.taskId))
  ]);
}

async function getResearchTask(taskId: string): Promise<ResearchTask> {
  if (appEnv.useMockApi) {
    const tasks = await mockListResearchTasks();
    const task = tasks.find((item) => item.taskId === taskId);
    if (!task) {
      throw new Error('研究任务不存在');
    }
    return task;
  }

  const data = await apiClient.request<Record<string, unknown>>(`/api/v1/research/tasks/${taskId}`);
  return mapResearchTask(data);
}

async function listLiveResearchTasks(): Promise<ResearchTask[]> {
  const data = await apiClient.request<Record<string, unknown>>(
    '/api/v1/research/tasks?page=1&page_size=20&sort_by=updated_at&sort_order=desc'
  );

  return sortResearchTasks(resolveCollectionItems(data).map(mapResearchTask));
}

export const researchService = {
  async getTask(taskId: string): Promise<ResearchTask> {
    return getResearchTask(taskId);
  },

  async listTasks(): Promise<ResearchTask[]> {
    if (appEnv.useMockApi) {
      return mockListResearchTasks();
    }

    const trackedTaskIds = listTaskIds('research');

    try {
      const liveTasks = await listLiveResearchTasks();
      const missingTrackedIds = trackedTaskIds.filter((taskId) => !liveTasks.some((item) => item.taskId === taskId));
      if (!missingTrackedIds.length) {
        return liveTasks;
      }

      const trackedTasks = await listTrackedResearchTasks(missingTrackedIds);
      return mergeResearchTasks(liveTasks, trackedTasks);
    } catch (error) {
      if (!trackedTaskIds.length) {
        throw error;
      }

      return sortResearchTasks(await listTrackedResearchTasks(trackedTaskIds));
    }
  },

  async createTask(input: CreateResearchTaskRequest): Promise<ResearchTask> {
    if (appEnv.useMockApi) {
      return mockCreateResearchTask(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/research/tasks', {
      method: 'POST',
      headers: {
        'Idempotency-Key': createIdempotencyKey('research-task', [
          input.topic,
          input.scope,
          input.depth,
          input.outputFormat,
          input.referenceUrls
        ])
      },
      body: JSON.stringify(toCreateResearchTaskRequestBody(input))
    });

    const task = buildResearchTaskFromCreateResponse(data, input);
    rememberTask('research', task.taskId);
    return task;
  }
};
