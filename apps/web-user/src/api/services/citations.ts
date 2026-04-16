import { appEnv } from '../../config/env';
import type { CitationDetail } from '../../types/domain';
import { createCitationApi } from '../../shared-sdk';
import { apiClient } from '../client';

const liveCitationService = createCitationApi({
  client: apiClient
});

export const citationService = {
  async getCitationDetail(citationId: string): Promise<CitationDetail> {
    if (appEnv.useMockApi) {
      return {
        id: citationId,
        title: '示例引用资料',
        sourceType: 'knowledge_base',
        docId: 'doc_mock_001',
        chunkId: 'chunk_mock_001',
        snippet: '这里展示引用片段与来源详情，便于后续接入 citations/{citation_id} 接口。',
        versionNo: 'v1'
      };
    }

    return liveCitationService.getCitationDetail(citationId);
  }
};
