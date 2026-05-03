import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, AlertTriangle, ArrowRight, CheckCircle2, FileText, Globe, ShieldCheck, X } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { businessApis } from "@/lib/sdk";
import { notifyError } from "@/lib/errors";
import type { IcpMaterialItem, IcpMaterialType, IcpMaterialCheckResult } from "@smartcloud-x/frontend-sdk/web-user";
import { cn } from "@/lib/cn";

type SubjectType = "enterprise" | "individual";

const ENTERPRISE_MATERIALS: { type: IcpMaterialType; name: string; required: boolean; desc: string }[] = [
  { type: "business_license",       name: "营业执照",            required: true,  desc: "工商局核发的营业执照彩色扫描件" },
  { type: "domain_certificate",     name: "域名证书",            required: true,  desc: "域名注册商出具的域名所有权证书" },
  { type: "website_responsible_id", name: "网站负责人身份证",    required: true,  desc: "网站负责人身份证正反面扫描件" },
  { type: "personal_id" as IcpMaterialType, name: "法人身份证",  required: true,  desc: "企业法定代表人身份证正反面" },
];

const INDIVIDUAL_MATERIALS: { type: IcpMaterialType; name: string; required: boolean; desc: string }[] = [
  { type: "personal_id",            name: "本人身份证",          required: true,  desc: "网站负责人身份证正反面扫描件" },
  { type: "domain_certificate",     name: "域名证书",            required: true,  desc: "域名注册商出具的域名所有权证书" },
];

export default function IcpPrecheckPage() {
  const navigate = useNavigate();
  const [subjectType, setSubjectType] = useState<SubjectType>("enterprise");
  const [prepared, setPrepared] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<IcpMaterialCheckResult | null>(null);

  const list = subjectType === "enterprise" ? ENTERPRISE_MATERIALS : INDIVIDUAL_MATERIALS;

  const checkMut = useMutation({
    mutationFn: () => {
      const materials: IcpMaterialItem[] = list.map((m) => ({
        fileName: m.name,
        type: m.type,
        required: m.required,
        status: prepared.has(m.type) ? "prepared" : "missing",
      }));
      return businessApis.icp.checkIcpMaterials({ subjectType, materials });
    },
    onSuccess: (r) => setResult(r),
    onError: (e) => notifyError(e, "校验失败"),
  });

  function toggle(t: string) {
    setPrepared((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
    setResult(null);
  }

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="ICP 材料预校验"
        description="预先检查备案所需材料是否齐全，提交前更省心"
        breadcrumb={[{ label: "业务中心" }, { label: "ICP 备案", to: "/icp" }, { label: "材料预校验" }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/icp")}>返回</Button>}
      />

      <Card>
        <CardHeader title="主体类型" description="选择申请备案的主体类型" />
        <div className="grid grid-cols-2 gap-3">
          {(["enterprise", "individual"] as const).map((t) => {
            const active = t === subjectType;
            return (
              <button
                key={t}
                type="button"
                onClick={() => { setSubjectType(t); setPrepared(new Set()); setResult(null); }}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-xl border p-4 text-left transition focus-ring",
                  active ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300",
                )}
              >
                <div className={cn(
                  "flex size-10 items-center justify-center rounded-lg",
                  active ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-500",
                )}>
                  {t === "enterprise" ? <ShieldCheck className="size-5" /> : <FileText className="size-5" />}
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-900">{t === "enterprise" ? "企业主体" : "个人主体"}</div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {t === "enterprise" ? "需要营业执照、法人身份证等材料" : "仅需本人身份证、域名证书"}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="材料清单" description="勾选你已经准备好的材料" />
        <ul className="space-y-2">
          {list.map((m) => {
            const checked = prepared.has(m.type);
            return (
              <li key={m.type}>
                <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-slate-100 p-3 transition hover:bg-slate-50/60">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(m.type)}
                    className="mt-1 size-4 rounded border-slate-300 text-brand-500 focus:ring-brand-500"
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-slate-900">{m.name}</span>
                      {m.required && <span className="text-xs text-danger-500">*必需</span>}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">{m.desc}</div>
                  </div>
                </label>
              </li>
            );
          })}
        </ul>
      </Card>

      {result && (
        <Card className={cn("mt-5", result.passed ? "border-success-200 bg-success-50/50" : "border-warning-200 bg-warning-50/50")}>
          <div className="flex items-start gap-3">
            {result.passed ? (
              <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-success-600" />
            ) : (
              <AlertTriangle className="mt-0.5 size-6 shrink-0 text-warning-600" />
            )}
            <div className="flex-1">
              <div className={cn("text-base font-semibold", result.passed ? "text-success-700" : "text-warning-700")}>
                {result.passed ? "材料完整，可以提交申请" : "还有部分材料需要补充"}
              </div>
              {result.issues?.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {result.issues.map((iss, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-sm text-slate-700">
                      {iss.severity === "error" ? <X className="mt-0.5 size-3.5 shrink-0 text-danger-500" /> : <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning-500" />}
                      <span>{iss.message}{iss.field && <span className="text-slate-400">（{iss.field}）</span>}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={() => navigate("/icp")}>取消</Button>
        <Button onClick={() => checkMut.mutate()} loading={checkMut.isPending}>开始校验</Button>
        <Button variant="primary" rightIcon={<ArrowRight className="size-3.5" />} onClick={() => navigate(`/icp/new?subjectType=${subjectType}`)} disabled={!result?.passed}>
          继续申请
        </Button>
      </div>
    </PageContainer>
  );
}
