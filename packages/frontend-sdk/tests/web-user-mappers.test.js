import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { mapChatStreamEvents } = require('../../../.tmp/frontend-sdk-runtime/frontend-sdk/src/web-user/mappers.js');

test('mapChatStreamEvents normalizes structured message.error alias payloads into clarification actions', () => {
  const events = mapChatStreamEvents({
    event: 'message.error',
    data: {
      error_code: 'CHAT_CONTINUATION_NOT_AVAILABLE',
      error_message: '请补充订单号',
      error_detail: {
        missing_fields: ['order_no']
      }
    }
  });

  assert.deepEqual(events, [
    {
      event: 'action_required',
      data: {
        code: 'CHAT_CONTINUATION_NOT_AVAILABLE',
        message: '请补充订单号',
        type: 'clarification'
      }
    },
    {
      event: 'error',
      data: {
        code: 'CHAT_CONTINUATION_NOT_AVAILABLE',
        message: '请补充订单号'
      }
    }
  ]);
});

test('mapChatStreamEvents normalizes nested permission failures and direct action_required events', () => {
  const permissionEvents = mapChatStreamEvents({
    event: 'message.error',
    data: {
      error: {
        code: 'TOOL_HUB_CALLER_FORBIDDEN',
        message: '当前账号无权访问工具调用结果'
      }
    }
  });

  assert.deepEqual(permissionEvents, [
    {
      event: 'action_required',
      data: {
        code: 'TOOL_HUB_CALLER_FORBIDDEN',
        message: '当前账号无权访问工具调用结果',
        type: 'permission'
      }
    },
    {
      event: 'error',
      data: {
        code: 'TOOL_HUB_CALLER_FORBIDDEN',
        message: '当前账号无权访问工具调用结果'
      }
    }
  ]);

  const actionRequiredEvents = mapChatStreamEvents({
    event: 'action_required',
    data: {
      error_code: 'AUTH_UNAUTHORIZED',
      error_message: '请重新登录后继续',
      type: 'permission'
    }
  });

  assert.deepEqual(actionRequiredEvents, [
    {
      event: 'action_required',
      data: {
        code: 'AUTH_UNAUTHORIZED',
        message: '请重新登录后继续',
        type: 'permission'
      }
    }
  ]);
});
