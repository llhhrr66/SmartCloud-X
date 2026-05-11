import type { ChatMessage, Citation, FaqDocumentRef, ToolCallRecord } from '../../types/domain';
import { formatDateTime, toolStatusLabel } from '../../lib/format';
import { Badge } from '../Badge';

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  streamingContent: string;
  streamingAgent?: string;
  streamingCitations: Citation[];
  streamingToolCalls: ToolCallRecord[];
  streamingDocumentRefs: FaqDocumentRef[];
  onCitationSelect?: (citation: Citation) => void;
}

const roleLabels: Record<ChatMessage['role'], string> = {
  system: 'System',
  user: '用户',
  assistant: '助手',
  tool: 'Tool',
  agent: 'Agent'
};

function renderToolCalls(toolCalls?: ToolCallRecord[]): JSX.Element | null {
  if (!toolCalls?.length) {
    return null;
  }

  return (
    <div className="message__tool-calls">
      {toolCalls.map((tool) => (
        <div key={tool.toolCallId} className="message__tool-card">
          <div className="message__tool-header">
            <strong>{tool.toolName}</strong>
            <Badge tone={tool.status === 'success' ? 'success' : tool.status === 'running' ? 'info' : 'warning'}>
              {toolStatusLabel(tool.status)}
            </Badge>
          </div>
          {tool.dataPreview ? <pre>{JSON.stringify(tool.dataPreview, null, 2)}</pre> : null}
        </div>
      ))}
    </div>
  );
}

function renderDocumentRefs(documentRefs?: FaqDocumentRef[]): JSX.Element | null {
  if (!documentRefs?.length) {
    return null;
  }

  return (
    <div className="message__document-refs">
      <span className="message__document-refs-label">参考文档</span>
      {documentRefs.map((ref) => {
        const href = ref.url ?? `/#/document-viewer?docId=${encodeURIComponent(ref.docId)}&title=${encodeURIComponent(ref.title)}`;
        return (
          <a
            key={ref.docId}
            className="message__document-ref"
            href={href}
            target="_blank"
            rel="noreferrer"
          >
            <Badge tone="success">文档</Badge>
            <span>{ref.title}</span>
          </a>
        );
      })}
    </div>
  );
}

function renderCitations(citations?: Citation[], onCitationSelect?: (citation: Citation) => void): JSX.Element | null {
  if (!citations?.length) {
    return null;
  }

  return (
    <div className="message__citations">
      {citations.map((citation) => (
        <button
          key={citation.id}
          type="button"
          className="message__citation message__citation-button"
          onClick={() => onCitationSelect?.(citation)}
        >
          <Badge tone="info">引用</Badge>
          <span>{citation.title}</span>
        </button>
      ))}
    </div>
  );
}

export function MessageList({
  messages,
  isStreaming,
  streamingContent,
  streamingAgent,
  streamingCitations,
  streamingToolCalls,
  streamingDocumentRefs,
  onCitationSelect
}: MessageListProps): JSX.Element {
  const displayMessages = [...messages];

  if (isStreaming) {
    displayMessages.push({
      id: 'streaming',
      messageId: 'streaming',
      conversationId: messages.at(-1)?.conversationId ?? '',
      role: 'assistant',
      messageType: 'markdown',
      content: streamingContent || '正在整理答案，请稍候…',
      createdAt: new Date().toISOString(),
      agentName: streamingAgent,
      status: 'running',
      citations: streamingCitations,
      toolCalls: streamingToolCalls,
      documentRefs: streamingDocumentRefs
    });
  }

  if (!displayMessages.length) {
    return (
      <div className="card empty-state">
        <h3>从一个实际问题开始</h3>
        <p className="muted">可尝试账单查询、GPU 选型、ICP 咨询、营销海报或深度研究。</p>
      </div>
    );
  }

  return (
    <div className="message-list card">
      {displayMessages.map((message) => (
        <article key={message.id} className={`message message--${message.role}`}>
          <div className="message__meta">
            <div>
              <strong>{roleLabels[message.role]}</strong>
              {message.agentName ? <span className="muted"> · {message.agentName}</span> : null}
            </div>
            <span className="muted">{formatDateTime(message.createdAt)}</span>
          </div>
          <div className="message__bubble">
            <p>{message.content}</p>
            {message.status === 'running' ? <Badge tone="info">生成中</Badge> : null}
            {renderToolCalls(message.toolCalls)}
            {renderDocumentRefs(message.documentRefs)}
            {renderCitations(message.citations, onCitationSelect)}
          </div>
        </article>
      ))}
    </div>
  );
}
