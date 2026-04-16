import { joinUrl } from '../core/utils';
import {
  normalizeCompleteUploadRequest,
  normalizeUploadPolicyRequest
} from './business-normalizers';
import {
  mapCitationDetail,
  mapFileRecord,
  mapUploadPolicy
} from './business-mappers';
import { extractFileNameFromObjectKey } from './business-state';
import type {
  CitationDetail,
  CompleteUploadRequest,
  FileRecord,
  UploadPolicy,
  UploadPolicyRequest
} from './business-types';
import type { Citation } from './types';

export interface BuildUploadPolicyFallbackOptions {
  fileId: string;
  apiBaseUrl: string;
  input: UploadPolicyRequest;
  objectKey?: string;
  expireAt?: string;
  uploadPath?: string;
  formFields?: Record<string, string | number | boolean>;
}

export function buildUploadPolicyFallback(
  options: BuildUploadPolicyFallbackOptions
): UploadPolicy {
  const normalizedInput = normalizeUploadPolicyRequest(options.input);
  const objectKey =
    options.objectKey ?? `mock/${options.fileId}/${normalizedInput.fileName}`;

  return mapUploadPolicy({
    file_id: options.fileId,
    upload_url: joinUrl(
      options.apiBaseUrl,
      options.uploadPath ?? `/mock/upload/${options.fileId}`
    ),
    form_fields: {
      key: objectKey,
      ...(options.formFields ?? {})
    },
    object_key: objectKey,
    expire_at:
      options.expireAt ??
      new Date(Date.now() + 10 * 60 * 1000).toISOString()
  });
}

export interface BuildCompletedUploadFileRecordFallbackOptions {
  input: CompleteUploadRequest;
  mimeType?: string;
  downloadUrl?: string;
  expiresAt?: string;
  status?: FileRecord['status'];
  scanStatus?: FileRecord['scanStatus'];
}

export function buildCompletedUploadFileRecordFallback(
  options: BuildCompletedUploadFileRecordFallbackOptions
): FileRecord {
  const normalizedInput = normalizeCompleteUploadRequest(options.input);

  return mapFileRecord({
    file_id: normalizedInput.fileId,
    file_name: extractFileNameFromObjectKey(normalizedInput.objectKey),
    size: normalizedInput.size,
    mime_type: options.mimeType ?? 'application/octet-stream',
    download_url: options.downloadUrl,
    expires_at: options.expiresAt,
    status: options.status ?? 'ready',
    scan_status: options.scanStatus ?? 'passed'
  });
}

export interface BuildStoredFileRecordFallbackOptions {
  fileId: string;
  fileName?: string;
  size?: number;
  mimeType?: string;
  downloadUrl?: string;
  expiresAt?: string;
  status?: FileRecord['status'];
  scanStatus?: FileRecord['scanStatus'];
}

export function buildStoredFileRecordFallback(
  options: BuildStoredFileRecordFallbackOptions
): FileRecord {
  return mapFileRecord({
    file_id: options.fileId,
    file_name: options.fileName ?? `${options.fileId}.txt`,
    size: options.size ?? 1024,
    mime_type: options.mimeType ?? 'text/plain',
    download_url: options.downloadUrl,
    expires_at: options.expiresAt,
    status: options.status,
    scan_status: options.scanStatus
  });
}

export interface BuildCitationDetailFallbackOptions {
  citationId: string;
  fallback?: Citation | Partial<CitationDetail>;
  title?: string;
  sourceType?: Citation['sourceType'];
  docId?: string;
  chunkId?: string;
  snippet?: string;
  versionNo?: string;
  score?: number;
}

export function buildCitationDetailFallback(
  options: BuildCitationDetailFallbackOptions
): CitationDetail {
  const fallbackDetail = options.fallback as Partial<CitationDetail> | undefined;

  return mapCitationDetail({
    id: options.fallback?.id ?? options.citationId,
    title: options.fallback?.title ?? options.title ?? '示例引用资料',
    sourceType:
      options.fallback?.sourceType ?? options.sourceType ?? 'knowledge_base',
    docId: options.fallback?.docId ?? options.docId ?? 'doc_mock_001',
    chunkId: options.fallback?.chunkId ?? options.chunkId ?? 'chunk_mock_001',
    url: options.fallback?.url,
    snippet:
      fallbackDetail?.snippet ??
      options.snippet ??
      '这里展示引用片段与来源详情，便于后续接入 citations/{citation_id} 接口。',
    versionNo: fallbackDetail?.versionNo ?? options.versionNo ?? 'v1',
    score: fallbackDetail?.score ?? options.score
  });
}
