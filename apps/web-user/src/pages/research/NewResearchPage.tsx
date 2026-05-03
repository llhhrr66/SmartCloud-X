import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, FileText, FileSearch, Link as LinkIcon, Plus, Send, Trash2, Zap, FlaskConical, Microscope } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { researchService } from "@/lib/research-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import type { CreateResearchTaskRequest } from "@smartcloud-x/frontend-sdk/web-user";
import { cn } from "@/lib/cn";

const DEPTH_OPTIONS: { value: CreateResearchTaskRequest["depth"]; label: string; desc: string; mins: string; icon: any }[] = [
  { value: "lite",     label: "速览",   desc: "5-10 分钟，市场概览",  mins: "~10 分钟", icon: Zap },
  { value: "standard", label: "标准",   desc: "20-40 分钟，常规调研", mins: "~30 分钟", icon: FlaskConical },
  { value: "deep",     label: "深度",   desc: "1-2 小时，详尽分析",   mins: "~90 分钟", icon: Microscope },
];

const FORMAT_OPTIONS: { value: CreateResearchTaskRequest["outputFormat"]; label: string; desc: string }[] = [
  { value: "markdown", label: "Markdown",  desc: "便于在线阅读、二次编辑" },
  { value: "pdf",      label: "PDF 报告",  desc: "正式排版，便于打印分发" },
];

export default function NewResearchPage() {
  const navigate = useNavigate();
  const [topic, setTopic] = useState("");
  const [scope, setScope] = useState("");
  const [depth, setDepth] = useState<CreateResearchTaskRequest["depth"]>("standard");
  const [outputFormat, setOutputFormat] = useState<CreateResearchTaskRequest["outputFormat"]>("markdown");
  const [refUrl, setRefUrl] = useState("");
  const [refUrls, setRefUrls] = useState<string[]>([]);

  const createMut = useMutation({
    mutationFn: () => researchService.createTask({ topic, scope, depth, outputFormat, referenceUrls: refUrls }),
    onSuccess: (t) => {
      notifySuccess("调研任务已创建");
      navigate(`/research/${t.taskId}`);
    },
    onError: (e) => notifyError(e, "创建任务失败"),
  });

  function addUrl() {
    const u = refUrl.trim();
    if (!u) return;
    setRefUrls((p) => [...new Set([...p, u])]);
    setRefUrl("");
  }

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="新建调研任务"
        description="设置调研主题与深度，AI 会输出有引用的市场分析报告"
        breadcrumb={[{ label: "市场调研" }, { label: "调研任务", to: "/research" }, { label: "新建调研" }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/research")}>返回</Button>}
      />

      <Card>
        <CardHeader title="主题与范围" />
        <div className="space-y-4">
          <Input
            label="调研主题"
            placeholder="例如：2026 年中国云原生数据库市场格局"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            hint="一句话概括你想调研的目标"
          />
          <div>
            <label className="label">调研范围 / 关注重点</label>
            <textarea
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              rows={4}
              placeholder="例如：&#10;1. 头部厂商市场份额变化&#10;2. 主流产品差异化能力&#10;3. 客户主要痛点与采购决策因素"
              className="input min-h-[120px]"
            />
          </div>
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="调研深度" description="深度越大，AI 检索的资源越多，等待时间也更长" />
        <div className="grid grid-cols-3 gap-2">
          {DEPTH_OPTIONS.map((d) => {
            const active = d.value === depth;
            return (
              <button
                key={d.value}
                type="button"
                onClick={() => setDepth(d.value)}
                className={cn(
                  "cursor-pointer rounded-xl border p-4 text-left transition focus-ring",
                  active ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300",
                )}
              >
                <div className={cn(
                  "flex size-10 items-center justify-center rounded-lg",
                  active ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-500",
                )}>
                  <d.icon className="size-5" />
                </div>
                <div className="mt-3 text-sm font-medium text-slate-900">{d.label}</div>
                <div className="mt-0.5 text-xs text-slate-500">{d.desc}</div>
                <div className="mt-1 text-[11px] text-brand-600">{d.mins}</div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="输出格式" />
        <div className="grid grid-cols-2 gap-2">
          {FORMAT_OPTIONS.map((f) => {
            const active = f.value === outputFormat;
            return (
              <button
                key={f.value}
                type="button"
                onClick={() => setOutputFormat(f.value)}
                className={cn(
                  "cursor-pointer rounded-lg border p-3 text-left transition focus-ring",
                  active ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300",
                )}
              >
                <div className="inline-flex items-center gap-2 text-sm font-medium text-slate-900">
                  <FileText className="size-4 text-slate-400" />{f.label}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">{f.desc}</div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="参考链接（可选）" description="提供已有的资料链接，AI 会优先采集这些内容" />
        <div className="flex gap-2">
          <Input
            containerClassName="flex-1"
            prefix={<LinkIcon className="size-3.5" />}
            placeholder="https://..."
            value={refUrl}
            onChange={(e) => setRefUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addUrl(); } }}
          />
          <Button variant="secondary" leftIcon={<Plus className="size-3" />} onClick={addUrl}>添加</Button>
        </div>
        {refUrls.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {refUrls.map((u) => (
              <li key={u} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-1.5 text-xs text-slate-700">
                <span className="truncate">{u}</span>
                <button
                  type="button"
                  aria-label={`移除 ${u}`}
                  className="ml-2 cursor-pointer text-slate-400 hover:text-danger-600"
                  onClick={() => setRefUrls((p) => p.filter((v) => v !== u))}
                >
                  <Trash2 className="size-3" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={() => navigate("/research")}>取消</Button>
        <Button
          loading={createMut.isPending}
          disabled={!topic.trim() || !scope.trim()}
          onClick={() => createMut.mutate()}
          leftIcon={<Send className="size-3.5" />}
        >提交调研任务</Button>
      </div>
    </PageContainer>
  );
}
