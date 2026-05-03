import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Copy, Hash, Megaphone, RefreshCcw, Sparkles, Wand2 } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Empty, Loading } from "@/components/ui/Empty";
import { marketingService } from "@/lib/marketing-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import type { MarketingCopyRequest, MarketingCopyResult } from "@smartcloud-x/frontend-sdk/web-user";
import { cn } from "@/lib/cn";

const TONES: { value: MarketingCopyRequest["tone"]; label: string; desc: string }[] = [
  { value: "professional", label: "专业", desc: "稳重、可信，适合企业客户" },
  { value: "growth",       label: "增长", desc: "数据驱动，适合 ToB 增长场景" },
  { value: "launch",       label: "新品", desc: "热度感强，适合新品发布" },
];

export default function CopyGenerationPage() {
  const campaigns = useQuery({
    queryKey: ["marketing", "campaigns", "for-copy"],
    queryFn: () => marketingService.listCampaigns(1, 50),
  });

  const [campaignId, setCampaignId] = useState("");
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [tone, setTone] = useState<MarketingCopyRequest["tone"]>("professional");
  const [keyword, setKeyword] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);

  const [result, setResult] = useState<MarketingCopyResult | null>(null);

  const generateMut = useMutation({
    mutationFn: () => marketingService.generateCopy({ campaignId, topic, audience, tone, keywords }),
    onSuccess: (r) => setResult(r),
    onError: (e) => notifyError(e, "生成文案失败"),
  });

  function addKeyword() {
    const k = keyword.trim();
    if (!k) return;
    setKeywords((p) => [...new Set([...p, k])]);
    setKeyword("");
  }

  function copyAll() {
    if (!result) return;
    const text = `【${result.headline}】\n\n${result.summary}\n\n${result.body}\n\n${result.callToAction}`;
    navigator.clipboard.writeText(text).then(() => notifySuccess("已复制到剪贴板"));
  }

  return (
    <PageContainer>
      <PageHeader
        title="AI 营销文案生成"
        description="根据活动 + 受众生成多版本文案，可一键复用"
        breadcrumb={[{ label: "营销中心" }, { label: "AI 文案生成" }]}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader title={<span className="inline-flex items-center gap-2"><Wand2 className="size-4 text-brand-500" />生成参数</span>} />
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
              label="文案主题"
              placeholder="例如：双 11 云服务器 5 折优惠"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            />
            <Input
              label="目标受众"
              placeholder="例如：中小企业 IT 决策人"
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
            />
            <div>
              <label className="label">语气风格</label>
              <div className="grid grid-cols-3 gap-2">
                {TONES.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => setTone(t.value)}
                    className={cn(
                      "cursor-pointer rounded-lg border px-3 py-2.5 text-left transition focus-ring",
                      tone === t.value ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300",
                    )}
                  >
                    <div className="text-sm font-medium text-slate-900">{t.label}</div>
                    <div className="mt-0.5 text-[11px] text-slate-500">{t.desc}</div>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="label">关键词</label>
              <div className="flex gap-2">
                <Input
                  containerClassName="flex-1"
                  prefix={<Hash className="size-3.5" />}
                  placeholder="回车添加，最多 8 个"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addKeyword(); } }}
                />
                <Button variant="secondary" onClick={addKeyword}>添加</Button>
              </div>
              {keywords.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {keywords.map((k) => (
                    <span
                      key={k}
                      className="inline-flex cursor-pointer items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-600 hover:bg-brand-100"
                      onClick={() => setKeywords((p) => p.filter((v) => v !== k))}
                    >
                      {k} <span aria-hidden>×</span>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <Button
              onClick={() => generateMut.mutate()}
              loading={generateMut.isPending}
              disabled={!campaignId || !topic.trim() || !audience.trim()}
              block
              size="lg"
              leftIcon={<Sparkles className="size-4" />}
            >生成文案</Button>
          </div>
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader
            title={<span className="inline-flex items-center gap-2"><Megaphone className="size-4 text-pink-500" />生成结果</span>}
            extra={result && (
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" leftIcon={<Copy className="size-3.5" />} onClick={copyAll}>复制全部</Button>
                <Button size="sm" variant="ghost" leftIcon={<RefreshCcw className="size-3.5" />} onClick={() => generateMut.mutate()}>再生成</Button>
              </div>
            )}
          />
          {generateMut.isPending ? (
            <Loading tip="AI 正在创作中…" />
          ) : !result ? (
            <Empty title="尚未生成文案" description="填写左侧参数后点击「生成文案」" />
          ) : (
            <div className="space-y-5">
              <div className="rounded-xl border border-brand-200 bg-linear-to-br from-brand-50 to-white p-5">
                <div className="text-xs font-medium text-brand-600">主标题</div>
                <h2 className="mt-1 text-2xl font-semibold text-slate-900">{result.headline}</h2>
                <div className="mt-3 text-sm leading-6 text-slate-700">{result.summary}</div>
              </div>
              <div className="rounded-xl border border-slate-100 p-5">
                <div className="text-xs font-medium text-slate-500">正文</div>
                <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{result.body}</div>
              </div>
              <div className="rounded-xl border border-success-200 bg-success-50/40 p-5">
                <div className="text-xs font-medium text-success-700">行动号召（CTA）</div>
                <div className="mt-1 text-base font-semibold text-success-700">{result.callToAction}</div>
              </div>
              {result.keywords?.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {result.keywords.map((k) => (
                    <span key={k} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">
                      <Hash className="size-3" />{k}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>
    </PageContainer>
  );
}
