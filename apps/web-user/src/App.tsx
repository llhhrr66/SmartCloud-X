import { useEffect } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './auth/AuthContext';
import { AccessDeniedCard } from './components/AccessDeniedCard';
import { AppShell } from './components/AppShell';
import { appEnv } from './config/env';
import { recordTelemetryEvent } from './lib/telemetry';
import { canAccessFeature, getFeatureDefinition, type AppFeatureKey } from './lib/permissions';
import { AccountPage } from './pages/AccountPage';
import { BillingPage } from './pages/BillingPage';
import { ChatPage } from './pages/ChatPage';
import { DashboardPage } from './pages/DashboardPage';
import { IcpPage } from './pages/IcpPage';
import { LoginPage } from './pages/LoginPage';
import { MarketingPage } from './pages/MarketingPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { OrdersPage } from './pages/OrdersPage';
import { ResearchPage } from './pages/ResearchPage';
import { ServiceDeskPage } from './pages/ServiceDeskPage';
import { SessionsPage } from './pages/SessionsPage';
import { TicketsPage } from './pages/TicketsPage';

function RouteTelemetryObserver(): JSX.Element | null {
  const location = useLocation();
  const { session } = useAuth();

  useEffect(() => {
    const page = `${location.pathname}${location.search}`;
    recordTelemetryEvent({
      eventName: 'page_view',
      page,
      userId: session?.user.userId,
      metadata: {
        route: location.pathname
      },
      dedupeKey: `page_view:${location.key}:${page}:${session?.user.userId ?? 'anonymous'}`
    });
  }, [location.key, location.pathname, location.search, session?.user.userId]);

  return null;
}

function ProtectedLayout(): JSX.Element {
  const { isAuthenticated, isBootstrapping } = useAuth();

  if (isBootstrapping) {
    return (
      <div className="auth-layout">
        <section className="auth-card card">
          <p className="page-header__eyebrow">Session Check</p>
          <h2>正在恢复登录状态</h2>
          <p className="muted">正在同步当前用户信息与访问令牌，请稍候。</p>
        </section>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

function FeatureRoute({ feature, children }: { feature: AppFeatureKey; children: JSX.Element }): JSX.Element {
  const { session } = useAuth();
  const location = useLocation();
  const definition = getFeatureDefinition(feature);
  const canAccess = canAccessFeature(session, feature);

  useEffect(() => {
    if (canAccess) {
      return;
    }

    recordTelemetryEvent({
      eventName: 'permission_denied',
      page: location.pathname,
      userId: session?.user.userId,
      errorCode: 'PERMISSION_DENIED',
      metadata: {
        feature,
        route: definition.route,
        requiredAllOf: definition.permissionRule?.allOf ?? [],
        requiredAnyOf: definition.permissionRule?.anyOf ?? []
      },
      dedupeKey: `permission_denied:${location.pathname}:${feature}:${session?.user.userId ?? 'anonymous'}`
    });
  }, [canAccess, definition.permissionRule?.allOf, definition.permissionRule?.anyOf, definition.route, feature, location.pathname, session?.user.userId]);

  if (!canAccess) {
    return <AccessDeniedCard feature={feature} />;
  }

  return children;
}

function AppRoutes(): JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/profile" element={<AccountPage />} />
        <Route path="/account" element={<Navigate to="/profile" replace />} />
        <Route
          path="/chat"
          element={
            <FeatureRoute feature="chat">
              <ChatPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/chat/:conversationId"
          element={
            <FeatureRoute feature="chat">
              <ChatPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/sessions"
          element={
            <FeatureRoute feature="sessions">
              <SessionsPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/billing"
          element={
            <FeatureRoute feature="billing">
              <BillingPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/orders"
          element={
            <FeatureRoute feature="orders">
              <OrdersPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/tickets"
          element={
            <FeatureRoute feature="tickets">
              <TicketsPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/icp"
          element={
            <FeatureRoute feature="icp">
              <IcpPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/service-desk"
          element={
            <FeatureRoute feature="serviceDesk">
              <ServiceDeskPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/research"
          element={
            <FeatureRoute feature="research">
              <ResearchPage />
            </FeatureRoute>
          }
        />
        <Route
          path="/marketing"
          element={
            <FeatureRoute feature="marketing">
              <MarketingPage />
            </FeatureRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export default function App(): JSX.Element {
  useEffect(() => {
    document.title = appEnv.appTitle;
  }, []);

  return (
    <BrowserRouter>
      <AuthProvider>
        <RouteTelemetryObserver />
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
