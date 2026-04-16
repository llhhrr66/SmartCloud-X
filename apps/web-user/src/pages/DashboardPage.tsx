import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { billingService } from '../api/services/billing';
import { chatService } from '../api/services/chat';
import { marketingService } from '../api/services/marketing';
import { researchService } from '../api/services/research';
import { serviceDeskService } from '../api/services/serviceDesk';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';
import { StatCard } from '../components/StatCard';
import { formatCurrency } from '../lib/format';
import {
  canAccessFeature,
  dashboardQuickLinkFeatureKeys,
  getFeatureDefinition,
  listAccessibleFeatureDefinitions,
  listRestrictedFeatureDefinitions
} from '../lib/permissions';

interface DashboardStats {
  totalSessions: number;
  monthlySpend: string;
  researchTasks: number;
  campaigns: number;
  openTickets: number;
}

const initialStats: DashboardStats = {
  totalSessions: 0,
  monthlySpend: '0',
  researchTasks: 0,
  campaigns: 0,
  openTickets: 0
};

export function DashboardPage(): JSX.Element {
  const { session, isMock } = useAuth();
  const [loading, setLoading] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [stats, setStats] = useState<DashboardStats>(initialStats);

  const accessibleLinks = useMemo(
    () => listAccessibleFeatureDefinitions(session, dashboardQuickLinkFeatureKeys),
    [session]
  );
  const restrictedLinks = useMemo(
    () => listRestrictedFeatureDefinitions(session, dashboardQuickLinkFeatureKeys),
    [session]
  );
  const canReadChat = canAccessFeature(session, 'chat');
  const canReadBilling = canAccessFeature(session, 'billing');
  const canReadResearch = canAccessFeature(session, 'research');
  const canReadMarketing = canAccessFeature(session, 'marketing');
  const canReadTickets = canAccessFeature(session, 'tickets');

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      const [sessionsResult, billingResult, researchResult, campaignsResult, ticketsResult] = await Promise.allSettled([
        canReadChat ? chatService.listSessions({ page: 1, pageSize: 50 }) : Promise.resolve(null),
        canReadBilling ? billingService.getDashboard() : Promise.resolve(null),
        canReadResearch ? researchService.listTasks() : Promise.resolve(null),
        canReadMarketing ? marketingService.listCampaigns() : Promise.resolve(null),
        canReadTickets ? serviceDeskService.getWorkspace() : Promise.resolve(null)
      ]);

      if (!mounted) {
        return;
      }

      setStats({
        totalSessions:
          canReadChat && sessionsResult.status === 'fulfilled' && sessionsResult.value ? sessionsResult.value.total : 0,
        monthlySpend:
          canReadBilling && billingResult.status === 'fulfilled' && billingResult.value
            ? billingResult.value.summary.totalAmount
            : '0',
        researchTasks:
          canReadResearch && researchResult.status === 'fulfilled' && researchResult.value ? researchResult.value.length : 0,
        campaigns:
          canReadMarketing && campaignsResult.status === 'fulfilled' && campaignsResult.value
            ? campaignsResult.value.length
            : 0,
        openTickets:
          canReadTickets && ticketsResult.status === 'fulfilled' && ticketsResult.value
            ? ticketsResult.value.tickets.filter((item) => item.status !== 'closed').length
            : 0
      });

      const hasPartialFailure =
        (canReadChat && sessionsResult.status === 'rejected') ||
        (canReadBilling && billingResult.status === 'rejected') ||
        (canReadResearch && researchResult.status === 'rejected') ||
        (canReadMarketing && campaignsResult.status === 'rejected') ||
        (canReadTickets && ticketsResult.status === 'rejected');

      setPageError(hasPartialFailure ? '部分总览数据暂不可用，页面已按已成功接口展示。' : null);
      setLoading(false);
    };

    void load();

    return () => {
      mounted = false;
    };
  }, [canReadBilling, canReadChat, canReadMarketing, canReadResearch, canReadTickets]);

  return (
    <>
      <PageHeader
        eyebrow="Workspace Overview"
        title="用户工作台总览"
        description="统一查看当前账号已授权的会话、账单、工单、ICP、营销与研究入口，并把未授权能力显式隔离。"
        actions={<Badge tone={isMock ? 'warning' : 'success'}>{isMock ? 'Mock 数据' : 'Live API'}</Badge>}
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}

      <div className="hero card">
        <div>
          <h2>欢迎，{session?.user.name ?? '用户'} 👋</h2>
          <p className="muted">
            当前账号已开通 {accessibleLinks.length} 个用户端页面入口，另有 {restrictedLinks.length}{' '}
            个能力等待授权；导航与直达链接会按权限自动收敛。
          </p>
        </div>
        <div className="hero__actions">
          <Link className="button button--primary" to={canReadChat ? '/chat' : '/profile'}>
            {canReadChat ? '进入聊天主链路' : '查看权限状态'}
          </Link>
          <Link className="button button--ghost" to="/profile">
            查看个人中心
          </Link>
        </div>
      </div>

      <div className="grid grid--4">
        <StatCard
          label="总会话数"
          value={loading ? '--' : String(stats.totalSessions)}
          hint={canReadChat ? '覆盖用户历史咨询与上下文。' : '当前账号未开通 user:chat.use。'}
        />
        <StatCard
          label="本月消费"
          value={loading ? '--' : formatCurrency(stats.monthlySpend)}
          hint={canReadBilling ? '用于账单页卡片与客服问答。' : '当前账号未开通 user:billing.read。'}
        />
        <StatCard
          label="研究任务"
          value={loading ? '--' : String(stats.researchTasks)}
          hint={canReadResearch ? '对应 Deep Research Agent 输出。' : '当前账号未开通 user:research.read。'}
        />
        <StatCard
          label="进行中工单"
          value={loading ? '--' : String(stats.openTickets)}
          hint={canReadTickets ? '来自工单与服务台工作区。' : '当前账号未开通 user:ticket.read。'}
        />
      </div>

      <div className="grid grid--2">
        <div className="card stack">
          <h3>已授权入口</h3>
          {accessibleLinks.length ? (
            <div className="quick-links">
              {accessibleLinks.map((item) => (
                <Link key={item.key} className="quick-link" to={item.route}>
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </Link>
              ))}
            </div>
          ) : (
            <div className="empty-state empty-state--compact">
              <p className="muted">当前账号暂未返回任何用户侧业务权限，请先在个人中心确认权限集。</p>
            </div>
          )}
        </div>

        <div className="card stack">
          <h3>待授权能力</h3>
          {restrictedLinks.length ? (
            <>
              <p className="muted">以下能力已从导航中隐藏；若需要联调或演示，请先补齐对应权限码。</p>
              <div className="permission-grid">
                {restrictedLinks.map((item) => (
                  <Badge key={item.key} tone="neutral">
                    {item.label}
                  </Badge>
                ))}
              </div>
            </>
          ) : (
            <p className="muted">当前账号已具备完整用户端页面访问权限。</p>
          )}

          <div className="task-card stack stack--sm">
            <strong>推荐下一步</strong>
            <ul className="feature-list">
              <li>到个人中心核对权限码是否与当前 RBAC 配置一致</li>
              <li>优先从聊天页进入高频问题，再通过服务台或工单页转人工闭环</li>
              <li>营销 / 研究页面默认保留只读与写入能力的权限分层，便于联调授权链路</li>
            </ul>
          </div>
        </div>
      </div>

      <div className="card stack">
        <div className="task-card__header">
          <div>
            <h3>页面映射参考</h3>
            <p className="muted">总览中的页面说明直接来自当前路由访问规则，便于联调时核对菜单、直达链接和权限结果。</p>
          </div>
          <Badge tone="info">{session?.user.permissions.length ?? 0} 个权限码</Badge>
        </div>
        <div className="quick-links">
          {dashboardQuickLinkFeatureKeys.map((featureKey) => {
            const feature = getFeatureDefinition(featureKey);
            const isAccessible = canAccessFeature(session, feature.key);
            return (
              <div key={feature.key} className="quick-link">
                <strong>{feature.label}</strong>
                <span>{feature.description}</span>
                <Badge tone={isAccessible ? 'success' : 'neutral'}>{isAccessible ? '已开通' : '待授权'}</Badge>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
