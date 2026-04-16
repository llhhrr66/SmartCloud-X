import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  ApiError,
  classifyApiError,
  describeApiError
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
const { createApiClient } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/http.js');

test('FrontendApiClient refreshes the session once on a structured 401 response', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            code: 4010002,
            message: 'token expired',
            request_id: 'req-expired'
          }),
          {
            status: 401,
            headers: {
              'content-type': 'application/json'
            }
          }
        );
      }

      return new Response(
        JSON.stringify({
          code: 0,
          message: 'ok',
          request_id: 'req-ok',
          timestamp: 1776300000000,
          data: {
            value: 42
          }
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json'
          }
        }
      );
    },
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => {
      refreshCount += 1;
      return { refreshed: true };
    }
  });

  const result = await client.request('/api/v1/demo');

  assert.deepEqual(result, { value: 42 });
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('FrontendApiClient exposes rate-limit metadata on ApiError', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          code: 4290001,
          message: 'too many requests',
          request_id: 'req-rate'
        }),
        {
          status: 429,
          headers: {
            'content-type': 'application/json',
            'Retry-After': '1'
          }
        }
      )
  });

  await assert.rejects(
    client.request('/api/v1/limited'),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 429);
      assert.equal(error.code, 4290001);
      assert.equal(error.requestId, 'req-rate');
      assert.equal(error.retryAfterMs, 1000);
      return true;
    }
  );
});

test('FrontendApiClient preserves structured 403 envelope metadata', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          success: false,
          message: 'permission denied',
          request_id: 'req-forbidden',
          error: {
            code: 4030001
          }
        }),
        {
          status: 403,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/forbidden'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 403);
    assert.equal(error.code, 4030001);
    assert.equal(error.requestId, 'req-forbidden');
    return true;
  });
});

test('FrontendApiClient falls back to the generated request id when structured HTTP errors omit it', async () => {
  let capturedRequestId = null;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');

      return new Response(
        JSON.stringify({
          error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
          error_message: 'caller rejected'
        }),
        {
          status: 403,
          headers: {
            'content-type': 'application/json'
          }
        }
      );
    }
  });

  await assert.rejects(client.request('/api/v1/forbidden-no-request-id'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 403);
    assert.equal(error.code, 'TOOL_HUB_CALLER_FORBIDDEN');
    assert.equal(error.requestId, capturedRequestId);
    assert.match(error.message, new RegExp(String(capturedRequestId)));
    return true;
  });
});

test('FrontendApiClient supports error_code and error_message alias envelopes from shared service contracts', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'BUSINESS_TOOLS_CALLER_FORBIDDEN',
          error_message: 'caller rejected',
          requestId: 'req-business-tools'
        }),
        {
          status: 403,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/internal/v1/tools'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 403);
    assert.equal(error.code, 'BUSINESS_TOOLS_CALLER_FORBIDDEN');
    assert.equal(error.requestId, 'req-business-tools');
    assert.match(error.message, /caller rejected/);
    return true;
  });
});

test('FrontendApiClient extracts nested named error codes from structured 403 envelopes', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          message: 'permission denied',
          request_id: 'req-nested-forbidden',
          error_detail: {
            code: 'TOOL_HUB_CALLER_FORBIDDEN'
          }
        }),
        {
          status: 403,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/internal/tools'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 403);
    assert.equal(error.code, 'TOOL_HUB_CALLER_FORBIDDEN');
    assert.equal(error.requestId, 'req-nested-forbidden');
    return true;
  });
});

test('FrontendApiClient preserves retry metadata from structured 429 alias envelopes without Retry-After headers', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'slow down',
          requestId: 'req-rate-body',
          retry_after: 2
        }),
        {
          status: 429,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/rate-limited'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.requestId, 'req-rate-body');
    assert.equal(error.retryAfterMs, 2000);
    return true;
  });
});

test('FrontendApiClient preserves structured 409 error_detail envelopes', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          code: 4090001,
          message: 'idempotency conflict',
          request_id: 'req-conflict',
          error_detail: {
            missing_fields: ['order_no', 'amount']
          }
        }),
        {
          status: 409,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/refunds'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 409);
    assert.equal(error.code, 4090001);
    assert.equal(error.requestId, 'req-conflict');
    assert.deepEqual(error.details, {
      missing_fields: ['order_no', 'amount']
    });
    return true;
  });
});

test('FrontendApiClient preserves structured 401/403/409/429 semantics end-to-end for shared consumers', async () => {
  const cases = [
    {
      path: '/api/v1/unauthorized',
      payload: {
        error_code: 'AUTH_UNAUTHORIZED',
        error_message: 'session expired',
        requestId: 'req-http-401'
      },
      transportStatus: 401,
      expected: {
        kind: 'unauthorized',
        status: 401,
        code: 'AUTH_UNAUTHORIZED',
        requestId: 'req-http-401'
      }
    },
    {
      path: '/api/v1/forbidden-auth-context',
      payload: {
        requestId: 'req-http-403',
        error: {
          code: 'TOOL_HUB_CALLER_FORBIDDEN',
          message: 'billing.create_invoice requires auth context'
        },
        user_action_hint: {
          action: 'collect-auth-context',
          missing_auth_context: ['account_id'],
          required_permissions: ['user:billing.read']
        }
      },
      transportStatus: 401,
      expected: {
        kind: 'forbidden',
        status: 403,
        code: 'TOOL_HUB_CALLER_FORBIDDEN',
        requestId: 'req-http-403',
        details: {
          missingFields: [],
          requiredPermissions: ['user:billing.read'],
          missingAuthContext: ['account_id']
        }
      }
    },
    {
      path: '/api/v1/conflict-idempotency',
      payload: {
        code: 4090001,
        message: 'idempotency conflict',
        request_id: 'req-http-409',
        error_detail: {
          missing_fields: ['order_no', 'amount']
        }
      },
      transportStatus: 500,
      expected: {
        kind: 'conflict',
        status: 409,
        code: 4090001,
        requestId: 'req-http-409',
        details: {
          missingFields: ['order_no', 'amount'],
          requiredPermissions: [],
          missingAuthContext: []
        }
      }
    },
    {
      path: '/api/v1/rate-limited-shaped',
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-http-429',
        retry_after: 2
      },
      transportStatus: 500,
      expected: {
        kind: 'rate_limited',
        status: 429,
        code: 'RATE_LIMITED',
        requestId: 'req-http-429',
        retryAfterMs: 2000
      }
    }
  ];

  for (const item of cases) {
    const client = createApiClient({
      baseUrl: 'https://smartcloud.local',
      fetchFn: async () =>
        new Response(JSON.stringify(item.payload), {
          status: item.transportStatus,
          headers: {
            'content-type': 'application/json'
          }
        })
    });

    await assert.rejects(client.request(item.path), (error) => {
      assert.ok(error instanceof ApiError);
      const info = describeApiError(error);

      assert.equal(info.kind, item.expected.kind);
      assert.equal(info.status, item.expected.status);
      assert.equal(info.code, item.expected.code);
      assert.equal(info.requestId, item.expected.requestId);
      assert.equal(info.retryAfterMs, item.expected.retryAfterMs);
      assert.deepEqual(info.details, item.expected.details);
      return true;
    });
  }
});

test('FrontendApiClient resolves nested error.details request/status/message metadata', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error: {
            details: {
              code: 'RATE_LIMITED',
              message: 'slow down from nested details',
              status: 429,
              request_id: 'req-http-nested-details',
              retry_after_ms: 1750
            }
          },
          trace: {
            requestId: 'req-http-trace-fallback'
          }
        }),
        {
          status: 500,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/nested-rate-limit'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.requestId, 'req-http-nested-details');
    assert.equal(error.retryAfterMs, 1750);
    assert.match(error.message, /slow down from nested details/);
    assert.equal(classifyApiError(error), 'rate_limited');
    return true;
  });
});

test('FrontendApiClient prefers named shared error-code status over mismatched transport statuses', async () => {
  const cases = [
    {
      path: '/api/v1/forbidden-mismatch',
      payload: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-http-mismatched-403'
      },
      transportStatus: 400,
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN',
      expectedKind: 'forbidden'
    },
    {
      path: '/api/v1/conflict-mismatch',
      payload: {
        error_code: 'CHAT_CONVERSATION_RUNNING',
        error_message: 'conversation still running',
        requestId: 'req-http-mismatched-409'
      },
      transportStatus: 500,
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING',
      expectedKind: 'conflict'
    },
    {
      path: '/api/v1/rate-limit-mismatch',
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-http-mismatched-429',
        retry_after: 2
      },
      transportStatus: 500,
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedKind: 'rate_limited',
      expectedRetryAfterMs: 2000
    },
    {
      path: '/api/v1/agent-not-found-mismatch',
      payload: {
        error_code: 'ORCH_AGENT_NOT_FOUND',
        error_message: 'agent does not exist',
        requestId: 'req-http-mismatched-404'
      },
      transportStatus: 500,
      expectedStatus: 404,
      expectedCode: 'ORCH_AGENT_NOT_FOUND',
      expectedKind: 'not_found'
    },
    {
      path: '/api/v1/stream-events-not-found-mismatch',
      payload: {
        error_code: 'CHAT_STREAM_EVENTS_NOT_FOUND',
        error_message: 'stream events missing',
        requestId: 'req-http-mismatched-stream-404'
      },
      transportStatus: 500,
      expectedStatus: 404,
      expectedCode: 'CHAT_STREAM_EVENTS_NOT_FOUND',
      expectedKind: 'not_found'
    }
  ];

  for (const item of cases) {
    const client = createApiClient({
      baseUrl: 'https://smartcloud.local',
      fetchFn: async () =>
        new Response(JSON.stringify(item.payload), {
          status: item.transportStatus,
          headers: {
            'content-type': 'application/json'
          }
        })
    });

    await assert.rejects(client.request(item.path), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, item.expectedStatus);
      assert.equal(error.code, item.expectedCode);
      assert.equal(error.requestId, item.payload.requestId);
      assert.equal(error.retryAfterMs, item.expectedRetryAfterMs);
      assert.equal(classifyApiError(error), item.expectedKind);
      return true;
    });
  }
});

test('FrontendApiClient rejects in-band alias error envelopes without data using inferred shared status', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'slow down',
          requestId: 'req-inband-rate',
          retry_after: 2
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/rate-limited'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.requestId, 'req-inband-rate');
    assert.equal(error.retryAfterMs, 2000);
    return true;
  });
});

test('FrontendApiClient rejects success=false envelopes even when the response omits data', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          success: false,
          requestId: 'req-inband-service-unavailable',
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'dependency unavailable'
          }
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/dependency'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.equal(error.code, 'SERVICE_UNAVAILABLE');
    assert.equal(error.requestId, 'req-inband-service-unavailable');
    assert.match(error.message, /dependency unavailable/);
    return true;
  });
});

test('FrontendApiClient refreshes the session once on a structured 401 SSE response', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            code: 4010002,
            message: 'token expired',
            request_id: 'req-stream-expired'
          }),
          {
            status: 401,
            headers: {
              'content-type': 'application/json'
            }
          }
        );
      }

      return new Response(
        'id: evt-1\nevent: delta\nretry: 1500\ndata: {"content":"hello"}\n\n',
        {
          status: 200,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      );
    },
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => {
      refreshCount += 1;
      return { refreshed: true };
    }
  });

  const events = [];
  for await (const event of client.stream('/api/v1/chat/stream')) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      id: 'evt-1',
      event: 'delta',
      retry: 1500,
      data: {
        content: 'hello'
      }
    }
  ]);
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('FrontendApiClient refreshes the session once on an in-band 200 AUTH_UNAUTHORIZED SSE envelope', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            error_code: 'AUTH_UNAUTHORIZED',
            error_message: 'token expired',
            requestId: 'req-stream-inband-expired'
          }),
          {
            status: 200,
            headers: {
              'content-type': 'application/json'
            }
          }
        );
      }

      return new Response(
        'id: evt-2\nevent: message.delta\ndata: {"content":"recovered"}\n\n',
        {
          status: 200,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      );
    },
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => {
      refreshCount += 1;
      return { refreshed: true };
    }
  });

  const events = [];
  for await (const event of client.stream('/api/v1/chat/stream')) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      id: 'evt-2',
      event: 'message.delta',
      retry: undefined,
      data: {
        content: 'recovered'
      }
    }
  ]);
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('FrontendApiClient.stream surfaces structured 403/409/429 JSON envelopes as ApiError without emitting events', async () => {
  const cases = [
    {
      path: '/api/v1/stream-forbidden',
      payload: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-stream-403'
      },
      transportStatus: 403,
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN'
    },
    {
      path: '/api/v1/stream-forbidden-inband',
      payload: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-stream-403-inband'
      },
      transportStatus: 200,
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN'
    },
    {
      path: '/api/v1/stream-conflict',
      payload: {
        error_code: 'CHAT_CONVERSATION_RUNNING',
        error_message: 'conversation still running',
        requestId: 'req-stream-409'
      },
      transportStatus: 409,
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING'
    },
    {
      path: '/api/v1/stream-conflict-inband',
      payload: {
        error_code: 'CHAT_CONVERSATION_RUNNING',
        error_message: 'conversation still running',
        requestId: 'req-stream-409-inband'
      },
      transportStatus: 200,
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING'
    },
    {
      path: '/api/v1/stream-rate-limit',
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-stream-429',
        retry_after: 2
      },
      transportStatus: 429,
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedRetryAfterMs: 2000
    },
    {
      path: '/api/v1/stream-rate-limit-inband',
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-stream-429-inband',
        retry_after: 2
      },
      transportStatus: 200,
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedRetryAfterMs: 2000
    },
    {
      path: '/api/v1/stream-events-not-found',
      payload: {
        error_code: 'CHAT_STREAM_EVENTS_NOT_FOUND',
        error_message: 'stream events missing',
        requestId: 'req-stream-404'
      },
      transportStatus: 404,
      expectedStatus: 404,
      expectedCode: 'CHAT_STREAM_EVENTS_NOT_FOUND'
    },
    {
      path: '/api/v1/stream-events-not-found-inband',
      payload: {
        error_code: 'CHAT_STREAM_EVENTS_NOT_FOUND',
        error_message: 'stream events missing',
        requestId: 'req-stream-404-inband'
      },
      transportStatus: 200,
      expectedStatus: 404,
      expectedCode: 'CHAT_STREAM_EVENTS_NOT_FOUND'
    }
  ];

  for (const item of cases) {
    const client = createApiClient({
      baseUrl: 'https://smartcloud.local',
      fetchFn: async () =>
        new Response(JSON.stringify(item.payload), {
          status: item.transportStatus,
          headers: {
            'content-type': 'application/json'
          }
        })
    });

    await assert.rejects(
      async () => {
        const events = [];
        for await (const event of client.stream(item.path)) {
          events.push(event);
        }
        return events;
      },
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, item.expectedStatus);
        assert.equal(error.code, item.expectedCode);
        assert.equal(error.requestId, item.payload.requestId);
        assert.equal(error.retryAfterMs, item.expectedRetryAfterMs);
        assert.equal(
          classifyApiError(error),
          item.expectedStatus === 429
            ? 'rate_limited'
            : item.expectedStatus === 409
              ? 'conflict'
              : item.expectedStatus === 404
                ? 'not_found'
                : 'forbidden'
        );
        return true;
      }
    );
  }
});

test('FrontendApiClient resolves structured request statuses before calling the refresh hook', async () => {
  let refreshCount = 0;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
          error_message: 'caller rejected',
          requestId: 'req-refresh-guard'
        }),
        {
          status: 401,
          headers: {
            'content-type': 'application/json'
          }
        }
      ),
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => {
      refreshCount += 1;
      return { refreshed: true };
    }
  });

  await assert.rejects(client.request('/api/v1/internal/tools'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 403);
    assert.equal(error.code, 'TOOL_HUB_CALLER_FORBIDDEN');
    assert.equal(error.requestId, 'req-refresh-guard');
    assert.equal(refreshCount, 0);
    return true;
  });
});

test('FrontendApiClient stream refreshes on in-band AUTH_UNAUTHORIZED JSON envelopes', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            error_code: 'AUTH_UNAUTHORIZED',
            error_message: 'stream token expired',
            requestId: 'req-stream-inband-401'
          }),
          {
            status: 200,
            headers: {
              'content-type': 'application/json'
            }
          }
        );
      }

      return new Response(
        'event: delta\ndata: {"content":"hello again"}\n\n',
        {
          status: 200,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      );
    },
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => {
      refreshCount += 1;
      return { refreshed: true };
    }
  });

  const events = [];
  for await (const event of client.stream('/api/v1/chat/stream')) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      event: 'delta',
      id: undefined,
      retry: undefined,
      data: {
        content: 'hello again'
      }
    }
  ]);
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('FrontendApiClient stream rejects in-band structured 429 JSON envelopes instead of completing silently', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'slow down',
          requestId: 'req-stream-inband-429',
          retry_after: 2
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json'
          }
        }
      ),
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => ({ refreshed: true })
  });

  await assert.rejects(
    async () => {
      for await (const _event of client.stream('/api/v1/chat/stream')) {
        // no-op
      }
    },
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 429);
      assert.equal(error.code, 'RATE_LIMITED');
      assert.equal(error.requestId, 'req-stream-inband-429');
      assert.equal(error.retryAfterMs, 2000);
      return true;
    }
  );
});

test('FrontendApiClient stream falls back to the generated request id when structured JSON SSE errors omit it', async () => {
  let capturedRequestId = null;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');

      return new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'slow down',
          retry_after: 2
        }),
        {
          status: 429,
          headers: {
            'content-type': 'application/json'
          }
        }
      );
    }
  });

  await assert.rejects(
    (async () => {
      for await (const _event of client.stream('/api/v1/stream-rate-limited-no-request-id')) {
        throw new Error(`unexpected event: ${JSON.stringify(_event)}`);
      }
    })(),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 429);
      assert.equal(error.code, 'RATE_LIMITED');
      assert.equal(error.requestId, capturedRequestId);
      assert.equal(error.retryAfterMs, 2000);
      return true;
    }
  );
});

test('FrontendApiClient stream resolves structured statuses before calling the refresh hook', async () => {
  const cases = [
    {
      payload: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-stream-mislabeled-403'
      },
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN'
    },
    {
      payload: {
        error_code: 'CHAT_CONVERSATION_RUNNING',
        error_message: 'conversation still running',
        requestId: 'req-stream-mislabeled-409'
      },
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING'
    },
    {
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-stream-mislabeled-429',
        retry_after: 2
      },
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedRetryAfterMs: 2000
    }
  ];

  for (const item of cases) {
    let refreshCount = 0;

    const client = createApiClient({
      baseUrl: 'https://smartcloud.local',
      fetchFn: async () =>
        new Response(JSON.stringify(item.payload), {
          status: 401,
          headers: {
            'content-type': 'application/json'
          }
        }),
      shouldRefreshSession: (status) => status === 401,
      refreshSession: async () => {
        refreshCount += 1;
        return { refreshed: true };
      }
    });

    await assert.rejects(
      async () => {
        for await (const _event of client.stream('/api/v1/chat/stream')) {
          // no-op
        }
      },
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, item.expectedStatus);
        assert.equal(error.code, item.expectedCode);
        assert.equal(error.requestId, item.payload.requestId);
        assert.equal(error.retryAfterMs, item.expectedRetryAfterMs);
        assert.equal(refreshCount, 0);
        return true;
      }
    );
  }
});

test('FrontendApiClient.request parses structured text/event-stream error bodies into ApiError metadata', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        [
          'event: message.started',
          'data: {"conversation_id":"conv_001"}',
          '',
          'event: message.error',
          'retry: 1750',
          'data: {"error_code":"RATE_LIMITED","error_message":"slow down"}',
          ''
        ].join('\n'),
        {
          status: 429,
          headers: {
            'content-type': 'text/event-stream',
            'X-Request-Id': 'req-request-sse-429'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/chat/completions'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.requestId, 'req-request-sse-429');
    assert.equal(error.retryAfterMs, 1750);
    assert.match(error.message, /slow down/);
    return true;
  });
});

test('FrontendApiClient.request falls back to the generated request id for structured text/event-stream error bodies that omit it', async () => {
  let capturedRequestId = null;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');

      return new Response(
        [
          'event: message.error',
          'retry: 2250',
          'data: {"error_code":"RATE_LIMITED","error_message":"slow down"}',
          ''
        ].join('\n'),
        {
          status: 429,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      );
    }
  });

  await assert.rejects(client.request('/api/v1/chat/completions'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.requestId, capturedRequestId);
    assert.equal(error.retryAfterMs, 2250);
    assert.match(error.message, /slow down/);
    return true;
  });
});

test('FrontendApiClient stream refreshes on structured 401 text/event-stream error responses', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          [
            'event: message.started',
            'data: {"conversation_id":"conv_sse_401"}',
            '',
            'event: message.error',
            'data: {"error_code":"AUTH_UNAUTHORIZED","error_message":"stream token expired","request_id":"req-stream-sse-401"}',
            ''
          ].join('\n'),
          {
            status: 401,
            headers: {
              'content-type': 'text/event-stream'
            }
          }
        );
      }

      return new Response(
        'event: message.delta\ndata: {"content":"recovered after sse error"}\n\n',
        {
          status: 200,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      );
    },
    shouldRefreshSession: (status) => status === 401,
    refreshSession: async () => {
      refreshCount += 1;
      return { refreshed: true };
    }
  });

  const events = [];
  for await (const event of client.stream('/api/v1/chat/stream')) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      event: 'message.delta',
      id: undefined,
      retry: undefined,
      data: {
        content: 'recovered after sse error'
      }
    }
  ]);
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('FrontendApiClient.stream preserves structured 403/409/429 metadata from text/event-stream error responses', async () => {
  const cases = [
    {
      path: '/api/v1/stream-sse-forbidden',
      responseBody: [
        'event: message.started',
        'data: {"conversation_id":"conv_forbidden"}',
        '',
        'event: message.error',
        'data: {"error_code":"TOOL_HUB_CALLER_FORBIDDEN","error_message":"caller rejected","request_id":"req-stream-sse-403"}',
        ''
      ].join('\n'),
      transportStatus: 403,
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN',
      expectedRequestId: 'req-stream-sse-403',
      expectedKind: 'forbidden'
    },
    {
      path: '/api/v1/stream-sse-conflict',
      responseBody: [
        'event: message.started',
        'data: {"conversation_id":"conv_conflict"}',
        '',
        'event: message.error',
        'data: {"error_code":"CHAT_CONVERSATION_RUNNING","error_message":"conversation still running","request_id":"req-stream-sse-409"}',
        ''
      ].join('\n'),
      transportStatus: 409,
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING',
      expectedRequestId: 'req-stream-sse-409',
      expectedKind: 'conflict'
    },
    {
      path: '/api/v1/stream-sse-rate-limit',
      responseBody: [
        'event: message.started',
        'data: {"conversation_id":"conv_rate_limit"}',
        '',
        'event: message.error',
        'retry: 2250',
        'data: {"error_code":"RATE_LIMITED","error_message":"slow down"}',
        ''
      ].join('\n'),
      transportStatus: 429,
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedRequestId: 'req-stream-sse-429',
      expectedKind: 'rate_limited',
      expectedRetryAfterMs: 2250
    }
  ];

  for (const item of cases) {
    const client = createApiClient({
      baseUrl: 'https://smartcloud.local',
      fetchFn: async () =>
        new Response(item.responseBody, {
          status: item.transportStatus,
          headers: {
            'content-type': 'text/event-stream',
            'X-Request-Id': item.expectedRequestId
          }
        })
    });

    await assert.rejects(
      async () => {
        for await (const _event of client.stream(item.path)) {
          // no-op
        }
      },
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, item.expectedStatus);
        assert.equal(error.code, item.expectedCode);
        assert.equal(error.requestId, item.expectedRequestId);
        assert.equal(error.retryAfterMs, item.expectedRetryAfterMs);
        assert.equal(classifyApiError(error), item.expectedKind);
        return true;
      }
    );
  }
});

test('FrontendApiClient stream parses multiple CRLF-delimited SSE events correctly', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        'event: delta\r\ndata: {"content":"hello"}\r\n\r\nevent: delta\r\ndata: {"content":"world"}\r\n\r\n',
        {
          status: 200,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      )
  });

  const events = [];
  for await (const event of client.stream('/api/v1/chat/stream')) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      event: 'delta',
      id: undefined,
      retry: undefined,
      data: {
        content: 'hello'
      }
    },
    {
      event: 'delta',
      id: undefined,
      retry: undefined,
      data: {
        content: 'world'
      }
    }
  ]);
});

test('FrontendApiClient does not force JSON content-type for multipart bodies', async () => {
  let capturedContentType = null;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async (_url, init) => {
      capturedContentType = new Headers(init?.headers).get('Content-Type');
      return new Response(
        JSON.stringify({
          code: 0,
          data: {
            ok: true
          }
        }),
        {
          status: 200,
          headers: {
            'content-type': 'application/json'
          }
        }
      );
    }
  });

  const formData = new FormData();
  formData.set('file', 'demo.txt');

  const result = await client.request('/api/v1/files/upload', {
    method: 'POST',
    body: formData
  });

  assert.deepEqual(result, { ok: true });
  assert.equal(capturedContentType, null);
});

test('FrontendApiClient wraps SSE transport failures with ApiError metadata and request ids', async () => {
  let capturedRequestId = null;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');
      throw new TypeError('Failed to fetch');
    }
  });

  await assert.rejects(
    async () => {
      for await (const _event of client.stream('/api/v1/chat/stream')) {
        // no-op
      }
    },
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 503);
      assert.equal(error.requestId, capturedRequestId);
      assert.match(error.message, /Failed to fetch/);
      return true;
    }
  );
});

test('FrontendApiClient wraps request transport failures with service-unavailable ApiError metadata and request ids', async () => {
  let capturedRequestId = null;

  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');
      throw new TypeError('Failed to fetch');
    }
  });

  await assert.rejects(client.request('/api/v1/billing/summary'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.equal(classifyApiError(error), 'server');
    assert.equal(error.requestId, capturedRequestId);
    assert.match(error.message, /Failed to fetch/);
    return true;
  });
});

test('FrontendApiClient stream preserves structured 403 envelope metadata', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
          error_message: 'caller rejected',
          requestId: 'req-stream-forbidden'
        }),
        {
          status: 403,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(
    async () => {
      for await (const _event of client.stream('/api/v1/chat/stream')) {
        // no-op
      }
    },
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 403);
      assert.equal(error.code, 'TOOL_HUB_CALLER_FORBIDDEN');
      assert.equal(error.requestId, 'req-stream-forbidden');
      return true;
    }
  );
});

test('FrontendApiClient stream preserves structured 429 retry metadata', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'slow down',
          requestId: 'req-stream-rate',
          retry_after: 2
        }),
        {
          status: 429,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(
    async () => {
      for await (const _event of client.stream('/api/v1/chat/stream')) {
        // no-op
      }
    },
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 429);
      assert.equal(error.code, 'RATE_LIMITED');
      assert.equal(error.requestId, 'req-stream-rate');
      assert.equal(error.retryAfterMs, 2000);
      return true;
    }
  );
});

test('FrontendApiClient stream preserves structured 409 conflict envelopes and details', async () => {
  const client = createApiClient({
    baseUrl: 'https://smartcloud.local',
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          code: 4090001,
          message: 'idempotency conflict',
          request_id: 'req-stream-conflict',
          error_detail: {
            missing_fields: ['order_no', 'amount']
          }
        }),
        {
          status: 409,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(
    async () => {
      for await (const _event of client.stream('/api/v1/chat/stream')) {
        // no-op
      }
    },
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 409);
      assert.equal(error.code, 4090001);
      assert.equal(error.requestId, 'req-stream-conflict');
      assert.deepEqual(error.details, {
        missing_fields: ['order_no', 'amount']
      });
      return true;
    }
  );
});
