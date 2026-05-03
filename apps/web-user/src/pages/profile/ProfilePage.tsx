import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Building2, Globe, Languages, Mail, Phone, Save, ShieldCheck, User } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Avatar } from "@/components/ui/Avatar";
import { Badge } from "@/components/ui/Badge";
import { authService } from "@/lib/auth-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import { useAuthStore, selectCurrentUser } from "@/stores/auth";
import { maskEmail, maskMobile } from "@/lib/format";

const TIMEZONES = ["Asia/Shanghai", "Asia/Hong_Kong", "Asia/Tokyo", "Asia/Singapore", "America/Los_Angeles", "Europe/London"];
const LOCALES = [
  { value: "zh-CN", label: "简体中文" },
  { value: "zh-TW", label: "繁體中文" },
  { value: "en-US", label: "English (US)" },
];

export default function ProfilePage() {
  const user = useAuthStore(selectCurrentUser);
  const setUser = useAuthStore((s) => s.setUser);

  const [name, setName] = useState(user?.name ?? "");
  const [locale, setLocale] = useState(user?.locale ?? "zh-CN");
  const [timeZone, setTimeZone] = useState(user?.timeZone ?? "Asia/Shanghai");
  const [avatarUrl, setAvatarUrl] = useState(user?.avatarUrl ?? "");

  useEffect(() => {
    if (!user) return;
    setName(user.name);
    setLocale(user.locale);
    setTimeZone(user.timeZone);
    setAvatarUrl(user.avatarUrl ?? "");
  }, [user]);

  const updateMut = useMutation({
    mutationFn: () => authService.updateProfile({ name, avatarUrl: avatarUrl || undefined, locale, timeZone }),
    onSuccess: (next) => {
      setUser(next);
      notifySuccess("个人资料已更新");
    },
    onError: (e) => notifyError(e, "更新失败"),
  });

  return (
    <PageContainer>
      <PageHeader
        title="个人资料"
        description="管理你在 SmartCloud-X 的基本信息"
        breadcrumb={[{ label: "个人中心" }, { label: "个人资料" }]}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card>
          <CardHeader title="头像与身份" />
          <div className="flex flex-col items-center text-center">
            <Avatar name={user?.name ?? "用户"} src={avatarUrl} size="xl" />
            <div className="mt-3 text-base font-semibold text-slate-900">{user?.name ?? "—"}</div>
            <div className="mt-0.5 text-xs text-slate-500">{user?.email ?? "—"}</div>
            <div className="mt-2 flex flex-wrap items-center justify-center gap-1.5">
              <Badge tone="brand"><Building2 className="size-3" />租户 {user?.tenantId ?? "—"}</Badge>
              <Badge tone="success">已实名</Badge>
            </div>

            <div className="mt-5 w-full">
              <Input
                label="头像 URL"
                placeholder="留空使用默认字母头像"
                value={avatarUrl}
                onChange={(e) => setAvatarUrl(e.target.value)}
              />
              <Button block className="mt-3" variant="secondary">上传新头像</Button>
            </div>
          </div>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="基本信息" description="姓名、手机、邮箱与本地化偏好" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Input
              label="姓名"
              prefix={<User className="size-4" />}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <Input
              label="所属租户"
              prefix={<Building2 className="size-4" />}
              value={user?.tenantId ?? ""}
              disabled
              hint="租户由管理员维护"
            />
            <Input
              label="手机号"
              prefix={<Phone className="size-4" />}
              value={maskMobile(user?.mobile)}
              disabled
              suffix={<a href="/profile/security" className="text-xs text-brand-600 hover:underline">变更</a>}
            />
            <Input
              label="邮箱"
              prefix={<Mail className="size-4" />}
              value={maskEmail(user?.email)}
              disabled
              suffix={<a href="/profile/security" className="text-xs text-brand-600 hover:underline">变更</a>}
            />
            <div>
              <label className="label">语言</label>
              <select value={locale} onChange={(e) => setLocale(e.target.value)} className="input cursor-pointer">
                {LOCALES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
              </select>
            </div>
            <div>
              <label className="label">时区</label>
              <select value={timeZone} onChange={(e) => setTimeZone(e.target.value)} className="input cursor-pointer">
                {TIMEZONES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          <div className="mt-5 flex justify-end gap-2 border-t border-slate-100 pt-4">
            <Button
              loading={updateMut.isPending}
              onClick={() => updateMut.mutate()}
              leftIcon={<Save className="size-3.5" />}
            >保存修改</Button>
          </div>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title={<span className="inline-flex items-center gap-2"><ShieldCheck className="size-4 text-success-500" />我的权限</span>}
          description="当前账户拥有的权限码"
        />
        {user?.permissions?.length ? (
          <div className="flex flex-wrap gap-1.5">
            {user.permissions.map((p) => (
              <Badge key={p} tone="neutral">{p}</Badge>
            ))}
          </div>
        ) : (
          <div className="text-sm text-slate-500">暂无可见权限</div>
        )}
      </Card>
    </PageContainer>
  );
}
