import { appEnv } from '../config/env';
import { browserFetch } from '../lib/fetch';
import { storageKeys } from '../lib/storage';
import { createWebUserSessionManager, createWebUserSessionStore, type AuthSession } from '../shared-sdk';

const AUTH_SESSION_EVENT = 'smartcloud-x:web-user:auth-session-changed';

const authSessionStore = createWebUserSessionStore(storageKeys.authSession, AUTH_SESSION_EVENT);

const sessionManager = createWebUserSessionManager({
  runtime: {
    apiBaseUrl: appEnv.apiBaseUrl,
    requestTimeoutMs: appEnv.requestTimeoutMs,
    useMockApi: appEnv.useMockApi,
    clientPlatform: appEnv.clientPlatform,
    appVersion: appEnv.appVersion
  },
  fetchFn: browserFetch,
  storage: authSessionStore
});

export const getStoredAuthSession = sessionManager.getStoredAuthSession;
export const persistAuthSession = sessionManager.persistAuthSession;
export const clearAuthSession = sessionManager.clearAuthSession;
export const isAuthSessionExpired = sessionManager.isAuthSessionExpired;
export const subscribeToAuthSession = sessionManager.subscribeToAuthSession;
export const refreshAuthSession = sessionManager.refreshAuthSession;
export const syncCurrentUser = sessionManager.syncCurrentUser;
