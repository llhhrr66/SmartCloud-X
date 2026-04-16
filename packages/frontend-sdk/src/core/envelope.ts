import type {
  ApiEnvelope,
  CanonicalErrorEnvelope,
  CanonicalSuccessEnvelope
} from '@smartcloud-x/common-schemas';
import type { FrontendFoundationErrorCode } from './error-codes';
import {
  getNumber,
  getOptionalNumber,
  getOptionalString,
  isAbortError,
  isNetworkErrorLike,
  isRecord
} from './utils';

export type ApiErrorKind =
  | 'unauthorized'
  | 'forbidden'
  | 'not_found'
  | 'conflict'
  | 'rate_limited'
  | 'timeout'
  | 'validation'
  | 'server'
  | 'unknown';

export class ApiError extends Error {
  status: number;
  code?: number | string;
  details?: unknown;
  requestId?: string;
  retryAfterMs?: number;

  constructor(
    message: string,
    status = 500,
    code?: number | string,
    details?: unknown,
    requestId?: string,
    retryAfterMs?: number
  ) {
    super(requestId ? `${message} (request id: ${requestId})` : message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.retryAfterMs = retryAfterMs;
  }
}

export interface RawSseEvent {
  event: string;
  data: unknown;
  id?: string;
  retry?: number;
}

export type EnvelopePayload<T = unknown> =
  | ApiEnvelope<T>
  | CanonicalSuccessEnvelope<T>
  | CanonicalErrorEnvelope
  | T;

export async function parseResponsePayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  const text = await response.text();
  if (!text.trim()) {
    return {};
  }

  if (contentType.includes('json') || /^[\[{]/.test(text.trimStart())) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return { message: text };
    }
  }

  return { message: text };
}

export function extractEnvelopeRequestId(payload: unknown, response?: Response): string | undefined {
  if (isRecord(payload)) {
    const payloadRequestId = getOptionalString(payload, ['request_id', 'requestId']);
    if (payloadRequestId?.trim()) {
      return payloadRequestId;
    }

    if (isRecord(payload.error)) {
      const nestedRequestId = getOptionalString(payload.error, ['request_id', 'requestId']);
      if (nestedRequestId?.trim()) {
        return nestedRequestId;
      }
    }

    if (isRecord(payload.error_detail)) {
      const nestedRequestId = getOptionalString(payload.error_detail, ['request_id', 'requestId']);
      if (nestedRequestId?.trim()) {
        return nestedRequestId;
      }
    }
  }

  const headerRequestId = response?.headers.get('X-Request-Id')?.trim();
  return headerRequestId || undefined;
}

export function extractEnvelopeMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) {
    return fallback;
  }

  const topLevelMessage = getOptionalString(payload, ['message', 'error_message', 'errorMessage']);
  if (topLevelMessage?.trim()) {
    return topLevelMessage;
  }

  if (isRecord(payload.error)) {
    const nestedMessage = getOptionalString(payload.error, [
      'message',
      'reason',
      'error_message',
      'errorMessage'
    ]);
    if (nestedMessage?.trim()) {
      return nestedMessage;
    }
  }

  if (isRecord(payload.error_detail)) {
    const detailMessage = getOptionalString(payload.error_detail, [
      'message',
      'reason',
      'error_message',
      'errorMessage'
    ]);
    if (detailMessage?.trim()) {
      return detailMessage;
    }
  }

  return fallback;
}

export function extractEnvelopeCode(payload: unknown): number | string | undefined {
  if (!isRecord(payload)) {
    return undefined;
  }

  return extractCodeFromRecord(payload);
}

function extractCodeFromRecord(record: Record<string, unknown>): number | string | undefined {
  if (typeof record.code === 'number' || typeof record.code === 'string') {
    return record.code;
  }

  if (typeof record.error_code === 'number' || typeof record.error_code === 'string') {
    return record.error_code;
  }

  if (typeof record.errorCode === 'number' || typeof record.errorCode === 'string') {
    return record.errorCode;
  }

  if (isRecord(record.error)) {
    const nested = extractCodeFromRecord(record.error);
    if (nested !== undefined) {
      return nested;
    }
  }

  if (isRecord(record.error_detail)) {
    const nested = extractCodeFromRecord(record.error_detail);
    if (nested !== undefined) {
      return nested;
    }
  }

  if (isRecord(record.details)) {
    const nested = extractCodeFromRecord(record.details);
    if (nested !== undefined) {
      return nested;
    }
  }

  return undefined;
}

export function extractEnvelopeStatus(payload: unknown): number | undefined {
  if (!isRecord(payload)) {
    return undefined;
  }

  const status = getOptionalNumber(payload, ['status', 'http_status', 'httpStatus', 'status_code', 'statusCode']);
  if (status !== undefined) {
    return status;
  }

  if (isRecord(payload.error)) {
    return getOptionalNumber(payload.error, [
      'status',
      'http_status',
      'httpStatus',
      'status_code',
      'statusCode'
    ]);
  }

  if (isRecord(payload.error_detail)) {
    return getOptionalNumber(payload.error_detail, [
      'status',
      'http_status',
      'httpStatus',
      'status_code',
      'statusCode'
    ]);
  }

  return undefined;
}

function parseRetryAfterHeader(value: string | null): number | undefined {
  if (!value) {
    return undefined;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }

  const seconds = Number(trimmed);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return seconds * 1000;
  }

  const timestamp = Date.parse(trimmed);
  if (Number.isNaN(timestamp)) {
    return undefined;
  }

  return Math.max(timestamp - Date.now(), 0);
}

function extractRetryAfterFromRecord(record: Record<string, unknown>): number | undefined {
  const retryAfterMs = getOptionalNumber(record, ['retry_after_ms', 'retryAfterMs']);
  if (retryAfterMs !== undefined) {
    return retryAfterMs;
  }

  const retryAfterSeconds = getOptionalNumber(record, ['retry_after', 'retryAfter']);
  if (retryAfterSeconds !== undefined) {
    return retryAfterSeconds * 1000;
  }

  if (isRecord(record.error)) {
    return extractRetryAfterFromRecord(record.error);
  }

  if (isRecord(record.error_detail)) {
    return extractRetryAfterFromRecord(record.error_detail);
  }

  if (isRecord(record.details)) {
    return extractRetryAfterFromRecord(record.details);
  }

  return undefined;
}

function mergeDetailRecords(
  primary?: Record<string, unknown>,
  secondary?: Record<string, unknown>
): Record<string, unknown> | undefined {
  if (primary && secondary) {
    return {
      ...secondary,
      ...primary
    };
  }

  return primary ?? secondary;
}

function extractEnvelopeDetails(payload: unknown): unknown {
  if (!isRecord(payload)) {
    return payload;
  }

  const errorRecord = isRecord(payload.error) ? payload.error : undefined;
  const errorDetailRecord = isRecord(payload.error_detail) ? payload.error_detail : undefined;
  const detailsRecord = isRecord(payload.details) ? payload.details : undefined;

  if (errorRecord) {
    const mergedDetails = mergeDetailRecords(
      isRecord(errorRecord.details) ? errorRecord.details : undefined,
      mergeDetailRecords(errorDetailRecord, detailsRecord)
    );

    return mergedDetails
      ? {
          ...errorRecord,
          details: mergedDetails
        }
      : errorRecord;
  }

  return errorDetailRecord ?? detailsRecord ?? payload;
}

export function extractEnvelopeRetryAfterMs(payload: unknown, response?: Response): number | undefined {
  const headerDelay = parseRetryAfterHeader(response?.headers.get('Retry-After') ?? null);
  if (headerDelay !== undefined) {
    return headerDelay;
  }

  if (!isRecord(payload)) {
    return undefined;
  }

  return extractRetryAfterFromRecord(payload);
}

export function createApiError(
  payload: unknown,
  status: number,
  response?: Response,
  fallbackMessage = `HTTP ${status}`
): ApiError {
  const requestId = extractEnvelopeRequestId(payload, response);
  const resolvedStatus = resolveEnvelopeErrorStatus(payload, status);
  return new ApiError(
    extractEnvelopeMessage(payload, fallbackMessage),
    resolvedStatus,
    extractEnvelopeCode(payload),
    extractEnvelopeDetails(payload),
    requestId,
    extractEnvelopeRetryAfterMs(payload, response)
  );
}

type FoundationErrorMeta = {
  kind: ApiErrorKind;
  status: number;
};

const FOUNDATION_ERROR_META_BY_NAME = {
  AUTH_INVALID_TOKEN: { kind: 'unauthorized', status: 401 },
  AUTH_UNAUTHORIZED: { kind: 'unauthorized', status: 401 },
  BUSINESS_TOOLS_CALLER_FORBIDDEN: { kind: 'forbidden', status: 403 },
  CHAT_CONVERSATION_ARCHIVED: { kind: 'conflict', status: 409 },
  CHAT_CONVERSATION_NOT_FOUND: { kind: 'not_found', status: 404 },
  CHAT_CONVERSATION_RESTORE_INVALID: { kind: 'conflict', status: 409 },
  CHAT_CONTINUATION_NOT_AVAILABLE: { kind: 'conflict', status: 409 },
  CHAT_CONVERSATION_RUNNING: { kind: 'conflict', status: 409 },
  CHAT_MESSAGE_CANCELLED: { kind: 'conflict', status: 409 },
  CHAT_MESSAGE_NOT_FOUND: { kind: 'not_found', status: 404 },
  CHAT_MESSAGE_NOT_RUNNING: { kind: 'conflict', status: 409 },
  IDEMPOTENCY_CONFLICT: { kind: 'conflict', status: 409 },
  INTERNAL_ERROR: { kind: 'server', status: 500 },
  KNOWLEDGE_SYNC_FAILED: { kind: 'server', status: 502 },
  ORCH_CALLER_FORBIDDEN: { kind: 'forbidden', status: 403 },
  ORCH_ROUTE_FAILED: { kind: 'server', status: 500 },
  ORCH_SESSION_STATE_NOT_FOUND: { kind: 'not_found', status: 404 },
  ORCH_TOOL_AUTH_REQUIRED: { kind: 'forbidden', status: 403 },
  ORCH_TOOL_CALL_NOT_FOUND: { kind: 'not_found', status: 404 },
  ORCH_TOOL_NOT_FOUND: { kind: 'not_found', status: 404 },
  ORCH_TOOL_OPERATION_INVALID: { kind: 'validation', status: 422 },
  ORCH_TOOL_PAYLOAD_INVALID: { kind: 'validation', status: 422 },
  RAG_RETRIEVAL_UNAVAILABLE: { kind: 'server', status: 503 },
  RATE_LIMITED: { kind: 'rate_limited', status: 429 },
  SERVICE_UNAVAILABLE: { kind: 'server', status: 503 },
  TOOL_HUB_CALLER_FORBIDDEN: { kind: 'forbidden', status: 403 },
  VALIDATION_ERROR: { kind: 'validation', status: 400 }
} satisfies Record<FrontendFoundationErrorCode, FoundationErrorMeta>;

const FOUNDATION_ERROR_META_BY_NUMERIC: Record<string, FoundationErrorMeta> = {
  '4000001': FOUNDATION_ERROR_META_BY_NAME.VALIDATION_ERROR,
  '4010001': FOUNDATION_ERROR_META_BY_NAME.AUTH_INVALID_TOKEN,
  '4010002': FOUNDATION_ERROR_META_BY_NAME.AUTH_UNAUTHORIZED,
  '4032101': FOUNDATION_ERROR_META_BY_NAME.ORCH_CALLER_FORBIDDEN,
  '4033001': FOUNDATION_ERROR_META_BY_NAME.TOOL_HUB_CALLER_FORBIDDEN,
  '4033003': FOUNDATION_ERROR_META_BY_NAME.ORCH_TOOL_AUTH_REQUIRED,
  '4033201': FOUNDATION_ERROR_META_BY_NAME.BUSINESS_TOOLS_CALLER_FORBIDDEN,
  '4042103': FOUNDATION_ERROR_META_BY_NAME.ORCH_SESSION_STATE_NOT_FOUND,
  '4042104': FOUNDATION_ERROR_META_BY_NAME.CHAT_CONVERSATION_NOT_FOUND,
  '4042105': FOUNDATION_ERROR_META_BY_NAME.CHAT_MESSAGE_NOT_FOUND,
  '4043002': FOUNDATION_ERROR_META_BY_NAME.ORCH_TOOL_NOT_FOUND,
  '4043004': FOUNDATION_ERROR_META_BY_NAME.ORCH_TOOL_CALL_NOT_FOUND,
  '4090001': FOUNDATION_ERROR_META_BY_NAME.IDEMPOTENCY_CONFLICT,
  '4092104': FOUNDATION_ERROR_META_BY_NAME.CHAT_CONVERSATION_ARCHIVED,
  '4092105': FOUNDATION_ERROR_META_BY_NAME.CHAT_CONVERSATION_RESTORE_INVALID,
  '4092106': FOUNDATION_ERROR_META_BY_NAME.CHAT_CONTINUATION_NOT_AVAILABLE,
  '4092107': FOUNDATION_ERROR_META_BY_NAME.CHAT_CONVERSATION_RUNNING,
  '4092108': FOUNDATION_ERROR_META_BY_NAME.CHAT_MESSAGE_NOT_RUNNING,
  '4092109': FOUNDATION_ERROR_META_BY_NAME.CHAT_MESSAGE_CANCELLED,
  '4223004': FOUNDATION_ERROR_META_BY_NAME.ORCH_TOOL_OPERATION_INVALID,
  '4223005': FOUNDATION_ERROR_META_BY_NAME.ORCH_TOOL_PAYLOAD_INVALID,
  '4290001': FOUNDATION_ERROR_META_BY_NAME.RATE_LIMITED,
  '5000001': FOUNDATION_ERROR_META_BY_NAME.INTERNAL_ERROR,
  '5002102': FOUNDATION_ERROR_META_BY_NAME.ORCH_ROUTE_FAILED,
  '5002201': FOUNDATION_ERROR_META_BY_NAME.RAG_RETRIEVAL_UNAVAILABLE,
  '5004001': FOUNDATION_ERROR_META_BY_NAME.KNOWLEDGE_SYNC_FAILED,
  '5030001': FOUNDATION_ERROR_META_BY_NAME.SERVICE_UNAVAILABLE
};

function resolveFoundationErrorMeta(
  code: number | string | undefined
): FoundationErrorMeta | undefined {
  if (typeof code === 'number' && Number.isInteger(code)) {
    return FOUNDATION_ERROR_META_BY_NUMERIC[String(code)];
  }

  if (typeof code !== 'string') {
    return undefined;
  }

  const trimmed = code.trim();
  if (!trimmed) {
    return undefined;
  }

  if (/^\d+$/.test(trimmed)) {
    return FOUNDATION_ERROR_META_BY_NUMERIC[trimmed];
  }

  return FOUNDATION_ERROR_META_BY_NAME[trimmed.toUpperCase() as keyof typeof FOUNDATION_ERROR_META_BY_NAME];
}

function inferHttpStatusFromCode(code: number | string | undefined): number | undefined {
  const foundationMeta = resolveFoundationErrorMeta(code);
  if (foundationMeta) {
    return foundationMeta.status;
  }

  if (typeof code === 'number' && Number.isInteger(code) && code >= 1000000) {
    return Math.trunc(code / 10_000);
  }

  if (typeof code === 'string') {
    const trimmed = code.trim();
    if (/^\d+$/.test(trimmed)) {
      return inferHttpStatusFromCode(Number(trimmed));
    }
  }

  return undefined;
}

function resolveEnvelopeErrorStatus(payload: unknown, fallbackStatus: number): number {
  const envelopeStatus = extractEnvelopeStatus(payload);
  if (envelopeStatus !== undefined) {
    return envelopeStatus;
  }

  if (fallbackStatus >= 400) {
    return fallbackStatus;
  }

  return inferHttpStatusFromCode(extractEnvelopeCode(payload)) ?? fallbackStatus;
}

export function classifyApiError(error: unknown): ApiErrorKind {
  const code =
    error instanceof ApiError
      ? error.code
      : isRecord(error)
        ? extractEnvelopeCode(error)
        : undefined;
  const inferredStatus = inferHttpStatusFromCode(code);
  const status =
    error instanceof ApiError
      ? error.status
      : isRecord(error)
      ? extractEnvelopeStatus(error) ?? inferredStatus ?? getNumber(error, ['status'], 0)
      : 0;
  const namedKind = resolveFoundationErrorMeta(code)?.kind;

  if (status === 401 || namedKind === 'unauthorized') {
    return 'unauthorized';
  }

  if (status === 403 || namedKind === 'forbidden') {
    return 'forbidden';
  }

  if (status === 404 || namedKind === 'not_found') {
    return 'not_found';
  }

  if (status === 409 || namedKind === 'conflict') {
    return 'conflict';
  }

  if (status === 429 || namedKind === 'rate_limited') {
    return 'rate_limited';
  }

  if (status === 408) {
    return 'timeout';
  }

  if (status === 400 || status === 422 || namedKind === 'validation') {
    return 'validation';
  }

  if (status >= 500 || namedKind === 'server') {
    return 'server';
  }

  return 'unknown';
}

export function shouldRetryApiError(error: unknown): boolean {
  const kind = classifyApiError(error);
  return kind === 'timeout' || kind === 'rate_limited' || kind === 'server';
}

export function shouldReconnectSseStream(error: unknown): boolean {
  if (isAbortError(error)) {
    return false;
  }

  if (error instanceof Error && !(error instanceof ApiError)) {
    return isNetworkErrorLike(error);
  }

  if (!isRecord(error) && !(error instanceof ApiError)) {
    return false;
  }

  if (
    isRecord(error) &&
    extractEnvelopeStatus(error) === undefined &&
    extractEnvelopeCode(error) === undefined &&
    extractEnvelopeRetryAfterMs(error) === undefined
  ) {
    return false;
  }

  const kind = classifyApiError(error);
  return (
    kind !== 'unauthorized' &&
    kind !== 'forbidden' &&
    kind !== 'not_found' &&
    kind !== 'conflict' &&
    kind !== 'validation'
  );
}

export interface SseReconnectDelayOptions {
  attempt?: number;
  defaultMs?: number;
  maxMs?: number;
  event?: Pick<RawSseEvent, 'retry'> | null;
  error?: unknown;
}

export function resolveSseReconnectDelayMs(options: SseReconnectDelayOptions = {}): number | null {
  if (options.error && !shouldReconnectSseStream(options.error)) {
    return null;
  }

  const eventDelay =
    options.event && typeof options.event.retry === 'number' && Number.isFinite(options.event.retry)
      ? options.event.retry
      : undefined;
  if (eventDelay !== undefined) {
    return eventDelay;
  }

  if (options.error instanceof ApiError && options.error.retryAfterMs !== undefined) {
    return options.error.retryAfterMs;
  }

  if (options.error) {
    const retryAfterMs = extractEnvelopeRetryAfterMs(options.error);
    if (retryAfterMs !== undefined) {
      return retryAfterMs;
    }
  }

  const attempt = Math.max(options.attempt ?? 1, 1);
  const defaultMs = options.defaultMs ?? 1_000;
  const maxMs = options.maxMs ?? 30_000;
  return Math.min(defaultMs * 2 ** (attempt - 1), maxMs);
}

export function unwrapEnvelope<T>(payload: unknown, status = 200, response?: Response): T {
  if (!isRecord(payload)) {
    return payload as T;
  }

  if (payload.success === false) {
    throw createApiError(payload, status, response, 'Request failed');
  }

  if ('success' in payload && 'data' in payload) {
    return payload.data as T;
  }

  const code = extractEnvelopeCode(payload);
  if (code !== undefined && code !== 0 && code !== '0') {
    throw createApiError(payload, status, response, 'Request failed');
  }

  if (code !== undefined && 'data' in payload) {
    return payload.data as T;
  }

  if ('data' in payload) {
    return payload.data as T;
  }

  return payload as T;
}

export function parseSseBlock(block: string): RawSseEvent | null {
  const lines = block.split(/\r?\n/);
  let event = 'message';
  let id: string | undefined;
  let retry: number | undefined;
  const dataLines: string[] = [];

  for (const line of lines) {
    if (!line.trim() || line.startsWith(':')) {
      continue;
    }

    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
      continue;
    }

    if (line.startsWith('id:')) {
      id = line.slice(3).trim() || undefined;
      continue;
    }

    if (line.startsWith('retry:')) {
      const parsed = Number(line.slice(6).trim());
      retry = Number.isFinite(parsed) && parsed >= 0 ? parsed : retry;
      continue;
    }

    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if ((event === 'ping' || event === 'heartbeat') && dataLines.length === 0) {
    return { event, data: {}, id, retry };
  }

  if (dataLines.length === 0) {
    return null;
  }

  const raw = dataLines.join('\n');

  try {
    return {
      event,
      data: JSON.parse(raw) as unknown,
      id,
      retry
    };
  } catch {
    return {
      event,
      data: raw,
      id,
      retry
    };
  }
}
