import {
  createWebUserApiClient,
  createWebUserSessionManager,
  createWebUserSessionStore,
  createChatApi,
  createWebUserBusinessApis,
  type WebUserRuntimeConfig,
  type AuthSession,
} from "@smartcloud-x/frontend-sdk/web-user";

import { runtimeConfig } from "./runtime-config";
import { createIdempotencyKey } from "./request-meta";

const SESSION_STORAGE_KEY = "smartcloud-x:web-user:auth-session";
const SESSION_EVENT_NAME = "smartcloud-x:web-user:auth-session-changed";

export const sdkRuntime: WebUserRuntimeConfig = {
  apiBaseUrl: runtimeConfig.apiBaseUrl,
  requestTimeoutMs: runtimeConfig.requestTimeoutMs,
  useMockApi: runtimeConfig.useMockApi,
  clientPlatform: runtimeConfig.clientPlatform,
  appVersion: runtimeConfig.appVersion,
};

export const sessionStore = createWebUserSessionStore(SESSION_STORAGE_KEY, SESSION_EVENT_NAME);

export const sessionManager = createWebUserSessionManager({
  runtime: sdkRuntime,
  storage: sessionStore,
});

export const apiClient = createWebUserApiClient({
  runtime: sdkRuntime,
  getSession: () => sessionManager.getStoredAuthSession(),
  refreshSession: (force) => sessionManager.refreshAuthSession(force),
});

export const chatApi = createChatApi({
  client: apiClient,
  createIdempotencyKey,
});

export const businessApis = createWebUserBusinessApis({
  client: apiClient,
  createIdempotencyKey,
  icpTrackingStore: createIcpTrackingStore(),
});

function createIcpTrackingStore() {
  const STORAGE_KEY = "smartcloud-x:web-user:icp-tracked-applications";
  return {
    list(): string[] {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        return raw ? (JSON.parse(raw) as string[]) : [];
      } catch {
        return [];
      }
    },
    remember(applicationNo: string) {
      try {
        const cur = new Set(this.list());
        cur.add(applicationNo);
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...cur]));
      } catch {
        /* noop */
      }
    },
  };
}

export type { AuthSession };
