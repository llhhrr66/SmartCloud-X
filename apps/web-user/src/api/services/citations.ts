import { appEnv } from '../../config/env';
import type { Citation, CitationDetail } from '../../types/domain';
import { buildCitationDetailFallback } from '../../shared-sdk';
import { liveBusinessApis } from '../business-sdk';

export const citationService = {
  async getCitationDetail(
    citationId: string,
    fallback?: Citation | Partial<CitationDetail>
  ): Promise<CitationDetail> {
    if (appEnv.useMockApi) {
      return buildCitationDetailFallback({
        citationId,
        fallback
      });
    }

    return liveBusinessApis.citations.getCitationDetail(citationId, fallback);
  }
};
