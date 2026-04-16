import type { AuthSession } from '../types/domain';

const storagePrefix = 'smartcloud-x:web-user';

export const storageKeys = {
  authSession: `${storagePrefix}:auth-session`,
  mockDatabase: `${storagePrefix}:mock-database`,
  taskRegistry: `${storagePrefix}:task-registry`,
  telemetry: `${storagePrefix}:telemetry`
} as const;

export function readJson<T>(key: string, fallback: T): T {
  if (typeof window === 'undefined') {
    return fallback;
  }

  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) {
      return fallback;
    }

    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson<T>(key: string, value: T): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.setItem(key, JSON.stringify(value));
}

export function removeItem(key: string): void {
  if (typeof window === 'undefined') {
    return;
  }

  window.localStorage.removeItem(key);
}

export function readAuthSession(): AuthSession | null {
  return readJson<AuthSession | null>(storageKeys.authSession, null);
}

export function writeAuthSession(session: AuthSession): void {
  writeJson(storageKeys.authSession, session);
}
