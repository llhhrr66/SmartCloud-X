import { appEnv } from '../../config/env';
import { createIdempotencyKey } from '../../lib/request-meta';
import { createId } from '../../lib/utils';
import type {
  CompleteUploadRequest,
  FileRecord,
  UploadPolicy,
  UploadPolicyRequest
} from '../../types/domain';
import { createFileApi } from '../../shared-sdk';
import { apiClient } from '../client';

const liveFileService = createFileApi({
  client: apiClient,
  createIdempotencyKey
});

export const fileService = {
  async getUploadPolicy(input: UploadPolicyRequest): Promise<UploadPolicy> {
    if (appEnv.useMockApi) {
      const fileId = createId('file');
      return {
        fileId,
        uploadUrl: `${appEnv.apiBaseUrl}/mock/upload/${fileId}`,
        formFields: {
          key: `mock/${fileId}/${input.fileName}`
        },
        objectKey: `mock/${fileId}/${input.fileName}`,
        expireAt: new Date(Date.now() + 10 * 60 * 1000).toISOString()
      };
    }

    return liveFileService.getUploadPolicy(input);
  },

  async completeUpload(input: CompleteUploadRequest): Promise<FileRecord> {
    if (appEnv.useMockApi) {
      return {
        fileId: input.fileId,
        fileName: input.objectKey.split('/').at(-1) ?? input.objectKey,
        size: input.size,
        mimeType: 'application/octet-stream',
        status: 'ready',
        scanStatus: 'passed'
      };
    }

    return liveFileService.completeUpload(input);
  },

  async getFile(fileId: string): Promise<FileRecord> {
    if (appEnv.useMockApi) {
      return {
        fileId,
        fileName: `${fileId}.txt`,
        size: 1024,
        mimeType: 'text/plain',
        downloadUrl: `${appEnv.apiBaseUrl}/mock/files/${fileId}`,
        expiresAt: new Date(Date.now() + 10 * 60 * 1000).toISOString()
      };
    }

    return liveFileService.getFile(fileId);
  },

  async deleteFile(fileId: string): Promise<{ success: true }> {
    if (!appEnv.useMockApi) {
      await liveFileService.deleteFile(fileId);
    }

    return { success: true };
  }
};
