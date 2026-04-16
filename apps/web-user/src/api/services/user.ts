import { appEnv } from '../../config/env';
import { getStoredAuthSession, persistAuthSession } from '../../auth/session-manager';
import { createId } from '../../lib/utils';
import {
  isOperationSuccessful,
  mapCurrentUser,
  toChangePasswordRequestBody,
  toUserProfileUpdateRequestBody
} from '../../shared-sdk';
import type {
  ChangePasswordRequest,
  CurrentUser,
  UserProfileUpdateRequest
} from '../../types/domain';
import { apiClient } from '../client';
import { mockChangePassword } from '../mock';
import { authService } from './auth';

export const userService = {
  getCurrentUser(): Promise<CurrentUser> {
    return authService.getCurrentUser();
  },

  async updateProfile(input: UserProfileUpdateRequest): Promise<CurrentUser> {
    const currentSession = getStoredAuthSession();

    if (appEnv.useMockApi) {
      if (!currentSession) {
        throw new Error('当前未登录');
      }

      const nextUser: CurrentUser = {
        ...currentSession.user,
        name: input.name ?? currentSession.user.name,
        avatarUrl: input.avatarUrl ?? currentSession.user.avatarUrl,
        locale: input.locale ?? currentSession.user.locale,
        timeZone: input.timeZone ?? currentSession.user.timeZone
      };

      persistAuthSession({
        ...currentSession,
        user: nextUser
      });

      return nextUser;
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/users/me', {
      method: 'PATCH',
      body: JSON.stringify(toUserProfileUpdateRequestBody(input))
    });

    const nextUser = mapCurrentUser(data);
    if (currentSession) {
      persistAuthSession({
        ...currentSession,
        user: nextUser
      });
    }

    return nextUser;
  },

  async changePassword(input: ChangePasswordRequest): Promise<{ success: true; requestId: string }> {
    if (input.newPassword !== input.confirmPassword) {
      throw new Error('两次输入的新密码不一致');
    }

    if (appEnv.useMockApi) {
      await mockChangePassword(input);
      return {
        success: true,
        requestId: createId('req')
      };
    }

    const data = await apiClient.request<Record<string, unknown>>('/api/v1/users/me/change-password', {
      method: 'POST',
      body: JSON.stringify(toChangePasswordRequestBody(input))
    });

    if (!isOperationSuccessful(data)) {
      throw new Error('修改密码失败');
    }

    return {
      success: true,
      requestId: createId('req')
    };
  }
};
