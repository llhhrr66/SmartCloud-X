import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren
} from 'react';
import { authService } from '../api/services/auth';
import {
  clearAuthSession,
  getStoredAuthSession,
  isAuthSessionExpired,
  persistAuthSession,
  refreshAuthSession,
  subscribeToAuthSession,
  syncCurrentUser
} from './session-manager';
import { appEnv } from '../config/env';
import type { AuthSession, LoginRequest } from '../types/domain';

interface AuthContextValue {
  session: AuthSession | null;
  isAuthenticated: boolean;
  isBootstrapping: boolean;
  isMock: boolean;
  login: (input: LoginRequest) => Promise<void>;
  refreshSession: () => Promise<AuthSession | null>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: PropsWithChildren): JSX.Element {
  const [session, setSession] = useState<AuthSession | null>(() => getStoredAuthSession());
  const [isBootstrapping, setIsBootstrapping] = useState(() => Boolean(getStoredAuthSession()) && !appEnv.useMockApi);

  const login = useCallback(async (input: LoginRequest) => {
    const nextSession = await authService.login(input);
    setSession(nextSession);
    persistAuthSession(nextSession);
  }, []);

  const refreshSession = useCallback(async () => {
    const nextSession = await refreshAuthSession(true);
    setSession(nextSession);
    return nextSession;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout(session?.refreshToken);
    } finally {
      clearAuthSession();
      setSession(null);
    }
  }, [session?.refreshToken]);

  useEffect(() => subscribeToAuthSession(() => setSession(getStoredAuthSession())), []);

  useEffect(() => {
    let active = true;

    const bootstrap = async () => {
      if (!session || appEnv.useMockApi) {
        if (active) {
          setIsBootstrapping(false);
        }
        return;
      }

      try {
        if (isAuthSessionExpired(session)) {
          await refreshAuthSession(true);
        } else {
          try {
            await syncCurrentUser();
          } catch {
            await refreshAuthSession(true);
          }
        }
      } finally {
        if (active) {
          setSession(getStoredAuthSession());
          setIsBootstrapping(false);
        }
      }
    };

    void bootstrap();

    return () => {
      active = false;
    };
  }, [session?.accessToken]);

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      isAuthenticated: Boolean(session),
      isBootstrapping,
      isMock: appEnv.useMockApi,
      login,
      refreshSession,
      logout
    }),
    [isBootstrapping, login, logout, refreshSession, session]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }

  return context;
}
