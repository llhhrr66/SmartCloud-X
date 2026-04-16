import { useMemo, type PropsWithChildren } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { appEnv } from '../config/env';
import { clearTelemetryEvents, useTelemetryStore, type TelemetryEvent } from '../lib/telemetry';
import { canAccessFeature, getFeatureDefinition, listRestrictedFeatureDefinitions, navFeatureKeys } from '../lib/permissions';
import { Badge } from './Badge';

function formatTelemetryTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }).format(new Date(value));
}

function shortenIdentifier(value: string): string {
  if (value.length <= 20) {
    return value;
  }

  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function getTelemetryTone(eventName: TelemetryEvent['eventName']): 'neutral' | 'info' | 'success' | 'warning' | 'danger' {
  switch (eventName) {
    case 'page_view':
      return 'neutral';
    case 'login_submit':
      return 'info';
    case 'chat_stream_start':
    case 'chat_stream_end':
      return 'success';
    case 'permission_denied':
      return 'warning';
    case 'api_error':
    case 'chat_stream_error':
      return 'danger';
  }
}

export function AppShell({ children }: PropsWithChildren): JSX.Element {
  const { logout, session, isMock } = useAuth();
  const navigate = useNavigate();
  const telemetryState = useTelemetryStore();
  const navItems = useMemo(
    () => navFeatureKeys.map(getFeatureDefinition).filter((item) => canAccessFeature(session, item.key)),
    [session]
  );
  const restrictedItems = useMemo(() => listRestrictedFeatureDefinitions(session, navFeatureKeys), [session]);
  const recentTelemetryEvents = useMemo(() => telemetryState.events.slice(0, 4), [telemetryState.events]);

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar__brand">
          <div className="sidebar__logo">SC</div>
          <div>
            <p className="sidebar__title">{appEnv.appTitle}</p>
            <p className="muted">工业级多智能体用户端</p>
          </div>
        </div>

        <nav className="nav-list">
          {navItems.map((item) => (
            <NavLink
              key={item.route}
              to={item.route}
              className={({ isActive }) => 'nav-link' + (isActive ? ' nav-link--active' : '')}
              end={item.route === '/'}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar__footer">
          {restrictedItems.length ? (
            <div className="card sidebar__restricted">
              <div className="task-card__header">
                <strong>待授权能力</strong>
                <Badge tone="neutral">{restrictedItems.length}</Badge>
              </div>
              <p className="muted">未满足权限的页面已自动从导航中隐藏，避免误入未授权链路。</p>
              <div className="sidebar__restricted-list">
                {restrictedItems.map((item) => (
                  <Badge key={item.key} tone="neutral">
                    {item.label}
                  </Badge>
                ))}
              </div>
            </div>
          ) : null}

          <div className="sidebar__meta card">
            <div className="sidebar__meta-row">
              <span>版本</span>
              <code className="mono">{appEnv.appVersion}</code>
            </div>
            <div className="sidebar__meta-row">
              <span>运行模式</span>
              <Badge tone={isMock ? 'warning' : 'success'}>{isMock ? 'Mock' : 'Live'}</Badge>
            </div>
            <div className="sidebar__meta-row">
              <span>API 网关</span>
              <code className="mono">{appEnv.apiBaseUrl}</code>
            </div>
            <div className="sidebar__meta-row">
              <span>配置来源</span>
              <Badge tone={appEnv.runtimeConfigEnabled ? 'info' : 'neutral'}>
                {appEnv.runtimeConfigEnabled ? 'Runtime' : 'Build'}
              </Badge>
            </div>
            <div className="sidebar__meta-row">
              <span>SSE 心跳</span>
              <span>{appEnv.sseHeartbeatSeconds}s</span>
            </div>
            <div className="sidebar__meta-row">
              <span>页面权限</span>
              <span>
                {navItems.length}/{navFeatureKeys.length}
              </span>
            </div>
          </div>

          <div className="card sidebar__telemetry">
            <div className="task-card__header">
              <strong>最近埋点</strong>
              <Badge tone="info">{telemetryState.events.length}</Badge>
            </div>
            <p className="muted">保留最近 40 条 page / api / stream 事件，便于联调排查。</p>
            {recentTelemetryEvents.length ? (
              <div className="sidebar__telemetry-list">
                {recentTelemetryEvents.map((event) => (
                  <div key={event.id} className="sidebar__telemetry-item">
                    <div className="task-card__header">
                      <Badge tone={getTelemetryTone(event.eventName)}>{event.eventName}</Badge>
                      <span className="muted">{formatTelemetryTime(event.createdAt)}</span>
                    </div>
                    <strong>{event.page}</strong>
                    <div className="sidebar__telemetry-meta">
                      <span className="muted">request_id</span>
                      <code className="mono">{shortenIdentifier(event.requestId)}</code>
                    </div>
                    {event.errorCode ? (
                      <div className="sidebar__telemetry-meta">
                        <span className="muted">error_code</span>
                        <code className="mono">{event.errorCode}</code>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">当前还没有记录到埋点事件。</p>
            )}
            {telemetryState.events.length ? (
              <button type="button" className="button button--ghost" onClick={clearTelemetryEvents}>
                清空埋点
              </button>
            ) : null}
          </div>
        </div>
      </aside>

      <div className="app-shell__content">
        <header className="topbar card">
          <div>
            <p className="topbar__greeting">欢迎回来，{session?.user.name ?? '访客'}</p>
            <p className="muted">当前租户：{session?.user.tenantId ?? 'default'}</p>
          </div>
          <div className="topbar__actions">
            <div className="topbar__identity">
              <strong>{session?.user.email ?? '未登录'}</strong>
              <span className="muted">{session?.user.locale ?? 'zh-CN'}</span>
            </div>
            <button type="button" className="button button--ghost" onClick={handleLogout}>
              退出登录
            </button>
          </div>
        </header>

        <main className="page">{children}</main>
      </div>
    </div>
  );
}
