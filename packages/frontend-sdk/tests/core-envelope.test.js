import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  ApiError,
  classifyApiError,
  createApiError,
  extractEnvelopeRetryAfterMs,
  parseSseBlock,
  resolveSseReconnectDelayMs,
  shouldReconnectSseStream,
  shouldRetryApiError
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
const {
  frontendFoundationErrorCodes,
  frontendSupplementalFoundationErrorCodes
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/error-codes.js');
test('extractEnvelopeRetryAfterMs prefers Retry-After header over payload hints', () => {
  const payload = {
    code: 4290001,
    message: 'slow down',
    error: {
      details: {
        retry_after_ms: 1500
      }
    }
  };
  const response = new Response(JSON.stringify(payload), {
    status: 429,
    headers: {
      'Retry-After': '2'
    }
  });

  assert.equal(extractEnvelopeRetryAfterMs(payload, response), 2000);
});

test('createApiError preserves top-level error_detail payloads for shared conflict handling', () => {
  const payload = {
    code: 4090001,
    message: 'idempotency conflict',
    request_id: 'req-conflict',
    error_detail: {
      missing_fields: ['order_no', 'amount']
    }
  };

  const error = createApiError(payload, 409);

  assert.equal(error.status, 409);
  assert.equal(error.code, 4090001);
  assert.equal(error.requestId, 'req-conflict');
  assert.deepEqual(error.details, {
    missing_fields: ['order_no', 'amount']
  });
  assert.equal(classifyApiError(error), 'conflict');
  assert.equal(shouldReconnectSseStream(error), false);
});

test('classifyApiError and retry helpers cover structured auth and rate-limit failures', () => {
  assert.equal(classifyApiError(new ApiError('expired', 401, 4010002)), 'unauthorized');
  assert.equal(classifyApiError(new ApiError('forbidden', 403, 4030001)), 'forbidden');
  assert.equal(classifyApiError(new ApiError('missing', 404, 4042104)), 'not_found');
  assert.equal(classifyApiError(new ApiError('conflict', 409, 4090001)), 'conflict');
  assert.equal(classifyApiError(new ApiError('slow down', 429, 4290001)), 'rate_limited');
  assert.equal(classifyApiError(new ApiError('timeout', 408)), 'timeout');

  assert.equal(shouldRetryApiError(new ApiError('slow down', 429, 4290001)), true);
  assert.equal(shouldRetryApiError(new ApiError('missing', 404, 4042104)), false);
  assert.equal(shouldRetryApiError(new ApiError('conflict', 409, 4090001)), false);
  assert.equal(shouldReconnectSseStream(new ApiError('forbidden', 403, 4030001)), false);
  assert.equal(shouldReconnectSseStream(new ApiError('missing', 404, 4042104)), false);
  assert.equal(shouldReconnectSseStream(new ApiError('server', 500)), true);
});

test('classifyApiError and reconnect delay also handle structured error-like payloads', () => {
  assert.equal(
    classifyApiError({
      status: 403,
      error: {
        code: 4030001
      }
    }),
    'forbidden'
  );

  assert.equal(
    resolveSseReconnectDelayMs({
      error: {
        status: 429,
        error_detail: {
          retry_after_ms: 2750
        }
      }
    }),
    2750
  );

  assert.equal(
    resolveSseReconnectDelayMs({
      error: {
        status: 401,
        error: {
          code: 4010002
        }
      }
    }),
    null
  );
});

test('classifyApiError aligns named shared error codes and nested code outlets to the expected retry bucket', () => {
  assert.equal(
    classifyApiError({
      error_detail: {
        code: 'AUTH_UNAUTHORIZED'
      }
    }),
    'unauthorized'
  );
  assert.equal(
    classifyApiError({
      error: {
        details: {
          code: 'IDEMPOTENCY_CONFLICT'
        }
      }
    }),
    'conflict'
  );
  assert.equal(
    classifyApiError({
      code: '5030001'
    }),
    'server'
  );
  assert.equal(
    classifyApiError({
      details: {
        code: 'VALIDATION_ERROR'
      }
    }),
    'validation'
  );
  assert.equal(
    classifyApiError({
      error: {
        error_code: 'BUSINESS_TOOLS_CALLER_FORBIDDEN'
      }
    }),
    'forbidden'
  );
  assert.equal(
    classifyApiError({
      error_detail: {
        error_code: 'CHAT_MESSAGE_NOT_RUNNING'
      }
    }),
    'conflict'
  );
  assert.equal(
    classifyApiError({
      error_code: 'CHAT_CONVERSATION_NOT_FOUND'
    }),
    'not_found'
  );
});

test('parseSseBlock captures retry and id metadata and reconnect delay respects them', () => {
  const event = parseSseBlock([
    'id: evt-1',
    'event: delta',
    'retry: 4500',
    'data: {"content":"hello"}'
  ].join('\n'));

  assert.deepEqual(event, {
    id: 'evt-1',
    event: 'delta',
    retry: 4500,
    data: {
      content: 'hello'
    }
  });

  assert.equal(resolveSseReconnectDelayMs({ event, attempt: 3 }), 4500);
  assert.equal(resolveSseReconnectDelayMs({ error: new ApiError('unauthorized', 401, 4010002) }), null);
  assert.equal(
    resolveSseReconnectDelayMs({
      error: new ApiError('rate limited', 429, 4290001, undefined, undefined, 1800),
      attempt: 2
    }),
    1800
  );
  assert.equal(resolveSseReconnectDelayMs({ error: new Error('render state mismatch') }), null);
  assert.equal(resolveSseReconnectDelayMs({ error: new TypeError('Failed to fetch'), attempt: 2 }), 2000);
  assert.equal(shouldReconnectSseStream(new Error('unexpected render state mismatch')), false);
  assert.equal(shouldReconnectSseStream({ message: 'opaque object error' }), false);
  assert.equal(shouldReconnectSseStream(new TypeError('stream connection lost')), true);
});

test('createApiError honors error_code and error_message aliases from frozen service contracts', () => {
  const payload = {
    error_code: 'CHAT_CONVERSATION_NOT_FOUND',
    error_message: 'conversation missing',
    requestId: 'req-missing-conversation'
  };

  const error = createApiError(payload, 404);

  assert.equal(error.status, 404);
  assert.equal(error.code, 'CHAT_CONVERSATION_NOT_FOUND');
  assert.equal(error.requestId, 'req-missing-conversation');
  assert.match(error.message, /conversation missing/);
  assert.equal(classifyApiError(error), 'not_found');
  assert.equal(shouldReconnectSseStream(error), false);
});

test('createApiError infers shared status for in-band alias envelopes when HTTP status stays 200', () => {
  const error = createApiError(
    {
      error_code: 'RATE_LIMITED',
      error_message: 'slow down',
      requestId: 'req-rate-inband',
      retry_after: 2
    },
    200
  );

  assert.equal(error.status, 429);
  assert.equal(error.code, 'RATE_LIMITED');
  assert.equal(error.requestId, 'req-rate-inband');
  assert.equal(error.retryAfterMs, 2000);
});

test('resolveSseReconnectDelayMs honors named rate-limit aliases and structured retry_after payloads', () => {
  assert.equal(
    resolveSseReconnectDelayMs({
      error: {
        error_code: 'RATE_LIMITED',
        retry_after: '2'
      }
    }),
    2000
  );
});

test('frontend shared error-code outlet extends frozen foundation exports with the current owned supplement', () => {
  assert.deepEqual(frontendSupplementalFoundationErrorCodes, [
    'BUSINESS_TOOLS_CALLER_FORBIDDEN',
    'CHAT_CONTINUATION_NOT_AVAILABLE',
    'CHAT_CONVERSATION_RUNNING',
    'CHAT_MESSAGE_CANCELLED',
    'CHAT_MESSAGE_NOT_RUNNING',
    'TOOL_HUB_CALLER_FORBIDDEN'
  ]);

  assert.equal(frontendFoundationErrorCodes.includes('RATE_LIMITED'), true);
  assert.equal(frontendFoundationErrorCodes.includes('TOOL_HUB_CALLER_FORBIDDEN'), true);
});
