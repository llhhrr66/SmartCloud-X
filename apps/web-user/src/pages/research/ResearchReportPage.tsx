import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, Calendar, Download, FileText, Link as LinkIcon, RefreshCcw } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { researchService } from "@/lib/research-service";
import { formatDate } from "@/lib/format";

export default function ResearchReportPage() {
  const { taskId } = useParams();
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: ["research", "task", taskId],
    enabled: !!taskId,
    queryFn: () => researchService.getTask(taskId!),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "running" || s === "queued" ? 4000 : false;
    },
  });

  if (query.isLoading) return <PageContainer><Loading /></PageContainer>;
  if (!query.data) return <PageContainer><Empty title="调研任务不存在" /></PageContainer>;

  const t = query.data;

  return (
    <PageContainer>
      <PageHeader
        title={t.topic}
        description={
          <span className="inline-flex items-center gap-2 font-mono text-xs">
            任务号 <span className="text-brand-600">{t.taskId}</span>
            <StatusBadge status={t.status} />
          </span>
        }
        breadcrumb={[{ label: "市场调研" }, { label: "调研任务", to: "/research" }, { label: t.topic }]}
        extra={
          <>
            <Button variant="secondary" leftIcon={<RefreshCcw className="size-3.5" />} onClick={() => query.refetch()}>刷新</Button>
            <Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/research")}>返回</Button>
            {t.status === "completed" && t.reportFileId && (
              <Button leftIcon={<Download className="size-3.5" />} onClick={() => window.open(`/api/v1/files/${encodeURIComponent(t.reportFileId!)}`, "_blank")}>
                下载报告
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="调研报告"
            description={t.status === "completed" ? "AI 已完成调研" : t.status === "running" ? "AI 正在分析中" : t.status === "queued" ? "已排队，等待执行" : "执行失败"}
          />
          {t.status === "running" && (
            <div className="mb-4">
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>调研进度</span>
                <span>{Math.round(t.progress * 100)}%</span>
              </div>
              <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-linear-to-r from-brand-400 to-brand-600 transition-all" style={{ width: `${Math.max(2, t.progress * 100)}%` }} />
              </div>
            </div>
          )}
          {t.status === "failed" && t.errorMessage && (
            <div className="mb-4 rounded-lg bg-danger-50 p-3 text-sm text-danger-700">{t.errorMessage}</div>
          )}
          {t.summary ? (
            <div className="markdown">
              <ReactMarkdown>{t.summary}</ReactMarkdown>
            </div>
          ) : (
            <Empty
              compact
              title={t.status === "completed" ? "暂无内容" : "尚未输出"}
              description="任务完成后将在此显示完整报告"
            />
          )}
        </Card>

        <Card>
          <CardHeader title="任务信息" />
          <Field label="主题" value={t.topic} />
          <Field label="范围" value={t.scope} />
          <Field label="深度" value={
            <Badge tone="brand">
              {t.depth === "deep" ? "深度" : t.depth === "standard" ? "标准" : "速览"}
            </Badge>
          } />
          <Field label="格式" value={<Badge>{t.outputFormat.toUpperCase()}</Badge>} />
          <Field icon={<Calendar className="size-3.5" />} label="创建时间" value={formatDate(t.createdAt)} />
          {t.startedAt  && <Field icon={<Calendar className="size-3.5" />} label="开始时间"   value={formatDate(t.startedAt)}  />}
          {t.finishedAt && <Field icon={<Calendar className="size-3.5" />} label="完成时间"   value={formatDate(t.finishedAt)} />}

          {t.referenceUrls?.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="mb-2 text-xs font-medium text-slate-500">参考链接</div>
              <ul className="space-y-1">
                {t.referenceUrls.map((u) => (
                  <li key={u} className="truncate">
                    <a href={u} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline">
                      <LinkIcon className="size-3" />
                      {u}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {t.reportFileId && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="mb-2 text-xs font-medium text-slate-500">报告文件</div>
              <Button
                size="sm"
                variant="secondary"
                block
                leftIcon={<FileText className="size-3.5" />}
                onClick={() => window.open(`/api/v1/files/${encodeURIComponent(t.reportFileId!)}`, "_blank")}
              >
                查看 / 下载
              </Button>
            </div>
          )}
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
