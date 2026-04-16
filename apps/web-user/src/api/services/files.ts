import { appEnv } from '../../config/env';
import { createId } from '../../lib/utils';
import {
  buildCompletedUploadFileRecordFallback,
  buildStoredFileRecordFallback,
  buildUploadPolicyFallback
} from '../../shared-sdk';
import type {
  CompleteUploadRequest,
  FileRecord,
  UploadPolicy,
  UploadPolicyRequest
} from '../../types/domain';
import { liveBusinessApis } from '../business-sdk';

export const fileService = {
  async getUploadPolicy(input: UploadPolicyRequest): Promise<UploadPolicy> {
    if (appEnv.useMockApi) {
      const fileId = createId('file');
      return buildUploadPolicyFallback({
        fileId,
        apiBaseUrl: appEnv.apiBaseUrl,
        input
      });
    }

    return liveBusinessApis.files.getUploadPolicy(input);
  },

  async completeUpload(input: CompleteUploadRequest): Promise<FileRecord> {
    if (appEnv.useMockApi) {
      return buildCompletedUploadFileRecordFallback({
        input,
        mimeType: 'application/octet-stream',
        status: 'ready',
        scanStatus: 'passed'
      });
    }

    return liveBusinessApis.files.completeUpload(input);
  },

  async getFile(fileId: string): Promise<FileRecord> {
    if (appEnv.useMockApi) {
      return buildStoredFileRecordFallback({
        fileId,
        downloadUrl: `${appEnv.apiBaseUrl}/mock/files/${fileId}`,
        expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString()
      });
    }

    return liveBusinessApis.files.getFile(fileId);
  },

  async deleteFile(fileId: string): Promise<{ success: true }> {
    if (!appEnv.useMockApi) {
      await liveBusinessApis.files.deleteFile(fileId);
    }

    return { success: true };
  }
};
