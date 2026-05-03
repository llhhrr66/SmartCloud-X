import {
  buildAuthSessionFromLoginResponse,
  mapCurrentUser,
  mapForgotPasswordChallenge,
  mapSendCodeResponse,
  toForgotPasswordChallengeRequestBody,
  toLoginRequestBody,
  toLogoutRequestBody,
  toResetPasswordRequestBody,
  toSendCodeRequestBody,
  toUserProfileUpdateRequestBody,
  toChangePasswordRequestBody,
  type AuthSession,
  type CurrentUser,
  type ForgotPasswordChallenge,
  type ForgotPasswordChallengeRequest,
  type LoginRequest,
  type ResetPasswordRequest,
  type SendCodeRequest,
  type SendCodeResponse,
  type UserProfileUpdateRequest,
  type ChangePasswordRequest,
} from "@smartcloud-x/frontend-sdk/web-user";

import { apiClient, sessionManager, sessionStore } from "./sdk";

export const authService = {
  async login(input: LoginRequest): Promise<AuthSession> {
    const data = await apiClient.request<Record<string, unknown>>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(toLoginRequestBody(input)),
    });
    const session = buildAuthSessionFromLoginResponse(data);
    sessionStore.set(session);
    return session;
  },

  async logout(): Promise<void> {
    const current = sessionManager.getStoredAuthSession();
    try {
      if (current) {
        await apiClient.request<unknown>("/api/v1/auth/logout", {
          method: "POST",
          body: JSON.stringify(toLogoutRequestBody(current.refreshToken)),
        });
      }
    } catch {
      /* logout best-effort */
    } finally {
      sessionStore.clear();
    }
  },

  async sendVerificationCode(input: SendCodeRequest): Promise<SendCodeResponse> {
    const data = await apiClient.request<Record<string, unknown>>("/api/v1/auth/code/send", {
      method: "POST",
      body: JSON.stringify(toSendCodeRequestBody(input)),
    });
    return mapSendCodeResponse(data, input.scene, input.account);
  },

  async createPasswordResetChallenge(input: ForgotPasswordChallengeRequest): Promise<ForgotPasswordChallenge> {
    const data = await apiClient.request<Record<string, unknown>>("/api/v1/auth/password/forgot", {
      method: "POST",
      body: JSON.stringify(toForgotPasswordChallengeRequestBody(input)),
    });
    return mapForgotPasswordChallenge(data);
  },

  async resetPassword(input: ResetPasswordRequest): Promise<void> {
    await apiClient.request<unknown>("/api/v1/auth/password/reset", {
      method: "POST",
      body: JSON.stringify(toResetPasswordRequestBody(input)),
    });
  },

  async getCurrentUser(): Promise<CurrentUser> {
    const data = await apiClient.request<Record<string, unknown>>("/api/v1/auth/me", { method: "GET" });
    return mapCurrentUser(data);
  },

  async updateProfile(input: UserProfileUpdateRequest): Promise<CurrentUser> {
    const data = await apiClient.request<Record<string, unknown>>("/api/v1/users/me", {
      method: "PATCH",
      body: JSON.stringify(toUserProfileUpdateRequestBody(input)),
    });
    return mapCurrentUser(data);
  },

  async changePassword(input: ChangePasswordRequest): Promise<void> {
    await apiClient.request<unknown>("/api/v1/users/me/change-password", {
      method: "POST",
      body: JSON.stringify(toChangePasswordRequestBody(input)),
    });
  },
};
