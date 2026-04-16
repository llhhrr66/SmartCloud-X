import type { BillingDashboard } from '../../types/domain';
import { createBillingApi } from '../../shared-sdk';
import { appEnv } from '../../config/env';
import { apiClient } from '../client';
import { mockGetBillingDashboard } from '../mock';

const liveBillingService = createBillingApi({
  client: apiClient
});

export const billingService = {
  async getDashboard(): Promise<BillingDashboard> {
    if (appEnv.useMockApi) {
      return mockGetBillingDashboard();
    }

    return liveBillingService.getDashboard();
  }
};
