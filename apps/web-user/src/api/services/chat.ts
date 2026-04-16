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
  createChatApi
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

const liveChatService = createChatApi({
  client: apiClient,
  createIdempotencyKey
});

export const chatService = {
  async listSessions(query: SessionListQuery = {}): Promise<PaginatedResult<ConversationSummary>> {
    if (appEnv.useMockApi) {
      return mockListSessions(query);
    }

    return liveChatService.listSessions(query);
  },

  async createSession(input: SessionCreateRequest): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockCreateSession(input);
    }

    return liveChatService.createSession(input);
  },

  async getSession(conversationId: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockGetSession(conversationId);
    }

    return liveChatService.getSession(conversationId);
  },

  async getMessages(conversationId: string): Promise<ChatMessage[]> {
    if (appEnv.useMockApi) {
      return mockGetMessages(conversationId);
    }

    return liveChatService.getMessages(conversationId);
  },

  async renameSession(conversationId: string, title: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockRenameSession(conversationId, title);
    }

    return liveChatService.renameSession(conversationId, title);
  },

  async archiveSession(conversationId: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockArchiveSession(conversationId);
    }

    return liveChatService.archiveSession(conversationId);
  },

  async restoreSession(conversationId: string): Promise<ConversationSummary> {
    if (appEnv.useMockApi) {
      return mockRestoreSession(conversationId);
    }

    return liveChatService.restoreSession(conversationId);
  },

  async deleteSession(conversationId: string): Promise<{ success: true }> {
    if (appEnv.useMockApi) {
      return mockDeleteSession(conversationId);
    }

    return liveChatService.deleteSession(conversationId);
  },

  async cancelMessage(conversationId: string, messageId: string): Promise<SessionCancelResult> {
    if (appEnv.useMockApi) {
      return mockCancelSessionMessage(conversationId, messageId);
    }

    return liveChatService.cancelMessage(conversationId, messageId);
  },

  async retryMessage(
    conversationId: string,
    messageId: string,
    overrideInput?: string
  ): Promise<SessionRetryResult> {
    if (appEnv.useMockApi) {
      return mockRetrySessionMessage(conversationId, messageId, overrideInput);
    }

    return liveChatService.retryMessage(conversationId, messageId, overrideInput);
  },

  streamCompletion(request: ChatCompletionRequest, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    if (appEnv.useMockApi) {
      return mockStreamChatCompletion(request, signal);
    }

    return liveChatService.streamCompletion(request, signal);
  }
};
