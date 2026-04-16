import type {
  ApiEnvelope,
  CanonicalErrorEnvelope,
  CanonicalSuccessEnvelope
} from '@smartcloud-x/common-schemas';
import type { FrontendFoundationErrorCode } from './error-codes';
import {
  getNumber,
  getOptionalBoolean,
  getOptionalNumber,
  getOptionalString,
  getStringArray,
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

export type ApiUserActionKind =
  | 'clarify-tool-input'
  | 'collect-auth-context'
  | 'user-confirmation';

export interface ApiErrorDetailsInfo {
  missingFields: string[];
  requiredPermissions: string[];
  missingAuthContext: string[];
  missingPayloadHints?: Record<string, string>;
  requiresAccountContext?: boolean;
  confirmationRequired?: boolean;
  confirmToolNames?: string[];
  sessionContextBindings?: Record<string, string[]>;
  userProfileBindings?: Record<string, string[]>;
}

export interface ApiErrorInfo {
  kind: ApiErrorKind;
  message: string;
  status?: number;
  code?: number | string;
  requestId?: string;
  retryAfterMs?: number;
  details?: ApiErrorDetailsInfo;
}

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

function looksLikeSsePayload(text: string, contentType: string): boolean {
  if (contentType.includes('text/event-stream')) {
    return true;
  }

  const trimmed = text.trimStart();
  return /^(?:event|data|id|retry|:)/.test(trimmed) && /\r?\n/.test(trimmed);
}

function parseSseErrorPayload(text: string): unknown | undefined {
  const trimmed = text.trim();
  if (!trimmed) {
    return undefined;
  }

  const parsedEvents = trimmed
    .split(/\r?\n\r?\n/)
    .map((block) => parseSseBlock(block))
    .filter((event): event is RawSseEvent => Boolean(event));

  if (!parsedEvents.length) {
    return undefined;
  }

  const preferredEvent =
    [...parsedEvents]
      .reverse()
      .find((event) =>
        ['error', 'message.error', 'action_required', 'message.action_required'].includes(
          event.event
        )
      ) ?? parsedEvents.at(-1);

  if (!preferredEvent) {
    return undefined;
  }

  if (isRecord(preferredEvent.data)) {
    return {
      ...(preferredEvent.retry !== undefined &&
      extractEnvelopeRetryAfterMs(preferredEvent.data) === undefined
        ? { retry_after_ms: preferredEvent.retry }
        : {}),
      ...preferredEvent.data
    };
  }

  if (typeof preferredEvent.data === 'string' && preferredEvent.data.trim()) {
    return {
      message: preferredEvent.data.trim(),
      ...(preferredEvent.retry !== undefined
        ? { retry_after_ms: preferredEvent.retry }
        : {})
    };
  }

  if (preferredEvent.retry !== undefined) {
    return {
      retry_after_ms: preferredEvent.retry
    };
  }

  return undefined;
}

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

  if (looksLikeSsePayload(text, contentType)) {
    const ssePayload = parseSseErrorPayload(text);
    if (ssePayload !== undefined) {
      return ssePayload;
    }
  }

  return { message: text };
}

function findOptionalStringInNestedRecords(
  record: Record<string, unknown>,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): string | undefined {
  if (seen.has(record)) {
    return undefined;
  }

  seen.add(record);

  const directValue = getOptionalString(record, keys);
  if (directValue?.trim()) {
    return directValue;
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(record[nestedKey])) {
      continue;
    }

    const nestedValue = findOptionalStringInNestedRecords(
      record[nestedKey],
      keys,
      nestedKeys,
      seen
    );
    if (nestedValue?.trim()) {
      return nestedValue;
    }
  }

  return undefined;
}

function findOptionalNumberInNestedRecords(
  record: Record<string, unknown>,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): number | undefined {
  if (seen.has(record)) {
    return undefined;
  }

  seen.add(record);

  const directValue = getOptionalNumber(record, keys);
  if (directValue !== undefined) {
    return directValue;
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(record[nestedKey])) {
      continue;
    }

    const nestedValue = findOptionalNumberInNestedRecords(
      record[nestedKey],
      keys,
      nestedKeys,
      seen
    );
    if (nestedValue !== undefined) {
      return nestedValue;
    }
  }

  return undefined;
}

export function extractEnvelopeRequestId(payload: unknown, response?: Response): string | undefined {
  if (isRecord(payload)) {
    const payloadRequestId = findOptionalStringInNestedRecords(
      payload,
      ['request_id', 'requestId'],
      ['error', 'error_detail', 'details', 'trace', 'trace_context']
    );
    if (payloadRequestId?.trim()) {
      return payloadRequestId;
    }
  }

  const headerRequestId = response?.headers.get('X-Request-Id')?.trim();
  return headerRequestId || undefined;
}

export function extractEnvelopeMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) {
    return fallback;
  }

  const resolvedMessage = findOptionalStringInNestedRecords(
    payload,
    [
      'message',
      'reason',
      'error_message',
      'errorMessage'
    ],
    ['error', 'error_detail', 'details', 'user_action_hint']
  );
  if (resolvedMessage?.trim()) {
    return resolvedMessage;
  }

  const pendingUserActionMessage = getOptionalString(
    extractPendingUserActionDetailsRecord(payload) ?? {},
    ['message']
  );
  if (pendingUserActionMessage?.trim()) {
    return pendingUserActionMessage;
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

  return findOptionalNumberInNestedRecords(
    payload,
    [
      'status',
      'http_status',
      'httpStatus',
      'status_code',
      'statusCode'
    ],
    ['error', 'error_detail', 'details']
  );
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

const PENDING_USER_ACTION_NESTED_KEYS = [
  'error',
  'error_detail',
  'details',
  'data',
  'response',
  'state_snapshot'
] as const;

function extractPendingUserActionRecords(
  payload: unknown,
  nestedKeys = PENDING_USER_ACTION_NESTED_KEYS,
  seen = new Set<Record<string, unknown>>()
): Record<string, unknown>[] {
  if (!isRecord(payload)) {
    return [];
  }

  if (seen.has(payload)) {
    return [];
  }

  seen.add(payload);
  const records: Record<string, unknown>[] = [];

  for (const key of ['pending_user_actions', 'pendingUserActions'] as const) {
    if (!Array.isArray(payload[key])) {
      continue;
    }

    for (const item of payload[key]) {
      if (isRecord(item)) {
        records.push(item);
      }
    }
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(payload[nestedKey])) {
      continue;
    }

    records.push(...extractPendingUserActionRecords(payload[nestedKey], nestedKeys, seen));
  }

  return records;
}

function mergePendingUserActionDetails(
  actions: Record<string, unknown>[]
): Record<string, unknown> | undefined {
  if (!actions.length) {
    return undefined;
  }

  const merged: Record<string, unknown> = {};

  for (const action of actions) {
    for (const key of ['action', 'message', 'tool_name', 'tool_call_id', 'agent'] as const) {
      const value = getOptionalString(action, [key]);
      if (value && merged[key] === undefined) {
        merged[key] = value;
      }
    }

    for (const key of [
      'missing_fields',
      'required_permissions',
      'missing_auth_context',
      'confirm_tool_names'
    ] as const) {
      const bucket = new Set<string>(getStringArray(merged[key]));
      for (const value of getStringArray(action[key])) {
        const trimmed = value.trim();
        if (trimmed) {
          bucket.add(trimmed);
        }
      }
      if (bucket.size) {
        merged[key] = [...bucket];
      }
    }

    for (const key of [
      'missing_payload_hints',
      'session_context_bindings',
      'user_profile_bindings'
    ] as const) {
      if (!isRecord(action[key])) {
        continue;
      }

      const nextMap: Record<string, unknown> = isRecord(merged[key]) ? { ...merged[key] } : {};

      for (const [entryKey, entryValue] of Object.entries(action[key])) {
        const trimmedKey = entryKey.trim();
        if (!trimmedKey) {
          continue;
        }

        if (key === 'missing_payload_hints') {
          if (typeof entryValue === 'string' && entryValue.trim() && nextMap[trimmedKey] === undefined) {
            nextMap[trimmedKey] = entryValue.trim();
          }
          continue;
        }

        const bucket = new Set<string>(
          Array.isArray(nextMap[trimmedKey]) ? getStringArray(nextMap[trimmedKey]) : []
        );
        for (const value of getStringArray(entryValue)) {
          const trimmed = value.trim();
          if (trimmed) {
            bucket.add(trimmed);
          }
        }
        if (bucket.size) {
          nextMap[trimmedKey] = [...bucket];
        }
      }

      if (Object.keys(nextMap).length) {
        merged[key] = nextMap;
      }
    }

    for (const key of ['requires_account_context', 'confirmation_required'] as const) {
      const value = getOptionalBoolean(action, [key]);
      if (value === undefined) {
        continue;
      }

      if (value || merged[key] === undefined) {
        merged[key] = value;
      }
    }
  }

  return Object.keys(merged).length ? merged : undefined;
}

function extractPendingUserActionDetailsRecord(
  payload: unknown
): Record<string, unknown> | undefined {
  return mergePendingUserActionDetails(extractPendingUserActionRecords(payload));
}

function extractEnvelopeDetails(payload: unknown): unknown {
  if (!isRecord(payload)) {
    return payload;
  }

  const errorRecord = isRecord(payload.error) ? payload.error : undefined;
  const errorDetailRecord = isRecord(payload.error_detail) ? payload.error_detail : undefined;
  const detailsRecord = isRecord(payload.details) ? payload.details : undefined;
  const userActionHintRecord = isRecord(payload.user_action_hint)
    ? payload.user_action_hint
    : undefined;
  const pendingUserActionDetailsRecord = extractPendingUserActionDetailsRecord(payload);

  if (errorRecord) {
    const mergedDetails = mergeDetailRecords(
      isRecord(errorRecord.details) ? errorRecord.details : undefined,
      mergeDetailRecords(
        userActionHintRecord,
        mergeDetailRecords(
          pendingUserActionDetailsRecord,
          mergeDetailRecords(errorDetailRecord, detailsRecord)
        )
      )
    );

    return mergedDetails
      ? {
          ...errorRecord,
          details: mergedDetails
        }
      : errorRecord;
  }

  return (
    mergeDetailRecords(
      userActionHintRecord,
      mergeDetailRecords(
        pendingUserActionDetailsRecord,
        mergeDetailRecords(errorDetailRecord, detailsRecord)
      )
    ) ?? payload
  );
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

function extractStringArrayDetails(
  payload: unknown,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): string[] {
  if (!isRecord(payload)) {
    return [];
  }

  if (seen.has(payload)) {
    return [];
  }

  seen.add(payload);
  const values = new Set<string>();

  for (const key of keys) {
    for (const item of getStringArray(payload[key])) {
      const trimmed = item.trim();
      if (trimmed) {
        values.add(trimmed);
      }
    }
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(payload[nestedKey])) {
      continue;
    }

    for (const item of extractStringArrayDetails(payload[nestedKey], keys, nestedKeys, seen)) {
      values.add(item);
    }
  }

  return [...values];
}

function extractStringRecordDetails(
  payload: unknown,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): Record<string, string> | undefined {
  if (!isRecord(payload)) {
    return undefined;
  }

  if (seen.has(payload)) {
    return undefined;
  }

  seen.add(payload);
  const values: Record<string, string> = {};

  for (const key of keys) {
    if (!isRecord(payload[key])) {
      continue;
    }

    for (const [itemKey, itemValue] of Object.entries(payload[key])) {
      if (typeof itemValue !== 'string') {
        continue;
      }

      const trimmedKey = itemKey.trim();
      const trimmedValue = itemValue.trim();

      if (trimmedKey && trimmedValue && values[trimmedKey] === undefined) {
        values[trimmedKey] = trimmedValue;
      }
    }
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(payload[nestedKey])) {
      continue;
    }

    const nestedValues = extractStringRecordDetails(payload[nestedKey], keys, nestedKeys, seen);
    if (!nestedValues) {
      continue;
    }

    for (const [itemKey, itemValue] of Object.entries(nestedValues)) {
      if (values[itemKey] === undefined) {
        values[itemKey] = itemValue;
      }
    }
  }

  return Object.keys(values).length ? values : undefined;
}

function extractStringArrayRecordDetails(
  payload: unknown,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): Record<string, string[]> | undefined {
  if (!isRecord(payload)) {
    return undefined;
  }

  if (seen.has(payload)) {
    return undefined;
  }

  seen.add(payload);
  const values = new Map<string, Set<string>>();

  for (const key of keys) {
    if (!isRecord(payload[key])) {
      continue;
    }

    for (const [itemKey, itemValue] of Object.entries(payload[key])) {
      const trimmedKey = itemKey.trim();
      if (!trimmedKey) {
        continue;
      }

      const bucket = values.get(trimmedKey) ?? new Set<string>();

      for (const entry of getStringArray(itemValue)) {
        const trimmedEntry = entry.trim();
        if (trimmedEntry) {
          bucket.add(trimmedEntry);
        }
      }

      if (bucket.size > 0) {
        values.set(trimmedKey, bucket);
      }
    }
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(payload[nestedKey])) {
      continue;
    }

    const nestedValues = extractStringArrayRecordDetails(payload[nestedKey], keys, nestedKeys, seen);
    if (!nestedValues) {
      continue;
    }

    for (const [itemKey, itemValues] of Object.entries(nestedValues)) {
      const bucket = values.get(itemKey) ?? new Set<string>();

      for (const entry of itemValues) {
        const trimmedEntry = entry.trim();
        if (trimmedEntry) {
          bucket.add(trimmedEntry);
        }
      }

      if (bucket.size > 0) {
        values.set(itemKey, bucket);
      }
    }
  }

  if (values.size === 0) {
    return undefined;
  }

  return Object.fromEntries(
    [...values.entries()].map(([itemKey, itemValues]) => [itemKey, [...itemValues]])
  );
}

function extractOptionalBooleanDetails(
  payload: unknown,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): boolean | undefined {
  if (!isRecord(payload)) {
    return undefined;
  }

  if (seen.has(payload)) {
    return undefined;
  }

  seen.add(payload);

  const directValue = getOptionalBoolean(payload, keys);
  if (directValue !== undefined) {
    return directValue;
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(payload[nestedKey])) {
      continue;
    }

    const nestedValue = extractOptionalBooleanDetails(payload[nestedKey], keys, nestedKeys, seen);
    if (nestedValue !== undefined) {
      return nestedValue;
    }
  }

  return undefined;
}

const API_USER_ACTION_KINDS = [
  'clarify-tool-input',
  'collect-auth-context',
  'user-confirmation'
] as const;

function extractOptionalUserActionKind(
  payload: unknown,
  keys: readonly string[],
  nestedKeys: readonly string[],
  seen = new Set<Record<string, unknown>>()
): ApiUserActionKind | undefined {
  if (!isRecord(payload)) {
    return undefined;
  }

  if (seen.has(payload)) {
    return undefined;
  }

  seen.add(payload);

  const directValue = getOptionalString(payload, keys);
  if (
    directValue &&
    (API_USER_ACTION_KINDS as readonly string[]).includes(directValue)
  ) {
    return directValue as ApiUserActionKind;
  }

  for (const nestedKey of nestedKeys) {
    if (!isRecord(payload[nestedKey])) {
      continue;
    }

    const nestedValue = extractOptionalUserActionKind(payload[nestedKey], keys, nestedKeys, seen);
    if (nestedValue) {
      return nestedValue;
    }
  }

  return undefined;
}

export function extractUserActionHintAction(
  payload: unknown
): ApiUserActionKind | undefined {
  if (payload instanceof ApiError) {
    return extractUserActionHintAction(payload.details);
  }

  const directAction = extractOptionalUserActionKind(
    payload,
    ['action'],
    ['error', 'error_detail', 'details', 'user_action_hint']
  );
  if (directAction) {
    return directAction;
  }

  return extractOptionalUserActionKind(
    extractPendingUserActionDetailsRecord(payload),
    ['action'],
    []
  );
}

export function extractApiErrorDetails(payload: unknown): ApiErrorDetailsInfo | undefined {
  if (payload instanceof ApiError) {
    return extractApiErrorDetails(payload.details);
  }

  const nestedKeys = ['error', 'error_detail', 'details', 'user_action_hint'] as const;
  const pendingUserActionDetails = extractPendingUserActionDetailsRecord(payload);
  const mergeStrings = (primary: string[], secondary: string[]): string[] => [
    ...new Set([...primary, ...secondary].map((value) => value.trim()).filter(Boolean))
  ];
  const mergeStringRecord = (
    primary?: Record<string, string>,
    secondary?: Record<string, string>
  ): Record<string, string> | undefined => {
    if (!primary && !secondary) {
      return undefined;
    }

    return {
      ...(secondary ?? {}),
      ...(primary ?? {})
    };
  };
  const mergeStringArrayRecord = (
    primary?: Record<string, string[]>,
    secondary?: Record<string, string[]>
  ): Record<string, string[]> | undefined => {
    if (!primary && !secondary) {
      return undefined;
    }

    const merged = new Map<string, Set<string>>();

    for (const source of [secondary, primary]) {
      if (!source) {
        continue;
      }

      for (const [key, values] of Object.entries(source)) {
        const bucket = merged.get(key) ?? new Set<string>();
        for (const value of values) {
          const trimmed = value.trim();
          if (trimmed) {
            bucket.add(trimmed);
          }
        }
        if (bucket.size) {
          merged.set(key, bucket);
        }
      }
    }

    return merged.size
      ? Object.fromEntries(
          [...merged.entries()].map(([key, values]) => [key, [...values]])
        )
      : undefined;
  };

  const missingFields = mergeStrings(
    extractStringArrayDetails(payload, ['missing_fields', 'missingFields'], nestedKeys),
    extractStringArrayDetails(pendingUserActionDetails, ['missing_fields', 'missingFields'], [])
  );
  const requiredPermissions = mergeStrings(
    extractStringArrayDetails(
      payload,
      ['required_permissions', 'requiredPermissions'],
      nestedKeys
    ),
    extractStringArrayDetails(
      pendingUserActionDetails,
      ['required_permissions', 'requiredPermissions'],
      []
    )
  );
  const missingAuthContext = mergeStrings(
    extractStringArrayDetails(
      payload,
      ['missing_auth_context', 'missingAuthContext'],
      nestedKeys
    ),
    extractStringArrayDetails(
      pendingUserActionDetails,
      ['missing_auth_context', 'missingAuthContext'],
      []
    )
  );
  const missingPayloadHints = mergeStringRecord(
    extractStringRecordDetails(
      payload,
      ['missing_payload_hints', 'missingPayloadHints'],
      nestedKeys
    ),
    extractStringRecordDetails(
      pendingUserActionDetails,
      ['missing_payload_hints', 'missingPayloadHints'],
      []
    )
  );
  const requiresAccountContext =
    extractOptionalBooleanDetails(
      payload,
      ['requires_account_context', 'requiresAccountContext'],
      nestedKeys
    ) ??
    extractOptionalBooleanDetails(
      pendingUserActionDetails,
      ['requires_account_context', 'requiresAccountContext'],
      []
    );
  const confirmationRequired =
    extractOptionalBooleanDetails(
      payload,
      ['confirmation_required', 'confirmationRequired'],
      nestedKeys
    ) ??
    extractOptionalBooleanDetails(
      pendingUserActionDetails,
      ['confirmation_required', 'confirmationRequired'],
      []
    );
  const confirmToolNames = mergeStrings(
    extractStringArrayDetails(
      payload,
      ['confirm_tool_names', 'confirmToolNames'],
      nestedKeys
    ),
    extractStringArrayDetails(
      pendingUserActionDetails,
      ['confirm_tool_names', 'confirmToolNames'],
      []
    )
  );
  const sessionContextBindings = mergeStringArrayRecord(
    extractStringArrayRecordDetails(
      payload,
      ['session_context_bindings', 'sessionContextBindings'],
      nestedKeys
    ),
    extractStringArrayRecordDetails(
      pendingUserActionDetails,
      ['session_context_bindings', 'sessionContextBindings'],
      []
    )
  );
  const userProfileBindings = mergeStringArrayRecord(
    extractStringArrayRecordDetails(
      payload,
      ['user_profile_bindings', 'userProfileBindings'],
      nestedKeys
    ),
    extractStringArrayRecordDetails(
      pendingUserActionDetails,
      ['user_profile_bindings', 'userProfileBindings'],
      []
    )
  );

  if (
    missingFields.length === 0 &&
    requiredPermissions.length === 0 &&
    missingAuthContext.length === 0 &&
    !missingPayloadHints &&
    requiresAccountContext === undefined &&
    confirmationRequired === undefined &&
    confirmToolNames.length === 0 &&
    !sessionContextBindings &&
    !userProfileBindings
  ) {
    return undefined;
  }

  return {
    missingFields,
    requiredPermissions,
    missingAuthContext,
    ...(missingPayloadHints ? { missingPayloadHints } : {}),
    ...(requiresAccountContext !== undefined ? { requiresAccountContext } : {}),
    ...(confirmationRequired !== undefined ? { confirmationRequired } : {}),
    ...(confirmToolNames.length ? { confirmToolNames } : {}),
    ...(sessionContextBindings ? { sessionContextBindings } : {}),
    ...(userProfileBindings ? { userProfileBindings } : {})
  };
}

export function createApiError(
  payload: unknown,
  status: number,
  response?: Response,
  fallbackMessage?: string,
  fallbackRequestId?: string
): ApiError {
  const requestId =
    extractEnvelopeRequestId(payload, response) ??
    (typeof fallbackRequestId === 'string' && fallbackRequestId.trim()
      ? fallbackRequestId.trim()
      : undefined);
  const resolvedStatus = resolveEnvelopeStatus(payload, status);
  return new ApiError(
    extractEnvelopeMessage(payload, fallbackMessage ?? `HTTP ${status}`),
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
  CHAT_STREAM_EVENTS_NOT_FOUND: { kind: 'not_found', status: 404 },
  ORCH_AGENT_NOT_FOUND: { kind: 'not_found', status: 404 },
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
  '4042102': FOUNDATION_ERROR_META_BY_NAME.ORCH_AGENT_NOT_FOUND,
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
  '5002005': FOUNDATION_ERROR_META_BY_NAME.CHAT_STREAM_EVENTS_NOT_FOUND,
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

export function resolveEnvelopeStatus(payload: unknown, fallbackStatus: number): number {
  const envelopeStatus = extractEnvelopeStatus(payload);
  if (envelopeStatus !== undefined) {
    return envelopeStatus;
  }

  const inferredStatus = inferHttpStatusFromCode(extractEnvelopeCode(payload));
  if (inferredStatus !== undefined && inferredStatus !== fallbackStatus) {
    return inferredStatus;
  }

  if (fallbackStatus >= 400) {
    return fallbackStatus;
  }

  return inferredStatus ?? fallbackStatus;
}

export function classifyApiError(error: unknown): ApiErrorKind {
  if (isAbortError(error)) {
    return 'timeout';
  }

  if (error instanceof Error && !(error instanceof ApiError)) {
    return isNetworkErrorLike(error) ? 'server' : 'unknown';
  }

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

  if (namedKind) {
    return namedKind;
  }

  if (status === 401) {
    return 'unauthorized';
  }

  if (status === 403) {
    return 'forbidden';
  }

  if (status === 404) {
    return 'not_found';
  }

  if (status === 409) {
    return 'conflict';
  }

  if (status === 429) {
    return 'rate_limited';
  }

  if (status === 408) {
    return 'timeout';
  }

  if (status === 400 || status === 422) {
    return 'validation';
  }

  if (status >= 500) {
    return 'server';
  }

  return 'unknown';
}

export function describeApiError(
  error: unknown,
  fallbackMessage = 'Request failed'
): ApiErrorInfo {
  if (error instanceof ApiError) {
    const status = inferHttpStatusFromCode(error.code) ?? error.status;
    const details = extractApiErrorDetails(error.details);
    return {
      kind: classifyApiError(error),
      message: error.message,
      status: status > 0 ? status : undefined,
      code: error.code,
      requestId: error.requestId,
      retryAfterMs: error.retryAfterMs,
      ...(details ? { details } : {})
    };
  }

  if (isRecord(error)) {
    const status = resolveEnvelopeStatus(error, 0);
    const details = extractApiErrorDetails(error);
    return {
      kind: classifyApiError(error),
      message: extractEnvelopeMessage(error, fallbackMessage),
      status: status > 0 ? status : undefined,
      code: extractEnvelopeCode(error),
      requestId: extractEnvelopeRequestId(error),
      retryAfterMs: extractEnvelopeRetryAfterMs(error),
      ...(details ? { details } : {})
    };
  }

  if (isAbortError(error)) {
    return {
      kind: 'timeout',
      message: error.message || fallbackMessage,
      status: 408
    };
  }

  if (error instanceof Error) {
    return {
      kind: isNetworkErrorLike(error) ? 'server' : 'unknown',
      message: error.message || fallbackMessage
    };
  }

  return {
    kind: 'unknown',
    message: fallbackMessage
  };
}

function hasStructuredUserActionDetails(
  details: ApiErrorDetailsInfo | undefined
): boolean {
  if (!details) {
    return false;
  }

  return (
    details.missingFields.length > 0 ||
    details.requiredPermissions.length > 0 ||
    details.missingAuthContext.length > 0 ||
    Boolean(details.missingPayloadHints && Object.keys(details.missingPayloadHints).length > 0) ||
    Boolean(details.requiresAccountContext) ||
    Boolean(details.confirmationRequired) ||
    Boolean(details.confirmToolNames?.length) ||
    Boolean(details.sessionContextBindings && Object.keys(details.sessionContextBindings).length > 0) ||
    Boolean(details.userProfileBindings && Object.keys(details.userProfileBindings).length > 0)
  );
}

function hasPendingUserActionHint(error: unknown): boolean {
  return (
    extractUserActionHintAction(error) !== undefined ||
    hasStructuredUserActionDetails(extractApiErrorDetails(error))
  );
}

export function shouldRetryApiError(error: unknown): boolean {
  if (hasPendingUserActionHint(error)) {
    return false;
  }

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

  if (hasPendingUserActionHint(error)) {
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

export function unwrapEnvelope<T>(
  payload: unknown,
  status = 200,
  response?: Response,
  fallbackRequestId?: string
): T {
  if (!isRecord(payload)) {
    return payload as T;
  }

  if (payload.success === false) {
    throw createApiError(payload, status, response, 'Request failed', fallbackRequestId);
  }

  if ('success' in payload && 'data' in payload) {
    return payload.data as T;
  }

  const code = extractEnvelopeCode(payload);
  if (code !== undefined && code !== 0 && code !== '0') {
    throw createApiError(payload, status, response, 'Request failed', fallbackRequestId);
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

  const parseSseField = (line: string): { field: string; value: string } | null => {
    if (!line.trim() || line.startsWith(':')) {
      return null;
    }

    const separatorIndex = line.indexOf(':');
    if (separatorIndex === -1) {
      return {
        field: line,
        value: ''
      };
    }

    const field = line.slice(0, separatorIndex);
    let value = line.slice(separatorIndex + 1);
    if (value.startsWith(' ')) {
      value = value.slice(1);
    }

    return { field, value };
  };

  for (const line of lines) {
    const parsedLine = parseSseField(line);
    if (!parsedLine) {
      continue;
    }

    if (parsedLine.field === 'event') {
      event = parsedLine.value.trim() || event;
      continue;
    }

    if (parsedLine.field === 'id') {
      id = parsedLine.value.trim() || undefined;
      continue;
    }

    if (parsedLine.field === 'retry') {
      const parsed = Number(parsedLine.value.trim());
      retry = Number.isFinite(parsed) && parsed >= 0 ? parsed : retry;
      continue;
    }

    if (parsedLine.field === 'data') {
      dataLines.push(parsedLine.value);
    }
  }

  if ((event === 'ping' || event === 'heartbeat') && dataLines.length === 0) {
    return { event, data: {}, id, retry };
  }

  if (dataLines.length === 0) {
    if (retry !== undefined) {
      return {
        event: event === 'message' ? 'heartbeat' : event,
        data: {},
        id,
        retry
      };
    }

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
