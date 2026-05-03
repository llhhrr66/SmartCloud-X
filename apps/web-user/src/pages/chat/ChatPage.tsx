import { useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUp, Bot, Edit3, MoreHorizontal, Paperclip, Plus, Search, Sparkles, Trash2, Archive,
  Wallet, Code, Globe, Megaphone, MessageSquareQuote,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/Button";
import { Empty, Loading } from "@/components/ui/Empty";
import { Avatar } from "@/components/ui/Avatar";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAuthStore, selectCurrentUser } from "@/stores/auth";
import { useChatStore } from "@/stores/chat";
import { chatApi } from "@/lib/sdk";
import { runtimeConfig } from "@/lib/runtime-config";
import { notifyError, notifySuccess } from "@/lib/errors";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/cn";
import { NewConversationModal } from "./NewConversationModal";
import type { ChatCompletionRequest, ChatMessage, ConversationSummary } from "@smartcloud-x/frontend-sdk/web-user";
import { getAgentMeta } from "./agentMeta";

const EMPTY_MESSAGES: ChatMessage[] = [];
const AGENT_DISPLAY_NAMES: Record<string, string> = {
  billing: "账单专员",
  customer_service: "客服助手",
  deep_research_agent: "市场研究专员",
  finance_order_agent: "账单专员",
  icp: "ICP 备案专员",
  icp_service_agent: "ICP 备案专员",
  marketing: "营销专员",
  ops_marketing_agent: "营销专员",
  orchestrator: "AI 助手",
  product_tech_agent: "技术支持",
  research: "市场研究专员",
  technical_support: "技术支持",
};
const AGENT_CAPABILITY_LINES: Record<string, string> = {
  billing: "我可以帮你查询账单、订单、退款、发票和工单进度。",
  customer_service: "我可以帮你处理通用咨询、订单查询、售后问题和使用反馈。",
  deep_research_agent: "我可以帮你做行业调研、竞品对比、整理参考资料和导出研究报告。",
  finance_order_agent: "我可以帮你查询账单、订单、退款、发票和工单进度。",
  icp: "我可以帮你检查备案材料、核验主体信息、提交备案申请和跟踪进度。",
  icp_service_agent: "我可以帮你检查备案材料、核验主体信息、提交备案申请和跟踪进度。",
  marketing: "我可以帮你策划营销活动、生成文案、制作海报和生成推广链接。",
  ops_marketing_agent: "我可以帮你策划营销活动、生成文案、制作海报和生成推广链接。",
  orchestrator: "我可以帮你处理客服、账单、技术、营销等方面的问题。",
  product_tech_agent: "我可以帮你排查故障、推荐实例规格、查看服务状态，也能给出部署和排障建议。",
  research: "我可以帮你做行业调研、竞品对比、整理参考资料和导出研究报告。",
  technical_support: "我可以帮你排查故障、推荐实例规格、查看服务状态，也能给出部署和排障建议。",
};

const STARTER_PROMPTS = [
  { Icon: Wallet, tone: "from-amber-500 to-amber-600", title: "查看账单明细", text: "我想了解本月的费用详细，账单分布如何", scene: "billing" },
  { Icon: Code, tone: "from-violet-500 to-violet-600", title: "技术支持", text: "我的服务出现了异常，需要技术支持帮忙排查", scene: "technical_support" },
  { Icon: Globe, tone: "from-cyan-500 to-cyan-600", title: "ICP 备案", text: "我想提交一个新的 ICP 备案申请，需要哪些资料？", scene: "icp" },
  { Icon: Megaphone, tone: "from-pink-500 to-pink-600", title: "营销文案", text: "为我们的双 11 活动写一组营销海报文案", scene: "marketing" },
] as const;

function normalizeAgentKey(value?: string | null): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/-/g, "_");
}

function formatAgentName(value?: string | null): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "AI 助手";
  return AGENT_DISPLAY_NAMES[normalizeAgentKey(raw)] ?? raw;
}

function normalizeAssistantDisplayContent(content: string, agentName?: string): string {
  const text = String(content ?? "").trim();
  if (!text || !/^[a-z_]+ 已完成当前阶段处理。?$/i.test(text)) {
    return content;
  }
  const rawAgent = agentName ?? text.split(" ", 1)[0] ?? "";
  const normalizedAgent = normalizeAgentKey(rawAgent);
  const capability = AGENT_CAPABILITY_LINES[normalizedAgent] ?? "我可以帮你处理当前场景下的问题。";
  return `你好，我是${formatAgentName(rawAgent)}。${capability}`;
}

function isConversationMissingError(error: unknown): boolean {
  const status = typeof error === "object" && error !== null && "status" in error ? (error as { status?: number }).status : undefined;
  const code = typeof error === "object" && error !== null && "code" in error ? String((error as { code?: string | number }).code ?? "").toUpperCase() : "";
  const message = typeof error === "object" && error !== null && "message" in error ? String((error as { message?: string }).message ?? "") : "";
  if (status === 404) return true;
  if (code === "CHAT_CONVERSATION_NOT_FOUND" || code === "4042104") return true;
  return /CHAT_CONVERSATION_NOT_FOUND|会话不存在|conversation .* was not found/i.test(message);
}

export default function ChatPage() {
  const { conversationId } = useParams();
  const location = useLocation();
  const locationState = (location.state ?? {}) as {
    initialMessage?: string;
    initialScene?: ChatCompletionRequest["scene"];
  };
  const navigate = useNavigate();
  const qc = useQueryClient();
  const user = useAuthStore(selectCurrentUser);

  const [showNew, setShowNew] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [modalScene, setModalScene] = useState<ChatCompletionRequest["scene"] | undefined>(undefined);

  const conversations = useChatStore((s) => s.conversations);
  const setConversations = useChatStore((s) => s.setConversations);
  const messages = useChatStore((s) => (conversationId ? s.messagesByConversation[conversationId] ?? EMPTY_MESSAGES : EMPTY_MESSAGES));
  const setMessages = useChatStore((s) => s.setMessages);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const upsertConversation = useChatStore((s) => s.upsertConversation);
  const removeConversation = useChatStore((s) => s.removeConversation);
  const streaming = useChatStore((s) => s.streaming);
  const beginStreaming = useChatStore((s) => s.beginStreaming);
  const applyStreamEvent = useChatStore((s) => s.applyStreamEvent);
  const finishStreaming = useChatStore((s) => s.finishStreaming);

  useQuery({
    queryKey: ["chat", "sessions"],
    queryFn: async () => {
      const res = await chatApi.listSessions({ page: 1, pageSize: 50 });
      setConversations(res.items);
      return res;
    },
  });

  const messagesQuery = useQuery({
    queryKey: ["chat", "messages", conversationId],
    enabled: Boolean(conversationId) && !locationState.initialMessage?.trim(),
    queryFn: async () => {
      const list = await chatApi.getMessages(conversationId!);
      setMessages(conversationId!, list);
      return list;
    },
  });

  const visibleConversations = conversations.filter((c) => c.status !== "archived");
  const filtered = visibleConversations.filter((c) =>
    !keyword || c.title.includes(keyword) || c.summary?.includes(keyword)
  );

  const activeConversation = conversations.find((c) => c.conversationId === conversationId);

  // Sends a chat message to a conversation (used for first-message from NewConversationModal)
  const sendMessageToConversation = useCallback(async (
    convId: string,
    input: string,
    sceneOverride?: ChatCompletionRequest["scene"],
  ) => {
    const messageId = `m-${Date.now()}`;
    appendMessage(convId, {
      id: messageId,
      messageId,
      conversationId: convId,
      role: "user",
      messageType: "text",
      content: input,
      status: "completed",
      createdAt: new Date().toISOString(),
    });
    beginStreaming(convId, messageId);

    const conv = conversations.find((c) => c.conversationId === convId);
    const req: ChatCompletionRequest = {
      conversationId: convId,
      messageId,
      userInput: input,
      stream: true,
      scene: (sceneOverride ?? conv?.scene ?? "customer_service") as ChatCompletionRequest["scene"],
      attachments: [],
      context: {
        userId: user?.userId ?? "",
        tenantId: user?.tenantId ?? "",
        channel: "web",
        locale: user?.locale ?? "zh-CN",
      },
      options: {
        useRag: true,
        useTools: true,
        maxHistoryTurns: 12,
      },
    };

    try {
      for await (const ev of chatApi.streamCompletion(req)) {
        applyStreamEvent(ev);
      }
      finishStreaming("done");
    } catch (e) {
      finishStreaming("error", (e as Error).message);
      notifyError(e, "对话出错");
    } finally {
      void qc.invalidateQueries({ queryKey: ["chat", "messages", convId] });
      void qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
    }
  }, [conversations, user, appendMessage, beginStreaming, applyStreamEvent, finishStreaming, qc]);

  useEffect(() => {
    if (!conversationId || !messagesQuery.isError) return;
    if (!isConversationMissingError(messagesQuery.error)) return;
    removeConversation(conversationId);
    qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
    navigate("/chat", { replace: true });
    notifyError(messagesQuery.error, "该会话不存在或历史消息已被清理");
  }, [conversationId, messagesQuery.isError, messagesQuery.error, navigate, qc, removeConversation]);

  const autoSendRef = useRef<string | null>(null);
  useEffect(() => {
    const initialMessage = locationState.initialMessage?.trim();
    if (!conversationId || !initialMessage) return;
    const key = `${conversationId}:${initialMessage}`;
    if (autoSendRef.current === key) return;
    autoSendRef.current = key;
    void sendMessageToConversation(
      conversationId,
      initialMessage,
      locationState.initialScene,
    ).finally(() => {
      navigate(location.pathname, { replace: true, state: null });
    });
  }, [
    conversationId,
    location.pathname,
    locationState.initialMessage,
    locationState.initialScene,
    navigate,
    sendMessageToConversation,
  ]);

  return (
    <div className="flex h-full overflow-hidden">
      <ConversationListPanel
        conversations={filtered}
        keyword={keyword}
        onKeywordChange={setKeyword}
        activeId={conversationId}
        onSelect={(id) => navigate(`/chat/${id}`)}
        onNew={() => { setModalScene(undefined); setShowNew(true); }}
        onAction={async (action, id) => {
          try {
            if (action === "archive") {
              await chatApi.archiveSession(id);
              removeConversation(id);
              notifySuccess("已归档");
              if (id === conversationId) navigate("/chat");
            } else if (action === "delete") {
              if (!confirm("确认删除该会话？")) return;
              await chatApi.deleteSession(id);
              removeConversation(id);
              notifySuccess("已删除");
              if (id === conversationId) navigate("/chat");
            } else if (action === "rename") {
              const next = prompt("修改会话名称");
              if (!next) return;
              const updated = await chatApi.renameSession(id, next);
              upsertConversation(updated);
              qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
            }
          } catch (e) {
            notifyError(e);
          }
        }}
      />

      <div className="flex flex-1 flex-col overflow-hidden bg-slate-50/50">
        {!conversationId ? (
          <ChatHero
            onPick={(text, scene) => {
              setModalScene(scene);
              setShowNew(true);
            }}
            userName={user?.name ?? "你"}
          />
        ) : (
          <>
            <ChatHeader conversation={activeConversation} />
            <div className="flex-1 overflow-y-auto px-6 py-6">
              <MessageStream
                messages={messages}
                streaming={streaming}
                userName={user?.name ?? "你"}
                loading={messagesQuery.isLoading && messages.length === 0}
                error={messagesQuery.isError && messages.length === 0}
                conversation={activeConversation}
                onPromptSelect={async (prompt) => {
                  if (!conversationId) return;
                  await sendMessageToConversation(conversationId, prompt, activeConversation?.scene);
                }}
              />
            </div>
            <ChatComposer
              busy={streaming.status === "running"}
              onSubmit={async (input) => {
                if (!conversationId) return;
                await sendMessageToConversation(conversationId, input);
              }}
            />
          </>
        )}
      </div>

      <NewConversationModal
        open={showNew}
        onClose={() => setShowNew(false)}
        initialScene={modalScene}
      />
    </div>
  );
}

function ConversationListPanel({
  conversations, keyword, onKeywordChange, activeId, onSelect, onNew, onAction,
}: {
  conversations: ConversationSummary[];
  keyword: string;
  onKeywordChange: (v: string) => void;
  activeId?: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onAction: (action: "rename" | "archive" | "delete", id: string) => void;
}) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);

  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3.5">
        <div>
          <div className="text-sm font-semibold text-slate-900">AI 会话</div>
          <div className="text-[11px] text-slate-400">{conversations.length} 个会话</div>
        </div>
        <Button size="sm" leftIcon={<Plus className="size-3.5" />} onClick={onNew}>新建</Button>
      </div>

      <div className="border-b border-slate-100 px-4 py-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
          <input
            value={keyword}
            onChange={(e) => onKeywordChange(e.target.value)}
            placeholder="搜索会话…"
            className="h-8 w-full rounded-md border border-slate-200 bg-slate-50 pl-8 pr-2 text-xs placeholder:text-slate-400 focus:bg-white focus:border-brand-500 focus:outline-none"
          />
        </div>
      </div>

      <div className="scrollbar-thin flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <Empty compact title="还没有会话" description="点击新建开始你的第一次对话" />
        ) : (
          <ul className="space-y-px py-1">
            {conversations.map((c) => {
              const active = c.conversationId === activeId;
              return (
                <li key={c.conversationId} className="relative px-2">
                  <button
                    type="button"
                    onClick={() => onSelect(c.conversationId)}
                    className={cn(
                      "group flex w-full items-start gap-2.5 rounded-lg px-3 py-2.5 text-left transition",
                      active ? "bg-brand-50 ring-1 ring-brand-100" : "hover:bg-slate-50",
                    )}
                  >
                    <div className={cn(
                      "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md",
                      active ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-500",
                    )}>
                      <Bot className="size-3.5" />
                    </div>
                    <div className="flex-1 overflow-hidden">
                      <div className="flex items-center gap-1.5">
                        <span className={cn("truncate text-[13px] font-medium", active ? "text-brand-700" : "text-slate-800")}>
                          {c.title || "未命名会话"}
                        </span>
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-slate-400">{c.summary || "无"}</div>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                        <StatusBadge status={c.status} dot={false} />
                        <span>·</span>
                        <span>{formatRelative(c.updatedAt)}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setOpenMenu(openMenu === c.conversationId ? null : c.conversationId); }}
                      className="rounded-md p-1 opacity-0 transition hover:bg-slate-200 group-hover:opacity-100"
                    >
                      <MoreHorizontal className="size-3.5 text-slate-500" />
                    </button>
                  </button>
                  {openMenu === c.conversationId && (
                    <div className="absolute right-3 top-12 z-10 w-32 rounded-md border border-slate-100 bg-white py-1 text-xs shadow-lg">
                      <button onClick={() => { setOpenMenu(null); onAction("rename", c.conversationId); }}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-slate-700 hover:bg-slate-50"><Edit3 className="size-3" />重命名</button>
                      <button onClick={() => { setOpenMenu(null); onAction("archive", c.conversationId); }}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-slate-700 hover:bg-slate-50"><Archive className="size-3" />归档</button>
                      <button onClick={() => { setOpenMenu(null); onAction("delete", c.conversationId); }}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-danger-600 hover:bg-danger-50"><Trash2 className="size-3" />删除</button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

function ChatHeader({ conversation }: { conversation?: ConversationSummary }) {
  if (!conversation) return null;
  return (
    <div className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-3.5">
      <div>
        <div className="text-base font-semibold text-slate-900">{conversation.title || "未命名会话"}</div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
          <span className="inline-flex items-center gap-1"><Bot className="size-3" />{formatAgentName(conversation.currentAgent)}</span>
          <span>·</span>
          <span>共 {conversation.messageCount} 条</span>
          <StatusBadge status={conversation.status} />
        </div>
      </div>
    </div>
  );
}

function ChatHero({
  onPick,
  userName,
}: {
  onPick: (text: string, scene: ChatCompletionRequest["scene"]) => void;
  userName: string;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6">
      <div className="mb-4 flex size-16 items-center justify-center rounded-2xl bg-linear-to-br from-brand-400 to-brand-600 text-white shadow-lg shadow-brand-600/30">
        <Sparkles className="size-7" />
      </div>
      <h2 className="text-2xl font-semibold text-slate-900">你好，{userName}</h2>
      <p className="mt-2 text-sm text-slate-500">这是 SmartCloud-X AI 助手，能帮你处理客服、账单、技术、营销等方面的业务问题</p>
      <div className="mt-8 grid w-full max-w-2xl grid-cols-2 gap-3">
        {STARTER_PROMPTS.map((p) => (
          <button
            key={p.title}
            onClick={() => onPick(p.text, p.scene)}
            className="card card-hover flex cursor-pointer items-start gap-3 p-4 text-left transition focus-ring"
          >
            <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg bg-linear-to-br text-white shadow-sm", p.tone)}>
              <p.Icon className="size-[18px]" />
            </span>
            <div>
              <div className="text-sm font-medium text-slate-900">{p.title}</div>
              <div className="mt-0.5 text-xs text-slate-500">{p.text}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

type StreamingState = ReturnType<typeof useChatStore.getState>["streaming"];

function MessageStream({
  messages, streaming, userName, loading, error, conversation, onPromptSelect,
}: {
  messages: ChatMessage[];
  streaming: StreamingState;
  userName: string;
  loading?: boolean;
  error?: boolean;
  conversation?: ConversationSummary;
  onPromptSelect?: (prompt: string) => Promise<void>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, streaming.content]);

  if (loading) {
    return <Loading tip="正在加载对话记录…" />;
  }

  if (error) {
    return <Empty title="对话记录加载失败" description="请刷新页面重试" />;
  }

  if (!messages.length && streaming.status !== "running") {
    return (
      <ConversationIntro
        conversation={conversation}
        onPromptSelect={onPromptSelect}
      />
    );
  }

  return (
    <div ref={containerRef} className="mx-auto flex max-w-3xl flex-col gap-5">
      {messages.map((m) => (
        <MessageBubble key={m.id} role={m.role} content={m.content} agentName={m.agentName} userName={userName} />
      ))}
      {streaming.status === "running" && (
        <MessageBubble
          role="assistant"
          content={streaming.content || (streaming.reasoning ? `_${streaming.reasoning}_` : "正在思考中…")}
          agentName={streaming.agent}
          userName={userName}
          streaming
        />
      )}
    </div>
  );
}

function ConversationIntro({
  conversation,
  onPromptSelect,
}: {
  conversation?: ConversationSummary;
  onPromptSelect?: (prompt: string) => Promise<void>;
}) {
  const [pendingPrompt, setPendingPrompt] = useState<string | null>(null);
  const agent = getAgentMeta(conversation?.scene);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5">
      <div className="flex gap-3">
        <div className={cn("flex size-9 shrink-0 items-center justify-center rounded-full bg-linear-to-br text-white shadow shadow-brand-600/20", agent.tone)}>
          <agent.icon className="size-4" />
        </div>
        <div className="flex max-w-[78%] flex-col gap-1">
          <div className="text-[11px] text-slate-400">{agent.name}</div>
          <div className="rounded-2xl bg-white px-4 py-3 shadow-sm ring-1 ring-slate-100">
            <p className="whitespace-pre-wrap text-sm leading-6 text-slate-700">
              {agent.intro}
            </p>
            <div className="mt-3 flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-slate-400">
              <MessageSquareQuote className="size-3.5 text-slate-400" />
              快捷提问
            </div>
            <div className="mt-2 flex flex-col gap-2">
              {agent.prompts.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  disabled={pendingPrompt !== null}
                  onClick={async () => {
                    if (!onPromptSelect) return;
                    setPendingPrompt(prompt);
                    try {
                      await onPromptSelect(prompt);
                    } finally {
                      setPendingPrompt(null);
                    }
                  }}
                  className={cn(
                    "w-full rounded-2xl border border-slate-200 bg-slate-50/80 px-3.5 py-2.5 text-left text-xs leading-5 text-slate-700 transition",
                    "hover:-translate-y-0.5 hover:border-brand-200 hover:bg-white hover:text-brand-700 hover:shadow-sm disabled:cursor-wait disabled:opacity-70",
                    pendingPrompt === prompt && "border-brand-300 bg-brand-50 text-brand-700 shadow-sm",
                  )}
                >
                  <span className="block">{prompt}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  role, content, agentName, userName, streaming,
}: {
  role: string;
  content: string;
  agentName?: string;
  userName: string;
  streaming?: boolean;
}) {
  const isUser = role === "user";
  const displayContent = isUser ? content : normalizeAssistantDisplayContent(content, agentName);
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      {isUser ? (
        <Avatar name={userName} size="md" />
      ) : (
        <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-brand-400 to-brand-600 text-white shadow shadow-brand-600/20">
          <Bot className="size-4" />
        </div>
      )}
      <div className={cn("flex max-w-[78%] flex-col gap-1", isUser && "items-end")}>
        <div className="text-[11px] text-slate-400">
          {isUser ? userName : formatAgentName(agentName)}
        </div>
        <div className={cn(
          "rounded-2xl px-4 py-3",
          isUser ? "bg-brand-500 text-white shadow-md shadow-brand-600/20" : "bg-white shadow-sm ring-1 ring-slate-100",
          streaming && "ring-2 ring-brand-200",
        )}>
          {isUser ? (
            <div className="whitespace-pre-wrap text-sm leading-6">{displayContent}</div>
          ) : (
            <div className="markdown text-sm">
              <ReactMarkdown>{displayContent || "…"}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ChatComposer({ busy, onSubmit }: { busy?: boolean; onSubmit: (input: string) => void }) {
  const [value, setValue] = useState("");
  const submit = useCallback(() => {
    const v = value.trim();
    if (!v || busy) return;
    onSubmit(v);
    setValue("");
  }, [value, busy, onSubmit]);

  return (
    <div className="border-t border-slate-200 bg-white px-6 py-4">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-sm focus-within:border-brand-500 focus-within:shadow-[0_0_0_3px_rgba(61,110,248,0.12)]">
          <button type="button" className="rounded-lg p-2 text-slate-400 hover:bg-slate-50 hover:text-slate-600" title="上传文件">
            <Paperclip className="size-4" />
          </button>
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="输入消息…Shift+Enter 换行"
            rows={1}
            className="max-h-40 flex-1 resize-none bg-transparent px-2 py-2 text-sm placeholder:text-slate-400 focus:outline-none"
            style={{ minHeight: 36 }}
          />
          <Button onClick={submit} disabled={!value.trim() || busy} className="!size-9 !p-0 !rounded-xl" leftIcon={<ArrowUp className="size-4" />}>
            <span className="sr-only">发送</span>
          </Button>
        </div>
        <div className="mt-2 text-[11px] text-slate-400">
          AI 可能产生不准确内容，请注意信息甄别 · {runtimeConfig.useMockApi ? "Mock 模式" : "Live 模式"}
        </div>
      </div>
    </div>
  );
}
