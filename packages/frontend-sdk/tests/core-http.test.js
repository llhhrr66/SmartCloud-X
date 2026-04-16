import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { ApiError } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
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
