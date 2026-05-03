import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Calendar, Copy, Download, Hash, Image as ImageIcon, RefreshCcw, Tag } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { marketingService } from "@/lib/marketing-service";
import { formatDate } from "@/lib/format";

export default function PosterDetailPage() {
  const { taskId } = useParams();
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: ["marketing", "poster", taskId],
    enabled: !!taskId,
    queryFn: () => marketingService.getPosterTask(taskId!),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "running" || s === "queued" ? 3000 : false;
    },
  });

  if (query.isLoading) return <PageContainer><Loading /></PageContainer>;
  if (!query.data) return <PageContainer><Empty title="任务不存在" /></PageContainer>;

  const t = query.data;

  return (
    <PageContainer>
      <PageHeader
        title={t.theme}
        description={
          <span className="inline-flex items-center gap-2 font-mono text-xs">
            任务号 <span className="text-brand-600">{t.taskId}</span>
            <StatusBadge status={t.status} />
          </span>
        }
        breadcrumb={[{ label: "营销中心" }, { label: "AI 海报工作室", to: "/marketing/posters" }, { label: t.theme }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/marketing/posters")}>返回</Button>}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="海报预览"
            extra={t.imageUrl && (
              <div className="flex items-center gap-2">
                <Button size="sm" variant="ghost" leftIcon={<Download className="size-3.5" />} onClick={() => window.open(t.imageUrl, "_blank")}>下载 PNG</Button>
                <Button size="sm" variant="ghost" leftIcon={<Copy className="size-3.5" />}>复制链接</Button>
              </div>
            )}
          />
          <div className="rounded-xl bg-slate-50 p-6">
            {t.imageUrl ? (
              <img src={t.imageUrl} alt={t.theme} className="mx-auto max-h-[640px] rounded-lg shadow-md" />
            ) : (
              <div className="flex aspect-[9/16] max-h-[640px] flex-col items-center justify-center rounded-lg bg-white text-slate-400">
                <ImageIcon className="size-12" />
                <div className="mt-3 text-sm">{t.status === "running" ? "AI 正在生成…" : t.status === "queued" ? "任务排队中" : t.status === "failed" ? "生成失败" : "等待生成"}</div>
                {t.errorMessage && <div className="mt-2 max-w-xs text-center text-xs text-danger-600">{t.errorMessage}</div>}
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="任务信息" />
          <Field icon={<Tag className="size-3.5" />} label="活动" value={t.campaignName || "—"} />
          <Field icon={<Hash className="size-3.5" />} label="主题" value={t.theme} />
          <Field label="主标语" value={t.slogan} />
          <Field label="尺寸" value={t.size} />
          <Field label="状态" value={<StatusBadge status={t.status} />} />
          <Field icon={<Calendar className="size-3.5" />} label="创建时间" value={formatDate(t.createdAt)} />
          <Field icon={<Calendar className="size-3.5" />} label="更新时间" value={formatDate(t.updatedAt)} />
          {t.estimatedSeconds > 0 && (
            <Field label="预计耗时" value={`~${t.estimatedSeconds}s`} />
          )}

          <div className="mt-4 flex justify-end gap-2 border-t border-slate-100 pt-3">
            <Button size="sm" variant="ghost" leftIcon={<RefreshCcw className="size-3.5" />} onClick={() => query.refetch()}>刷新</Button>
          </div>
        </Card>
      </div>
    </PageContainer>
  );
}

function Field({ icon, label, value }: { icon?: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <div className="inline-flex items-center gap-1 text-slate-500">{icon}{label}</div>
      <div className="col-span-2 break-words font-medium text-slate-900">{value}</div>
    </div>
  );
}
