import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { userService } from '../api/services/user';
import { useAuth } from '../auth/AuthContext';
import { Badge } from '../components/Badge';
import { PageHeader } from '../components/PageHeader';

interface ProfileFormState {
  name: string;
  avatarUrl: string;
  locale: string;
  timeZone: string;
}

const initialPasswordState = {
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
};

export function AccountPage(): JSX.Element {
  const navigate = useNavigate();
  const { session, isMock, logout, refreshSession } = useAuth();
  const [profileForm, setProfileForm] = useState<ProfileFormState>({
    name: session?.user.name ?? '',
    avatarUrl: session?.user.avatarUrl ?? '',
    locale: session?.user.locale ?? 'zh-CN',
    timeZone: session?.user.timeZone ?? 'Asia/Shanghai'
  });
  const [passwordForm, setPasswordForm] = useState(initialPasswordState);
  const [profileSaving, setProfileSaving] = useState(false);
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);
  const [pageError, setPageError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) {
      return;
    }

    setProfileForm({
      name: session.user.name,
      avatarUrl: session.user.avatarUrl ?? '',
      locale: session.user.locale,
      timeZone: session.user.timeZone
    });
  }, [session]);

  const sortedPermissions = useMemo(
    () => [...(session?.user.permissions ?? [])].sort((left, right) => left.localeCompare(right)),
    [session?.user.permissions]
  );

  const handleProfileSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setProfileSaving(true);
    setProfileMessage(null);
    setPageError(null);

    try {
      await userService.updateProfile({
        name: profileForm.name.trim(),
        avatarUrl: profileForm.avatarUrl.trim() || undefined,
        locale: profileForm.locale.trim(),
        timeZone: profileForm.timeZone.trim()
      });
      await refreshSession();
      setProfileMessage('个人资料已更新。');
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '更新个人资料失败');
    } finally {
      setProfileSaving(false);
    }
  };

  const handlePasswordSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPasswordSaving(true);
    setPasswordMessage(null);
    setPageError(null);

    try {
      await userService.changePassword(passwordForm);
      setPasswordForm(initialPasswordState);
      setPasswordMessage(isMock ? 'Mock 模式下已模拟修改密码，正在返回登录页。' : '密码已修改，正在强制重新登录。');
      await logout();
      navigate('/login', {
        replace: true,
        state: {
          message: '密码已修改，请重新登录。'
        }
      });
    } catch (error) {
      setPageError(error instanceof Error ? error.message : '修改密码失败');
    } finally {
      setPasswordSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        eyebrow="Account Center"
        title="个人中心"
        description="对齐用户账户接口，提供个人资料、密码修改、权限概览与会话身份信息，方便前后端联调。"
        actions={<Badge tone={isMock ? 'warning' : 'success'}>{isMock ? 'Mock 身份' : 'Live 身份'}</Badge>}
      />

      {pageError ? <div className="error-banner">{pageError}</div> : null}

      <div className="grid grid--2">
        <form className="card stack" onSubmit={handleProfileSubmit}>
          <div className="stack stack--sm">
            <h3>个人资料</h3>
            <p className="muted">对应 `/api/v1/users/me`，支持昵称、头像、语言与时区更新。</p>
          </div>
          <label className="field">
            <span>昵称</span>
            <input value={profileForm.name} onChange={(event) => setProfileForm((previous) => ({ ...previous, name: event.target.value }))} />
          </label>
          <label className="field">
            <span>头像 URL</span>
            <input
              value={profileForm.avatarUrl}
              onChange={(event) => setProfileForm((previous) => ({ ...previous, avatarUrl: event.target.value }))}
              placeholder="https://example.com/avatar.png"
            />
          </label>
          <div className="grid grid--2">
            <label className="field field--compact">
              <span>语言</span>
              <input value={profileForm.locale} onChange={(event) => setProfileForm((previous) => ({ ...previous, locale: event.target.value }))} />
            </label>
            <label className="field field--compact">
              <span>时区</span>
              <input
                value={profileForm.timeZone}
                onChange={(event) => setProfileForm((previous) => ({ ...previous, timeZone: event.target.value }))}
              />
            </label>
          </div>
          {profileMessage ? <div className="success-banner">{profileMessage}</div> : null}
          <button type="submit" className="button button--primary" disabled={profileSaving}>
            {profileSaving ? '保存中...' : '保存资料'}
          </button>
        </form>

        <div className="stack">
          <form className="card stack" onSubmit={handlePasswordSubmit}>
            <div className="stack stack--sm">
              <h3>修改密码</h3>
              <p className="muted">对应 `/api/v1/users/me/change-password`，成功后会按规范强制重新登录。</p>
            </div>
            <label className="field">
              <span>旧密码</span>
              <input
                type="password"
                value={passwordForm.oldPassword}
                onChange={(event) => setPasswordForm((previous) => ({ ...previous, oldPassword: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>新密码</span>
              <input
                type="password"
                value={passwordForm.newPassword}
                onChange={(event) => setPasswordForm((previous) => ({ ...previous, newPassword: event.target.value }))}
              />
            </label>
            <label className="field">
              <span>确认新密码</span>
              <input
                type="password"
                value={passwordForm.confirmPassword}
                onChange={(event) => setPasswordForm((previous) => ({ ...previous, confirmPassword: event.target.value }))}
              />
            </label>
            {passwordMessage ? <div className="success-banner">{passwordMessage}</div> : null}
            <button type="submit" className="button button--ghost" disabled={passwordSaving}>
              {passwordSaving ? '提交中...' : '修改密码'}
            </button>
          </form>

          <div className="card stack">
            <h3>账户信息</h3>
            <div className="info-pair">
              <span>User ID</span>
              <code className="mono">{session?.user.userId ?? '--'}</code>
            </div>
            <div className="info-pair">
              <span>Tenant ID</span>
              <code className="mono">{session?.user.tenantId ?? '--'}</code>
            </div>
            <div className="info-pair">
              <span>邮箱</span>
              <span>{session?.user.email ?? '--'}</span>
            </div>
            <div className="info-pair">
              <span>手机号</span>
              <span>{session?.user.mobile ?? '--'}</span>
            </div>
            <div className="info-pair">
              <span>Access Expires</span>
              <code className="mono">{session?.expiresAt ?? '--'}</code>
            </div>
          </div>
        </div>
      </div>

      <div className="card stack">
        <div className="stack stack--sm">
          <h3>权限概览</h3>
          <p className="muted">来自 `/api/v1/auth/me`，用于控制菜单、页面访问与交互能力开关。</p>
        </div>
        {sortedPermissions.length ? (
          <div className="permission-grid">
            {sortedPermissions.map((permission) => (
              <Badge key={permission} tone="info">
                {permission}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="muted">当前会话未返回权限码。</p>
        )}
      </div>
    </>
  );
}
