import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, KeyRound, Smartphone, AtSign, Lock, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Tabs } from "@/components/ui/Tabs";
import { AuthLayout } from "./AuthLayout";
import { authService } from "@/lib/auth-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import type { AccountType, LoginType } from "@smartcloud-x/frontend-sdk/web-user";

type Mode = "password" | "sms";

export default function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("password");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [agreement, setAgreement] = useState(true);
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (countdown <= 0) return;
    const t = setTimeout(() => setCountdown((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  const accountType: AccountType = /@/.test(account) ? "email" : "mobile";

  const sendCodeMut = useMutation({
    mutationFn: () => authService.sendVerificationCode({ scene: "login", account, accountType }),
    onSuccess: (resp) => {
      notifySuccess(`验证码已发送至 ${resp.maskedAccount}`);
      setCountdown(60);
    },
    onError: (err) => notifyError(err, "发送验证码失败"),
  });

  const loginMut = useMutation({
    mutationFn: () => {
      const loginType: LoginType = mode === "password" ? "password" : accountType === "email" ? "email_code" : "sms";
      return authService.login({
        loginType,
        account,
        password: mode === "password" ? password : undefined,
        verificationCode: mode === "sms" ? code : undefined,
      });
    },
    onSuccess: () => {
      notifySuccess("登录成功");
      navigate("/", { replace: true });
    },
    onError: (err) => notifyError(err, "登录失败"),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!agreement) {
      notifyError(new Error("请先勾选协议"));
      return;
    }
    if (!account.trim()) {
      notifyError(new Error("请输入账号"));
      return;
    }
    loginMut.mutate();
  }

  return (
    <AuthLayout>
      <div className="card p-8">
        <div className="mb-6">
          <h2 className="text-2xl font-semibold text-slate-900">欢迎回来 👋</h2>
          <p className="mt-1.5 text-sm text-slate-500">登录 SmartCloud-X 控制台，开启智能云服务</p>
        </div>

        <Tabs
          variant="card"
          value={mode}
          onChange={(v) => setMode(v as Mode)}
          items={[
            { key: "password", label: <span className="inline-flex items-center gap-1.5"><KeyRound className="size-3.5" />密码登录</span> },
            { key: "sms",      label: <span className="inline-flex items-center gap-1.5"><Smartphone className="size-3.5" />验证码登录</span> },
          ]}
          className="mb-5"
        />

        <form onSubmit={submit} className="space-y-4">
          <Input
            label="账号"
            placeholder="手机号或邮箱"
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            prefix={<AtSign className="size-4" />}
            autoComplete="username"
          />

          {mode === "password" ? (
            <Input
              label="密码"
              type={showPwd ? "text" : "password"}
              placeholder="请输入密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              prefix={<Lock className="size-4" />}
              suffix={
                <button type="button" onClick={() => setShowPwd((v) => !v)} className="hover:text-slate-600">
                  {showPwd ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              }
              autoComplete="current-password"
            />
          ) : (
            <div className="flex items-end gap-2">
              <Input
                containerClassName="flex-1"
                label="验证码"
                placeholder="请输入 6 位验证码"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                prefix={<MailCheck className="size-4" />}
                maxLength={6}
                inputMode="numeric"
              />
              <Button
                type="button"
                variant="secondary"
                disabled={countdown > 0 || sendCodeMut.isPending || !account.trim()}
                onClick={() => sendCodeMut.mutate()}
                className="h-[38px]"
              >
                {countdown > 0 ? `${countdown}s 后重发` : sendCodeMut.isPending ? "发送中" : "获取验证码"}
              </Button>
            </div>
          )}

          <div className="flex items-center justify-between text-xs">
            <label className="inline-flex items-center gap-1.5 text-slate-600 cursor-pointer">
              <input
                type="checkbox"
                checked={agreement}
                onChange={(e) => setAgreement(e.target.checked)}
                className="size-3.5 rounded border-slate-300 text-brand-500 focus:ring-brand-500"
              />
              已阅读并同意《用户协议》《隐私政策》
            </label>
            <Link to="/forgot-password" className="text-brand-600 hover:underline">
              忘记密码？
            </Link>
          </div>

          <Button type="submit" size="lg" block loading={loginMut.isPending}>
            {loginMut.isPending ? "登录中…" : "登录"}
          </Button>

          <div className="text-center text-xs text-slate-500">
            还没有账号？<a className="text-brand-600 hover:underline" href="mailto:sales@smartcloud-x.example.com">联系销售开通</a>
          </div>
        </form>
      </div>
    </AuthLayout>
  );
}
