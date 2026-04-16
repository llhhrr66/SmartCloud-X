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

export const researchService = {
  async getTask(taskId: string): Promise<ResearchTask> {
    return getResearchTask(taskId);
  },

  async listTasks(): Promise<ResearchTask[]> {
    if (appEnv.useMockApi) {
      return mockListResearchTasks();
    }

    const taskIds = listTaskIds('research');
    if (!taskIds.length) {
      return [];
    }

    const settled = await Promise.allSettled(taskIds.map((taskId) => getResearchTask(taskId)));
    return settled
      .filter((item): item is PromiseFulfilledResult<ResearchTask> => item.status === 'fulfilled')
      .map((item) => item.value)
      .sort((left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime());
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
