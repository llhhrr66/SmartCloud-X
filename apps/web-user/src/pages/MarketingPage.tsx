import { useCallback, useEffect, useMemo, useState } from 'react';
import { marketingService } from '../api/services/marketing';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { formatDateTime } from '../lib/format';
import { hasPermission } from '../lib/permissions';
import type {
  CreatePosterTaskRequest,
  MarketingCampaign,
  MarketingCopyRequest,
  MarketingCopyResult,
  PosterTask
} from '../types/domain';

const initialCopyForm: MarketingCopyRequest = {
  campaignId: '',
  topic: '大模型上云加速方案',
  audience: '企业技术负责人',
  tone: 'professional',
  keywords: ['稳定算力', '弹性扩容', '专属支持']
};

const POSTER_POLL_INTERVAL_MS = 3000;
const POSTER_POLL_TIMEOUT_MS = 10 * 60 * 1000;

function isPollingCandidate(task: PosterTask): boolean {
  return task.status === 'queued' || task.status === 'running';
}

function hasPollingTimedOut(task: PosterTask): boolean {
  return isPollingCandidate(task) && Date.now() - new Date(task.createdAt).getTime() >= POSTER_POLL_TIMEOUT_MS;
}

function buildPollingNotice(tasks: PosterTask[]): string | null {
  if (!tasks.some(hasPollingTimedOut)) {
    return null;
  }

  return '部分海报任务已自动轮询超过 10 分钟，已停止后台刷新，请稍后手动查看。';
}

export function MarketingPage(): JSX.Element {
  const { isMock, session } = useAuth();
  const [campaigns, setCampaigns] = useState<MarketingCampaign[]>([]);
  const [tasks, setTasks] = useState<PosterTask[]>([]);
  const [copyForm, setCopyForm] = useState<MarketingCopyRequest>(initialCopyForm);
  const [keywordInput, setKeywordInput] = useState(initialCopyForm.keywords.join('\n'));
  const [copyResult, setCopyResult] = useState<MarketingCopyResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshingTasks, setRefreshingTasks] = useState(false);
  const [copySubmitting, setCopySubmitting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [pageNotice, setPageNotice] = useState<string | null>(null);
  const [pollingNotice, setPollingNotice] = useState<string | null>(null);
  const [form, setForm] = useState<CreatePosterTaskRequest>({
    campaignId: '',
    theme: '工业级上云活动',
    slogan: '部署大模型，从稳定算力开始',
    size: '1024x1536'
  });
  const canWriteMarketing = hasPermission(session, 'user:marketing.write');

  const refreshPosterTasks = useCallback(async (silent = false) => {
    if (!silent) {
      setRefreshingTasks(true);
    }

    try {
      const taskData = await marketingService.listPosterTasks();
      setTasks(taskData);
      if (!silent) {
        setPageError(null);
      }
      setPollingNotice(buildPollingNotice(taskData));
      return taskData;
    } catch (error) {
      const message = error instanceof Error ? error.message : '刷新海报任务失败';
      if (!silent) {
        setPageError(message);
      } else {
        setPollingNotice('海报任务自动刷新失败，请稍后手动刷新。');
      }
      throw error;
    } finally {
      if (!silent) {
        setRefreshingTasks(false);
      }
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      const [campaignsResult, tasksResult] = await Promise.allSettled([
          marketingService.listCampaigns(),
          marketingService.listPosterTasks()
        ]);

      if (!mounted) {
        return;
      }

      const campaignData = campaignsResult.status === 'fulfilled' ? campaignsResult.value : [];
      const taskData = tasksResult.status === 'fulfilled' ? tasksResult.value : [];
      const failureLabels: string[] = [];

      if (campaignsResult.status === 'rejected') {
        failureLabels.push('活动列表');
      }
      if (tasksResult.status === 'rejected') {
        failureLabels.push('海报任务历史');
      }

      setCampaigns(campaignData);
      setTasks(taskData);
      setPollingNotice(buildPollingNotice(taskData));
      setForm((previous) => ({
        ...previous,
        campaignId: previous.campaignId || campaignData[0]?.campaignId || ''
      }));
      setCopyForm((previous) => ({
        ...previous,
        campaignId: previous.campaignId || campaignData[0]?.campaignId || ''
      }));

      if (failureLabels.length === 2) {
        setPageError('加载营销数据失败');
        setPageNotice(null);
      } else {
        setPageError(null);
        setPageNotice(
          failureLabels.length ? `部分营销数据暂不可用：${failureLabels.join('、')}。页面已展示可成功加载的分区。` : null
        );
      }

      setLoading(false);
    };

    void load();

    return () => {
      mounted = false;
    };
  }, []);

  const hasActivePollingTask = tasks.some((task) => isPollingCandidate(task) && !hasPollingTimedOut(task));

  useEffect(() => {
    if (isMock || !hasActivePollingTask) {
      return;
    }

    const timer = window.setInterval(() => {
      void refreshPosterTasks(true).catch(() => undefined);
    }, POSTER_POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(timer);
    };
  }, [hasActivePollingTask, isMock, refreshPosterTasks]);

  const selectedCampaign = useMemo(
    () => campaigns.find((item) => item.campaignId === form.campaignId),
    [campaigns, form.campaignId]
  );
  const selectedCopyCampaign = useMemo(
    () => campaigns.find((item) => item.campaignId === copyForm.campaignId),
    [campaigns, copyForm.campaignId]
  );

  const handleCopySubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWriteMarketing) {
      setPageError('当前账号仅开通营销只读能力，暂不可生成营销文案。');
      return;
    }

    setCopySubmitting(true);
    setPageError(null);

    try {
      const result = await marketingService.generateCopy({
        ...copyForm,
        keywords: keywordInput
          .split(/\n+/)
          .map((item) => item.trim())
          .filter(Boolean)
      });
      setCopyResult(result);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '生成营销文案失败');
    } finally {
      setCopySubmitting(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWriteMarketing) {
      setPageError('当前账号仅开通营销只读能力，暂不可创建海报任务。');
      return;
    }

    setSubmitting(true);
    setPageError(null);

    try {
      const task = await marketingService.createPosterTask(form);
      setTasks((previous) => [task, ...previous]);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '创建海报任务失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Marketing Hub"
        title="营销中心"
        description="展示营销活动、文案生成器与海报任务列表，对齐 Ops_Marketing_Agent 的用户侧工作台。"
        actions={
          <div className="page-header__actions">
            {!isMock ? <Badge tone="info">Live 历史列表优先</Badge> : null}
            <button
              type="button"
              className="button button--ghost"
              onClick={() => void refreshPosterTasks()}
              disabled={loading || refreshingTasks}
            >
              {refreshingTasks ? '刷新中...' : '刷新海报任务'}
            </button>
          </div>
        }
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}
      {!pageError && pageNotice ? <div className="error-banner">{pageNotice}</div> : null}
      {!pageError && pollingNotice ? <div className="error-banner">{pollingNotice}</div> : null}
      {!canWriteMarketing ? (
        <div className="warning-banner">当前账号缺少 `user:marketing.write`，可查看活动与任务历史，但不能生成文案或创建海报任务。</div>
      ) : null}

      <div className="grid grid--2">
        <div className="card stack">
          <h3>活动列表</h3>
          {loading ? (
            <p className="muted">正在加载营销活动...</p>
          ) : campaigns.length ? (
            campaigns.map((campaign) => (
              <div key={campaign.campaignId} className="campaign-card">
                <div className="campaign-card__header">
                  <strong>{campaign.name}</strong>
                  <span>{campaign.status}</span>
                </div>
                <p className="muted">{campaign.productType}</p>
                <div className="campaign-card__tags">
                  {campaign.highlights.map((item) => (
                    <span key={item} className="tag">
                      {item}
                    </span>
                  ))}
                </div>
                <p className="muted">有效期至：{formatDateTime(campaign.endAt)}</p>
              </div>
            ))
          ) : (
            <p className="muted">暂无营销活动。</p>
          )}
        </div>

        <form className="card stack" onSubmit={handleCopySubmit}>
          <h3>营销文案生成器</h3>
          <label className="field field--compact">
            <span>活动</span>
            <select
              value={copyForm.campaignId}
              onChange={(event) => setCopyForm((previous) => ({ ...previous, campaignId: event.target.value }))}
            >
              {campaigns.map((campaign) => (
                <option key={campaign.campaignId} value={campaign.campaignId}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>主题</span>
            <input value={copyForm.topic} onChange={(event) => setCopyForm((previous) => ({ ...previous, topic: event.target.value }))} />
          </label>
          <label className="field">
            <span>目标受众</span>
            <input
              value={copyForm.audience}
              onChange={(event) => setCopyForm((previous) => ({ ...previous, audience: event.target.value }))}
            />
          </label>
          <label className="field field--compact">
            <span>语气风格</span>
            <select
              value={copyForm.tone}
              onChange={(event) =>
                setCopyForm((previous) => ({
                  ...previous,
                  tone: event.target.value as MarketingCopyRequest['tone']
                }))
              }
            >
              <option value="professional">Professional</option>
              <option value="growth">Growth</option>
              <option value="launch">Launch</option>
            </select>
          </label>
          <label className="field">
            <span>关键词（每行一个）</span>
            <textarea value={keywordInput} onChange={(event) => setKeywordInput(event.target.value)} rows={4} />
          </label>
          {selectedCopyCampaign ? <p className="muted">默认落地页：{selectedCopyCampaign.landingPageUrl}</p> : null}
          <button
            type="submit"
            className="button button--primary"
            disabled={copySubmitting || !copyForm.campaignId || !canWriteMarketing}
          >
            {!canWriteMarketing ? '缺少写权限' : copySubmitting ? '生成中...' : '生成营销文案'}
          </button>
        </form>
      </div>

      <div className="grid grid--2">
        <div className="card stack">
          <h3>文案结果预览</h3>
          {copyResult ? (
            <>
              <div className="stack stack--sm">
                <Badge tone="info">{copyResult.tone}</Badge>
                <strong>{copyResult.headline}</strong>
                <p className="muted">{copyResult.summary}</p>
              </div>
              <div className="task-card stack stack--sm">
                <strong>正文</strong>
                <p style={{ whiteSpace: 'pre-wrap' }}>{copyResult.body}</p>
              </div>
              <div className="info-pair">
                <span>行动号召</span>
                <strong>{copyResult.callToAction}</strong>
              </div>
              <div className="campaign-card__tags">
                {copyResult.keywords.map((keyword) => (
                  <span key={keyword} className="tag">
                    {keyword}
                  </span>
                ))}
              </div>
              {copyResult.landingPageUrl ? (
                <a className="quick-link" href={copyResult.landingPageUrl} target="_blank" rel="noreferrer">
                  <strong>打开活动落地页</strong>
                  <span>{copyResult.landingPageUrl}</span>
                </a>
              ) : null}
              <p className="muted">生成时间：{formatDateTime(copyResult.createdAt)}</p>
            </>
          ) : (
            <p className="muted">选择活动并提交后，在这里查看可复用的营销文案结果。</p>
          )}
        </div>

        <form className="card stack" onSubmit={handleSubmit}>
          <h3>创建海报任务</h3>
          <label className="field field--compact">
            <span>活动</span>
            <select value={form.campaignId} onChange={(event) => setForm((previous) => ({ ...previous, campaignId: event.target.value }))}>
              {campaigns.map((campaign) => (
                <option key={campaign.campaignId} value={campaign.campaignId}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>主题</span>
            <input value={form.theme} onChange={(event) => setForm((previous) => ({ ...previous, theme: event.target.value }))} />
          </label>
          <label className="field">
            <span>宣传语</span>
            <textarea value={form.slogan} onChange={(event) => setForm((previous) => ({ ...previous, slogan: event.target.value }))} rows={3} />
          </label>
          <label className="field field--compact">
            <span>尺寸</span>
            <select value={form.size} onChange={(event) => setForm((previous) => ({ ...previous, size: event.target.value }))}>
              <option value="1024x1536">1024x1536</option>
              <option value="1080x1920">1080x1920</option>
              <option value="1280x720">1280x720</option>
            </select>
          </label>
          {selectedCampaign ? <p className="muted">落地页：{selectedCampaign.landingPageUrl}</p> : null}
          <button
            type="submit"
            className="button button--primary"
            disabled={submitting || !form.campaignId || !canWriteMarketing}
          >
            {!canWriteMarketing ? '缺少写权限' : submitting ? '生成中...' : '创建海报任务'}
          </button>
        </form>
      </div>

      <div className="card stack">
        <div className="session-sidebar__header">
          <div>
            <h3>海报任务历史</h3>
            <p className="muted">自动轮询间隔 3 秒，最长保持 10 分钟，超时后改为手动刷新。</p>
          </div>
          <button
            type="button"
            className="button button--ghost"
            onClick={() => void refreshPosterTasks()}
            disabled={refreshingTasks}
          >
            {refreshingTasks ? '刷新中...' : '手动刷新'}
          </button>
        </div>
        {tasks.length ? (
          <div className="poster-grid">
            {tasks.map((task) => (
              <div key={task.taskId} className="poster-card">
                <div className="poster-card__preview">
                  {task.imageUrl ? <img src={task.imageUrl} alt={task.slogan} /> : <div className="poster-card__placeholder">待生成</div>}
                </div>
                <div className="poster-card__body">
                  <strong>{task.campaignName}</strong>
                  <p className="muted">{task.theme}</p>
                  <p className="muted">{task.slogan}</p>
                  <div className="list-row">
                    <span>{task.size}</span>
                    <span>{task.status}</span>
                    <span>{formatDateTime(task.updatedAt)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="muted">
            {isMock ? '暂无海报任务。' : '暂无海报任务。页面会直接读取后端历史列表，必要时才回补当前浏览器最近跟踪的任务详情。'}
          </p>
        )}
      </div>
    </>
  );
}
