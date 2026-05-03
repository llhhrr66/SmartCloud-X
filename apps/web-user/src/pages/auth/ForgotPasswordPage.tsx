import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, AtSign, Check, Lock, MailCheck, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { AuthLayout } from "./AuthLayout";
import { authService } from "@/lib/auth-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import type { AccountType } from "@smartcloud-x/frontend-sdk/web-user";
import { cn } from "@/lib/cn";

type Step = 1 | 2 | 3;

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(1);
  const [account, setAccount] = useState("");
  const [code, setCode] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [pwd, setPwd] = useState("");
  const [pwd2, setPwd2] = useState("");
  const [countdown, setCountdown] = useState(0);

  useEffect(() => {
    if (countdown <= 0) return;
    const t = setTimeout(() => setCountdown((n) => n - 1), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  const accountType: AccountType = /@/.test(account) ? "email" : "mobile";

  const sendCodeMut = useMutation({
    mutationFn: () => authService.sendVerificationCode({ scene: "reset_password", account, accountType }),
    onSuccess: (resp) => {
      notifySuccess(`验证码已发送至 ${resp.maskedAccount}`);
      setCountdown(60);
    },
    onError: (err) => notifyError(err, "发送验证码失败"),
  });

  const challengeMut = useMutation({
    mutationFn: () => authService.createPasswordResetChallenge({ account, accountType, verificationCode: code }),
    onSuccess: (resp) => {
      setChallengeId(resp.challengeId);
      setStep(2);
    },
    onError: (err) => notifyError(err, "验证码校验失败"),
  });

  const resetMut = useMutation({
    mutationFn: () => authService.resetPassword({ challengeId, account, verificationCode: code, newPassword: pwd, confirmPassword: pwd2 }),
    onSuccess: () => {
      setStep(3);
    },
    onError: (err) => notifyError(err, "重置密码失败"),
  });

  return (
    <AuthLayout>
      <div className="card p-8">
        <Link to="/login" className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-brand-600">
          <ArrowLeft className="size-3.5" />返回登录
        </Link>

        <h2 className="text-2xl font-semibold text-slate-900">找回密码</h2>
        <p className="mt-1.5 text-sm text-slate-500">通过手机或邮箱验证身份后重置密码</p>

        <Stepper step={step} />

        {step === 1 && (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); challengeMut.mutate(); }}>
            <Input
              label="账号"
              placeholder="注册时的手机号或邮箱"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              prefix={<AtSign className="size-4" />}
            />
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
                {countdown > 0 ? `${countdown}s` : sendCodeMut.isPending ? "发送中" : "获取验证码"}
              </Button>
            </div>
            <Button type="submit" size="lg" block loading={challengeMut.isPending}>
              下一步
            </Button>
          </form>
        )}

        {step === 2 && (
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); resetMut.mutate(); }}>
            <Input
              label="新密码"
              type="password"
              placeholder="8-32 位，包含字母与数字"
              value={pwd}
              onChange={(e) => setPwd(e.target.value)}
              prefix={<Lock className="size-4" />}
              hint="建议使用大小写字母 + 数字 + 符号组合"
            />
            <Input
              label="确认新密码"
              type="password"
              placeholder="请再次输入"
              value={pwd2}
              onChange={(e) => setPwd2(e.target.value)}
              prefix={<ShieldCheck className="size-4" />}
              error={pwd && pwd2 && pwd !== pwd2 ? "两次输入不一致" : undefined}
            />
            <div className="flex gap-2">
              <Button type="button" variant="secondary" block onClick={() => setStep(1)}>上一步</Button>
              <Button type="submit" block loading={resetMut.isPending} disabled={!pwd || pwd !== pwd2}>
                提交重置
              </Button>
            </div>
          </form>
        )}

        {step === 3 && (
          <div className="py-4 text-center">
            <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full bg-success-50 text-success-600">
              <Check className="size-7" />
            </div>
            <h3 className="text-lg font-semibold text-slate-900">密码已重置</h3>
            <p className="mt-1.5 text-sm text-slate-500">请使用新密码重新登录</p>
            <Button className="mt-6" size="lg" block onClick={() => navigate("/login", { replace: true })}>
              立即登录
            </Button>
          </div>
        )}
      </div>
    </AuthLayout>
  );
}

function Stepper({ step }: { step: Step }) {
  const steps = ["身份验证", "设置新密码", "完成"];
  return (
    <div className="my-6 flex items-center gap-2">
      {steps.map((label, idx) => {
        const active = idx + 1 === step;
        const done = idx + 1 < step;
        return (
          <div key={label} className="flex flex-1 items-center gap-2">
            <div className={cn(
              "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-medium",
              done ? "bg-success-500 text-white" : active ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-400",
            )}>
              {done ? <Check className="size-4" /> : idx + 1}
            </div>
            <span className={cn("text-xs", active ? "font-medium text-slate-700" : "text-slate-400")}>{label}</span>
            {idx < steps.length - 1 && <div className={cn("h-px flex-1", done ? "bg-success-500" : "bg-slate-200")} />}
          </div>
        );
      })}
    </div>
  );
}
