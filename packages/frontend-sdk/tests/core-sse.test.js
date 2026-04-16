import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { ApiError } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/envelope.js');
const { consumeSseStreamWithReconnect } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/sse.js');

test('consumeSseStreamWithReconnect retries network-like stream failures and resumes consumption', async () => {
  const consumed = [];
  const reconnects = [];
  let connectCount = 0;

  const result = await consumeSseStreamWithReconnect({
    connect: async function* (_signal, attempt) {
      connectCount += 1;
      assert.equal(attempt, connectCount - 1);
      if (connectCount === 1) {
        throw new TypeError('Failed to fetch');
      }

      yield { event: 'message.delta', data: { content: 'ok' } };
    },
    consumeEvent: async (event) => {
      consumed.push(event);
    },
    maxReconnectAttempts: 2,
    defaultDelayMs: 25,
    maxDelayMs: 25,
    onBeforeReconnect: async (context) => {
      reconnects.push(context);
    },
    waitForDelay: async () => undefined
  });

  assert.equal(result.reconnectAttempts, 1);
  assert.equal(connectCount, 2);
  assert.deepEqual(consumed, [{ event: 'message.delta', data: { content: 'ok' } }]);
  assert.equal(reconnects.length, 1);
  assert.equal(reconnects[0].attempt, 1);
  assert.equal(reconnects[0].reason, 'error');
  assert.equal(reconnects[0].delayMs, 25);
  assert.match(String(reconnects[0].error), /Failed to fetch/);
});

test('consumeSseStreamWithReconnect does not retry structured unauthorized failures', async () => {
  let reconnectCount = 0;

  await assert.rejects(
    consumeSseStreamWithReconnect({
      connect: async function* () {
        throw new ApiError('unauthorized', 401, 'AUTH_UNAUTHORIZED');
      },
      consumeEvent: async () => undefined,
      maxReconnectAttempts: 3,
      onBeforeReconnect: async () => {
        reconnectCount += 1;
      },
      waitForDelay: async () => undefined
    }),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 401);
      assert.equal(error.code, 'AUTH_UNAUTHORIZED');
      assert.equal(reconnectCount, 0);
      return true;
    }
  );
});

test('consumeSseStreamWithReconnect does not retry structured forbidden envelope failures', async () => {
  let reconnectCount = 0;
  const envelope = {
    status: 403,
    error_detail: {
      code: 'TOOL_HUB_CALLER_FORBIDDEN'
    }
  };

  await assert.rejects(
    consumeSseStreamWithReconnect({
      connect: async function* () {
        throw envelope;
      },
      consumeEvent: async () => undefined,
      maxReconnectAttempts: 3,
      onBeforeReconnect: async () => {
        reconnectCount += 1;
      },
      waitForDelay: async () => undefined
    }),
    (error) => {
      assert.equal(error, envelope);
      assert.equal(reconnectCount, 0);
      return true;
    }
  );
});

test('consumeSseStreamWithReconnect does not retry structured conflict envelope failures', async () => {
  let reconnectCount = 0;
  const envelope = {
    error_code: 'CHAT_CONVERSATION_RUNNING',
    error_message: 'conversation still running'
  };

  await assert.rejects(
    consumeSseStreamWithReconnect({
      connect: async function* () {
        throw envelope;
      },
      consumeEvent: async () => undefined,
      maxReconnectAttempts: 3,
      onBeforeReconnect: async () => {
        reconnectCount += 1;
      },
      waitForDelay: async () => undefined
    }),
    (error) => {
      assert.equal(error, envelope);
      assert.equal(reconnectCount, 0);
      return true;
    }
  );
});

test('consumeSseStreamWithReconnect retries graceful stream closes when the caller marks them reconnectable', async () => {
  const consumed = [];
  const reconnects = [];
  let connectCount = 0;

  const result = await consumeSseStreamWithReconnect({
    connect: async function* () {
      connectCount += 1;
      yield { event: 'delta', data: { chunk: connectCount } };
    },
    consumeEvent: async (event) => {
      consumed.push(event);
    },
    shouldReconnectOnClose: () => consumed.length < 2,
    maxReconnectAttempts: 2,
    defaultDelayMs: 0,
    maxDelayMs: 0,
    onBeforeReconnect: async (context) => {
      reconnects.push(context);
    },
    waitForDelay: async () => undefined
  });

  assert.equal(result.reconnectAttempts, 1);
  assert.equal(connectCount, 2);
  assert.deepEqual(consumed, [
    { event: 'delta', data: { chunk: 1 } },
    { event: 'delta', data: { chunk: 2 } }
  ]);
  assert.equal(reconnects[0].reason, 'close');
});

test('consumeSseStreamWithReconnect honors retry_after metadata from structured rate-limit errors', async () => {
  const delays = [];
  let connectCount = 0;

  const result = await consumeSseStreamWithReconnect({
    connect: async function* () {
      connectCount += 1;
      if (connectCount === 1) {
        throw new ApiError('slow down', 429, 'RATE_LIMITED', undefined, undefined, 2750);
      }
    },
    consumeEvent: async () => undefined,
    maxReconnectAttempts: 1,
    onBeforeReconnect: async (context) => {
      delays.push(context.delayMs);
    },
    waitForDelay: async (delayMs) => {
      delays.push(delayMs);
    }
  });

  assert.equal(result.reconnectAttempts, 1);
  assert.equal(connectCount, 2);
  assert.deepEqual(delays, [2750, 2750]);
});

test('consumeSseStreamWithReconnect honors retry_after metadata from structured rate-limit envelopes', async () => {
  const delays = [];
  let connectCount = 0;

  const result = await consumeSseStreamWithReconnect({
    connect: async function* () {
      connectCount += 1;
      if (connectCount === 1) {
        throw {
          error_code: 'RATE_LIMITED',
          retry_after: 2
        };
      }
    },
    consumeEvent: async () => undefined,
    maxReconnectAttempts: 1,
    onBeforeReconnect: async (context) => {
      delays.push(context.delayMs);
    },
    waitForDelay: async (delayMs) => {
      delays.push(delayMs);
    }
  });

  assert.equal(result.reconnectAttempts, 1);
  assert.equal(connectCount, 2);
  assert.deepEqual(delays, [2000, 2000]);
});

test('consumeSseStreamWithReconnect uses the caller disconnect error after exhausting close retries', async () => {
  await assert.rejects(
    consumeSseStreamWithReconnect({
      connect: async function* () {
        yield { event: 'delta', data: { content: 'partial' } };
      },
      consumeEvent: async () => undefined,
      shouldReconnectOnClose: () => true,
      maxReconnectAttempts: 1,
      defaultDelayMs: 0,
      maxDelayMs: 0,
      waitForDelay: async () => undefined,
      buildDisconnectError: ({ maxReconnectAttempts }) =>
        new ApiError(`stream lost after ${maxReconnectAttempts} reconnects`, 502, 'CHAT_STREAM_DISCONNECTED')
    }),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 502);
      assert.equal(error.code, 'CHAT_STREAM_DISCONNECTED');
      assert.match(error.message, /stream lost/);
      return true;
    }
  );
});
