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
        type: 'clarification',
        details: {
          missingFields: ['order_no'],
          requiredPermissions: [],
          missingAuthContext: []
        }
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

test('mapChatStreamEvents treats nested auth-context requirements as permission actions even when the transport code looks like a conflict', () => {
  const events = mapChatStreamEvents({
    event: 'message.error',
    data: {
      error_code: 'CHAT_CONVERSATION_RUNNING',
      error_message: '请补充鉴权信息后继续',
      error_detail: {
        required_permissions: ['user:billing.read'],
        missing_auth_context: ['account_id']
      }
    }
  });

  assert.deepEqual(events, [
    {
      event: 'action_required',
      data: {
        code: 'CHAT_CONVERSATION_RUNNING',
        message: '请补充鉴权信息后继续',
        type: 'permission',
        details: {
          missingFields: [],
          requiredPermissions: ['user:billing.read'],
          missingAuthContext: ['account_id']
        }
      }
    },
    {
      event: 'error',
      data: {
        code: 'CHAT_CONVERSATION_RUNNING',
        message: '请补充鉴权信息后继续'
      }
    }
  ]);
});

test('mapChatStreamEvents preserves structured action-required metadata from frozen continuation hints', () => {
  const events = mapChatStreamEvents({
    event: 'message.action_required',
    data: {
      error_code: 'SERVICE_UNAVAILABLE',
      error_message: '请补充账号上下文后继续',
      action: 'collect-auth-context',
      tool_name: 'billing.create_invoice',
      tool_call_id: 'tc_auth_001',
      agent: 'Finance_Order_Agent',
      user_action_hint: {
        missing_auth_context: ['account_id'],
        required_permissions: ['user:billing.read'],
        user_profile_bindings: {
          permissions: ['permissions']
        }
      }
    }
  });

  assert.deepEqual(events, [
    {
      event: 'action_required',
      data: {
        code: 'SERVICE_UNAVAILABLE',
        message: '请补充账号上下文后继续',
        type: 'permission',
        action: 'collect-auth-context',
        toolName: 'billing.create_invoice',
        toolCallId: 'tc_auth_001',
        agent: 'Finance_Order_Agent',
        details: {
          missingFields: [],
          requiredPermissions: ['user:billing.read'],
          missingAuthContext: ['account_id'],
          userProfileBindings: {
            permissions: ['permissions']
          }
        }
      }
    }
  ]);
});

test('mapChatStreamEvents derives action-required metadata from pending_user_actions on structured message.error payloads', () => {
  const events = mapChatStreamEvents({
    event: 'message.error',
    data: {
      error_code: 'SERVICE_UNAVAILABLE',
      error_message: '需要补充账号上下文',
      pending_user_actions: [
        {
          tool_name: 'billing.create_invoice',
          tool_call_id: 'tc_auth_003',
          agent: 'Finance_Order_Agent',
          action: 'collect-auth-context',
          message: '请补充账号上下文',
          missing_auth_context: ['account_id'],
          required_permissions: ['user:billing.read'],
          user_profile_bindings: {
            permissions: ['permissions']
          }
        }
      ]
    }
  });

  assert.deepEqual(events, [
    {
      event: 'action_required',
      data: {
        code: 'SERVICE_UNAVAILABLE',
        message: '需要补充账号上下文',
        type: 'permission',
        action: 'collect-auth-context',
        details: {
          missingFields: [],
          requiredPermissions: ['user:billing.read'],
          missingAuthContext: ['account_id'],
          userProfileBindings: {
            permissions: ['permissions']
          }
        }
      }
    },
    {
      event: 'error',
      data: {
        code: 'SERVICE_UNAVAILABLE',
        message: '需要补充账号上下文'
      }
    }
  ]);
});
