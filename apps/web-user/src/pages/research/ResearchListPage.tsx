import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ChevronRight, FileSearch, Plus, Search } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { researchService } from "@/lib/research-service";
import { formatDate } from "@/lib/format";

export default function ResearchListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["research", "tasks", page],
    queryFn: () => researchService.listTasks(page, 12),
    refetchInterval: 6000,
  });

  const items = (query.data?.items ?? []).filter(
    (t) => !keyword || t.topic.includes(keyword) || t.scope.includes(keyword),
  );

  return (
    <PageContainer>
      <PageHeader
        title="市场调研"
        description="提交调研主题，AI 会输出可信的市场分析报告"
        breadcrumb={[{ label: "市场调研" }, { label: "调研任务" }]}
        extra={<Button leftIcon={<Plus className="size-3.5" />} onClick={() => navigate("/research/new")}>新建调研</Button>}
      />

      <div className="mb-4 flex items-center justify-between gap-3">
        <Input
          containerClassName="w-72"
          prefix={<Search className="size-3.5" />}
          placeholder="搜索主题 / 范围"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {query.isLoading ? <Loading /> : items.length === 0 ? (
        <Empty
          title="还没有调研任务"
          description="提交一个调研主题，AI 会自动整理可信的市场报告"
          action={<Button onClick={() => navigate("/research/new")} leftIcon={<FileSearch className="size-3.5" />}>开始第一个调研</Button>}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {items.map((t) => (
            <Card
              key={t.taskId}
              hoverable
              className="cursor-pointer"
              onClick={() => navigate(`/research/${t.taskId}`)}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <div className="font-mono text-[11px] text-slate-400">{t.taskId}</div>
                  <div className="mt-0.5 line-clamp-1 text-base font-semibold text-slate-900">{t.topic}</div>
                  <div className="mt-1 line-clamp-2 text-sm text-slate-500">{t.scope}</div>
                </div>
                <StatusBadge status={t.status} />
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <Badge tone="brand">{t.depth === "deep" ? "深度调研" : t.depth === "standard" ? "标准调研" : "速览"}</Badge>
                <Badge tone="neutral">{t.outputFormat.toUpperCase()}</Badge>
                <span>更新于 {formatDate(t.updatedAt)}</span>
              </div>

              {t.status === "running" && (
                <div className="mt-3">
                  <div className="flex items-center justify-between text-xs text-slate-500">
                    <span>进度</span>
                    <span>{Math.round(t.progress * 100)}%</span>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-linear-to-r from-brand-400 to-brand-600 transition-all" style={{ width: `${Math.max(2, t.progress * 100)}%` }} />
                  </div>
                </div>
              )}

              {t.status === "completed" && t.summary && (
                <div className="mt-3 line-clamp-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{t.summary}</div>
              )}

              {t.errorMessage && (
                <div className="mt-3 rounded-lg bg-danger-50 p-2.5 text-xs text-danger-600">{t.errorMessage}</div>
              )}

              <div className="mt-3 inline-flex items-center gap-1 text-sm text-brand-600">
                查看详情 <ChevronRight className="size-3.5" />
              </div>
            </Card>
          ))}
        </div>
      )}

      {query.data && query.data.total > 0 && (
        <Pagination
          page={query.data.page}
          pageSize={query.data.pageSize}
          total={query.data.total}
          onChange={setPage}
          className="mt-6"
        />
      )}
    </PageContainer>
  );
}
