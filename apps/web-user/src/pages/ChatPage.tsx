import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { citationService } from '../api/services/citations';
import { chatService } from '../api/services/chat';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { ChatComposer } from '../components/chat/ChatComposer';
import { MessageList } from '../components/chat/MessageList';
import { formatDateTime, sceneLabels, toolStatusLabel } from '../lib/format';
import { createRequestId } from '../lib/request-meta';
import { recordTelemetryEvent } from '../lib/telemetry';
import { buildConversationTitle, createId } from '../lib/utils';
import { classifyApiError, consumeSseStreamWithReconnect, isAbortError } from '../shared-sdk';
import {
  conversationStoreActions,
  createInitialStreamState,
  getConversationStoreState,
  getMessageStoreState,
  getSseStoreState,
  messageStoreActions,
  sseStoreActions,
  useConversationStore,
  useMessageStore,
  useSseStore
} from '../stores/chat';
import type { ChatCompletionRequest, Citation, CitationDetail, ConversationSummary, Scene } from '../types/domain';

const MAX_STREAM_RECONNECT_ATTEMPTS = 3;
const STREAM_RECONNECT_DELAY_MS = 1_200;

const sceneTicketCategoryMap: Record<Scene, 'technical_support' | 'billing' | 'order' | 'icp'> = {
  customer_service: 'technical_support',
  technical_support: 'technical_support',
  billing: 'billing',
  icp: 'icp',
  marketing: 'technical_support',
  research: 'technical_support'
};

const starterPrompts: Array<{ title: string; scene: Scene; prompt: string }> = [
  {
    title: '账单分析',
    scene: 'billing',
    prompt: '帮我查询最近三个月的云服务器账单，并总结费用最高的实例。'
  },
  {
    title: '技术咨询',
    scene: 'technical_support',
    prompt: '我准备部署一个 AI 推理服务，帮我推荐 GPU 机型和网络配置。'
  },
  {
    title: 'ICP备案',
    scene: 'icp',
    prompt: '我要提交 ICP 备案，需要准备哪些材料？未通过预检查时应该怎么补齐？'
  },
  {
    title: '营销推荐',
    scene: 'marketing',
    prompt: '请结合当前营销活动，帮我生成一段适合推广云服务器的活动文案。'
  }
];

function toErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function isConversationNotFoundError(error: unknown): boolean {
  return classifyApiError(error) === 'not_found' || (error instanceof Error && error.message.includes('会话不存在'));
}

export function ChatPage(): JSX.Element {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const { session } = useAuth();
  const abortRef = useRef<AbortController | null>(null);

  const conversationState = useConversationStore();
  const messageState = useMessageStore();
  const sseState = useSseStore();
  const emptyStreamState = useMemo(() => createInitialStreamState(), []);

  const [selectedScene, setSelectedScene] = useState<Scene>('customer_service');
  const [draft, setDraft] = useState('');
  const [isMutatingSession, setIsMutatingSession] = useState(false);
  const [retryingTurn, setRetryingTurn] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageNotice, setPageNotice] = useState<string | null>(null);
  const [missingConversationId, setMissingConversationId] = useState<string | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<CitationDetail | null>(null);
  const [selectedCitationId, setSelectedCitationId] = useState<string | null>(null);
  const [citationLoading, setCitationLoading] = useState(false);
  const [citationError, setCitationError] = useState<string | null>(null);

  const pendingConversationId = sseState.isPreparing || sseState.stream.isStreaming ? sseState.conversationId : null;
  const resolvedConversationId = conversationId ?? pendingConversationId ?? null;
  const activeConversation = useMemo(
    () => conversationState.items.find((item) => item.conversationId === resolvedConversationId),
    [conversationState.items, resolvedConversationId]
  );
  const messages = resolvedConversationId ? messageState.byConversationId[resolvedConversationId] ?? [] : [];
  const isCurrentConversationStream = Boolean(resolvedConversationId && sseState.conversationId === resolvedConversationId);
  const streamState = isCurrentConversationStream ? sseState.stream : emptyStreamState;
  const isConversationRouteNotFound = Boolean(conversationId && missingConversationId === conversationId);
  const loadingMessages = Boolean(
    resolvedConversationId &&
      messageState.loadingConversationId === resolvedConversationId &&
      !messageState.loadedConversationIds[resolvedConversationId]
  );
  const isPreparingResponse = sseState.isPreparing && !streamState.isStreaming;
  const isSendingMessage = isPreparingResponse || streamState.isStreaming;

  const latestUserMessage = useMemo(
    () => [...messages].reverse().find((item) => item.role === 'user'),
    [messages]
  );
  const latestRetriableMessage = useMemo(
    () => [...messages].reverse().find((item) => item.role === 'assistant' || item.role === 'user'),
    [messages]
  );

  const clearCitationState = useCallback(() => {
    setSelectedCitation(null);
    setSelectedCitationId(null);
    setCitationLoading(false);
    setCitationError(null);
  }, []);

  const loadSessions = useCallback(async (force = false) => {
    const snapshot = getConversationStoreState();
    if (!force && (snapshot.loaded || snapshot.loading)) {
      return snapshot.items;
    }

    conversationStoreActions.startLoading();
    try {
      const data = await chatService.listSessions({ page: 1, pageSize: 50 });
      const latestSnapshot = getConversationStoreState();
      const preservedConversation =
        resolvedConversationId && !data.items.some((item) => item.conversationId === resolvedConversationId)
          ? latestSnapshot.items.find((item) => item.conversationId === resolvedConversationId)
          : undefined;
      const nextItems = preservedConversation ? [preservedConversation, ...data.items] : data.items;
      conversationStoreActions.setSessions(nextItems);
      return nextItems;
    } catch (error) {
      const message = toErrorMessage(error, '加载会话列表失败');
      conversationStoreActions.setError(message);
      throw error;
    }
  }, [resolvedConversationId]);

  const ensureConversationDetail = useCallback(async (nextConversationId: string): Promise<ConversationSummary> => {
    const snapshot = getConversationStoreState();
    const existing = snapshot.items.find((item) => item.conversationId === nextConversationId);
    if (existing) {
      return existing;
    }

    const conversation = await chatService.getSession(nextConversationId);
    conversationStoreActions.upsertConversation(conversation);
    return conversation;
  }, []);

  const loadMessages = useCallback(async (nextConversationId: string, force = false) => {
    const snapshot = getMessageStoreState();
    if (
      !force &&
      (snapshot.loadedConversationIds[nextConversationId] || snapshot.loadingConversationId === nextConversationId)
    ) {
      return snapshot.byConversationId[nextConversationId] ?? [];
    }

    messageStoreActions.startLoading(nextConversationId);
    try {
      const items = await chatService.getMessages(nextConversationId);
      messageStoreActions.setConversationMessages(nextConversationId, items);
      return items;
    } catch (error) {
      const message = toErrorMessage(error, '加载会话消息失败');
      messageStoreActions.setError(message);
      throw error;
    }
  }, []);

  const refreshConversationState = useCallback(
    async (nextConversationId?: string) => {
      await loadSessions(true);

      const targetConversationId = nextConversationId ?? resolvedConversationId;
      if (targetConversationId) {
        await loadMessages(targetConversationId, true);
      }
    },
    [loadMessages, loadSessions, resolvedConversationId]
  );

  useEffect(() => {
    void loadSessions().catch((error) => {
      setPageError(toErrorMessage(error, '加载会话列表失败'));
    });
  }, [loadSessions]);

  useEffect(() => {
    if (activeConversation?.scene) {
      setSelectedScene(activeConversation.scene);
    }
  }, [activeConversation?.scene]);

  useEffect(() => {
    if (!conversationId) {
      setMissingConversationId(null);
      return;
    }

    let cancelled = false;
    setMissingConversationId(null);
    setPageError(null);

    void (async () => {
      try {
        await ensureConversationDetail(conversationId);
        await loadMessages(conversationId);
        if (!cancelled) {
          setMissingConversationId(null);
          messageStoreActions.clearError();
        }
      } catch (error) {
        if (cancelled) {
          return;
        }

        if (isConversationNotFoundError(error)) {
          setMissingConversationId(conversationId);
          setPageError(null);
          conversationStoreActions.removeConversation(conversationId);
          messageStoreActions.clearConversation(conversationId);
          messageStoreActions.clearError();
          return;
        }

        setPageError(toErrorMessage(error, '加载会话详情失败'));
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [conversationId, ensureConversationDetail, loadMessages]);

  useEffect(() => {
    setPageNotice(null);
    clearCitationState();
  }, [clearCitationState, conversationId]);

  const handleNewSession = useCallback(() => {
    abortRef.current?.abort();
    sseStoreActions.reset();
    navigate('/chat');
    setDraft('');
    setSelectedScene('customer_service');
    setPageError(null);
    setPageNotice(null);
    setMissingConversationId(null);
    clearCitationState();
  }, [clearCitationState, navigate]);

  const ensureConversation = useCallback(
    async (initialPrompt: string): Promise<ConversationSummary> => {
      if (activeConversation) {
        return activeConversation;
      }

      const created = await chatService.createSession({
        scene: selectedScene,
        title: buildConversationTitle(initialPrompt),
        initialContext: '由用户端聊天页创建的会话'
      });

      conversationStoreActions.upsertConversation(created);
      navigate(`/chat/${created.conversationId}`);
      return created;
    },
    [activeConversation, navigate, selectedScene]
  );

  const isConversationWritable = !isConversationRouteNotFound && (!activeConversation || activeConversation.status === 'active');
  const canEscalateToTicket = Boolean(
    !isConversationRouteNotFound &&
      (activeConversation || latestUserMessage || draft.trim() || streamState.actionRequired || streamState.error)
  );

  const handleSend = useCallback(async () => {
    if (!session || !draft.trim() || isSendingMessage || !isConversationWritable) {
      return;
    }

    const userInput = draft.trim();
    const requestMessageId = createId('msg');
    const streamTelemetryRequestId = createRequestId('stream');
    let targetConversationId: string | null = null;
    let streamStarted = false;
    let reconnectAttempts = 0;

    setPageError(null);
    setPageNotice(null);
    clearCitationState();
    sseStoreActions.prepare(requestMessageId);

    try {
      const conversation = await ensureConversation(userInput);
      targetConversationId = conversation.conversationId;
      streamStarted = true;

      sseStoreActions.start(
        targetConversationId,
        requestMessageId,
        conversation.currentAgent,
        MAX_STREAM_RECONNECT_ATTEMPTS
      );
      setDraft('');
      messageStoreActions.appendMessage(targetConversationId, {
        id: createId('m'),
        messageId: requestMessageId,
        conversationId: targetConversationId,
        role: 'user',
        messageType: 'text',
        content: userInput,
        createdAt: new Date().toISOString(),
        status: 'completed'
      });

      const streamRequest: ChatCompletionRequest = {
        conversationId: targetConversationId,
        messageId: requestMessageId,
        userInput,
        stream: true,
        scene: conversation.scene,
        attachments: [],
        context: {
          userId: session.user.userId,
          tenantId: session.user.tenantId,
          channel: 'web',
          locale: session.user.locale
        },
        options: {
          useRag: true,
          useTools: true,
          maxHistoryTurns: 20,
          agentHint: conversation.currentAgent
        }
      };

      recordTelemetryEvent({
        eventName: 'chat_stream_start',
        requestId: streamTelemetryRequestId,
        userId: session.user.userId,
        conversationId: targetConversationId,
        metadata: {
          scene: conversation.scene,
          messageId: requestMessageId
        },
        dedupeKey: `chat_stream_start:${requestMessageId}`
      });

      const controller = new AbortController();
      abortRef.current = controller;

      await consumeSseStreamWithReconnect({
        signal: controller.signal,
        connect: (signal) => chatService.streamCompletion(streamRequest, signal),
        consumeEvent: (event) => {
          sseStoreActions.applyEvent(event);
        },
        maxReconnectAttempts: MAX_STREAM_RECONNECT_ATTEMPTS,
        defaultDelayMs: STREAM_RECONNECT_DELAY_MS,
        maxDelayMs: STREAM_RECONNECT_DELAY_MS * MAX_STREAM_RECONNECT_ATTEMPTS * 4,
        shouldReconnectOnClose: () => {
          const latestStreamState = getSseStoreState().stream;
          return !controller.signal.aborted && latestStreamState.isStreaming;
        },
        onBeforeReconnect: ({ attempt, error }) => {
          reconnectAttempts = attempt;
          sseStoreActions.updateStream((previous) => ({
            ...createInitialStreamState(),
            isStreaming: true,
            reconnecting: true,
            reconnectAttempt: attempt,
            maxReconnectAttempts: MAX_STREAM_RECONNECT_ATTEMPTS,
            agent: previous.agent ?? conversation.currentAgent,
            traceId: previous.traceId,
            lastEventAt: previous.lastEventAt
          }));
        },
        buildDisconnectError: () =>
          new ApiError(
            `流式连接已中断，重连 ${MAX_STREAM_RECONNECT_ATTEMPTS} 次后仍未恢复`,
            502,
            'CHAT_STREAM_DISCONNECTED'
          )
      });

      const latestStreamState = getSseStoreState().stream;
      if (latestStreamState.error) {
        setPageError(latestStreamState.error);
        recordTelemetryEvent({
          eventName: 'chat_stream_error',
          requestId: streamTelemetryRequestId,
          userId: session.user.userId,
          conversationId: targetConversationId,
          errorCode: 'CHAT_STREAM_EVENT_ERROR',
          metadata: {
            message: latestStreamState.error,
            reconnectAttempts,
            messageId: requestMessageId
          }
        });
      } else {
        recordTelemetryEvent({
          eventName: 'chat_stream_end',
          requestId: streamTelemetryRequestId,
          userId: session.user.userId,
          conversationId: targetConversationId,
          metadata: {
            finishReason: latestStreamState.finishReason ?? 'completed',
            reconnectAttempts,
            messageId: requestMessageId
          },
          dedupeKey: `chat_stream_end:${requestMessageId}:${latestStreamState.finishReason ?? 'completed'}`
        });
      }

      await refreshConversationState(targetConversationId);
    } catch (error) {
      if (isAbortError(error)) {
        sseStoreActions.updateStream((previous) => ({
          ...previous,
          isStreaming: false,
          reconnecting: false,
          finishReason: 'cancelled',
          error: '本轮生成已手动停止。'
        }));
        if (targetConversationId) {
          recordTelemetryEvent({
            eventName: 'chat_stream_end',
            requestId: streamTelemetryRequestId,
            userId: session.user.userId,
            conversationId: targetConversationId,
            metadata: {
              finishReason: 'cancelled',
              messageId: requestMessageId,
              reconnectAttempts
            },
            dedupeKey: `chat_stream_end:${requestMessageId}:cancelled`
          });
        }
      } else {
        const message = toErrorMessage(error, '聊天请求失败');
        setPageError(message);

        if (streamStarted) {
          sseStoreActions.updateStream((previous) => ({
            ...previous,
            isStreaming: false,
            reconnecting: false,
            error: message
          }));
          if (targetConversationId) {
            recordTelemetryEvent({
              eventName: 'chat_stream_error',
              requestId: streamTelemetryRequestId,
              userId: session.user.userId,
              conversationId: targetConversationId,
              errorCode: error instanceof ApiError ? error.code ?? error.status : 'CHAT_STREAM_FAILED',
              metadata: {
                message,
                messageId: requestMessageId,
                reconnectAttempts
              }
            });
          }
        } else {
          sseStoreActions.reset();
        }
      }

      if (targetConversationId) {
        try {
          await refreshConversationState(targetConversationId);
        } catch {
          messageStoreActions.markConversationStale(targetConversationId);
        }
      }
    } finally {
      abortRef.current = null;
      sseStoreActions.finishPreparing();
    }
  }, [
    clearCitationState,
    draft,
    ensureConversation,
    isConversationWritable,
    isSendingMessage,
    refreshConversationState,
    session
  ]);

  const handleStop = useCallback(async () => {
    abortRef.current?.abort();

    const currentStreamState = getSseStoreState();
    if (currentStreamState.conversationId && currentStreamState.requestMessageId) {
      try {
        await chatService.cancelMessage(currentStreamState.conversationId, currentStreamState.requestMessageId);
      } catch {
        // best-effort cancel
      }
    }
  }, []);

  const handleRetryLatestTurn = useCallback(async () => {
    if (
      !activeConversation ||
      !latestRetriableMessage ||
      retryingTurn ||
      isSendingMessage ||
      !isConversationWritable
    ) {
      return;
    }

    setRetryingTurn(true);
    setPageError(null);
    setPageNotice(null);
    clearCitationState();

    try {
      const result = await chatService.retryMessage(activeConversation.conversationId, latestRetriableMessage.messageId);
      const currentTraceId = getSseStoreState().stream.traceId;
      sseStoreActions.replace(activeConversation.conversationId, result.messageId, {
        ...createInitialStreamState(),
        agent: result.agentName,
        traceId: currentTraceId,
        toolCalls: result.toolCalls ?? [],
        citations: result.citations ?? [],
        finishReason: result.finishReason,
        actionRequired: result.actionRequired,
        error: result.resolution === 'failed' ? result.answer ?? '重试失败' : undefined
      });
      setPageNotice('已重新生成上一轮回复，消息列表已刷新。');
      await refreshConversationState(activeConversation.conversationId);
    } catch (error) {
      setPageError(toErrorMessage(error, '重试上一轮失败'));
    } finally {
      setRetryingTurn(false);
    }
  }, [
    activeConversation,
    clearCitationState,
    isConversationWritable,
    isSendingMessage,
    latestRetriableMessage,
    refreshConversationState,
    retryingTurn
  ]);

  const handleArchive = useCallback(async () => {
    if (!activeConversation || isMutatingSession) {
      return;
    }

    setIsMutatingSession(true);
    setPageError(null);
    try {
      const updated = await chatService.archiveSession(activeConversation.conversationId);
      conversationStoreActions.upsertConversation(updated);
      setPageNotice('会话已归档，恢复后才可继续发送消息。');
    } catch (error) {
      setPageError(toErrorMessage(error, '归档会话失败'));
    } finally {
      setIsMutatingSession(false);
    }
  }, [activeConversation, isMutatingSession]);

  const handleRestore = useCallback(async () => {
    if (!activeConversation || isMutatingSession) {
      return;
    }

    setIsMutatingSession(true);
    setPageError(null);
    try {
      const updated = await chatService.restoreSession(activeConversation.conversationId);
      conversationStoreActions.upsertConversation(updated);
      setPageNotice('会话已恢复，可以继续发起对话。');
    } catch (error) {
      setPageError(toErrorMessage(error, '恢复会话失败'));
    } finally {
      setIsMutatingSession(false);
    }
  }, [activeConversation, isMutatingSession]);

  const handleDelete = useCallback(async () => {
    if (!activeConversation || isMutatingSession) {
      return;
    }

    const confirmed = window.confirm(`确认删除会话“${activeConversation.title}”吗？`);
    if (!confirmed) {
      return;
    }

    setIsMutatingSession(true);
    setPageError(null);
    try {
      await chatService.deleteSession(activeConversation.conversationId);
      conversationStoreActions.removeConversation(activeConversation.conversationId);
      messageStoreActions.clearConversation(activeConversation.conversationId);
      if (getSseStoreState().conversationId === activeConversation.conversationId) {
        sseStoreActions.reset();
      }
      navigate('/chat', { replace: true });
      setDraft('');
      clearCitationState();
      setPageNotice('会话已删除。');
    } catch (error) {
      setPageError(toErrorMessage(error, '删除会话失败'));
    } finally {
      setIsMutatingSession(false);
    }
  }, [activeConversation, clearCitationState, isMutatingSession, navigate]);

  const handleSelectCitation = useCallback(async (citation: Citation) => {
    setSelectedCitationId(citation.id);
    setCitationLoading(true);
    setCitationError(null);

    try {
      const detail = await citationService.getCitationDetail(citation.id, citation);
      setSelectedCitation(detail);
    } catch (error) {
      setSelectedCitation(null);
      setCitationError(toErrorMessage(error, '加载引用详情失败'));
    } finally {
      setCitationLoading(false);
    }
  }, []);

  const handleEscalateToTicket = useCallback(() => {
    const resolvedScene = activeConversation?.scene ?? selectedScene;
    const latestQuestion = latestUserMessage?.content?.trim() || draft.trim();
    const subjectPrefix = sceneLabels[resolvedScene];
    const title = activeConversation?.title ?? buildConversationTitle(latestQuestion || '聊天人工协助');
    const lines = [
      '请人工继续跟进以下聊天会话：',
      activeConversation?.conversationId ? `- conversation_id: ${activeConversation.conversationId}` : null,
      `- scene: ${subjectPrefix}`,
      `- current_agent: ${streamState.agent ?? activeConversation?.currentAgent ?? 'Orchestrator'}`,
      streamState.traceId ? `- trace_id: ${streamState.traceId}` : null,
      latestQuestion ? `- 用户诉求: ${latestQuestion}` : null,
      streamState.actionRequired ? `- action_required: ${streamState.actionRequired.message}` : null,
      streamState.error ? `- stream_error: ${streamState.error}` : null,
      '',
      '请人工补充处理进展，并在必要时回访用户。'
    ].filter(Boolean);

    const params = new URLSearchParams({
      subject: `${subjectPrefix}人工协助：${title}`.slice(0, 80),
      content: lines.join('\n'),
      category: sceneTicketCategoryMap[resolvedScene],
      priority: streamState.actionRequired?.type === 'manual_intervention' || streamState.error ? 'high' : 'medium',
      prefill_notice: '已从聊天页带入人工协助草稿，建议补充实例 ID、账单周期、截图或权限说明后再提交。'
    });

    navigate(`/tickets?${params.toString()}`);
  }, [
    activeConversation?.conversationId,
    activeConversation?.currentAgent,
    activeConversation?.scene,
    activeConversation?.title,
    draft,
    latestUserMessage?.content,
    navigate,
    selectedScene,
    streamState.actionRequired,
    streamState.agent,
    streamState.error,
    streamState.traceId
  ]);

  const visibleError = isConversationRouteNotFound
    ? pageError ?? conversationState.error
    : pageError ?? conversationState.error ?? messageState.error;

  return (
    <>
      <PageHeader
        eyebrow="Streaming Chat"
        title="聊天主链路"
        description="支持会话管理、SSE 流式展示、Agent / Tool / Citation 可视化，是用户端 baseline 的核心页面。"
        actions={
          <div className="page-header__actions">
            <Badge tone={isSendingMessage ? 'info' : 'neutral'}>
              {isPreparingResponse
                ? '准备请求'
                : streamState.reconnecting
                  ? `重连中 ${streamState.reconnectAttempt}/${streamState.maxReconnectAttempts}`
                : streamState.isStreaming
                  ? '生成中'
                  : streamState.finishReason
                    ? `finish=${streamState.finishReason}`
                    : '空闲'}
            </Badge>
            <button
              type="button"
              className="button button--ghost"
              onClick={() => void handleRetryLatestTurn()}
              disabled={!activeConversation || !latestRetriableMessage || retryingTurn || isSendingMessage || !isConversationWritable}
            >
              {retryingTurn ? '重试中...' : '重试上一轮'}
            </button>
            <button type="button" className="button button--primary" onClick={handleNewSession} disabled={isSendingMessage}>
              新建会话
            </button>
          </div>
        }
      />

      <div className="chat-layout">
        <aside className="card session-sidebar">
          <div className="session-sidebar__header">
            <div>
              <h3>会话列表</h3>
              <p className="muted">最近 50 条用户会话</p>
            </div>
            <button type="button" className="button button--ghost" onClick={handleNewSession} disabled={isSendingMessage}>
              清空当前草稿
            </button>
          </div>

          <div className="session-sidebar__list">
            {conversationState.loading && !conversationState.items.length ? (
              <p className="muted">正在同步会话列表...</p>
            ) : conversationState.items.length ? (
              conversationState.items.map((item) => (
                <button
                  key={item.conversationId}
                  type="button"
                  className={`session-sidebar__item${item.conversationId === resolvedConversationId ? ' session-sidebar__item--active' : ''}`}
                  onClick={() => navigate(`/chat/${item.conversationId}`)}
                >
                  <strong>{item.title}</strong>
                  <span>{sceneLabels[item.scene]}</span>
                  <span>{item.currentAgent}</span>
                  <span className="muted">{item.status === 'active' ? '进行中' : item.status === 'archived' ? '已归档' : item.status}</span>
                </button>
              ))
            ) : (
              <p className="muted">暂无会话，发送第一条消息后会自动创建。</p>
            )}
          </div>
        </aside>

        <section className="chat-main">
          <div className="card chat-main__header">
            <div>
              <h3>{isConversationRouteNotFound ? '会话不存在' : activeConversation?.title ?? '新会话（发送后自动创建）'}</h3>
              {isConversationRouteNotFound ? (
                <p className="muted">
                  未找到会话 <code className="mono">{conversationId}</code>。请返回会话历史重新选择，或直接发起一轮新对话。
                </p>
              ) : (
                <p className="muted">
                  当前场景：{sceneLabels[activeConversation?.scene ?? selectedScene]} · 当前 Agent：{streamState.agent ?? activeConversation?.currentAgent ?? 'Orchestrator'}
                </p>
              )}
              {activeConversation && !isConversationRouteNotFound ? (
                <p className="muted">
                  创建于 {formatDateTime(activeConversation.createdAt)} · 消息数 {activeConversation.messageCount}
                </p>
              ) : null}
            </div>
            <div className="chat-main__header-actions">
              {activeConversation ? (
                <>
                  <Badge tone={activeConversation.status === 'active' ? 'success' : 'warning'}>
                    {activeConversation.status === 'active' ? '可继续对话' : activeConversation.status === 'archived' ? '已归档' : activeConversation.status}
                  </Badge>
                  <Badge tone="info">更新于 {formatDateTime(activeConversation.updatedAt)}</Badge>
                </>
              ) : null}
            </div>
          </div>

          {pageNotice ? <div className="success-banner">{pageNotice}</div> : null}
          {visibleError ? <div className="error-banner">{visibleError}</div> : null}
          {streamState.reconnecting ? (
            <div className="warning-banner">
              流式连接已中断，正在进行第 {streamState.reconnectAttempt}/{streamState.maxReconnectAttempts} 次自动重连。
              {streamState.lastEventAt ? ` 最近事件时间：${formatDateTime(streamState.lastEventAt)}。` : ''}
            </div>
          ) : null}

          {isConversationRouteNotFound ? (
            <div className="card empty-state">
              <h3>未找到对应会话</h3>
              <p className="muted">
                该会话可能已被删除、归档后失效，或当前链接中的 `conversation_id` 不正确。
              </p>
              <div className="page-header__actions">
                <button type="button" className="button button--primary" onClick={handleNewSession}>
                  发起新对话
                </button>
                <button type="button" className="button button--ghost" onClick={() => navigate('/sessions')}>
                  返回会话历史
                </button>
              </div>
            </div>
          ) : (
            <>
              {!messages.length && !isSendingMessage ? (
                <div className="card starter-prompts">
                  <div className="starter-prompts__header">
                    <div>
                      <h3>常用提问模板</h3>
                      <p className="muted">先选择一个实际业务问题，系统会自动帮你创建会话并带入对应场景。</p>
                    </div>
                    <Badge tone="info">Spec 20.15.1</Badge>
                  </div>
                  <div className="starter-prompts__grid">
                    {starterPrompts.map((item) => (
                      <button
                        key={item.title}
                        type="button"
                        className="starter-prompt"
                        onClick={() => {
                          setSelectedScene(item.scene);
                          setDraft(item.prompt);
                        }}
                      >
                        <strong>{item.title}</strong>
                        <span>{item.prompt}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {activeConversation ? (
                <div className="card conversation-status-card">
                  <div className="stack stack--sm">
                    <strong>会话操作</strong>
                    <p className="muted">
                      支持归档、恢复与删除；归档后的会话只读，恢复后才能继续发起流式对话。
                    </p>
                  </div>
                  <div className="conversation-status-card__actions">
                    {activeConversation.status === 'active' ? (
                      <button type="button" className="button button--ghost" onClick={handleArchive} disabled={isMutatingSession || isSendingMessage}>
                        {isMutatingSession ? '处理中...' : '归档会话'}
                      </button>
                    ) : activeConversation.status === 'archived' ? (
                      <button type="button" className="button button--primary" onClick={handleRestore} disabled={isMutatingSession || isSendingMessage}>
                        {isMutatingSession ? '处理中...' : '恢复会话'}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={() => void handleRetryLatestTurn()}
                      disabled={!latestRetriableMessage || retryingTurn || isMutatingSession || isSendingMessage || !isConversationWritable}
                    >
                      {retryingTurn ? '重试中...' : '重试上一轮'}
                    </button>
                    <button type="button" className="button button--danger" onClick={handleDelete} disabled={isMutatingSession || isSendingMessage}>
                      删除会话
                    </button>
                  </div>
                </div>
              ) : null}

              {!isConversationWritable ? (
                <div className="card empty-state">
                  <h3>当前会话为只读状态</h3>
                  <p className="muted">
                    {activeConversation?.status === 'archived'
                      ? '会话已归档，请先恢复后再继续对话。'
                      : '当前会话状态不允许继续发送消息，请新建会话。'}
                  </p>
                </div>
              ) : null}

              {loadingMessages ? (
                <div className="card empty-state">
                  <p className="muted">正在加载消息...</p>
                </div>
              ) : (
                <MessageList
                  messages={messages}
                  isStreaming={streamState.isStreaming}
                  streamingContent={streamState.partialContent}
                  streamingAgent={streamState.agent}
                  streamingCitations={streamState.citations}
                  streamingToolCalls={streamState.toolCalls}
                  streamingDocumentRefs={streamState.documentRefs}
                  onCitationSelect={handleSelectCitation}
                />
              )}

              <ChatComposer
                value={draft}
                scene={activeConversation?.scene ?? selectedScene}
                sceneLocked={Boolean(activeConversation)}
                disabled={!draft.trim() || !session || !isConversationWritable || isSendingMessage}
                isSubmitting={isPreparingResponse}
                isStreaming={streamState.isStreaming}
                onChange={setDraft}
                onSceneChange={setSelectedScene}
                onSend={() => void handleSend()}
                onStop={() => void handleStop()}
              />
            </>
          )}
        </section>

        <aside className="chat-activity stack">
          <div className="card stack">
            <h3>流状态</h3>
            <div className="info-pair"><span>Trace ID</span><code className="mono">{streamState.traceId ?? '--'}</code></div>
            <div className="info-pair"><span>当前 Agent</span><span>{streamState.agent ?? activeConversation?.currentAgent ?? 'Orchestrator'}</span></div>
            <div className="info-pair"><span>Finish Reason</span><span>{streamState.finishReason ?? '--'}</span></div>
            <div className="info-pair"><span>重连状态</span><span>{streamState.reconnecting ? `${streamState.reconnectAttempt}/${streamState.maxReconnectAttempts}` : '未重连'}</span></div>
            <div className="info-pair"><span>最近事件</span><span>{streamState.lastEventAt ? formatDateTime(streamState.lastEventAt) : '--'}</span></div>
            <div className="info-pair"><span>会话状态</span><span>{activeConversation?.status ?? 'draft'}</span></div>
            {streamState.error ? <div className="error-banner">{streamState.error}</div> : null}
          </div>

          <div className="card stack">
            <h3>Agent 路由</h3>
            {streamState.routes.length ? (
              <ol className="timeline">
                {streamState.routes.map((item, index) => (
                  <li key={`${item.fromAgent}-${item.toAgent}-${index}`}>
                    <strong>
                      {item.fromAgent} → {item.toAgent}
                    </strong>
                    <p className="muted">{item.reason}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">如发生 handoff，会在这里显示路由原因。</p>
            )}
          </div>

          <div className="card stack">
            <div className="session-sidebar__header">
              <div>
                <h3>人工协助</h3>
                <p className="muted">需要人工继续跟进时，可一键带入当前会话上下文创建工单。</p>
              </div>
              <Badge tone={streamState.actionRequired ? (streamState.actionRequired.type === 'permission' ? 'warning' : 'info') : streamState.error ? 'warning' : 'neutral'}>
                {streamState.actionRequired ? streamState.actionRequired.type : streamState.error ? 'error' : '可选'}
              </Badge>
            </div>
            <p className="muted">
              {streamState.actionRequired?.message ??
                (streamState.error
                  ? '当前流式对话出现异常，建议将 trace / 会话上下文带入工单中心继续处理。'
                  : '如涉及线下排查、权限确认、材料补齐或跨团队协同，可转入人工工单流程。')}
            </p>
            {streamState.actionRequired ? <code className="mono">{String(streamState.actionRequired.code)}</code> : null}
            <div className="conversation-status-card__actions">
              <button type="button" className="button button--primary" onClick={handleEscalateToTicket} disabled={!canEscalateToTicket}>
                创建协助工单
              </button>
              <button type="button" className="button button--ghost" onClick={() => navigate('/service-desk')}>
                打开服务台
              </button>
            </div>
          </div>

          <div className="card stack">
            <h3>推理步骤</h3>
            {streamState.reasoning.length ? (
              <ol className="timeline">
                {streamState.reasoning.map((item) => (
                  <li key={`${item.agent}-${item.step}`}>
                    <strong>{item.agent}</strong>
                    <p className="muted">{item.summary}</p>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">发送消息后展示 reasoning 事件。</p>
            )}
          </div>

          <div className="card stack">
            <h3>工具调用</h3>
            {streamState.toolCalls.length ? (
              streamState.toolCalls.map((tool) => (
                <div key={tool.toolCallId} className="tool-row">
                  <div>
                    <strong>{tool.toolName}</strong>
                    <p className="muted">{tool.toolCallId}</p>
                  </div>
                  <Badge tone={tool.status === 'success' ? 'success' : tool.status === 'running' ? 'info' : 'warning'}>
                    {toolStatusLabel(tool.status)}
                  </Badge>
                </div>
              ))
            ) : (
              <p className="muted">暂无 tool_call / tool_result 事件。</p>
            )}
          </div>

          <div className="card stack">
            <h3>检索与引用</h3>
            {streamState.retrievals.length ? (
              streamState.retrievals.map((retrieval) => (
                <div key={retrieval.query} className="stack stack--sm">
                  <strong>{retrieval.query}</strong>
                  {retrieval.sources.map((source) => (
                    <div key={`${source.docId}-${source.chunkId}`} className="citation-row">
                      <span>{source.title}</span>
                      <Badge tone="info">score {source.score.toFixed(2)}</Badge>
                    </div>
                  ))}
                </div>
              ))
            ) : (
              <p className="muted">未触发 retrieval 事件。</p>
            )}
            {streamState.citations.length ? (
              <div className="stack stack--sm">
                {streamState.citations.map((citation) => (
                  <button
                    key={citation.id}
                    type="button"
                    className={`citation-row citation-row--button${selectedCitationId === citation.id ? ' citation-row--active' : ''}`}
                    onClick={() => void handleSelectCitation(citation)}
                  >
                    <span>{citation.title}</span>
                    <Badge tone="neutral">{citation.docId}</Badge>
                  </button>
                ))}
              </div>
            ) : null}
          </div>

          <div className="card stack">
            <div className="session-sidebar__header">
              <div>
                <h3>引用详情</h3>
                <p className="muted">点击消息或右侧引用卡片后查看知识片段与文档定位。</p>
              </div>
              {selectedCitation ? (
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => {
                    setSelectedCitation(null);
                    setSelectedCitationId(null);
                    setCitationError(null);
                  }}
                >
                  关闭
                </button>
              ) : null}
            </div>
            {citationLoading ? <p className="muted">正在加载引用详情...</p> : null}
            {citationError ? <div className="error-banner">{citationError}</div> : null}
            {selectedCitation ? (
              <div className="stack stack--sm citation-detail">
                <Badge tone="info">{selectedCitation.sourceType}</Badge>
                <strong>{selectedCitation.title}</strong>
                <p className="muted">{selectedCitation.snippet}</p>
                <div className="info-pair">
                  <span>Doc</span>
                  <code className="mono">{selectedCitation.docId || '--'}</code>
                </div>
                <div className="info-pair">
                  <span>Chunk</span>
                  <code className="mono">{selectedCitation.chunkId || '--'}</code>
                </div>
                <div className="info-pair">
                  <span>Version</span>
                  <span>{selectedCitation.versionNo ?? '--'}</span>
                </div>
                {selectedCitation.url ? (
                  <a className="quick-link citation-detail__link" href={selectedCitation.url} target="_blank" rel="noreferrer">
                    <strong>打开来源链接</strong>
                    <span>{selectedCitation.url}</span>
                  </a>
                ) : null}
              </div>
            ) : (
              <p className="muted">尚未选择引用。发送账单、技术支持或研究类问题后即可查看详情。</p>
            )}
          </div>
        </aside>
      </div>
    </>
  );
}
