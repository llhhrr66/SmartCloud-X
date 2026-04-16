import { appEnv } from '../../config/env';
import { apiClient } from '../client';
import {
  mockCreatePasswordResetChallenge,
  mockLogin,
  mockResetPassword,
  mockSendAuthCode
} from '../mock';
import { getStoredAuthSession } from '../../auth/session-manager';
import {
  buildAuthSessionFromLoginResponse,
  buildAuthSessionFromRefreshResponse,
  isOperationSuccessful,
  mapCurrentUser,
  mapForgotPasswordChallenge,
  mapSendCodeResponse,
  toForgotPasswordChallengeRequestBody,
  toLoginRequestBody,
  toLogoutRequestBody,
  toRefreshTokenRequestBody,
  toResetPasswordRequestBody,
  toSendCodeRequestBody
} from '../../shared-sdk';
import type {
  AuthSession,
  CurrentUser,
  ForgotPasswordChallenge,
  ForgotPasswordChallengeRequest,
  LoginRequest,
  ResetPasswordRequest,
  SendCodeRequest,
  SendCodeResponse
} from '../../types/domain';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export const authService = {
  async login(input: LoginRequest): Promise<AuthSession> {
    if (appEnv.useMockApi) {
      return mockLogin(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(toLoginRequestBody(input))
    });

    return buildAuthSessionFromLoginResponse(data);
  },

  async sendCode(input: SendCodeRequest): Promise<SendCodeResponse> {
    if (appEnv.useMockApi) {
      return mockSendAuthCode(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/auth/send-code', {
      method: 'POST',
      body: JSON.stringify(toSendCodeRequestBody(input))
    });

    return mapSendCodeResponse(data, input.scene, input.account);
  },

  async createPasswordResetChallenge(input: ForgotPasswordChallengeRequest): Promise<ForgotPasswordChallenge> {
    if (appEnv.useMockApi) {
      return mockCreatePasswordResetChallenge(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/auth/password/forgot', {
      method: 'POST',
      body: JSON.stringify(toForgotPasswordChallengeRequestBody(input))
    });

    return mapForgotPasswordChallenge(data);
  },

  async resetPassword(input: ResetPasswordRequest): Promise<{ success: true }> {
    if (input.newPassword !== input.confirmPassword) {
      throw new Error('两次输入的新密码不一致');
    }

    if (appEnv.useMockApi) {
      return mockResetPassword(input);
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/auth/password/reset', {
      method: 'POST',
      body: JSON.stringify(toResetPasswordRequestBody(input))
    });

    if (!isOperationSuccessful(data)) {
      throw new Error('密码重置失败');
    }

    return { success: true };
  },

  async refresh(refreshToken: string): Promise<AuthSession> {
    const currentSession = getStoredAuthSession();

    if (appEnv.useMockApi) {
      if (!currentSession) {
        throw new Error('当前未登录');
      }

      return {
        ...currentSession,
        expiresAt: new Date(Date.now() + currentSession.expiresIn * 1000).toISOString()
      };
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/auth/refresh', {
      method: 'POST',
      body: JSON.stringify(toRefreshTokenRequestBody(refreshToken))
    });

    const fallbackSession: AuthSession =
      currentSession ?? {
        accessToken: '',
        refreshToken,
        expiresIn: Number(data.expires_in ?? data.expiresIn ?? 7200),
        expiresAt: new Date().toISOString(),
        user: mapCurrentUser(isRecord(data.user) ? data.user : {})
      };

    return buildAuthSessionFromRefreshResponse(data, fallbackSession);
  },

  async getCurrentUser(): Promise<CurrentUser> {
    const currentSession = getStoredAuthSession();

    if (appEnv.useMockApi) {
      if (!currentSession) {
        throw new Error('当前未登录');
      }

      return currentSession.user;
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/auth/me', {
      method: 'GET'
    });

    return mapCurrentUser(data);
  },

  async logout(refreshToken?: string): Promise<void> {
    if (appEnv.useMockApi) {
      return;
    }

    await apiClient.request('/api/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify(toLogoutRequestBody(refreshToken))
    });
  }
};
