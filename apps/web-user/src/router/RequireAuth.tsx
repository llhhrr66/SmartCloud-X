import { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import { sessionManager } from "@/lib/sdk";

function AuthBootstrapFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center text-slate-500">
      正在恢复登录态…
    </div>
  );
}

function useBootstrapAuthSession() {
  const bootstrapped = useAuthStore((s) => s.bootstrapped);

  useEffect(() => {
    if (bootstrapped) {
      return;
    }

    let cancelled = false;

    void (async () => {
      const stored = sessionManager.getStoredAuthSession();
      if (!stored) {
        if (!cancelled) {
          useAuthStore.setState({ session: null, bootstrapped: true });
        }
        return;
      }

      const restored = sessionManager.isAuthSessionExpired(stored)
        ? await sessionManager.refreshAuthSession(true)
        : stored;

      if (!restored) {
        if (!cancelled) {
          useAuthStore.getState().clear();
        }
        return;
      }

      try {
        const synced = await sessionManager.syncCurrentUser();
        if (!cancelled) {
          if (!synced) {
            useAuthStore.getState().clear();
            return;
          }
          useAuthStore.setState({ session: synced, bootstrapped: true });
        }
      } catch {
        if (!cancelled) {
          useAuthStore.getState().clear();
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [bootstrapped]);

  return bootstrapped;
}

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const session = useAuthStore((s) => s.session);
  const bootstrapped = useBootstrapAuthSession();

  if (!bootstrapped) {
    return <AuthBootstrapFallback />;
  }
  if (!session) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <>{children}</>;
}

export function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const session = useAuthStore((s) => s.session);
  const bootstrapped = useBootstrapAuthSession();

  if (!bootstrapped) {
    return <AuthBootstrapFallback />;
  }
  if (session) return <Navigate to="/" replace />;
  return <>{children}</>;
}
