import type { RawSseEvent } from '../core/envelope';
import type { FrontendApiClient } from '../core/http';
import { asRecord, isRecord } from '../core/utils';
import {
  buildSessionListQuery,
  mapChatMessage,
  mapChatStreamEvents,
  mapConversationSummary,
  mapSessionCancelResult,
  mapSessionRetryResult,
  toChatCompletionRequestBody,
  toSessionCreateRequestBody
} from './mappers';
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
} from './types';

export interface ChatRequestClient {
  request<T>(path: string, init?: RequestInit): Promise<T>;
}

export interface ChatStreamClient extends ChatRequestClient {
  stream(path: string, init?: RequestInit): AsyncGenerator<RawSseEvent>;
}

export interface CreateChatApiOptions {
  client: ChatRequestClient | FrontendApiClient;
  createIdempotencyKey: (scope: string, parts: unknown[]) => string;
  now?: () => string;
}

function isConversationPayload(value: unknown): boolean {
  const record = asRecord(value);
  return (
    'conversation_id' in record ||
    'conversationId' in record ||
    'title' in record ||
    isRecord(record.conversation)
  );
}

function resolveConversationRecord(value: unknown): Record<string, unknown> {
  const record = asRecord(value);
  return isRecord(record.conversation) ? asRecord(record.conversation) : record;
}

function resolveCollectionRecord(value: unknown): Record<string, unknown> {
  const record = asRecord(value);
  if (isRecord(record.data)) {
    const dataRecord = asRecord(record.data);
    if (
      Array.isArray(dataRecord.items) ||
      Array.isArray(dataRecord.messages) ||
      Array.isArray(dataRecord.conversations) ||
      Array.isArray(dataRecord.list)
    ) {
      return dataRecord;
    }
  }

  return record;
}

function hasStreamClient(client: ChatRequestClient | FrontendApiClient): client is ChatStreamClient {
  return typeof (client as ChatStreamClient).stream === 'function';
}

export function createChatApi(options: CreateChatApiOptions) {
  const now = () => (options.now ? options.now() : new Date().toISOString());

  async function getConversation(conversationId: string): Promise<ConversationSummary> {
    const data = await options.client.request<Record<string, unknown>>(
      `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}`
    );
    return mapConversationSummary(resolveConversationRecord(data));
  }

  return {
    async listSessions(query: SessionListQuery = {}): Promise<PaginatedResult<ConversationSummary>> {
      const data = resolveCollectionRecord(
        await options.client.request<Record<string, unknown>>(
          `/api/v1/chat/sessions${buildSessionListQuery(query)}`
        )
      );
      const items = Array.isArray(data.items)
        ? data.items
        : Array.isArray(data.conversations)
          ? data.conversations
          : Array.isArray(data.list)
            ? data.list
            : [];

      return {
        items: items.map(mapConversationSummary),
        total: Number(data.total ?? items.length),
        page: Number(data.page ?? query.page ?? 1),
        pageSize: Number(data.page_size ?? data.pageSize ?? query.pageSize ?? 20)
      };
    },

    async createSession(input: SessionCreateRequest): Promise<ConversationSummary> {
      const data = await options.client.request<Record<string, unknown>>('/api/v1/chat/sessions', {
        method: 'POST',
        headers: {
          'Idempotency-Key': options.createIdempotencyKey('chat-session', [
            input.scene,
            input.title,
            input.initialContext ?? ''
          ])
        },
        body: JSON.stringify(toSessionCreateRequestBody(input))
      });

      return mapConversationSummary({
        ...resolveConversationRecord(data),
        title: input.title,
        scene: input.scene,
        created_at: now(),
        summary: input.initialContext ?? ''
      });
    },

    getSession: getConversation,

    async getMessages(conversationId: string): Promise<ChatMessage[]> {
      const data = resolveCollectionRecord(
        await options.client.request<Record<string, unknown>>(
          `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}/messages`
        )
      );
      const items = Array.isArray(data.items)
        ? data.items
        : Array.isArray(data.messages)
          ? data.messages
          : [];
      return items.map((item) => mapChatMessage(item, conversationId));
    },

    async renameSession(conversationId: string, title: string): Promise<ConversationSummary> {
      const data = await options.client.request<Record<string, unknown>>(
        `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}`,
        {
          method: 'PATCH',
          body: JSON.stringify({ title })
        }
      );

      if (!isConversationPayload(data)) {
        const current = await getConversation(conversationId);
        return {
          ...current,
          title
        };
      }

      return mapConversationSummary({
        ...resolveConversationRecord(data),
        title
      });
    },

    async archiveSession(conversationId: string): Promise<ConversationSummary> {
      const data = await options.client.request<Record<string, unknown>>(
        `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}/archive`,
        {
          method: 'POST'
        }
      );

      if (isConversationPayload(data)) {
        return mapConversationSummary(resolveConversationRecord(data));
      }

      return getConversation(conversationId);
    },

    async restoreSession(conversationId: string): Promise<ConversationSummary> {
      const data = await options.client.request<Record<string, unknown>>(
        `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}/restore`,
        {
          method: 'POST'
        }
      );

      if (isConversationPayload(data)) {
        return mapConversationSummary(resolveConversationRecord(data));
      }

      return getConversation(conversationId);
    },

    async deleteSession(conversationId: string): Promise<{ success: true }> {
      await options.client.request(`/api/v1/chat/sessions/${encodeURIComponent(conversationId)}`, {
        method: 'DELETE'
      });

      return { success: true };
    },

    async cancelMessage(conversationId: string, messageId: string): Promise<SessionCancelResult> {
      const data = await options.client.request<Record<string, unknown>>(
        `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}/cancel`,
        {
          method: 'POST',
          body: JSON.stringify({
            message_id: messageId
          })
        }
      );

      return mapSessionCancelResult(data);
    },

    async retryMessage(
      conversationId: string,
      messageId: string,
      overrideInput?: string
    ): Promise<SessionRetryResult> {
      const data = await options.client.request<Record<string, unknown>>(
        `/api/v1/chat/sessions/${encodeURIComponent(conversationId)}/retry`,
        {
          method: 'POST',
          headers: {
            'Idempotency-Key': options.createIdempotencyKey('chat-retry', [
              conversationId,
              messageId,
              overrideInput ?? ''
            ])
          },
          body: JSON.stringify({
            message_id: messageId,
            override_input: overrideInput
          })
        }
      );

      return mapSessionRetryResult(data);
    },

    async *streamCompletion(
      request: ChatCompletionRequest,
      signal?: AbortSignal
    ): AsyncGenerator<ChatStreamEvent> {
      if (!hasStreamClient(options.client)) {
        throw new Error('Configured chat client does not support streaming');
      }

      for await (const event of options.client.stream('/api/v1/chat/completions', {
        method: 'POST',
        headers: {
          'Idempotency-Key': options.createIdempotencyKey('chat-completion', [
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
        for (const mappedEvent of mappedEvents) {
          yield mappedEvent;
        }
      }
    }
  };
}
