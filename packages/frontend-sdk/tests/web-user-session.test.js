import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { ApiError } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
const { createWebUserApiClient } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/api.js');
const {
  buildWebUserHeaders,
  createWebUserSessionManager
} = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/session.js');

const runtime = {
  apiBaseUrl: 'https://smartcloud.local',
  requestTimeoutMs: 30_000,
  useMockApi: false,
  clientPlatform: 'web-user',
  appVersion: 'test'
};

const session = {
  accessToken: 'access-token',
  refreshToken: 'refresh-token',
  expiresIn: 7200,
  expiresAt: '2026-04-16T02:00:00.000Z',
  user: {
    userId: 'user_001',
    tenantId: 'tenant_001',
    name: 'SmartCloud 用户',
    email: 'user@example.com',
    mobile: '13800000000',
    locale: 'zh-CN',
    timeZone: 'Asia/Shanghai',
    permissions: ['user:billing.read']
  }
};

async function collectStreamEvents(stream) {
  const events = [];

  for await (const event of stream) {
    events.push(event);
  }

  return events;
}

test('buildWebUserHeaders keeps multipart uploads boundary-safe while still adding auth context', () => {
  const formData = new FormData();
  formData.set('file', 'demo.txt');

  const headers = buildWebUserHeaders(runtime, session, undefined, false, formData);

  assert.equal(headers.get('Content-Type'), null);
  assert.equal(headers.get('Authorization'), 'Bearer access-token');
  assert.equal(headers.get('X-Tenant-Id'), 'tenant_001');
  assert.equal(headers.get('X-User-Id'), 'user_001');
});

test('createWebUserApiClient does not reintroduce JSON content-type for multipart bodies', async () => {
  let capturedContentType = null;

  const client = createWebUserApiClient({
    runtime,
    getSession: () => session,
    refreshSession: async () => session,
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

test('createWebUserApiClient refreshes on in-band AUTH_UNAUTHORIZED envelopes without data', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createWebUserApiClient({
    runtime,
    getSession: () => session,
    refreshSession: async () => {
      refreshCount += 1;
      return session;
    },
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            error_code: 'AUTH_UNAUTHORIZED',
            error_message: 'access token expired',
            requestId: 'req-auth-expired'
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

  const result = await client.request('/api/v1/auth/me');

  assert.deepEqual(result, { ok: true });
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('createWebUserApiClient does not refresh on explicit AUTH_INVALID_TOKEN failures', async () => {
  let refreshCount = 0;

  const client = createWebUserApiClient({
    runtime,
    getSession: () => session,
    refreshSession: async () => {
      refreshCount += 1;
      return session;
    },
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'AUTH_INVALID_TOKEN',
          error_message: 'token malformed',
          requestId: 'req-auth-invalid'
        }),
        {
          status: 401,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  await assert.rejects(client.request('/api/v1/auth/me'), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 401);
    assert.equal(error.code, 'AUTH_INVALID_TOKEN');
    assert.equal(error.requestId, 'req-auth-invalid');
    assert.equal(refreshCount, 0);
    return true;
  });
});

test('createWebUserApiClient does not refresh when structured 403/404/409/429 failures are mislabeled as HTTP 401', async () => {
  const cases = [
    {
      payload: {
        error_code: 'TOOL_HUB_CALLER_FORBIDDEN',
        error_message: 'caller rejected',
        requestId: 'req-mislabeled-403'
      },
      expectedStatus: 403,
      expectedCode: 'TOOL_HUB_CALLER_FORBIDDEN'
    },
    {
      payload: {
        error_code: 'CHAT_CONVERSATION_RUNNING',
        error_message: 'conversation still running',
        requestId: 'req-mislabeled-409'
      },
      expectedStatus: 409,
      expectedCode: 'CHAT_CONVERSATION_RUNNING'
    },
    {
      payload: {
        error_code: 'ORCH_AGENT_NOT_FOUND',
        error_message: 'agent missing',
        requestId: 'req-mislabeled-404'
      },
      expectedStatus: 404,
      expectedCode: 'ORCH_AGENT_NOT_FOUND'
    },
    {
      payload: {
        error_code: 'CHAT_STREAM_EVENTS_NOT_FOUND',
        error_message: 'stream events missing',
        requestId: 'req-mislabeled-stream-404'
      },
      expectedStatus: 404,
      expectedCode: 'CHAT_STREAM_EVENTS_NOT_FOUND'
    },
    {
      payload: {
        error_code: 'RATE_LIMITED',
        error_message: 'slow down',
        requestId: 'req-mislabeled-429',
        retry_after: 2
      },
      expectedStatus: 429,
      expectedCode: 'RATE_LIMITED',
      expectedRetryAfterMs: 2000
    }
  ];

  for (const item of cases) {
    let refreshCount = 0;

    const client = createWebUserApiClient({
      runtime,
      getSession: () => session,
      refreshSession: async () => {
        refreshCount += 1;
        return session;
      },
      fetchFn: async () =>
        new Response(JSON.stringify(item.payload), {
          status: 401,
          headers: {
            'content-type': 'application/json'
          }
        })
    });

    await assert.rejects(client.request('/api/v1/auth/me'), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, item.expectedStatus);
      assert.equal(error.code, item.expectedCode);
      assert.equal(error.requestId, item.payload.requestId);
      assert.equal(error.retryAfterMs, item.expectedRetryAfterMs);
      assert.equal(refreshCount, 0);
      return true;
    });
  }
});

test('createWebUserApiClient refreshes on in-band AUTH_UNAUTHORIZED JSON SSE envelopes', async () => {
  let requestCount = 0;
  let refreshCount = 0;

  const client = createWebUserApiClient({
    runtime,
    getSession: () => session,
    refreshSession: async () => {
      refreshCount += 1;
      return session;
    },
    fetchFn: async () => {
      requestCount += 1;

      if (requestCount === 1) {
        return new Response(
          JSON.stringify({
            error_code: 'AUTH_UNAUTHORIZED',
            error_message: 'stream token expired',
            requestId: 'req-stream-auth-expired'
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
        'event: message.delta\ndata: {"content":"ok"}\n\n',
        {
          status: 200,
          headers: {
            'content-type': 'text/event-stream'
          }
        }
      );
    }
  });

  const events = await collectStreamEvents(client.stream('/api/v1/chat/completions/stream'));

  assert.deepEqual(events, [
    {
      event: 'message.delta',
      data: {
        content: 'ok'
      },
      id: undefined,
      retry: undefined
    }
  ]);
  assert.equal(requestCount, 2);
  assert.equal(refreshCount, 1);
});

test('createWebUserApiClient stream does not refresh when structured 403/409/429 failures are mislabeled as HTTP 401', async () => {
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

    const client = createWebUserApiClient({
      runtime,
      getSession: () => session,
      refreshSession: async () => {
        refreshCount += 1;
        return session;
      },
      fetchFn: async () =>
        new Response(JSON.stringify(item.payload), {
          status: 401,
          headers: {
            'content-type': 'application/json'
          }
        })
    });

    await assert.rejects(
      collectStreamEvents(client.stream('/api/v1/chat/completions/stream')),
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

test('createWebUserSessionManager surfaces structured 429 metadata from auth/session helpers', async () => {
  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => undefined,
      subscribe: () => () => undefined
    },
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          code: 4290001,
          message: 'too many requests',
          request_id: 'req-auth-me'
        }),
        {
          status: 429,
          headers: {
            'content-type': 'application/json',
            'Retry-After': '3'
          }
        }
      )
  });

  await assert.rejects(manager.syncCurrentUser(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 4290001);
    assert.equal(error.requestId, 'req-auth-me');
    assert.equal(error.retryAfterMs, 3000);
    return true;
  });
});

test('createWebUserSessionManager falls back to the generated request id when auth/session errors omit it', async () => {
  let capturedRequestId = null;

  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => undefined,
      subscribe: () => () => undefined
    },
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');

      return new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'profile refresh throttled',
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

  await assert.rejects(manager.syncCurrentUser(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 429);
    assert.equal(error.code, 'RATE_LIMITED');
    assert.equal(error.requestId, capturedRequestId);
    assert.equal(error.retryAfterMs, 2000);
    return true;
  });
});

test('createWebUserSessionManager preserves the generated request id on auth/session abort timeouts', async () => {
  let capturedRequestId = null;

  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => undefined,
      subscribe: () => () => undefined
    },
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');
      const error = new Error('request aborted');
      error.name = 'AbortError';
      throw error;
    }
  });

  await assert.rejects(manager.syncCurrentUser(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 408);
    assert.equal(error.requestId, capturedRequestId);
    return true;
  });
});

test('createWebUserSessionManager preserves the generated request id on auth/session network transport failures', async () => {
  let capturedRequestId = null;

  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => undefined,
      subscribe: () => () => undefined
    },
    fetchFn: async (_url, init) => {
      capturedRequestId = new Headers(init?.headers).get('X-Request-Id');
      throw new TypeError('Failed to fetch');
    }
  });

  await assert.rejects(manager.syncCurrentUser(), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 503);
    assert.equal(error.requestId, capturedRequestId);
    assert.match(error.message, /Auth\/session request failed: Failed to fetch/);
    return true;
  });
});

test('createWebUserSessionManager preserves the stored session when refresh is rate limited', async () => {
  let clearCount = 0;

  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => {
        clearCount += 1;
      },
      subscribe: () => () => undefined
    },
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'RATE_LIMITED',
          error_message: 'refresh too fast',
          requestId: 'req-refresh-rate',
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

  const nextSession = await manager.refreshAuthSession(true);

  assert.equal(nextSession, null);
  assert.equal(clearCount, 0);
});

test('createWebUserSessionManager preserves the stored session on refresh transport failures', async () => {
  let clearCount = 0;

  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => {
        clearCount += 1;
      },
      subscribe: () => () => undefined
    },
    fetchFn: async () => {
      throw new TypeError('Failed to fetch');
    }
  });

  const nextSession = await manager.refreshAuthSession(true);

  assert.equal(nextSession, null);
  assert.equal(clearCount, 0);
});

test('createWebUserSessionManager clears the stored session on explicit refresh-token auth failures', async () => {
  let clearCount = 0;

  const manager = createWebUserSessionManager({
    runtime,
    storage: {
      get: () => session,
      set: () => undefined,
      clear: () => {
        clearCount += 1;
      },
      subscribe: () => () => undefined
    },
    fetchFn: async () =>
      new Response(
        JSON.stringify({
          error_code: 'AUTH_INVALID_TOKEN',
          error_message: 'refresh token expired',
          requestId: 'req-refresh-invalid'
        }),
        {
          status: 401,
          headers: {
            'content-type': 'application/json'
          }
        }
      )
  });

  const nextSession = await manager.refreshAuthSession(true);

  assert.equal(nextSession, null);
  assert.equal(clearCount, 1);
});
