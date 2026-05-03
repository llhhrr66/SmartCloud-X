import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { consumeSseStreamWithReconnect } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/core/sse.js');
const { createChatApi } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/chat-api.js');

test('createChatApi normalizes shared session, message, cancel, and retry payloads', async () => {
  const requests = [];

  const api = createChatApi({
    client: {
      async request(path, init) {
        requests.push({
          path,
          method: init?.method ?? 'GET',
          headers: Object.fromEntries(new Headers(init?.headers).entries()),
          body: init?.body ? JSON.parse(String(init.body)) : null
        });

        if (path === '/api/v1/chat/sessions?page=2&page_size=5&scene=billing') {
          return {
            items: [
              {
                conversation_id: 'conv_001',
                title: '账单分析',
                scene: 'billing',
                current_agent: 'Finance_Order_Agent',
                updated_at: '2026-04-16T02:00:00.000Z'
              }
            ],
            total: 7,
            page: 2,
            page_size: 5
          };
        }

        if (path === '/api/v1/chat/sessions') {
          return {
            conversation_id: 'conv_002',
            current_agent: 'Orchestrator'
          };
        }

        if (path === '/api/v1/chat/sessions/conv_002/messages') {
          return {
            messages: [
              {
                message_id: 'msg_001',
                role: 'assistant',
                message_type: 'markdown',
                content: '您好，这里是账单助手。',
                status: 'completed'
              }
            ]
          };
        }

        if (path === '/api/v1/chat/sessions/conv_002/cancel') {
          return {
            cancelled: true
          };
        }

        if (path === '/api/v1/chat/sessions/conv_002/retry') {
          return {
            message_id: 'msg_001',
            response: {
              status: 'need_user_input'
            },
            answer: '请先补充账单月份'
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: (scope) => `idem-${scope}`,
    now: () => '2026-04-16T03:00:00.000Z'
  });

  const sessions = await api.listSessions({ page: 2, pageSize: 5, scene: 'billing' });
  const created = await api.createSession({
    scene: 'billing',
    title: '本月账单',
    initialContext: '用户从账单页发起'
  });
  const messages = await api.getMessages('conv_002');
  const cancelled = await api.cancelMessage('conv_002', 'msg_001');
  const retried = await api.retryMessage('conv_002', 'msg_001', '请补充 2026-04');

  assert.equal(sessions.total, 7);
  assert.equal(sessions.page, 2);
  assert.equal(sessions.pageSize, 5);
  assert.equal(sessions.items[0].conversationId, 'conv_001');
  assert.equal(sessions.items[0].currentAgent, 'Finance_Order_Agent');

  assert.equal(created.conversationId, 'conv_002');
  assert.equal(created.title, '本月账单');
  assert.equal(created.scene, 'billing');
  assert.equal(created.createdAt, '2026-04-16T03:00:00.000Z');
  assert.equal(created.summary, '用户从账单页发起');

  assert.equal(messages.length, 1);
  assert.equal(messages[0].messageId, 'msg_001');
  assert.equal(messages[0].conversationId, 'conv_002');
  assert.equal(messages[0].content, '您好，这里是账单助手。');

  assert.deepEqual(cancelled, { status: 'cancelled' });
  assert.equal(retried.messageId, 'msg_001');
  assert.equal(retried.status, 'completed');
  assert.equal(retried.resolution, 'need_user_input');
  assert.equal(retried.actionRequired?.type, 'clarification');

  assert.equal(requests[1].headers['idempotency-key'], 'idem-chat-session');
  assert.deepEqual(requests[1].body, {
    scene: 'billing',
    title: '本月账单',
    initial_context: '用户从账单页发起'
  });
  assert.equal(requests[4].headers['idempotency-key'], 'idem-chat-retry');
});

test('createChatApi refetches the shared conversation detail when rename, archive, and restore return non-conversation envelopes', async () => {
  const requests = [];

  const api = createChatApi({
    client: {
      async request(path, init) {
        requests.push({ path, method: init?.method ?? 'GET' });

        if (path === '/api/v1/chat/sessions/conv_003' && init?.method === 'PATCH') {
          return {
            success: true
          };
        }

        if (
          path === '/api/v1/chat/sessions/conv_003/archive' ||
          path === '/api/v1/chat/sessions/conv_003/restore'
        ) {
          return {
            success: true
          };
        }

        if (path === '/api/v1/chat/sessions/conv_003') {
          return {
            conversation: {
              conversation_id: 'conv_003',
              title: '恢复中的会话',
              scene: 'customer_service',
              status: 'active',
              current_agent: 'Orchestrator'
            }
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'unused'
  });

  const renamed = await api.renameSession('conv_003', '已重命名会话');
  const archived = await api.archiveSession('conv_003');
  const restored = await api.restoreSession('conv_003');

  assert.equal(renamed.conversationId, 'conv_003');
  assert.equal(renamed.title, '已重命名会话');
  assert.equal(archived.conversationId, 'conv_003');
  assert.equal(restored.conversationId, 'conv_003');
  assert.deepEqual(
    requests.map((item) => item.path),
    [
      '/api/v1/chat/sessions/conv_003',
      '/api/v1/chat/sessions/conv_003',
      '/api/v1/chat/sessions/conv_003/archive',
      '/api/v1/chat/sessions/conv_003',
      '/api/v1/chat/sessions/conv_003/restore',
      '/api/v1/chat/sessions/conv_003'
    ]
  );
});

test('createChatApi maps streamed chat events through the shared adapter and forwards idempotency headers', async () => {
  const streamRequests = [];

  const api = createChatApi({
    client: {
      async request() {
        throw new Error('request should not be called');
      },
      async *stream(path, init) {
        streamRequests.push({
          path,
          method: init?.method ?? 'GET',
          headers: Object.fromEntries(new Headers(init?.headers).entries()),
          body: init?.body ? JSON.parse(String(init.body)) : null
        });

        yield {
          event: 'message.started',
          data: {
            conversation_id: 'conv_stream_001',
            message_id: 'msg_stream_001',
            trace_id: 'trace_001',
            agent: 'Finance_Order_Agent'
          }
        };
        yield {
          event: 'message.delta',
          data: {
            content: '账单已加载'
          }
        };
        yield {
          event: 'message.completed',
          data: {
            finish_reason: 'stop',
            usage: {
              prompt_tokens: 10,
              completion_tokens: 6,
              total_tokens: 16
            }
          }
        };
      }
    },
    createIdempotencyKey: (scope) => `idem-${scope}`
  });

  const events = [];
  for await (const event of api.streamCompletion({
    conversationId: 'conv_stream_001',
    messageId: 'msg_stream_001',
    userInput: '帮我看下账单',
    stream: true,
    scene: 'billing',
    attachments: [
      {
        fileId: 'file_001',
        fileName: 'invoice.pdf',
        mimeType: 'application/pdf',
        size: 256
      }
    ],
    context: {
      userId: 'user_001',
      tenantId: 'tenant_001',
      channel: 'web',
      locale: 'zh-CN'
    },
    options: {
      useRag: true,
      useTools: true,
      maxHistoryTurns: 20,
      agentHint: 'Finance_Order_Agent'
    }
  })) {
    events.push(event);
  }

  assert.deepEqual(events, [
    {
      event: 'meta',
      data: {
        conversationId: 'conv_stream_001',
        messageId: 'msg_stream_001',
        traceId: 'trace_001',
        agent: 'Finance_Order_Agent'
      }
    },
    {
      event: 'delta',
      data: {
        content: '账单已加载'
      }
    },
    {
      event: 'done',
      data: {
        finishReason: 'stop',
        usage: {
          promptTokens: 10,
          completionTokens: 6,
          totalTokens: 16
        }
      }
    }
  ]);

  assert.equal(streamRequests.length, 1);
  assert.equal(streamRequests[0].path, '/api/v1/chat/completions');
  assert.equal(streamRequests[0].method, 'POST');
  assert.equal(streamRequests[0].headers['idempotency-key'], 'idem-chat-completion');
  assert.equal(streamRequests[0].body.message_id, 'msg_stream_001');
  assert.equal(streamRequests[0].body.attachments[0].file_id, 'file_001');
});

test('createChatApi preserves SSE retry hints on mapped chat events so reconnect helpers can honor server backoff', async () => {
  const reconnectDelays = [];
  let connectCount = 0;

  const api = createChatApi({
    client: {
      async request() {
        throw new Error('request should not be called');
      },
      async *stream() {
        connectCount += 1;

        if (connectCount === 1) {
          yield {
            event: 'heartbeat',
            retry: 1750,
            data: {}
          };
          return;
        }

        yield {
          event: 'message.delta',
          data: {
            content: '恢复成功'
          }
        };
        yield {
          event: 'message.completed',
          data: {
            finish_reason: 'stop',
            usage: {
              prompt_tokens: 4,
              completion_tokens: 3,
              total_tokens: 7
            }
          }
        };
      }
    },
    createIdempotencyKey: (scope) => `idem-${scope}`
  });

  const events = [];
  const result = await consumeSseStreamWithReconnect({
    connect: (signal) =>
      api.streamCompletion(
        {
          conversationId: 'conv_stream_retry_001',
          messageId: 'msg_stream_retry_001',
          userInput: '继续',
          stream: true,
          scene: 'customer_service',
          attachments: [],
          context: {
            userId: 'user_001',
            tenantId: 'tenant_001',
            channel: 'web',
            locale: 'zh-CN'
          },
          options: {
            useRag: true,
            useTools: true,
            maxHistoryTurns: 20
          }
        },
        signal
      ),
    consumeEvent: async (event) => {
      events.push(event);
    },
    shouldReconnectOnClose: () => connectCount < 2,
    maxReconnectAttempts: 1,
    defaultDelayMs: 25,
    maxDelayMs: 25,
    onBeforeReconnect: async (context) => {
      reconnectDelays.push(context.delayMs);
    },
    waitForDelay: async (delayMs) => {
      reconnectDelays.push(delayMs);
    }
  });

  assert.equal(result.reconnectAttempts, 1);
  assert.equal(connectCount, 2);
  assert.deepEqual(reconnectDelays, [1750, 1750]);
  assert.deepEqual(events, [
    {
      event: 'ping',
      retry: 1750,
      data: {}
    },
    {
      event: 'delta',
      data: {
        content: '恢复成功'
      }
    },
    {
      event: 'done',
      data: {
        finishReason: 'stop',
        usage: {
          promptTokens: 4,
          completionTokens: 3,
          totalTokens: 7
        }
      }
    }
  ]);
});



test('createChatApi getMessages handles backend SessionMessagesPage format with items array', async () => {
  const api = createChatApi({
    client: {
      async request(path) {
        if (path === '/api/v1/chat/sessions/conv_items/messages') {
          return {
            items: [
              {
                message_id: 'msg_010',
                role: 'user',
                message_type: 'user_input',
                content: 'old conversation message',
                status: 'completed',
                created_at: '2026-04-01T00:00:00.000Z'
              },
              {
                message_id: 'msg_011',
                role: 'assistant',
                message_type: 'assistant_response',
                content: '{"final_answer": "reply to old message"}',
                status: 'completed',
                created_at: '2026-04-01T00:01:00.000Z'
              }
            ],
            next_cursor: null,
            has_more: false
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'unused'
  });

  const messages = await api.getMessages('conv_items');
  assert.equal(messages.length, 2);
  assert.equal(messages[0].messageId, 'msg_010');
  assert.equal(messages[0].conversationId, 'conv_items');
  assert.equal(messages[0].messageType, 'text');
  assert.equal(messages[0].content, 'old conversation message');
  assert.equal(messages[1].messageId, 'msg_011');
  assert.equal(messages[1].messageType, 'markdown');
  assert.equal(messages[1].content, 'reply to old message');
});


test('createChatApi getMessages returns empty list for messages key instead of items', async () => {
  const api = createChatApi({
    client: {
      async request(path) {
        if (path === '/api/v1/chat/sessions/conv_msg_key/messages') {
          return {
            messages: [
              {
                message_id: 'msg_020',
                role: 'user',
                message_type: 'user_input',
                content: 'using messages key',
                status: 'completed'
              }
            ]
          };
        }

        throw new Error(`unexpected path: ${path}`);
      }
    },
    createIdempotencyKey: () => 'unused'
  });

  const messages = await api.getMessages('conv_msg_key');
  assert.equal(messages.length, 1);
  assert.equal(messages[0].messageId, 'msg_020');
  assert.equal(messages[0].content, 'using messages key');
});
