import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Image as ImageIcon, Send, Sparkles } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { marketingService } from "@/lib/marketing-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import { cn } from "@/lib/cn";

const SIZES = [
  { value: "1080x1920", label: "竖屏 9:16", desc: "朋友圈、小红书" },
  { value: "1080x1080", label: "正方形 1:1", desc: "公众号、微博" },
  { value: "1920x1080", label: "横屏 16:9", desc: "网页 Banner" },
  { value: "1242x2208", label: "Hi-Res 9:16", desc: "应用启动图" },
];

export default function NewPosterPage() {
  const navigate = useNavigate();
  const campaigns = useQuery({
    queryKey: ["marketing", "campaigns", "for-poster"],
    queryFn: () => marketingService.listCampaigns(1, 50),
  });

  const [campaignId, setCampaignId] = useState("");
  const [theme, setTheme] = useState("");
  const [slogan, setSlogan] = useState("");
  const [size, setSize] = useState(SIZES[0].value);

  const createMut = useMutation({
    mutationFn: () => marketingService.createPosterTask({ campaignId, theme, slogan, size }),
    onSuccess: (t) => {
      notifySuccess("海报任务已创建");
      navigate(`/marketing/posters/${t.taskId}`);
    },
    onError: (e) => notifyError(e, "创建任务失败"),
  });

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="新建海报任务"
        description="填写主题与口号，AI 会自动产出多张可用海报"
        breadcrumb={[{ label: "营销中心" }, { label: "AI 海报工作室", to: "/marketing/posters" }, { label: "新建任务" }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/marketing/posters")}>返回</Button>}
      />

      <Card>
        <CardHeader title="任务信息" description="详细的描述会让生成结果更贴合预期" />
        <div className="space-y-4">
          <div>
            <label className="label">关联活动</label>
            <select
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
              className="input cursor-pointer"
            >
              <option value="">请选择活动…</option>
              {campaigns.data?.items.map((c) => (
                <option key={c.campaignId} value={c.campaignId}>{c.name}</option>
              ))}
            </select>
          </div>
          <Input
            label="海报主题"
            placeholder="例如：双 11 云服务大促"
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            hint="一句话描述海报传达的核心信息"
          />
          <div>
            <label className="label">主标语</label>
            <textarea
              value={slogan}
              onChange={(e) => setSlogan(e.target.value)}
              rows={3}
              placeholder="海报上最醒目的标语，建议 12-25 字"
              className="input min-h-[80px]"
            />
          </div>
          <div>
            <label className="label">尺寸规格</label>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {SIZES.map((s) => (
                <button
                  key={s.value}
                  type="button"
                  onClick={() => setSize(s.value)}
                  className={cn(
                    "cursor-pointer rounded-lg border p-3 text-left transition focus-ring",
                    size === s.value ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300",
                  )}
                >
                  <div className="flex size-12 items-center justify-center rounded-md bg-slate-100">
                    <ImageIcon className="size-5 text-slate-400" />
                  </div>
                  <div className="mt-2 text-sm font-medium text-slate-900">{s.label}</div>
                  <div className="mt-0.5 font-mono text-[11px] text-slate-500">{s.value}</div>
                  <div className="mt-1 text-[11px] text-slate-400">{s.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
            <Button variant="secondary" onClick={() => navigate("/marketing/posters")}>取消</Button>
            <Button
              loading={createMut.isPending}
              disabled={!campaignId || !theme.trim() || !slogan.trim()}
              onClick={() => createMut.mutate()}
              leftIcon={<Sparkles className="size-3.5" />}
            >提交生成</Button>
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}
