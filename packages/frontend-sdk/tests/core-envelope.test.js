import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  ApiError,
  classifyApiError,
  createApiError,
  describeApiError,
  extractApiErrorDetails,
  extractEnvelopeRetryAfterMs,
  extractUserActionHintAction,
  parseSseBlock,
  resolveSseReconnectDelayMs,
  shouldReconnectSseStream,
  shouldRetryApiError
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
const {
  frontendFoundationErrorCodes,
  frontendSupplementalFoundationErrorCodes,
  isFrontendFoundationErrorCode
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

test('extractEnvelopeRetryAfterMs supports HTTP-date Retry-After headers for shared 429 handling', () => {
  const originalNow = Date.now;
  Date.now = () => 1_776_300_000_000;

  try {
    const response = new Response('{}', {
      status: 429,
      headers: {
        'Retry-After': new Date(Date.now() + 3_000).toUTCString()
      }
    });

    assert.equal(extractEnvelopeRetryAfterMs({}, response), 3000);
  } finally {
    Date.now = originalNow;
  }
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

test('classifyApiError and retry helpers align raw abort and network transport errors with shared retry buckets', () => {
  const abortError = new Error('user cancelled');
  abortError.name = 'AbortError';

  assert.equal(classifyApiError(abortError), 'timeout');
  assert.equal(shouldRetryApiError(abortError), true);

  const networkError = new TypeError('Failed to fetch');
  assert.equal(classifyApiError(networkError), 'server');
  assert.equal(shouldRetryApiError(networkError), true);

  const renderError = new Error('render state mismatch');
  assert.equal(classifyApiError(renderError), 'unknown');
  assert.equal(shouldRetryApiError(renderError), false);
});

test('shared frontend supplemental stream-events not-found codes classify as non-retryable missing resources', () => {
  const cases = [
    new ApiError('stream events missing', 404, 'CHAT_STREAM_EVENTS_NOT_FOUND'),
    new ApiError('stream events missing', 500, 5002005)
  ];

  for (const error of cases) {
    assert.equal(classifyApiError(error), 'not_found');
    assert.equal(shouldRetryApiError(error), false);
    assert.equal(shouldReconnectSseStream(error), false);
    assert.equal(describeApiError(error).status, 404);
  }
});

test('describeApiError preserves structured 401/403/409/429 metadata across ApiError and envelope inputs', () => {
  const cases = [
    {
      input: new ApiError('expired', 401, 'AUTH_UNAUTHORIZED', undefined, 'req-auth'),
      expected: {
        kind: 'unauthorized',
        status: 401,
        code: 'AUTH_UNAUTHORIZED',
        requestId: 'req-auth',
        retryAfterMs: undefined
      }
    },
    {
      input: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-forbidden'
      },
      expected: {
        kind: 'forbidden',
        status: 403,
        code: 'TOOL_HUB_CALLER_FORBIDDEN',
        requestId: 'req-forbidden',
        retryAfterMs: undefined
      }
    },
    {
      input: {
        error: {
          code: 'CHAT_CONVERSATION_RUNNING',
          message: 'conversation still running'
        },
        request_id: 'req-conflict'
      },
      expected: {
        kind: 'conflict',
        status: 409,
        code: 'CHAT_CONVERSATION_RUNNING',
        requestId: 'req-conflict',
        retryAfterMs: undefined
      }
    },
    {
      input: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-rate',
        retry_after: 2
      },
      expected: {
        kind: 'rate_limited',
        status: 429,
        code: 'RATE_LIMITED',
        requestId: 'req-rate',
        retryAfterMs: 2000
      }
    }
  ];

  for (const item of cases) {
    const info = describeApiError(item.input);

    assert.equal(info.kind, item.expected.kind);
    assert.equal(info.status, item.expected.status);
    assert.equal(info.code, item.expected.code);
    assert.equal(info.requestId, item.expected.requestId);
    assert.equal(info.retryAfterMs, item.expected.retryAfterMs);
    assert.ok(info.message.length > 0);
  }
});

test('extractApiErrorDetails dedupes nested missing fields, permission requirements, and auth-context hints', () => {
  const payload = {
    error: {
      code: 'ORCH_TOOL_AUTH_REQUIRED',
      details: {
        missing_fields: ['order_no', ' amount ', 'order_no'],
        required_permissions: ['user:billing.read'],
        missing_auth_context: ['account_id']
      }
    },
    error_detail: {
      missing_auth_context: ['permission:user:billing.read', 'account_id']
    }
  };

  assert.deepEqual(extractApiErrorDetails(payload), {
    missingFields: ['order_no', 'amount'],
    requiredPermissions: ['user:billing.read'],
    missingAuthContext: ['account_id', 'permission:user:billing.read']
  });

  assert.deepEqual(describeApiError(payload).details, {
    missingFields: ['order_no', 'amount'],
    requiredPermissions: ['user:billing.read'],
    missingAuthContext: ['account_id', 'permission:user:billing.read']
  });
});

test('extractApiErrorDetails preserves structured action-hint metadata aligned to frozen continuation contracts', () => {
  const payload = {
    status: 500,
    error: {
      code: 'SERVICE_UNAVAILABLE',
      user_action_hint: {
        action: 'collect-auth-context',
        missing_payload_hints: {
          order_no: '请输入订单号',
          invoice_title: '请补充发票抬头'
        },
        requires_account_context: true,
        session_context_bindings: {
          account_id: ['account_id']
        }
      }
    },
    details: {
      confirmation_required: true,
      confirm_tool_names: ['billing.create_invoice'],
      user_profile_bindings: {
        permissions: ['permissions']
      }
    }
  };

  assert.equal(extractUserActionHintAction(payload), 'collect-auth-context');
  assert.deepEqual(extractApiErrorDetails(payload), {
    missingFields: [],
    requiredPermissions: [],
    missingAuthContext: [],
    missingPayloadHints: {
      order_no: '请输入订单号',
      invoice_title: '请补充发票抬头'
    },
    requiresAccountContext: true,
    confirmationRequired: true,
    confirmToolNames: ['billing.create_invoice'],
    sessionContextBindings: {
      account_id: ['account_id']
    },
    userProfileBindings: {
      permissions: ['permissions']
    }
  });
});

test('pending_user_actions metadata is treated as actionable shared continuation state instead of a retryable server failure', () => {
  const payload = {
    status: 500,
    error: {
      code: 'SERVICE_UNAVAILABLE',
      message: 'tool needs follow-up'
    },
    pending_user_actions: [
      {
        tool_name: 'billing.create_invoice',
        tool_call_id: 'tc_invoice_001',
        agent: 'Finance_Order_Agent',
        action: 'collect-auth-context',
        message: '请先补充账号与权限上下文',
        missing_auth_context: ['account_id', 'permission:user:billing.read'],
        required_permissions: ['user:billing.read'],
        missing_payload_hints: {
          statement_no: '请选择要开票的账单'
        },
        session_context_bindings: {
          account_id: ['account_id']
        },
        user_profile_bindings: {
          permissions: ['permissions']
        }
      }
    ]
  };

  const apiError = createApiError(payload, 500);

  assert.equal(extractUserActionHintAction(payload), 'collect-auth-context');
  assert.equal(extractUserActionHintAction(apiError), 'collect-auth-context');
  assert.deepEqual(extractApiErrorDetails(payload), {
    missingFields: [],
    requiredPermissions: ['user:billing.read'],
    missingAuthContext: ['account_id', 'permission:user:billing.read'],
    missingPayloadHints: {
      statement_no: '请选择要开票的账单'
    },
    sessionContextBindings: {
      account_id: ['account_id']
    },
    userProfileBindings: {
      permissions: ['permissions']
    }
  });
  assert.deepEqual(extractApiErrorDetails(apiError), {
    missingFields: [],
    requiredPermissions: ['user:billing.read'],
    missingAuthContext: ['account_id', 'permission:user:billing.read'],
    missingPayloadHints: {
      statement_no: '请选择要开票的账单'
    },
    sessionContextBindings: {
      account_id: ['account_id']
    },
    userProfileBindings: {
      permissions: ['permissions']
    }
  });
  assert.equal(shouldRetryApiError(payload), false);
  assert.equal(shouldRetryApiError(apiError), false);
  assert.equal(shouldReconnectSseStream(payload), false);
  assert.equal(shouldReconnectSseStream(apiError), false);
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

test('retry and reconnect helpers do not treat explicit user-action envelopes as transient even when they look server-shaped', () => {
  const payload = {
    status: 500,
    error: {
      code: 'SERVICE_UNAVAILABLE'
    },
    user_action_hint: {
      action: 'collect-auth-context',
      message: '请先补充账号上下文',
      missing_auth_context: ['account_id'],
      required_permissions: ['user:billing.read']
    }
  };

  assert.equal(shouldRetryApiError(payload), false);
  assert.equal(shouldReconnectSseStream(payload), false);
  assert.equal(resolveSseReconnectDelayMs({ error: payload }), null);
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
  assert.equal(
    classifyApiError({
      error_code: 'ORCH_AGENT_NOT_FOUND'
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

test('parseSseBlock preserves multiline raw data whitespace according to SSE field semantics', () => {
  const event = parseSseBlock([
    'event: message.delta',
    'data:  hello',
    'data:',
    'data: world  '
  ].join('\n'));

  assert.deepEqual(event, {
    event: 'message.delta',
    id: undefined,
    retry: undefined,
    data: ' hello\n\nworld  '
  });
});

test('parseSseBlock converts retry-only control frames into heartbeat no-op events so reconnect helpers can observe server backoff', () => {
  const event = parseSseBlock('retry: 1750');

  assert.deepEqual(event, {
    event: 'heartbeat',
    id: undefined,
    retry: 1750,
    data: {}
  });
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

test('createApiError resolves nested details metadata for request id, message, and status', () => {
  const payload = {
    error: {
      details: {
        code: 'RATE_LIMITED',
        message: 'slow down from nested details',
        status: 429,
        request_id: 'req-nested-details',
        retry_after_ms: 1750
      }
    },
    trace: {
      requestId: 'req-trace-fallback'
    }
  };

  const error = createApiError(payload, 500);

  assert.equal(error.status, 429);
  assert.equal(error.code, 'RATE_LIMITED');
  assert.equal(error.requestId, 'req-nested-details');
  assert.equal(error.retryAfterMs, 1750);
  assert.match(error.message, /slow down from nested details/);
  assert.equal(classifyApiError(error), 'rate_limited');
});

test('createApiError falls back to trace request ids when nested error metadata omits one', () => {
  const payload = {
    error: {
      code: 'SERVICE_UNAVAILABLE',
      message: 'dependency unavailable'
    },
    trace: {
      requestId: 'req-trace-only'
    }
  };

  const error = createApiError(payload, 503);

  assert.equal(error.status, 503);
  assert.equal(error.code, 'SERVICE_UNAVAILABLE');
  assert.equal(error.requestId, 'req-trace-only');
  assert.match(error.message, /dependency unavailable/);
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

test('createApiError prefers structured shared status over a mislabeled HTTP 401 transport status', () => {
  const error = createApiError(
    {
      error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
      error_message: 'caller rejected',
      requestId: 'req-mislabeled-status'
    },
    401
  );

  assert.equal(error.status, 403);
  assert.equal(error.code, 'TOOL_HUB_CALLER_FORBIDDEN');
  assert.equal(error.requestId, 'req-mislabeled-status');
});

test('createApiError lets frozen named error codes override generic mismatched transport statuses', () => {
  const cases = [
    {
      payload: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-mismatched-403'
      },
      transportStatus: 400,
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN',
      expectedKind: 'forbidden'
    },
    {
      payload: {
        error_code: 'CHAT_CONVERSATION_RUNNING',
        error_message: 'conversation still running',
        requestId: 'req-mismatched-409'
      },
      transportStatus: 500,
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING',
      expectedKind: 'conflict'
    },
    {
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-mismatched-429',
        retry_after: 2
      },
      transportStatus: 500,
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedKind: 'rate_limited',
      expectedRetryAfterMs: 2000
    },
    {
      payload: {
        error_code: 'SERVICE_UNAVAILABLE',
        error_message: 'dependency unavailable',
        requestId: 'req-mismatched-503'
      },
      transportStatus: 400,
      expectedStatus: 503,
      expectedCode: 'SERVICE_UNAVAILABLE',
      expectedKind: 'server'
    }
  ];

  for (const item of cases) {
    const error = createApiError(item.payload, item.transportStatus);

    assert.equal(error.status, item.expectedStatus);
    assert.equal(error.code, item.expectedCode);
    assert.equal(error.requestId, item.payload.requestId);
    assert.equal(error.retryAfterMs, item.expectedRetryAfterMs);
    assert.equal(classifyApiError(error), item.expectedKind);
  }
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

test('frontend shared error-code outlet stays aligned to the frozen catalog after foundation exported stream-events replay misses', () => {
  assert.deepEqual(frontendSupplementalFoundationErrorCodes, []);

  assert.equal(frontendFoundationErrorCodes.includes('CHAT_STREAM_EVENTS_NOT_FOUND'), true);
  assert.equal(frontendFoundationErrorCodes.includes('RATE_LIMITED'), true);
  assert.equal(frontendFoundationErrorCodes.includes('ORCH_AGENT_NOT_FOUND'), true);
  assert.equal(frontendFoundationErrorCodes.includes('TOOL_HUB_CALLER_FORBIDDEN'), true);
  assert.equal(isFrontendFoundationErrorCode('ORCH_AGENT_NOT_FOUND'), true);
  assert.equal(isFrontendFoundationErrorCode('CHAT_STREAM_EVENTS_NOT_FOUND'), true);
});
