import { useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { authService } from '../api/services/auth';
import { useAuth } from '../auth/AuthContext';
import { appEnv } from '../config/env';
import { Badge } from '../components/Badge';
import { recordTelemetryEvent } from '../lib/telemetry';
import type { AccountType, ForgotPasswordChallenge, LoginType } from '../types/domain';

interface VerificationAccountValidation {
  accountType: AccountType | null;
  message?: string;
}

function detectVerificationAccountType(account: string): AccountType | null {
  const normalized = account.trim();
  if (!normalized) {
    return null;
  }

  if (normalized.includes('@')) {
    return 'email';
  }

  if (/^[+]?[0-9][0-9\s-]{5,}$/.test(normalized)) {
    return 'mobile';
  }

  return null;
}

function getRequiredAccountType(loginType: LoginType): AccountType | null {
  if (loginType === 'sms') {
    return 'mobile';
  }

  if (loginType === 'email_code') {
    return 'email';
  }

  return null;
}

function validateVerificationAccount(account: string, requiredType: AccountType | null = null): VerificationAccountValidation {
  const accountType = detectVerificationAccountType(account);

  if (!accountType) {
    return {
      accountType: null,
      message: '验证码流程仅支持绑定邮箱或手机号'
    };
  }

  if (requiredType && accountType !== requiredType) {
    return {
      accountType,
      message: requiredType === 'mobile' ? '短信验证码登录仅支持绑定手机号' : '邮箱验证码登录仅支持绑定邮箱'
    };
  }

  return {
    accountType
  };
}

function normalizeAccount(value: string): string {
  return value.trim().toLowerCase();
}

const loginTypeLabels: Record<LoginType, string> = {
  password: '密码登录',
  sms: '短信验证码',
  email_code: '邮箱验证码'
};

type AuthView = 'login' | 'forgot_password';

type ResetChallengeState = ForgotPasswordChallenge & {
  account: string;
};

export function LoginPage(): JSX.Element {
  const location = useLocation();
  const { login, session, isMock } = useAuth();
  const [authView, setAuthView] = useState<AuthView>('login');
  const [loginType, setLoginType] = useState<LoginType>('password');
  const [account, setAccount] = useState('demo@smartcloud.local');
  const [password, setPassword] = useState('smartcloud-demo');
  const [verificationCode, setVerificationCode] = useState('123456');
  const [resetChallenge, setResetChallenge] = useState<ResetChallengeState | null>(null);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [creatingResetChallenge, setCreatingResetChallenge] = useState(false);
  const [resettingPassword, setResettingPassword] = useState(false);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [codeMessage, setCodeMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cooldownSeconds <= 0) {
      return;
    }

    const timer = window.setTimeout(() => {
      setCooldownSeconds((previous) => Math.max(previous - 1, 0));
    }, 1000);

    return () => {
      window.clearTimeout(timer);
    };
  }, [cooldownSeconds]);

  useEffect(() => {
    if (!resetChallenge) {
      return;
    }

    if (normalizeAccount(account) !== normalizeAccount(resetChallenge.account)) {
      setResetChallenge(null);
      setNewPassword('');
      setConfirmPassword('');
      setCodeMessage('账号已变更，请重新校验验证码并创建新的重置挑战。');
    }
  }, [account, resetChallenge]);

  const accountType = useMemo(() => detectVerificationAccountType(account.trim()), [account]);
  const requiredAccountType = useMemo(() => getRequiredAccountType(loginType), [loginType]);
  const showCodeActions = authView === 'login' && loginType !== 'password';
  const loginCodeTargetLabel = loginType === 'sms' ? '手机号' : '邮箱';
  const forgotPasswordTargetLabel =
    accountType === 'email' ? '邮箱找回' : accountType === 'mobile' ? '短信找回' : '邮箱 / 手机号';
  const loginNotice =
    location.state &&
    typeof location.state === 'object' &&
    'message' in location.state &&
    typeof location.state.message === 'string'
      ? location.state.message
      : null;

  if (session) {
    return <Navigate to="/" replace />;
  }

  const handleSendCode = async (scene: 'login' | 'reset_password') => {
    if (!account.trim() || cooldownSeconds > 0) {
      return;
    }

    const validation = validateVerificationAccount(account, scene === 'login' ? requiredAccountType : null);
    if (validation.message || !validation.accountType) {
      setError(validation.message ?? '验证码发送失败');
      setCodeMessage(null);
      return;
    }

    setSendingCode(true);
    setError(null);
    setCodeMessage(null);

    try {
      const response = await authService.sendCode({
        scene,
        account: account.trim(),
        accountType: validation.accountType
      });
      setCooldownSeconds(60);
      setCodeMessage(
        `${scene === 'login' ? '登录' : '重置'}验证码已发送至 ${response.maskedAccount}，有效期 ${response.expireIn} 秒。`
      );
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : '验证码发送失败');
    } finally {
      setSendingCode(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    recordTelemetryEvent({
      eventName: 'login_submit',
      page: '/login',
      metadata: {
        loginType,
        accountType: loginType === 'password' ? accountType ?? 'username' : requiredAccountType ?? 'unknown'
      }
    });
    setLoading(true);
    setError(null);
    setCodeMessage(null);

    try {
      const normalizedAccount = account.trim();
      if (loginType !== 'password') {
        const validation = validateVerificationAccount(normalizedAccount, requiredAccountType);
        if (validation.message) {
          setError(validation.message);
          return;
        }
      }

      await login({
        loginType,
        account: normalizedAccount,
        password: loginType === 'password' ? password : undefined,
        verificationCode: loginType === 'password' ? undefined : verificationCode
      });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '登录失败');
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPasswordSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setCodeMessage(null);

    const validation = validateVerificationAccount(account);
    if (validation.message || !validation.accountType) {
      setError(validation.message ?? '找回密码仅支持绑定邮箱或手机号');
      return;
    }

    if (!resetChallenge) {
      setCreatingResetChallenge(true);
      try {
        const response = await authService.createPasswordResetChallenge({
          account: account.trim(),
          accountType: validation.accountType,
          verificationCode
        });
        setResetChallenge({
          ...response,
          account: account.trim()
        });
        setCodeMessage(`重置挑战已创建，请在 ${response.expireIn} 秒内设置新密码。`);
      } catch (submitError) {
        setError(submitError instanceof Error ? submitError.message : '创建重置挑战失败');
      } finally {
        setCreatingResetChallenge(false);
      }
      return;
    }

    setResettingPassword(true);
    try {
      await authService.resetPassword({
        challengeId: resetChallenge.challengeId,
        account: resetChallenge.account,
        verificationCode,
        newPassword,
        confirmPassword
      });
      setAuthView('login');
      setLoginType('password');
      setResetChallenge(null);
      setPassword('');
      setVerificationCode('');
      setNewPassword('');
      setConfirmPassword('');
      setCodeMessage('密码已重置，请使用新密码重新登录。');
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : '密码重置失败');
    } finally {
      setResettingPassword(false);
    }
  };

  const switchToLogin = () => {
    setAuthView('login');
    setLoginType('password');
    setResetChallenge(null);
    setNewPassword('');
    setConfirmPassword('');
    setError(null);
    setCodeMessage(null);
  };

  const switchToForgotPassword = () => {
    setAuthView('forgot_password');
    setResetChallenge(null);
    setPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setVerificationCode('123456');
    setError(null);
    setCodeMessage(null);
  };

  return (
    <div className="auth-layout">
      <section className="auth-hero card">
        <Badge tone={isMock ? 'warning' : 'success'}>{isMock ? 'Mock 模式' : 'Live 模式'}</Badge>
        <h1>{appEnv.appTitle}</h1>
        <p className="muted">
          面向云服务企业的工业级多智能体用户端，覆盖 7x24 客服、账单查询、技术支持、备案咨询、营销推广与深度研究。
        </p>
        <ul className="feature-list">
          <li>支持密码、短信验证码、邮箱验证码三种登录模式</li>
          <li>支持找回密码 challenge + 重置密码流程，对齐 `/api/v1/auth/password/*`</li>
          <li>支持 SSE 流式对话、Agent 展示、Tool 调用状态</li>
          <li>默认启用本地 mock 数据，后端未完成时也可演示整条用户链路</li>
        </ul>
      </section>

      <section className="auth-card card">
        <div className="stack stack--sm">
          <div>
            <p className="page-header__eyebrow">用户登录</p>
            <h2>{authView === 'login' ? '进入 SmartCloud-X 控制台' : '找回并重置密码'}</h2>
            <p className="muted">当前 API 网关：{appEnv.apiBaseUrl}</p>
          </div>

          {authView === 'login' ? (
            <div className="segmented-control" role="tablist" aria-label="登录方式">
              {(Object.keys(loginTypeLabels) as LoginType[]).map((type) => (
                <button
                  key={type}
                  type="button"
                  className={`segmented-control__item${type === loginType ? ' segmented-control__item--active' : ''}`}
                  onClick={() => {
                    setLoginType(type);
                    setError(null);
                    setCodeMessage(null);
                  }}
                >
                  {loginTypeLabels[type]}
                </button>
              ))}
            </div>
          ) : (
            <div className="card service-note">
              <span className="muted">重置流程</span>
              <strong>{resetChallenge ? '第二步：提交新密码' : '第一步：校验验证码并创建 challenge'}</strong>
              <button type="button" className="button button--ghost" onClick={switchToLogin}>
                返回登录
              </button>
            </div>
          )}
        </div>

        {authView === 'login' ? (
          <form className="stack" onSubmit={handleSubmit}>
            <label className="field">
              <span>账号</span>
              <input
                value={account}
                onChange={(event) => setAccount(event.target.value)}
                placeholder={
                  loginType === 'password'
                    ? '邮箱 / 手机号 / 用户名'
                    : loginType === 'sms'
                      ? '请输入绑定手机号'
                      : '请输入绑定邮箱'
                }
              />
            </label>

            {loginType === 'password' ? (
              <label className="field">
                <span>密码</span>
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="请输入密码"
                />
              </label>
            ) : (
              <div className="grid grid--2">
                <label className="field">
                  <span>{loginType === 'sms' ? '短信验证码' : '邮箱验证码'}</span>
                  <input
                    value={verificationCode}
                    onChange={(event) => setVerificationCode(event.target.value)}
                    placeholder="请输入 6 位验证码"
                  />
                </label>
                <div className="card service-note">
                  <span className="muted">发送目标</span>
                  <strong>{loginCodeTargetLabel}</strong>
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => void handleSendCode('login')}
                    disabled={sendingCode || !account.trim() || cooldownSeconds > 0}
                  >
                    {sendingCode ? '发送中...' : cooldownSeconds > 0 ? `${cooldownSeconds}s 后重试` : '发送验证码'}
                  </button>
                </div>
              </div>
            )}

            {showCodeActions ? (
              <p className="muted">
                对齐 `/api/v1/auth/send-code` 与多形态 `/api/v1/auth/login` 合同，并在前端先校验验证码通道与账号类型是否匹配。
              </p>
            ) : null}

            {isMock ? <p className="muted">Mock 默认密码：`smartcloud-demo`；验证码：`123456`。</p> : null}
            {loginNotice ? <div className="success-banner">{loginNotice}</div> : null}
            {codeMessage ? <div className="success-banner">{codeMessage}</div> : null}
            {error ? <div className="error-banner">{error}</div> : null}

            <button type="submit" className="button button--primary button--block" disabled={loading}>
              {loading ? '登录中...' : '登录并进入控制台'}
            </button>
            <button type="button" className="button button--ghost button--block" onClick={switchToForgotPassword}>
              忘记密码？通过验证码重置
            </button>
          </form>
        ) : (
          <form className="stack" onSubmit={handleForgotPasswordSubmit}>
            <label className="field">
              <span>账号</span>
              <input value={account} onChange={(event) => setAccount(event.target.value)} placeholder="请输入绑定邮箱或手机号" />
            </label>

            <div className="grid grid--2">
              <label className="field">
                <span>验证码</span>
                <input
                  value={verificationCode}
                  onChange={(event) => setVerificationCode(event.target.value)}
                  placeholder="请输入找回密码验证码"
                />
              </label>
              <div className="card service-note">
                <span className="muted">验证通道</span>
                <strong>{forgotPasswordTargetLabel}</strong>
                <button
                  type="button"
                  className="button button--ghost"
                  onClick={() => void handleSendCode('reset_password')}
                  disabled={sendingCode || !account.trim() || cooldownSeconds > 0}
                >
                  {sendingCode ? '发送中...' : cooldownSeconds > 0 ? `${cooldownSeconds}s 后重试` : '发送重置验证码'}
                </button>
              </div>
            </div>

            {resetChallenge ? (
              <>
                <div className="success-banner">
                  challenge_id：{resetChallenge.challengeId}（{resetChallenge.expireIn} 秒内有效）
                </div>
                <div className="grid grid--2">
                  <label className="field">
                    <span>新密码</span>
                    <input
                      type="password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                      placeholder="请输入新密码"
                    />
                  </label>
                  <label className="field">
                    <span>确认新密码</span>
                    <input
                      type="password"
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                      placeholder="请再次输入新密码"
                    />
                  </label>
                </div>
                <p className="muted">将调用 `/api/v1/auth/password/reset` 完成最终密码重置，成功后请重新登录。</p>
              </>
            ) : (
              <p className="muted">
                先调用 `/api/v1/auth/password/forgot` 创建一次性重置 challenge，再输入新密码完成 `/api/v1/auth/password/reset`。
              </p>
            )}

            {isMock ? <p className="muted">Mock 默认找回验证码：`123456`。</p> : null}
            {loginNotice ? <div className="success-banner">{loginNotice}</div> : null}
            {codeMessage ? <div className="success-banner">{codeMessage}</div> : null}
            {error ? <div className="error-banner">{error}</div> : null}

            <button
              type="submit"
              className="button button--primary button--block"
              disabled={creatingResetChallenge || resettingPassword}
            >
              {resetChallenge
                ? resettingPassword
                  ? '重置中...'
                  : '提交新密码'
                : creatingResetChallenge
                  ? '校验中...'
                  : '校验验证码并创建挑战'}
            </button>
            <button type="button" className="button button--ghost button--block" onClick={switchToLogin}>
              返回登录页
            </button>
          </form>
        )}
      </section>
    </div>
  );
}
