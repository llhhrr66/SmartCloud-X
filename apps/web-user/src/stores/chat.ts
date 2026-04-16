import { useSyncExternalStore } from 'react';
import type {
  ChatActionRequiredPayload,
  ChatMessage,
  ChatStreamEvent,
  Citation,
  ConversationSummary,
  RetrievalSource,
  ToolCallRecord
} from '../types/domain';

export interface StreamState {
  isStreaming: boolean;
  reconnecting: boolean;
  reconnectAttempt: number;
  maxReconnectAttempts: number;
  agent?: string;
  traceId?: string;
  lastEventAt?: string;
  reasoning: Array<{ agent: string; summary: string; step: number }>;
  routes: Array<{ fromAgent: string; toAgent: string; reason: string }>;
  toolCalls: ToolCallRecord[];
  citations: Citation[];
  retrievals: Array<{ query: string; sources: RetrievalSource[] }>;
  partialContent: string;
  finishReason?: string;
  error?: string;
  actionRequired?: ChatActionRequiredPayload;
}

export interface ConversationStoreState {
  items: ConversationSummary[];
  loading: boolean;
  loaded: boolean;
  error: string | null;
}

export interface MessageStoreState {
  byConversationId: Record<string, ChatMessage[]>;
  loadedConversationIds: Record<string, true>;
  loadingConversationId: string | null;
  error: string | null;
}

export interface SseStoreState {
  conversationId: string | null;
  requestMessageId: string | null;
  isPreparing: boolean;
  stream: StreamState;
}

type Listener = () => void;
type StateUpdater<T> = T | ((previous: T) => T);

function createStore<T>(createInitialState: () => T) {
  let state = createInitialState();
  const listeners = new Set<Listener>();

  return {
    getSnapshot(): T {
      return state;
    },
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    setState(nextState: StateUpdater<T>): void {
      state = typeof nextState === 'function' ? (nextState as (previous: T) => T)(state) : nextState;
      listeners.forEach((listener) => listener());
    },
    reset(): void {
      state = createInitialState();
      listeners.forEach((listener) => listener());
    }
  };
}

export function createInitialStreamState(): StreamState {
  return {
    isStreaming: false,
    reconnecting: false,
    reconnectAttempt: 0,
    maxReconnectAttempts: 0,
    reasoning: [],
    routes: [],
    toolCalls: [],
    citations: [],
    retrievals: [],
    partialContent: ''
  };
}

function createInitialConversationStoreState(): ConversationStoreState {
  return {
    items: [],
    loading: false,
    loaded: false,
    error: null
  };
}

function createInitialMessageStoreState(): MessageStoreState {
  return {
    byConversationId: {},
    loadedConversationIds: {},
    loadingConversationId: null,
    error: null
  };
}

function createInitialSseStoreState(): SseStoreState {
  return {
    conversationId: null,
    requestMessageId: null,
    isPreparing: false,
    stream: createInitialStreamState()
  };
}

function upsertConversationItem(items: ConversationSummary[], nextItem: ConversationSummary): ConversationSummary[] {
  const index = items.findIndex((item) => item.conversationId === nextItem.conversationId);
  if (index === -1) {
    return [nextItem, ...items];
  }

  const updated = [...items];
  updated[index] = nextItem;
  return updated;
}

function upsertToolCall(collection: ToolCallRecord[], nextItem: ToolCallRecord): ToolCallRecord[] {
  const index = collection.findIndex((item) => item.toolCallId === nextItem.toolCallId);
  if (index === -1) {
    return [...collection, nextItem];
  }

  const updated = [...collection];
  updated[index] = {
    ...updated[index],
    ...nextItem
  };
  return updated;
}

function mergeCitations(collection: Citation[], nextItems: Citation[]): Citation[] {
  const merged = [...collection];

  for (const nextItem of nextItems) {
    const existingIndex = merged.findIndex((item) => item.id === nextItem.id);
    if (existingIndex === -1) {
      merged.push(nextItem);
      continue;
    }

    merged[existingIndex] = nextItem;
  }

  return merged;
}

function applyStreamEvent(previous: StreamState, event: ChatStreamEvent): StreamState {
  const receivedAt = new Date().toISOString();

  switch (event.event) {
    case 'meta':
      return {
        ...previous,
        reconnecting: false,
        agent: event.data.agent,
        traceId: event.data.traceId,
        lastEventAt: receivedAt
      };
    case 'route':
      return {
        ...previous,
        reconnecting: false,
        agent: event.data.toAgent,
        routes: [...previous.routes, event.data],
        lastEventAt: receivedAt
      };
    case 'reasoning':
      return {
        ...previous,
        reconnecting: false,
        agent: event.data.agent,
        reasoning: [...previous.reasoning, event.data],
        lastEventAt: receivedAt
      };
    case 'tool_call':
      return {
        ...previous,
        reconnecting: false,
        toolCalls: upsertToolCall(previous.toolCalls, event.data),
        lastEventAt: receivedAt
      };
    case 'tool_result':
      return {
        ...previous,
        reconnecting: false,
        toolCalls: upsertToolCall(previous.toolCalls, event.data),
        lastEventAt: receivedAt
      };
    case 'retrieval':
      return {
        ...previous,
        reconnecting: false,
        retrievals: [...previous.retrievals, { query: event.data.query, sources: event.data.sources }],
        lastEventAt: receivedAt
      };
    case 'delta':
      return {
        ...previous,
        reconnecting: false,
        partialContent: `${previous.partialContent}${event.data.content}`,
        lastEventAt: receivedAt
      };
    case 'citation':
      return {
        ...previous,
        reconnecting: false,
        citations: mergeCitations(previous.citations, event.data.citations),
        lastEventAt: receivedAt
      };
    case 'done':
      return {
        ...previous,
        isStreaming: false,
        reconnecting: false,
        finishReason: event.data.finishReason,
        lastEventAt: receivedAt
      };
    case 'error':
      return {
        ...previous,
        isStreaming: false,
        reconnecting: false,
        error: event.data.message,
        lastEventAt: receivedAt
      };
    case 'action_required':
      return {
        ...previous,
        reconnecting: false,
        actionRequired: event.data,
        lastEventAt: receivedAt
      };
    case 'ping':
      return {
        ...previous,
        reconnecting: false,
        lastEventAt: receivedAt
      };
  }
}

const conversationStore = createStore(createInitialConversationStoreState);
const messageStore = createStore(createInitialMessageStoreState);
const sseStore = createStore(createInitialSseStoreState);

export function getConversationStoreState(): ConversationStoreState {
  return conversationStore.getSnapshot();
}

export function getMessageStoreState(): MessageStoreState {
  return messageStore.getSnapshot();
}

export function getSseStoreState(): SseStoreState {
  return sseStore.getSnapshot();
}

export function useConversationStore(): ConversationStoreState {
  return useSyncExternalStore(conversationStore.subscribe, conversationStore.getSnapshot, conversationStore.getSnapshot);
}

export function useMessageStore(): MessageStoreState {
  return useSyncExternalStore(messageStore.subscribe, messageStore.getSnapshot, messageStore.getSnapshot);
}

export function useSseStore(): SseStoreState {
  return useSyncExternalStore(sseStore.subscribe, sseStore.getSnapshot, sseStore.getSnapshot);
}

export const conversationStoreActions = {
  startLoading(): void {
    conversationStore.setState((previous) => ({
      ...previous,
      loading: true,
      error: null
    }));
  },
  setSessions(items: ConversationSummary[]): void {
    conversationStore.setState({
      items,
      loading: false,
      loaded: true,
      error: null
    });
  },
  setError(message: string): void {
    conversationStore.setState((previous) => ({
      ...previous,
      loading: false,
      error: message
    }));
  },
  upsertConversation(item: ConversationSummary): void {
    conversationStore.setState((previous) => ({
      ...previous,
      items: upsertConversationItem(previous.items, item),
      loaded: true,
      error: null
    }));
  },
  removeConversation(conversationId: string): void {
    conversationStore.setState((previous) => ({
      ...previous,
      items: previous.items.filter((item) => item.conversationId !== conversationId)
    }));
  }
};

export const messageStoreActions = {
  startLoading(conversationId: string): void {
    messageStore.setState((previous) => ({
      ...previous,
      loadingConversationId: conversationId,
      error: null
    }));
  },
  setConversationMessages(conversationId: string, items: ChatMessage[]): void {
    messageStore.setState((previous) => ({
      ...previous,
      byConversationId: {
        ...previous.byConversationId,
        [conversationId]: items
      },
      loadedConversationIds: {
        ...previous.loadedConversationIds,
        [conversationId]: true
      },
      loadingConversationId: previous.loadingConversationId === conversationId ? null : previous.loadingConversationId,
      error: null
    }));
  },
  appendMessage(conversationId: string, message: ChatMessage): void {
    messageStore.setState((previous) => ({
      ...previous,
      byConversationId: {
        ...previous.byConversationId,
        [conversationId]: [...(previous.byConversationId[conversationId] ?? []), message]
      },
      loadedConversationIds: {
        ...previous.loadedConversationIds,
        [conversationId]: true
      },
      error: null
    }));
  },
  markConversationStale(conversationId: string): void {
    messageStore.setState((previous) => {
      const nextLoadedConversationIds = { ...previous.loadedConversationIds };
      delete nextLoadedConversationIds[conversationId];

      return {
        ...previous,
        loadedConversationIds: nextLoadedConversationIds,
        loadingConversationId: previous.loadingConversationId === conversationId ? null : previous.loadingConversationId
      };
    });
  },
  clearConversation(conversationId: string): void {
    messageStore.setState((previous) => {
      const nextByConversationId = { ...previous.byConversationId };
      const nextLoadedConversationIds = { ...previous.loadedConversationIds };
      delete nextByConversationId[conversationId];
      delete nextLoadedConversationIds[conversationId];

      return {
        ...previous,
        byConversationId: nextByConversationId,
        loadedConversationIds: nextLoadedConversationIds,
        loadingConversationId: previous.loadingConversationId === conversationId ? null : previous.loadingConversationId
      };
    });
  },
  setError(message: string): void {
    messageStore.setState((previous) => ({
      ...previous,
      loadingConversationId: null,
      error: message
    }));
  },
  clearError(): void {
    messageStore.setState((previous) => ({
      ...previous,
      error: null
    }));
  }
};

export const sseStoreActions = {
  prepare(requestMessageId?: string): void {
    sseStore.setState((previous) => ({
      ...previous,
      isPreparing: true,
      requestMessageId: requestMessageId ?? previous.requestMessageId
    }));
  },
  finishPreparing(): void {
    sseStore.setState((previous) => ({
      ...previous,
      isPreparing: false
    }));
  },
  start(conversationId: string, requestMessageId: string, agent?: string, maxReconnectAttempts = 0): void {
    sseStore.setState({
      conversationId,
      requestMessageId,
      isPreparing: false,
      stream: {
        ...createInitialStreamState(),
        isStreaming: true,
        agent,
        maxReconnectAttempts
      }
    });
  },
  applyEvent(event: ChatStreamEvent): void {
    sseStore.setState((previous) => ({
      ...previous,
      stream: applyStreamEvent(previous.stream, event)
    }));
  },
  updateStream(updater: (previous: StreamState) => StreamState): void {
    sseStore.setState((previous) => ({
      ...previous,
      stream: updater(previous.stream)
    }));
  },
  replace(conversationId: string, requestMessageId: string, stream: StreamState): void {
    sseStore.setState({
      conversationId,
      requestMessageId,
      isPreparing: false,
      stream
    });
  },
  reset(): void {
    sseStore.reset();
  }
};
