import { createApiClient, type FrontendApiClient } from '../core/http';
import { extractEnvelopeCode } from '../core/envelope';
import { buildWebUserHeaders, type WebUserRuntimeConfig } from './session';
import type { AuthSession } from './types';

export interface WebUserApiClientOptions {
  runtime: WebUserRuntimeConfig;
  getSession: () => AuthSession | null;
  refreshSession: (force?: boolean) => Promise<AuthSession | null>;
  fetchFn?: typeof fetch;
}

function normalizeEnvelopeCodeName(code: number | string | undefined): string | undefined {
  return typeof code === 'string' ? code.trim().toUpperCase() : undefined;
}

function shouldAttemptSessionRefresh(
  status: number,
  payload: unknown,
  useMockApi: boolean
): boolean {
  if (useMockApi) {
    return false;
  }

  const code = extractEnvelopeCode(payload);
  const codeName = normalizeEnvelopeCodeName(code);

  if (code === 4010001 || code === '4010001' || codeName === 'AUTH_INVALID_TOKEN') {
    return false;
  }

  if (code === 4010002 || code === '4010002' || codeName === 'AUTH_UNAUTHORIZED') {
    return true;
  }

  return status === 401;
}

export function createWebUserApiClient(options: WebUserApiClientOptions): FrontendApiClient {
  return createApiClient({
    baseUrl: options.runtime.apiBaseUrl,
    requestTimeoutMs: options.runtime.requestTimeoutMs,
    fetchFn: options.fetchFn,
    buildHeaders: ({ init, expectsStream }) =>
      buildWebUserHeaders(options.runtime, options.getSession(), init.headers, expectsStream, init.body),
    shouldRefreshSession: (status, payload) =>
      shouldAttemptSessionRefresh(status, payload, options.runtime.useMockApi),
    refreshSession: () => options.refreshSession(true),
    requestIdPrefix: 'web-user'
  });
}
