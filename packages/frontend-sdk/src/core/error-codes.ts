import type { FoundationErrorCode } from '@smartcloud-x/common-schemas';

export const frontendBaseFoundationErrorCodes: FoundationErrorCode[] = [
  'AUTH_INVALID_TOKEN',
  'AUTH_UNAUTHORIZED',
  'CHAT_CONVERSATION_ARCHIVED',
  'CHAT_CONVERSATION_NOT_FOUND',
  'CHAT_CONVERSATION_RESTORE_INVALID',
  'CHAT_MESSAGE_NOT_FOUND',
  'IDEMPOTENCY_CONFLICT',
  'INTERNAL_ERROR',
  'KNOWLEDGE_SYNC_FAILED',
  'ORCH_CALLER_FORBIDDEN',
  'ORCH_ROUTE_FAILED',
  'ORCH_SESSION_STATE_NOT_FOUND',
  'ORCH_TOOL_AUTH_REQUIRED',
  'ORCH_TOOL_CALL_NOT_FOUND',
  'ORCH_TOOL_NOT_FOUND',
  'ORCH_TOOL_OPERATION_INVALID',
  'ORCH_TOOL_PAYLOAD_INVALID',
  'RAG_RETRIEVAL_UNAVAILABLE',
  'RATE_LIMITED',
  'SERVICE_UNAVAILABLE',
  'VALIDATION_ERROR'
];

export type FrontendSupplementalFoundationErrorCode =
  | 'BUSINESS_TOOLS_CALLER_FORBIDDEN'
  | 'CHAT_CONTINUATION_NOT_AVAILABLE'
  | 'CHAT_CONVERSATION_RUNNING'
  | 'CHAT_MESSAGE_CANCELLED'
  | 'CHAT_MESSAGE_NOT_RUNNING'
  | 'TOOL_HUB_CALLER_FORBIDDEN';

export type FrontendFoundationErrorCode =
  | FoundationErrorCode
  | FrontendSupplementalFoundationErrorCode;

export const frontendSupplementalFoundationErrorCodes: FrontendSupplementalFoundationErrorCode[] = [
  'BUSINESS_TOOLS_CALLER_FORBIDDEN',
  'CHAT_CONTINUATION_NOT_AVAILABLE',
  'CHAT_CONVERSATION_RUNNING',
  'CHAT_MESSAGE_CANCELLED',
  'CHAT_MESSAGE_NOT_RUNNING',
  'TOOL_HUB_CALLER_FORBIDDEN'
];

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
