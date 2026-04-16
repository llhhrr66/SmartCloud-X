import type { FoundationErrorCode } from '@smartcloud-x/common-schemas';

const frontendFoundationErrorCodeRegistry = {
  AUTH_INVALID_TOKEN: true,
  AUTH_UNAUTHORIZED: true,
  BUSINESS_TOOLS_CALLER_FORBIDDEN: true,
  ORCH_AGENT_NOT_FOUND: true,
  CHAT_CONVERSATION_ARCHIVED: true,
  CHAT_CONVERSATION_NOT_FOUND: true,
  CHAT_CONTINUATION_NOT_AVAILABLE: true,
  CHAT_CONVERSATION_RUNNING: true,
  CHAT_CONVERSATION_RESTORE_INVALID: true,
  CHAT_STREAM_EVENTS_NOT_FOUND: true,
  CHAT_MESSAGE_CANCELLED: true,
  CHAT_MESSAGE_NOT_FOUND: true,
  CHAT_MESSAGE_NOT_RUNNING: true,
  IDEMPOTENCY_CONFLICT: true,
  INTERNAL_ERROR: true,
  KNOWLEDGE_SYNC_FAILED: true,
  ORCH_CALLER_FORBIDDEN: true,
  ORCH_ROUTE_FAILED: true,
  ORCH_SESSION_STATE_NOT_FOUND: true,
  ORCH_TOOL_AUTH_REQUIRED: true,
  ORCH_TOOL_CALL_NOT_FOUND: true,
  ORCH_TOOL_NOT_FOUND: true,
  ORCH_TOOL_OPERATION_INVALID: true,
  ORCH_TOOL_PAYLOAD_INVALID: true,
  RAG_RETRIEVAL_UNAVAILABLE: true,
  RATE_LIMITED: true,
  SERVICE_UNAVAILABLE: true,
  TOOL_HUB_CALLER_FORBIDDEN: true,
  VALIDATION_ERROR: true
} satisfies Record<FoundationErrorCode, true>;

export const frontendBaseFoundationErrorCodes = Object.keys(
  frontendFoundationErrorCodeRegistry
) as FoundationErrorCode[];

/**
 * Kept as a compatibility export for downstream imports. Foundation now exports
 * the full frozen catalog, so the frontend supplement list is currently empty.
 */
export type FrontendSupplementalFoundationErrorCode = Exclude<
  'CHAT_STREAM_EVENTS_NOT_FOUND',
  FoundationErrorCode
>;

const frontendSupplementalFoundationErrorCodeRegistry = {} satisfies Record<
  FrontendSupplementalFoundationErrorCode,
  true
>;

export type FrontendFoundationErrorCode =
  | FoundationErrorCode
  | FrontendSupplementalFoundationErrorCode;

export const frontendSupplementalFoundationErrorCodes = Object.keys(
  frontendSupplementalFoundationErrorCodeRegistry
) as FrontendSupplementalFoundationErrorCode[];

export const frontendFoundationErrorCodes: FrontendFoundationErrorCode[] = [
  ...frontendBaseFoundationErrorCodes,
  ...frontendSupplementalFoundationErrorCodes
];

export function isFrontendFoundationErrorCode(
  value: unknown
): value is FrontendFoundationErrorCode {
  return (
    typeof value === 'string' &&
    frontendFoundationErrorCodes.includes(value as FrontendFoundationErrorCode)
  );
}
