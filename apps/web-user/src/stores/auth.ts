import { create } from "zustand";
import type { AuthSession, CurrentUser } from "@smartcloud-x/frontend-sdk/web-user";
import { sessionManager, sessionStore } from "@/lib/sdk";

interface AuthState {
  session: AuthSession | null;
  bootstrapped: boolean;
  setSession: (session: AuthSession | null) => void;
  setUser: (user: CurrentUser) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  session: sessionManager.getStoredAuthSession(),
  bootstrapped: false,
  setSession: (session) => set({ session, bootstrapped: true }),
  setUser: (user) => {
    const cur = get().session;
    if (!cur) return;
    const next = { ...cur, user };
    sessionStore.set(next);
    set({ session: next });
  },
  clear: () => {
    sessionStore.clear();
    set({ session: null, bootstrapped: true });
  },
}));

sessionManager.subscribeToAuthSession(() => {
  const next = sessionManager.getStoredAuthSession();
  useAuthStore.setState({ session: next, bootstrapped: true });
});

export function selectIsAuthenticated(state: AuthState): boolean {
  return Boolean(state.session?.accessToken);
}

export function selectCurrentUser(state: AuthState): CurrentUser | null {
  return state.session?.user ?? null;
}
