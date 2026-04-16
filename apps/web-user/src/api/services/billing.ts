import type { BillingDashboard } from '../../types/domain';
import { appEnv } from '../../config/env';
import { liveBusinessApis } from '../business-sdk';
import { mockGetBillingDashboard } from '../mock';

export const billingService = {
  async getDashboard(): Promise<BillingDashboard> {
    if (appEnv.useMockApi) {
      return mockGetBillingDashboard();
    }

    return liveBusinessApis.billing.getDashboard();
  }
};
