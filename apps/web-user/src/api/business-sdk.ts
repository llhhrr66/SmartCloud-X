import { createWebUserBusinessApis } from '../shared-sdk';
import { createIdempotencyKey } from '../lib/request-meta';
import { listTaskIds, rememberTask } from '../lib/task-registry';
import { apiClient } from './client';

export const liveBusinessApis = createWebUserBusinessApis({
  client: apiClient,
  createIdempotencyKey,
  icpTrackingStore: {
    list: () => listTaskIds('icp'),
    remember: (applicationNo) => rememberTask('icp', applicationNo)
  }
});
