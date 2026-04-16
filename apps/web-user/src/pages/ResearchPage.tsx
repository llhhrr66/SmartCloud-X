import { useCallback, useEffect, useState } from 'react';
import { researchService } from '../api/services/research';
import { fileService } from '../api/services/files';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { formatDateTime } from '../lib/format';
import { hasPermission } from '../lib/permissions';
import type { CreateResearchTaskRequest, FileRecord, ResearchTask } from '../types/domain';

const initialForm: CreateResearchTaskRequest = {
  topic: 'LangGraph vs CrewAI vs AutoGen',
  scope: '面向生产客服编排的工程能力对比',
  depth: 'standard',
  outputFormat: 'markdown',
  referenceUrls: []
};

export function ResearchPage(): JSX.Element {
  const { isMock, session } = useAuth();
  const [tasks, setTasks] = useState<ResearchTask[]>([]);
  const [form, setForm] = useState<CreateResearchTaskRequest>(initialForm);
  const [referenceInput, setReferenceInput] = useState('https://docs.langchain.com/oss/python/langgraph/overview');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [reportFile, setReportFile] = useState<FileRecord | null>(null);
  const [selectedReportTaskId, setSelectedReportTaskId] = useState<string | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const canCreateResearch = hasPermission(session, 'user:research.write');

  const loadTasks = useCallback(async () => {
    setPageError(null);
    const data = await researchService.listTasks();
    setTasks(data);
  }, []);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const data = await researchService.listTasks();
        if (mounted) {
          setTasks(data);
        }
      } catch (error) {
        if (mounted) {
          setPageError(error instanceof Error ? error.message : '加载研究任务失败');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (isMock || !tasks.some((task) => task.status === 'queued' || task.status === 'running')) {
      return;
    }

    const timer = window.setInterval(() => {
      void loadTasks().catch(() => undefined);
    }, 5000);

    return () => {
      window.clearInterval(timer);
    };
  }, [isMock, loadTasks, tasks]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canCreateResearch) {
      setPageError('当前账号仅开通研究任务只读能力，暂不可创建新任务。');
      return;
    }

    const normalizedTopic = form.topic.trim().toLowerCase();
    const duplicateInFlight = tasks.some(
      (task) =>
        ['queued', 'running'].includes(task.status) && task.topic.trim().toLowerCase() === normalizedTopic
    );

    if (duplicateInFlight) {
      setPageError('同一主题已有进行中的研究任务，请等待当前任务完成后再重复提交。');
      return;
    }

    setSubmitting(true);
    setPageError(null);

    try {
      const task = await researchService.createTask({
        ...form,
        referenceUrls: referenceInput
          .split(/\n+/)
          .map((item) => item.trim())
          .filter(Boolean)
      });

      setTasks((previous) => [task, ...previous]);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '创建研究任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePreviewReport = async (task: ResearchTask) => {
    if (!task.reportFileId) {
      return;
    }

    setSelectedReportTaskId(task.taskId);
    setReportLoading(true);
    setReportError(null);

    try {
      const file = await fileService.getFile(task.reportFileId);
      setReportFile(file);
    } catch (error) {
      setReportFile(null);
      setReportError(error instanceof Error ? error.message : '加载报告文件失败');
    } finally {
      setReportLoading(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Deep Research"
        title="研究中心"
        description="用于创建研究任务、追踪状态，并在报告完成后预览导出文件信息。"
        actions={!isMock ? <Badge tone="info">Live 历史列表优先</Badge> : undefined}
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}
      {!canCreateResearch ? <div className="warning-banner">当前账号缺少 `user:research.write`，可查看历史任务，但不能创建新研究任务。</div> : null}

      <div className="grid grid--2">
        <form className="card stack" onSubmit={handleSubmit}>
          <h3>创建研究任务</h3>
          <label className="field">
            <span>主题</span>
            <input value={form.topic} onChange={(event) => setForm((previous) => ({ ...previous, topic: event.target.value }))} />
          </label>
          <label className="field">
            <span>范围</span>
            <textarea value={form.scope} onChange={(event) => setForm((previous) => ({ ...previous, scope: event.target.value }))} rows={4} />
          </label>
          <div className="grid grid--2">
            <label className="field field--compact">
              <span>深度</span>
              <select value={form.depth} onChange={(event) => setForm((previous) => ({ ...previous, depth: event.target.value as CreateResearchTaskRequest['depth'] }))}>
                <option value="lite">Lite</option>
                <option value="standard">Standard</option>
                <option value="deep">Deep</option>
              </select>
            </label>
            <label className="field field--compact">
              <span>输出格式</span>
              <select value={form.outputFormat} onChange={(event) => setForm((previous) => ({ ...previous, outputFormat: event.target.value as CreateResearchTaskRequest['outputFormat'] }))}>
                <option value="markdown">Markdown</option>
                <option value="pdf">PDF</option>
              </select>
            </label>
          </div>
          <label className="field">
            <span>参考链接（每行一个）</span>
            <textarea value={referenceInput} onChange={(event) => setReferenceInput(event.target.value)} rows={4} />
          </label>
          <button type="submit" className="button button--primary" disabled={submitting || !canCreateResearch}>
            {!canCreateResearch ? '缺少写权限' : submitting ? '创建中...' : '创建研究任务'}
          </button>
        </form>

        <div className="card stack">
          <h3>任务历史</h3>
          {loading ? (
            <p className="muted">正在加载研究任务...</p>
          ) : tasks.length ? (
            tasks.map((task) => (
              <div key={task.taskId} className="task-card">
                <div className="task-card__header">
                  <div>
                    <strong>{task.topic}</strong>
                    <p className="muted">{task.scope}</p>
                  </div>
                  <span>{task.status}</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-bar__value" style={{ width: `${task.progress}%` }} />
                </div>
                <p className="muted">{task.summary}</p>
                <div className="task-card__footer">
                  <span>更新时间：{formatDateTime(task.updatedAt)}</span>
                  <span>文件：{task.reportFileId ?? '待生成'}</span>
                </div>
                <div className="conversation-status-card__actions">
                  {task.reportFileId ? (
                    <button
                      type="button"
                      className="button button--ghost"
                      onClick={() => void handlePreviewReport(task)}
                      disabled={reportLoading && selectedReportTaskId === task.taskId}
                    >
                      {reportLoading && selectedReportTaskId === task.taskId ? '加载中...' : '查看报告文件'}
                    </button>
                  ) : null}
                </div>
              </div>
            ))
          ) : (
            <p className="muted">
              {isMock
                ? '暂无研究任务，先创建一条任务试试。'
                : '暂无研究任务。页面会优先读取后端历史列表，必要时才回补当前浏览器最近跟踪的任务详情。'}
            </p>
          )}
        </div>
      </div>

      <div className="card stack">
        <div className="session-sidebar__header">
          <div>
            <h3>报告预览</h3>
            <p className="muted">
              完成态任务可通过 <code className="mono">/api/v1/files/{'{file_id}'}</code> 获取下载信息。
            </p>
          </div>
          {selectedReportTaskId ? <Badge tone="info">{selectedReportTaskId}</Badge> : null}
        </div>
        {reportLoading ? <p className="muted">正在加载报告文件...</p> : null}
        {reportError ? <div className="error-banner">{reportError}</div> : null}
        {reportFile ? (
          <div className="stack stack--sm">
            <div className="info-pair">
              <span>文件名</span>
              <strong>{reportFile.fileName}</strong>
            </div>
            <div className="info-pair">
              <span>文件 ID</span>
              <code className="mono">{reportFile.fileId}</code>
            </div>
            <div className="info-pair">
              <span>MIME</span>
              <span>{reportFile.mimeType}</span>
            </div>
            <div className="info-pair">
              <span>大小</span>
              <span>{reportFile.size} bytes</span>
            </div>
            <div className="info-pair">
              <span>状态</span>
              <span>{reportFile.status ?? 'ready'}</span>
            </div>
            {reportFile.downloadUrl ? (
              <a className="quick-link" href={reportFile.downloadUrl} target="_blank" rel="noreferrer">
                <strong>打开下载链接</strong>
                <span>{reportFile.downloadUrl}</span>
              </a>
            ) : null}
          </div>
        ) : (
          <p className="muted">选择一条已生成报告文件的任务，即可在这里查看导出信息。</p>
        )}
      </div>
    </>
  );
}
