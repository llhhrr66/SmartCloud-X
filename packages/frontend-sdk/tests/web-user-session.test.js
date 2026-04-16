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
