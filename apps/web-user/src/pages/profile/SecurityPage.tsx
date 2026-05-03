import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, KeyRound, Lock, LogOut, Mail, Phone, ShieldCheck, Smartphone } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { authService } from "@/lib/auth-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import { useAuthStore, selectCurrentUser } from "@/stores/auth";
import { formatDate, maskEmail, maskMobile } from "@/lib/format";

export default function SecurityPage() {
  const navigate = useNavigate();
  const user = useAuthStore(selectCurrentUser);
  const clear = useAuthStore((s) => s.clear);

  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");

  const changePwdMut = useMutation({
    mutationFn: () => authService.changePassword({ oldPassword: oldPwd, newPassword: newPwd, confirmPassword: confirmPwd }),
    onSuccess: () => {
      notifySuccess("密码已更新，请重新登录");
      authService.logout().finally(() => {
        clear();
        navigate("/login", { replace: true });
      });
    },
    onError: (e) => notifyError(e, "修改密码失败"),
  });

  return (
    <PageContainer>
      <PageHeader
        title="安全设置"
        description="账户密码、双因素认证、登录设备"
        breadcrumb={[{ label: "个人中心" }, { label: "安全设置" }]}
      />

      <Card>
        <CardHeader title={<span className="inline-flex items-center gap-2"><Lock className="size-4 text-brand-500" />修改密码</span>} description="建议每 90 天更新一次，使用大小写字母 + 数字 + 符号" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Input
            label="当前密码"
            type="password"
            placeholder="请输入当前密码"
            value={oldPwd}
            onChange={(e) => setOldPwd(e.target.value)}
            prefix={<KeyRound className="size-4" />}
          />
          <Input
            label="新密码"
            type="password"
            placeholder="至少 8 位"
            value={newPwd}
            onChange={(e) => setNewPwd(e.target.value)}
            prefix={<Lock className="size-4" />}
          />
          <Input
            label="确认新密码"
            type="password"
            placeholder="再次输入"
            value={confirmPwd}
            onChange={(e) => setConfirmPwd(e.target.value)}
            prefix={<ShieldCheck className="size-4" />}
            error={confirmPwd && newPwd !== confirmPwd ? "两次输入不一致" : undefined}
          />
        </div>
        <div className="mt-4 flex justify-end">
          <Button
            loading={changePwdMut.isPending}
            disabled={!oldPwd || !newPwd || newPwd !== confirmPwd}
            onClick={() => changePwdMut.mutate()}
          >更新密码</Button>
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader
          title={<span className="inline-flex items-center gap-2"><Smartphone className="size-4 text-brand-500" />双因素认证 (2FA)</span>}
          description="登录时除了密码外，还需要短信 / TOTP 验证码"
          extra={<Badge tone="warning">未启用</Badge>}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <SecurityToggle
            icon={<Smartphone className="size-4" />}
            title="短信验证"
            desc="登录时通过手机短信接收一次性验证码"
            enabled={false}
          />
          <SecurityToggle
            icon={<KeyRound className="size-4" />}
            title="身份验证器"
            desc="使用 Authenticator 等 TOTP 应用"
            enabled={false}
          />
          <SecurityToggle
            icon={<ShieldCheck className="size-4" />}
            title="安全密钥"
            desc="支持 WebAuthn 硬件密钥（如 YubiKey）"
            enabled={false}
          />
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="联系方式" description="账号绑定的手机号与邮箱，丢失可用于找回密码" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <ContactRow icon={<Phone className="size-4" />} label="绑定手机" value={maskMobile(user?.mobile) || "未绑定"} verified={Boolean(user?.mobile)} />
          <ContactRow icon={<Mail className="size-4" />}  label="绑定邮箱" value={maskEmail(user?.email)   || "未绑定"} verified={Boolean(user?.email)} />
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader
          title={<span className="inline-flex items-center gap-2"><LogOut className="size-4 text-slate-500" />近期登录设备</span>}
          description="本账号近期的登录情况"
        />
        <div className="overflow-x-auto">
          <table className="table">
            <thead>
              <tr>
                <th>登录时间</th>
                <th>IP 地址</th>
                <th>设备 / 浏览器</th>
                <th>位置</th>
                <th className="text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {[
                { time: new Date().toISOString(),                              ip: "192.168.10.1",  ua: "Chrome 132 / macOS",  location: "广州，广东，CN", current: true },
                { time: new Date(Date.now() - 86400_000).toISOString(),        ip: "203.0.113.45",  ua: "Safari 18 / iOS",     location: "深圳，广东，CN", current: false },
                { time: new Date(Date.now() - 3 * 86400_000).toISOString(),    ip: "198.51.100.7",  ua: "Edge 120 / Windows",  location: "上海，CN",       current: false },
              ].map((s) => (
                <tr key={s.time}>
                  <td className="text-slate-700">{formatDate(s.time)}</td>
                  <td className="font-mono text-xs">{s.ip}</td>
                  <td>{s.ua}</td>
                  <td className="text-slate-500">{s.location}</td>
                  <td className="text-right">
                    {s.current
                      ? <Badge tone="success">当前会话</Badge>
                      : <Button size="sm" variant="ghost">下线</Button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </PageContainer>
  );
}

function SecurityToggle({ icon, title, desc, enabled }: { icon: React.ReactNode; title: string; desc: string; enabled: boolean }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex size-9 items-center justify-center rounded-lg bg-slate-100 text-slate-500">{icon}</div>
      <div className="flex-1">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-900">{title}</span>
          <Badge tone={enabled ? "success" : "neutral"}>{enabled ? "已启用" : "未启用"}</Badge>
        </div>
        <div className="mt-0.5 text-xs text-slate-500">{desc}</div>
        <Button size="sm" variant="ghost" className="mt-2 -ml-2">{enabled ? "关闭" : "立即启用"}</Button>
      </div>
    </div>
  );
}

function ContactRow({ icon, label, value, verified }: { icon: React.ReactNode; label: string; value: string; verified: boolean }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-slate-100 bg-slate-50/40 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-white text-slate-500 shadow-sm">{icon}</div>
        <div>
          <div className="text-xs text-slate-500">{label}</div>
          <div className="text-sm font-medium text-slate-900">{value}</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {verified && <span className="inline-flex items-center gap-1 text-xs text-success-600"><CheckCircle2 className="size-3.5" />已验证</span>}
        <Button size="sm" variant="ghost">变更</Button>
      </div>
    </div>
  );
}
