import type {
  ChatCompletionRequest,
  ChatMessage,
  ChatStreamEvent,
  ConversationSummary,
  PaginatedResult,
  SessionCancelResult,
  SessionCreateRequest,
  SessionListQuery,
  SessionRetryResult
} from '../../types/domain';
import { appEnv } from '../../config/env';
import { createIdempotencyKey } from '../../lib/request-meta';
import {
  buildSessionListQuery,
  mapChatMessage,
  mapChatStreamEvents,
  mapConversationSummary,
  mapSessionCancelResult,
  mapSessionRetryResult,
  toChatCompletionRequestBody,
  toSessionCreateRequestBody
} from '../../shared-sdk';
import { apiClient } from '../client';
import {
  mockArchiveSession,
  mockCancelSessionMessage,
  mockCreateSession,
  mockDeleteSession,
  mockGetSession,
  mockGetMessages,
  mockListSessions,
  mockRenameSession,
  mockRestoreSession,
  mockRetrySessionMessage,
  mockStreamChatCompletion
} from '../mock';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isConversationPayload(value: unknown): boolean {
  return (
    isRecord(value) &&
    ('conversation_id' in value || 'conversationId' in value || 'title' in value)
  );
}

async function fetchLiveConversation(conversationId: string): Promise<ConversationSummary> {
  const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}`);
  return mapConversationSummary(isRecord(data.conversation) ? data.conversation : data);
}

async function* liveStreamCompletion(
  request: ChatCompletionRequest,
  signal?: AbortSignal
): AsyncGenerator<ChatStreamEvent> {
  for await (const event of apiClient.stream('/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Idempotency-Key': createIdempotencyKey('chat-completion', [
        request.conversationId,
        request.messageId,
        request.scene,
        request.userInput,
        request.attachments.map((item) => item.fileId)
      ])
    },
    body: JSON.stringify(toChatCompletionRequestBody(request)),
    signal
  })) {
    const mappedEvents = mapChatStreamEvents(event);
    for (const mapped of mappedEvents) {
      yield mapped;
    }
  }
}

export const chatService = {
  async listSessions(query: SessionListQuery = {}): Promise<PaginatedResult<ConversationSummary>> {
    if (appEnv.useMockApi) {
      return mockListSessions(query);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions${buildSessionListQuery(query)}`);
    const items = Array.isArray(data.items) ? data.items.map(mapConversationSummary) : [];

    return {
      items,
      total: Number(data.total ?? items.length),
      page: Number(data.page ?? query.page ?? 1),
      pageSize: Number(data.page_size ?? data.pageSize ?? query.pageSize ?? 20)
    };
  },

  async createSession(input: SessionCreateRequest): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockCreateSession(input);
    }

    const now = new Date().toISOString();
    const data = await apiClient.request<Record<string, unknown>>('/api/v1/chat/sessions', {
      method: 'POST',
      headers: {
        'Idempotency-Key': createIdempotencyKey('chat-session', [input.scene, input.title, input.initialContext ?? ''])
      },
      body: JSON.stringify(toSessionCreateRequestBody(input))
    });

    return mapConversationSummary({
      ...data,
      title: input.title,
      scene: input.scene,
      created_at: now,
      summary: input.initialContext ?? ''
    });
  },

  async getSession(conversationId: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockGetSession(conversationId);
    }

    return fetchLiveConversation(conversationId);
  },

  async getMessages(conversationId: string): Promise<ChatMessage[]> {
    if (appEnv.useMockApi) {
      return mockGetMessages(conversationId);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}/messages`);
    const items = Array.isArray(data.items) ? data.items : Array.isArray(data.messages) ? data.messages : [];
    return items.map((item) => mapChatMessage(item, conversationId));
  },

  async renameSession(conversationId: string, title: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockRenameSession(conversationId, title);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title })
    });

    return mapConversationSummary(data);
  },

  async archiveSession(conversationId: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockArchiveSession(conversationId);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}/archive`, {
      method: 'POST'
    });

    if (isConversationPayload(data)) {
      return mapConversationSummary(data);
    }

    return fetchLiveConversation(conversationId);
  },

  async restoreSession(conversationId: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockRestoreSession(conversationId);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}/restore`, {
      method: 'POST'
    });

    if (isConversationPayload(data)) {
      return mapConversationSummary(data);
    }

    return fetchLiveConversation(conversationId);
  },

  async deleteSession(conversationId: string): Promise<{ success: true }> {
    if (appEnv.useMockApi) {
      return mockDeleteSession(conversationId);
    }

    await apiClient.request(`/api/v1/chat/sessions/${conversationId}`, {
      method: 'DELETE'
    });

    return { success: true };
  },

  async cancelMessage(conversationId: string, messageId: string): Promise<SessionCancelResult> {
    if (appEnv.useMockApi) {
      return mockCancelSessionMessage(conversationId, messageId);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({
        message_id: messageId
      })
    });

    return mapSessionCancelResult(data);
  },

  async retryMessage(
    conversationId: string,
    messageId: string,
    overrideInput?: string
  ): Promise<SessionRetryResult> {
    if (appEnv.useMockApi) {
      return mockRetrySessionMessage(conversationId, messageId, overrideInput);
    }

    const data = await apiClient.request<Record<string, unknown>>(`/api/v1/chat/sessions/${conversationId}/retry`, {
      method: 'POST',
      headers: {
        'Idempotency-Key': createIdempotencyKey('chat-retry', [conversationId, messageId, overrideInput ?? ''])
      },
      body: JSON.stringify({
        message_id: messageId,
        override_input: overrideInput
      })
    });

    return mapSessionRetryResult(data);
  },

  streamCompletion(request: ChatCompletionRequest, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    if (appEnv.useMockApi) {
      return mockStreamChatCompletion(request, signal);
    }

    return liveStreamCompletion(request, signal);
  }
};
