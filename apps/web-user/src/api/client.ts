import { ApiError, createWebUserApiClient, type RawSseEvent } from '../shared-sdk';
import { appEnv } from '../config/env';
import { getStoredAuthSession, refreshAuthSession } from '../auth/session-manager';
import { browserFetch } from '../lib/fetch';
import { recordTelemetryEvent } from '../lib/telemetry';

export { ApiError };
export type { RawSseEvent };

const baseClient = createWebUserApiClient({
  runtime: {
    apiBaseUrl: appEnv.apiBaseUrl,
    requestTimeoutMs: appEnv.requestTimeoutMs,
    useMockApi: appEnv.useMockApi,
    clientPlatform: appEnv.clientPlatform,
    appVersion: appEnv.appVersion
  },
  fetchFn: browserFetch,
  getSession: getStoredAuthSession,
  refreshSession: refreshAuthSession
});

function readCurrentPage(): string {
  if (typeof window === 'undefined') {
    return '/';
  }

  return `${window.location.pathname}${window.location.search}`;
}

function recordApiError(path: string, method: string, transport: 'http' | 'sse', error: unknown): void {
  const session = getStoredAuthSession();

  if (error instanceof ApiError) {
    recordTelemetryEvent({
      eventName: 'api_error',
      page: readCurrentPage(),
      requestId: error.requestId,
      userId: session?.user.userId,
      errorCode: error.code ?? error.status,
      metadata: {
        path,
        method,
        transport,
        status: error.status
      }
    });
    return;
  }

  recordTelemetryEvent({
    eventName: 'api_error',
    page: readCurrentPage(),
    userId: session?.user.userId,
    errorCode: 'UNKNOWN_API_ERROR',
    metadata: {
      path,
      method,
      transport,
      message: error instanceof Error ? error.message : 'Unknown error'
    }
  });
}

export const apiClient = {
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    try {
      return await baseClient.request<T>(path, init);
    } catch (error) {
      recordApiError(path, init.method ?? 'GET', 'http', error);
      throw error;
    }
  },
  async *stream(path: string, init: RequestInit = {}): AsyncGenerator<RawSseEvent> {
    try {
      yield* baseClient.stream(path, init);
    } catch (error) {
      recordApiError(path, init.method ?? 'GET', 'sse', error);
      throw error;
    }
  }
};
