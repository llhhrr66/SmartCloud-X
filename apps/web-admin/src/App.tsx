import { useEffect, useMemo, useState } from "react";
import { Shell, type AdminView } from "./components/Shell";
import { ToastProvider } from "./components/Toast";
import { adminApi, adminSession } from "./lib/api";
import type { AdminProfile, AdminSession } from "./types";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { KnowledgeBasesPage } from "./pages/KnowledgeBasesPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { ImportsPage } from "./pages/ImportsPage";
import { RetrievalPage } from "./pages/RetrievalPage";
import { AgentsPage } from "./pages/AgentsPage";
import { MarketingPage } from "./pages/MarketingPage";
import { AuditRuntimePage } from "./pages/AuditRuntimePage";
import { LlmProvidersPage } from "./pages/LlmProvidersPage";

const views: AdminView[] = ["dashboard", "knowledge", "documents", "imports", "retrieval", "agents", "marketing", "audit", "llm-providers"];

function readHash(): AdminView {
  const candidate = window.location.hash.replace(/^#\/?/, "") as AdminView;
  return views.includes(candidate) ? candidate : "dashboard";
}

function AppInner() {
  const [session, setSession] = useState<AdminSession | null>(() => adminSession.get());
  const [admin, setAdmin] = useState<AdminProfile | null>(() => session?.admin ?? null);
  const [active, setActive] = useState<AdminView>(() => readHash());

  useEffect(() => {
    const onHash = () => setActive(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!session) return;
    adminApi.me().then(setAdmin).catch(() => setAdmin(null));
  }, [session]);

  const page = useMemo(() => {
    switch (active) {
      case "knowledge": return <KnowledgeBasesPage />;
      case "documents": return <DocumentsPage />;
      case "imports": return <ImportsPage />;
      case "retrieval": return <RetrievalPage />;
      case "agents": return <AgentsPage />;
      case "marketing": return <MarketingPage />;
      case "audit": return <AuditRuntimePage />;
      case "llm-providers": return <LlmProvidersPage />;
      default: return <DashboardPage />;
    }
  }, [active]);

  function login(next: AdminSession) {
    setSession(next);
    setAdmin(next.admin);
  }

  function navigate(view: AdminView) {
    window.location.hash = view;
    setActive(view);
  }

  function logout() {
    adminApi.logout();
    setSession(null);
    setAdmin(null);
  }

  if (!session || !admin) return <LoginPage onLogin={login} />;

  return (
    <Shell admin={admin} active={active} onNavigate={navigate} onLogout={logout}>
      <div className="animate-fade-in">{page}</div>
    </Shell>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  );
}
