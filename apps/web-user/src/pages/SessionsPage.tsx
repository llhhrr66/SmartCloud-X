import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { chatService } from '../api/services/chat';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { conversationStatusLabel, formatDateTime, sceneLabels } from '../lib/format';
import { conversationStoreActions, messageStoreActions } from '../stores/chat';
import type { ConversationStatus, ConversationSummary, Scene } from '../types/domain';

export function SessionsPage(): JSX.Element {
  const [sessions, setSessions] = useState<ConversationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyConversationId, setBusyConversationId] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');
  const [scene, setScene] = useState<Scene | ''>('');
  const [status, setStatus] = useState<ConversationStatus | ''>('');

  const loadSessions = async () => {
    setLoading(true);
    setPageError(null);
    try {
      const data = await chatService.listSessions({
        page: 1,
        pageSize: 50,
        keyword: keyword || undefined,
        scene: scene || undefined,
        status: status || undefined
      });
      setSessions(data.items);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '加载会话列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadSessions();
  }, [keyword, scene, status]);

  const handleRename = async (session: ConversationSummary) => {
    const nextTitle = window.prompt('请输入新的会话标题', session.title);
    if (!nextTitle?.trim()) {
      return;
    }

    setPageError(null);
    try {
      const updated = await chatService.renameSession(session.conversationId, nextTitle.trim());
      conversationStoreActions.upsertConversation(updated);
      await loadSessions();
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '重命名会话失败');
    }
  };

  const handleArchive = async (session: ConversationSummary) => {
    setBusyConversationId(session.conversationId);
    setPageError(null);
    try {
      const updated = await chatService.archiveSession(session.conversationId);
      conversationStoreActions.upsertConversation(updated);
      await loadSessions();
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '归档会话失败');
    } finally {
      setBusyConversationId(null);
    }
  };

  const handleRestore = async (session: ConversationSummary) => {
    setBusyConversationId(session.conversationId);
    setPageError(null);
    try {
      const updated = await chatService.restoreSession(session.conversationId);
      conversationStoreActions.upsertConversation(updated);
      await loadSessions();
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '恢复会话失败');
    } finally {
      setBusyConversationId(null);
    }
  };

  const handleDelete = async (session: ConversationSummary) => {
    const confirmed = window.confirm(`确认删除会话“${session.title}”吗？`);
    if (!confirmed) {
      return;
    }

    setBusyConversationId(session.conversationId);
    setPageError(null);
    try {
      await chatService.deleteSession(session.conversationId);
      conversationStoreActions.removeConversation(session.conversationId);
      messageStoreActions.clearConversation(session.conversationId);
      await loadSessions();
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '删除会话失败');
    } finally {
      setBusyConversationId(null);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Conversation History"
        title="会话历史"
        description="筛选用户历史会话，作为聊天主链路的上下文入口。"
        actions={
          <Link className="button button--primary" to="/chat">
            新建会话
          </Link>
        }
      />

      <div className="card filters filters--inline">
        <label className="field field--compact">
          <span>关键词</span>
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索标题或摘要" />
        </label>
        <label className="field field--compact">
          <span>场景</span>
          <select value={scene} onChange={(event) => setScene(event.target.value as Scene | '')}>
            <option value="">全部</option>
            {Object.entries(sceneLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="field field--compact">
          <span>状态</span>
          <select value={status} onChange={(event) => setStatus(event.target.value as ConversationStatus | '')}>
            <option value="">全部</option>
            <option value="active">进行中</option>
            <option value="archived">已归档</option>
            <option value="closed">已关闭</option>
            <option value="expired">已过期</option>
          </select>
        </label>
      </div>

      <div className="stack">
        {pageError ? <div className="error-banner">{pageError}</div> : null}
        {loading ? (
          <div className="card empty-state">
            <p className="muted">正在加载会话列表...</p>
          </div>
        ) : sessions.length ? (
          sessions.map((item) => (
            <div key={item.conversationId} className="card session-card">
              <div className="session-card__header">
                <div>
                  <h3>{item.title}</h3>
                  <p className="muted">{item.summary || '暂无摘要'}</p>
                </div>
                <div className="session-card__badges">
                  <Badge tone="info">{sceneLabels[item.scene]}</Badge>
                  <Badge tone={item.status === 'active' ? 'success' : 'neutral'}>{conversationStatusLabel(item.status)}</Badge>
                </div>
              </div>
              <div className="session-card__meta">
                <span>创建时间：{formatDateTime(item.createdAt)}</span>
                <span>当前 Agent：{item.currentAgent}</span>
                <span>消息数：{item.messageCount}</span>
                <span>更新时间：{formatDateTime(item.updatedAt)}</span>
              </div>
              <div className="session-card__actions">
                <Link className="button button--primary" to={`/chat/${item.conversationId}`}>
                  {item.status === 'active' ? '继续对话' : '查看详情'}
                </Link>
                <button type="button" className="button button--ghost" onClick={() => handleRename(item)}>
                  重命名
                </button>
                {item.status === 'active' ? (
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => handleArchive(item)}
                    disabled={busyConversationId === item.conversationId}
                  >
                    归档
                  </button>
                ) : item.status === 'archived' ? (
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => handleRestore(item)}
                    disabled={busyConversationId === item.conversationId}
                  >
                    恢复
                  </button>
                ) : null}
                <button
                  type="button"
                  className="button button--danger"
                  onClick={() => handleDelete(item)}
                  disabled={busyConversationId === item.conversationId}
                >
                  删除
                </button>
              </div>
            </div>
          ))
        ) : (
          <div className="card empty-state">
            <h3>暂无匹配会话</h3>
            <p className="muted">调整筛选条件，或直接新建一轮对话。</p>
          </div>
        )}
      </div>
    </>
  );
}
