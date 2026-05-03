import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, AlertTriangle, CheckCircle2, FileText, Globe, ShieldCheck, User } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Empty, Loading } from "@/components/ui/Empty";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { businessApis } from "@/lib/sdk";
import { formatDate } from "@/lib/format";

const STEPS = [
  { key: "materials_pending", label: "材料准备" },
  { key: "submitted",         label: "已提交" },
  { key: "reviewing",         label: "审核中" },
  { key: "approved",          label: "已通过" },
];

export default function IcpDetailPage() {
  const { applicationNo } = useParams();
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: ["icp", "detail", applicationNo],
    enabled: !!applicationNo,
    queryFn: async () => {
      const list = await businessApis.icp.listIcpApplications();
      return list.find((a) => a.applicationNo === applicationNo) ?? null;
    },
  });

  if (query.isLoading) return <PageContainer><Loading /></PageContainer>;
  if (!query.data) return <PageContainer><Empty title="未找到此申请" /></PageContainer>;

  const a = query.data;
  const stepIdx = STEPS.findIndex((s) => s.key === a.status);
  const currentStepIdx = stepIdx === -1 ? 1 : stepIdx;

  return (
    <PageContainer>
      <PageHeader
        title={a.websiteName || a.domain}
        description={
          <span className="inline-flex items-center gap-2 font-mono text-xs">
            申请号 <span className="text-brand-600">{a.applicationNo}</span>
            <StatusBadge status={a.status} />
          </span>
        }
        breadcrumb={[{ label: "业务中心" }, { label: "ICP 备案", to: "/icp" }, { label: a.applicationNo }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/icp")}>返回</Button>}
      />

      <Card className="mb-5">
        <CardHeader title="处理进度" description="按阶段跟踪备案审核状态" />
        <div className="flex items-center">
          {STEPS.map((s, idx) => {
            const active = idx === currentStepIdx;
            const done = idx < currentStepIdx;
            return (
              <div key={s.key} className="flex flex-1 items-center gap-2">
                <div className="flex flex-col items-center">
                  <div className={`flex size-9 items-center justify-center rounded-full text-sm font-medium ${
                    done ? "bg-success-500 text-white" : active ? "bg-brand-500 text-white shadow-lg shadow-brand-500/30" : "bg-slate-100 text-slate-400"
                  }`}>
                    {done ? <CheckCircle2 className="size-5" /> : idx + 1}
                  </div>
                  <div className={`mt-2 text-xs ${active ? "font-medium text-slate-900" : "text-slate-500"}`}>{s.label}</div>
                </div>
                {idx < STEPS.length - 1 && <div className={`h-px flex-1 ${done ? "bg-success-500" : "bg-slate-200"}`} />}
              </div>
            );
          })}
        </div>
        {a.currentStep && (
          <div className="mt-4 rounded-lg bg-info-50 px-4 py-2.5 text-sm text-info-700">
            当前阶段：{a.currentStep}
          </div>
        )}
        {a.rejectReason && (
          <div className="mt-4 flex items-start gap-2 rounded-lg bg-danger-50 px-4 py-3 text-sm text-danger-700">
            <AlertTriangle className="size-4 shrink-0" />
            <div>
              <div className="font-medium">审核未通过</div>
              <div className="mt-0.5 text-xs">{a.rejectReason}</div>
            </div>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="备案信息" description="主体与网站基本信息" />
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Field icon={<Globe className="size-3.5" />} label="域名" value={a.domain} />
            <Field icon={<FileText className="size-3.5" />} label="网站名称" value={a.websiteName} />
            <Field icon={<ShieldCheck className="size-3.5" />} label="主体类型" value={a.subjectType === "enterprise" ? "企业" : "个人"} />
            <Field icon={<User className="size-3.5" />} label="联系人" value={a.contacts?.join("、") ?? "—"} />
            <Field label="提交时间" value={formatDate(a.submittedAt)} />
            <Field label="批准时间" value={formatDate(a.approvedAt)} />
          </div>
        </Card>

        <Card>
          <CardHeader title="材料清单" description="备案所需材料及状态" />
          <ul className="space-y-2">
            {a.materials.map((m, idx) => (
              <li key={idx} className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/50 px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm text-slate-700">{m.fileName}</div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-xs text-slate-400">
                    <Badge tone="neutral">{m.type}</Badge>
                    {m.required && <span className="text-danger-500">*必需</span>}
                  </div>
                </div>
                <StatusBadge status={m.status} dot={false} />
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </PageContainer>
  );
}

function Field({ icon, label, value }: { icon?: React.ReactNode; label: string; value?: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1 text-xs text-slate-500">{icon}{label}</div>
      <div className="mt-1 text-sm font-medium text-slate-900">{value || "—"}</div>
    </div>
  );
}
