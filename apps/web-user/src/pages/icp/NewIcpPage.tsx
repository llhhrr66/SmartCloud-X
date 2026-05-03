import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, AlertCircle, FileText, Globe, Plus, Send, Trash2, User } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { businessApis } from "@/lib/sdk";
import { notifyError, notifySuccess } from "@/lib/errors";
import type { IcpMaterialItem, IcpMaterialType } from "@smartcloud-x/frontend-sdk/web-user";

const ENT_MATERIAL_TYPES: IcpMaterialType[] = ["business_license", "domain_certificate", "website_responsible_id", "personal_id"];
const IND_MATERIAL_TYPES: IcpMaterialType[] = ["personal_id", "domain_certificate"];

const TYPE_LABEL: Record<string, string> = {
  business_license: "营业执照",
  domain_certificate: "域名证书",
  website_responsible_id: "网站负责人身份证",
  personal_id: "身份证",
};

export default function NewIcpPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [subjectType, setSubjectType] = useState<"enterprise" | "individual">("enterprise");
  const [domain, setDomain] = useState("");
  const [websiteName, setWebsiteName] = useState("");
  const [contacts, setContacts] = useState<string[]>([""]);
  const [materials, setMaterials] = useState<IcpMaterialItem[]>([]);

  useEffect(() => {
    const t = params.get("subjectType");
    if (t === "enterprise" || t === "individual") setSubjectType(t);
  }, [params]);

  const types = subjectType === "enterprise" ? ENT_MATERIAL_TYPES : IND_MATERIAL_TYPES;

  const submitMut = useMutation({
    mutationFn: () => businessApis.icp.createIcpApplication({
      subjectType,
      domain: domain.trim(),
      websiteName: websiteName.trim(),
      contacts: contacts.map((c) => c.trim()).filter(Boolean),
      materials,
    }),
    onSuccess: (a) => {
      notifySuccess("ICP 申请已提交");
      navigate(`/icp/${a.applicationNo}`);
    },
    onError: (e) => notifyError(e, "提交失败"),
  });

  function addMaterial(type: IcpMaterialType) {
    setMaterials((prev) => [
      ...prev,
      { type, fileName: TYPE_LABEL[type] ?? "材料", required: true, status: "prepared" },
    ]);
  }
  function removeMaterial(idx: number) {
    setMaterials((prev) => prev.filter((_, i) => i !== idx));
  }

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="新建 ICP 申请"
        description="提交备案申请后，运营团队会在 1-3 个工作日初审"
        breadcrumb={[{ label: "业务中心" }, { label: "ICP 备案", to: "/icp" }, { label: "新建申请" }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/icp")}>返回</Button>}
      />

      <Card>
        <CardHeader title="基本信息" description="主体与网站信息" />
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="label">主体类型</label>
            <div className="grid grid-cols-2 gap-2">
              {(["enterprise", "individual"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setSubjectType(t)}
                  className={`cursor-pointer rounded-lg border px-3 py-2 text-sm transition focus-ring ${
                    subjectType === t ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-200 bg-white text-slate-700 hover:border-slate-300"
                  }`}
                >{t === "enterprise" ? "企业" : "个人"}</button>
              ))}
            </div>
          </div>
          <Input
            label="备案域名"
            placeholder="example.com"
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            prefix={<Globe className="size-4" />}
          />
          <Input
            label="网站名称"
            placeholder="例如：智云科技官网"
            value={websiteName}
            onChange={(e) => setWebsiteName(e.target.value)}
            prefix={<FileText className="size-4" />}
            containerClassName="col-span-2"
          />
        </div>

        <div className="mt-5">
          <div className="label flex items-center justify-between">
            <span>联系人（手机号或邮箱）</span>
            <button
              type="button"
              onClick={() => setContacts((p) => [...p, ""])}
              className="inline-flex cursor-pointer items-center gap-1 text-xs text-brand-600 hover:underline"
            >
              <Plus className="size-3" />添加
            </button>
          </div>
          <div className="space-y-2">
            {contacts.map((c, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  containerClassName="flex-1"
                  prefix={<User className="size-4" />}
                  placeholder="手机号 / 邮箱"
                  value={c}
                  onChange={(e) => setContacts((p) => p.map((v, idx) => (idx === i ? e.target.value : v)))}
                />
                {contacts.length > 1 && (
                  <button
                    type="button"
                    aria-label="移除联系人"
                    className="icon-btn cursor-pointer hover:bg-danger-50 hover:text-danger-600"
                    onClick={() => setContacts((p) => p.filter((_, idx) => idx !== i))}
                  >
                    <Trash2 className="size-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="材料上传" description="将本次申请涉及的所有材料上传完整" />
        <div className="space-y-2">
          {materials.map((m, i) => (
            <div key={i} className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50/40 px-3 py-2">
              <FileText className="size-4 text-slate-400" />
              <div className="flex-1">
                <div className="text-sm text-slate-700">{m.fileName}</div>
                <div className="mt-0.5 text-xs text-slate-400">{TYPE_LABEL[m.type as string] ?? m.type}</div>
              </div>
              <button
                type="button"
                aria-label="移除材料"
                className="icon-btn cursor-pointer hover:bg-danger-50 hover:text-danger-600"
                onClick={() => removeMaterial(i)}
              >
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {types.map((t) => (
            <Button
              key={t}
              size="sm"
              variant="secondary"
              leftIcon={<Plus className="size-3" />}
              onClick={() => addMaterial(t)}
            >
              {TYPE_LABEL[t] ?? t}
            </Button>
          ))}
        </div>

        <div className="mt-5 rounded-lg bg-info-50 p-4 text-xs text-info-700">
          <div className="mb-1 inline-flex items-center gap-1 font-medium"><AlertCircle className="size-3.5" />温馨提示</div>
          <ul className="ml-5 list-disc space-y-1">
            <li>所有图片需为彩色扫描件，文字清晰，无遮挡</li>
            <li>身份证类材料需上传正反两面</li>
            <li>建议先做<a className="text-brand-600 hover:underline" href="/icp/precheck">材料预校验</a>再提交申请</li>
          </ul>
        </div>

        <div className="mt-5 flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button variant="secondary" onClick={() => navigate("/icp")}>取消</Button>
          <Button
            onClick={() => submitMut.mutate()}
            loading={submitMut.isPending}
            disabled={!domain.trim() || !websiteName.trim() || !materials.length}
            leftIcon={<Send className="size-3.5" />}
          >提交申请</Button>
        </div>
      </Card>
    </PageContainer>
  );
}
