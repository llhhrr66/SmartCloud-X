import { create } from "zustand";
import type {
  ChatMessage,
  ChatStreamEvent,
  ConversationSummary,
} from "@smartcloud-x/frontend-sdk/web-user";

interface StreamingState {
  conversationId?: string;
  messageId?: string;
  agent?: string;
  reasoning?: string;
  content: string;
  citations: ChatMessage["citations"];
  toolCalls: ChatMessage["toolCalls"];
  status: "idle" | "running" | "done" | "error";
  errorMessage?: string;
  reconnecting?: boolean;
  reconnectAttempt?: number;
  lastEventAt?: number;
}

interface ChatState {
  conversations: ConversationSummary[];
  conversationsLoaded: boolean;
  selectedId?: string;
  messagesByConversation: Record<string, ChatMessage[]>;
  streaming: StreamingState;

  setConversations: (list: ConversationSummary[]) => void;
  upsertConversation: (conv: ConversationSummary) => void;
  removeConversation: (id: string) => void;
  selectConversation: (id?: string) => void;
  setMessages: (id: string, msgs: ChatMessage[]) => void;
  appendMessage: (id: string, msg: ChatMessage) => void;
  beginStreaming: (conversationId: string, messageId: string) => void;
  applyStreamEvent: (event: ChatStreamEvent) => void;
  finishStreaming: (status: "done" | "error", errorMessage?: string) => void;
  cancelStreaming: () => void;
  setReconnect: (attempt: number) => void;
}

const emptyStreaming: StreamingState = { content: "", citations: [], toolCalls: [], status: "idle" };

export const useChatStore = create<ChatState>((set, get) => ({
  conversations: [],
  conversationsLoaded: false,
  messagesByConversation: {},
  streaming: emptyStreaming,

  setConversations: (list) => set({ conversations: list, conversationsLoaded: true }),
  upsertConversation: (conv) => set((s) => {
    const next = s.conversations.filter((c) => c.conversationId !== conv.conversationId);
    return { conversations: [conv, ...next] };
  }),
  removeConversation: (id) => set((s) => ({
    conversations: s.conversations.filter((c) => c.conversationId !== id),
  })),
  selectConversation: (id) => set({ selectedId: id }),
  setMessages: (id, msgs) => set((s) => ({
    messagesByConversation: { ...s.messagesByConversation, [id]: msgs },
  })),
  appendMessage: (id, msg) => set((s) => ({
    messagesByConversation: {
      ...s.messagesByConversation,
      [id]: [...(s.messagesByConversation[id] ?? []), msg],
    },
  })),
  beginStreaming: (conversationId, messageId) => set({
    streaming: { ...emptyStreaming, status: "running", conversationId, messageId, lastEventAt: Date.now() },
  }),
  applyStreamEvent: (event) => {
    set((s) => {
      const cur = s.streaming;
      const lastEventAt = Date.now();
      switch (event.event) {
        case "meta":
          return { streaming: { ...cur, agent: event.data.agent, conversationId: event.data.conversationId, messageId: event.data.messageId, lastEventAt } };
        case "reasoning":
          return { streaming: { ...cur, reasoning: event.data.summary, lastEventAt } };
        case "tool_call":
        case "tool_result": {
          const toolCalls = [...(cur.toolCalls ?? [])];
          const idx = toolCalls.findIndex((t) => t.toolCallId === event.data.toolCallId);
          if (idx >= 0) toolCalls[idx] = { ...toolCalls[idx], ...event.data };
          else toolCalls.push(event.data);
          return { streaming: { ...cur, toolCalls, lastEventAt } };
        }
        case "delta":
          return { streaming: { ...cur, content: cur.content + (event.data.content ?? ""), lastEventAt } };
        case "citation":
          return { streaming: { ...cur, citations: event.data.citations ?? [], lastEventAt } };
        case "done":
          return { streaming: { ...cur, status: "done", lastEventAt } };
        case "error":
          return { streaming: { ...cur, status: "error", errorMessage: event.data.message, lastEventAt } };
        default:
          return { streaming: { ...cur, lastEventAt } };
      }
    });
  },
  finishStreaming: (status, errorMessage) => {
    const cur = get().streaming;
    const conversationId = cur.conversationId;
    if (conversationId && cur.content) {
      const assistantMessageId = cur.messageId
        ? `assistant-local-${cur.messageId}`
        : `assistant-local-${Date.now()}`;
      const newMsg: ChatMessage = {
        id: assistantMessageId,
        messageId: assistantMessageId,
        conversationId,
        role: "assistant",
        messageType: "markdown",
        content: cur.content,
        createdAt: new Date().toISOString(),
        agentName: cur.agent,
        status: status === "error" ? "failed" : "completed",
        citations: cur.citations,
        toolCalls: cur.toolCalls,
      };
      const list = get().messagesByConversation[conversationId] ?? [];
      const dedup = list.filter((m) => m.messageId !== newMsg.messageId);
      set((s) => ({
        messagesByConversation: { ...s.messagesByConversation, [conversationId]: [...dedup, newMsg] },
      }));
    }
    set({ streaming: { ...emptyStreaming, status, errorMessage } });
  },
  cancelStreaming: () => set({ streaming: emptyStreaming }),
  setReconnect: (attempt) => set((s) => ({ streaming: { ...s.streaming, reconnecting: attempt > 0, reconnectAttempt: attempt } })),
}));
