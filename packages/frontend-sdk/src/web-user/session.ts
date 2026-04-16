import {
  ApiError,
  createApiError,
  parseResponsePayload,
  unwrapEnvelope
} from '../core/envelope';
import { createBrowserStorageStore, type BrowserStorageStore } from '../core/storage';
import { createRequestId, isAbortError, joinUrl, shouldDefaultJsonContentType } from '../core/utils';
import {
  buildAuthSessionFromRefreshResponse,
  mapCurrentUser,
  toRefreshTokenRequestBody
} from './mappers';
import type { AuthSession } from './types';

export interface WebUserRuntimeConfig {
  apiBaseUrl: string;
  requestTimeoutMs: number;
  useMockApi: boolean;
  clientPlatform: string;
  appVersion: string;
}

export interface WebUserSessionManagerOptions {
  runtime: WebUserRuntimeConfig;
  storage: BrowserStorageStore<AuthSession>;
  fetchFn?: typeof fetch;
}

export function buildWebUserHeaders(
  runtime: WebUserRuntimeConfig,
  session?: AuthSession | null,
  headers?: HeadersInit,
  expectsStream = false,
  body?: BodyInit | null
): Headers {
  const merged = new Headers(headers);

  if (!merged.has('Accept')) {
    merged.set('Accept', expectsStream ? 'text/event-stream' : 'application/json');
  }

  if (!merged.has('Content-Type') && !expectsStream && shouldDefaultJsonContentType(body)) {
    merged.set('Content-Type', 'application/json');
  }

  if (!merged.has('X-Client-Platform')) {
    merged.set('X-Client-Platform', runtime.clientPlatform);
  }

  if (!merged.has('X-Client-Version')) {
    merged.set('X-Client-Version', runtime.appVersion);
  }

  if (session?.accessToken && !merged.has('Authorization')) {
    merged.set('Authorization', `Bearer ${session.accessToken}`);
  }

  if (session?.user.tenantId && !merged.has('X-Tenant-Id')) {
    merged.set('X-Tenant-Id', session.user.tenantId);
  }

  if (session?.user.userId && !merged.has('X-User-Id')) {
    merged.set('X-User-Id', session.user.userId);
  }

  if (!merged.has('X-Request-Id')) {
    merged.set('X-Request-Id', createRequestId('web-user'));
  }

  return merged;
}

export function createWebUserSessionStore(storageKey: string, eventName: string): BrowserStorageStore<AuthSession> {
  return createBrowserStorageStore<AuthSession>({
    storageKey,
    eventName
  });
}

export function createWebUserSessionManager(options: WebUserSessionManagerOptions) {
  const fetchFn = options.fetchFn ?? fetch;
  let refreshPromise: Promise<AuthSession | null> | null = null;

  async function performSessionRequest(
    path: string,
    init: RequestInit,
    session?: AuthSession | null
  ): Promise<Record<string, unknown>> {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), options.runtime.requestTimeoutMs);

    try {
      const response = await fetchFn(joinUrl(options.runtime.apiBaseUrl, path), {
        ...init,
        headers: buildWebUserHeaders(options.runtime, session, init.headers, false, init.body),
        signal: controller.signal
      });

      const payload = await parseResponsePayload(response);
      if (!response.ok) {
        throw createApiError(payload, response.status, response);
      }

      return unwrapEnvelope<Record<string, unknown>>(payload, response.status, response);
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }

      if (isAbortError(error)) {
        throw new ApiError('Request timed out or was aborted', 408);
      }

      throw new ApiError(error instanceof Error ? error.message : 'Unknown request error');
    } finally {
      globalThis.clearTimeout(timeout);
    }
  }

  function getStoredAuthSession(): AuthSession | null {
    return options.storage.get();
  }

  function persistAuthSession(session: AuthSession): void {
    options.storage.set(session);
  }

  function clearAuthSession(): void {
    options.storage.clear();
  }

  function isAuthSessionExpired(session: AuthSession, skewMs = 60_000): boolean {
    return new Date(session.expiresAt).getTime() - skewMs <= Date.now();
  }

  function subscribeToAuthSession(listener: () => void): () => void {
    return options.storage.subscribe(listener);
  }

  async function refreshAuthSession(force = false): Promise<AuthSession | null> {
    const session = getStoredAuthSession();
    if (!session) {
      return null;
    }

    if (options.runtime.useMockApi) {
      return session;
    }

    if (!force && !isAuthSessionExpired(session)) {
      return session;
    }

    if (refreshPromise) {
      return refreshPromise;
    }

    refreshPromise = performSessionRequest(
      '/api/v1/auth/refresh',
      {
        method: 'POST',
        body: JSON.stringify(toRefreshTokenRequestBody(session.refreshToken))
      },
      session
    )
      .then((data) => {
        const nextSession = buildAuthSessionFromRefreshResponse(data, session);
        persistAuthSession(nextSession);
        return nextSession;
      })
      .catch(() => {
        clearAuthSession();
        return null;
      })
      .finally(() => {
        refreshPromise = null;
      });

    return refreshPromise;
  }

  async function syncCurrentUser(): Promise<AuthSession | null> {
    const session = getStoredAuthSession();
    if (!session || options.runtime.useMockApi) {
      return session;
    }

    const data = await performSessionRequest('/api/v1/auth/me', { method: 'GET' }, session);
    const nextSession = {
      ...session,
      user: mapCurrentUser(data)
    };

    persistAuthSession(nextSession);
    return nextSession;
  }

  return {
    getStoredAuthSession,
    persistAuthSession,
    clearAuthSession,
    isAuthSessionExpired,
    subscribeToAuthSession,
    refreshAuthSession,
    syncCurrentUser
  };
}
