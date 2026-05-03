import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Image as ImageIcon, Plus, Search, Sparkles } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { marketingService } from "@/lib/marketing-service";
import { formatDate } from "@/lib/format";

export default function PosterTasksPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["marketing", "posters", page],
    queryFn: () => marketingService.listPosterTasks(page, 12),
    refetchInterval: 6000, // poll for status updates
  });

  const items = (query.data?.items ?? []).filter(
    (t) => !keyword || t.theme.includes(keyword) || t.campaignName.includes(keyword) || t.slogan.includes(keyword),
  );

  return (
    <PageContainer>
      <PageHeader
        title="AI 海报工作室"
        description="一键生成活动海报，AI 自动设计构图与配色"
        breadcrumb={[{ label: "营销中心" }, { label: "AI 海报工作室" }]}
        extra={
          <Button leftIcon={<Plus className="size-3.5" />} onClick={() => navigate("/marketing/posters/new")}>
            新建海报任务
          </Button>
        }
      />
      <div className="mb-4 flex items-center justify-between gap-3">
        <Input
          containerClassName="w-72"
          prefix={<Search className="size-3.5" />}
          placeholder="搜索主题 / 活动 / 标语"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
      </div>

      {query.isLoading ? <Loading /> : items.length === 0 ? (
        <Empty
          title="暂无海报任务"
          description="提交一个海报生成任务，AI 会快速产出可用素材"
          action={<Button leftIcon={<Sparkles className="size-3.5" />} onClick={() => navigate("/marketing/posters/new")}>开始创作</Button>}
        />
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((t) => (
            <Card
              key={t.taskId}
              hoverable
              padded={false}
              className="cursor-pointer overflow-hidden"
              onClick={() => navigate(`/marketing/posters/${t.taskId}`)}
            >
              <div className="relative aspect-[3/4] overflow-hidden bg-linear-to-br from-slate-100 to-slate-200">
                {t.imageUrl ? (
                  <img src={t.imageUrl} alt={t.theme} className="size-full object-cover transition-transform duration-300 group-hover:scale-105" />
                ) : (
                  <div className="flex size-full flex-col items-center justify-center text-slate-400">
                    <ImageIcon className="size-10" />
                    <div className="mt-2 text-xs">{t.status === "running" ? "生成中…" : t.status === "queued" ? "排队中" : t.status === "failed" ? "生成失败" : "等待生成"}</div>
                  </div>
                )}
                <span className="absolute right-2 top-2"><StatusBadge status={t.status} /></span>
              </div>
              <div className="p-3">
                <div className="line-clamp-1 text-sm font-medium text-slate-900">{t.theme}</div>
                <div className="mt-0.5 line-clamp-1 text-xs text-slate-500">{t.campaignName}</div>
                <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
                  <span>{t.size}</span>
                  <span>{formatDate(t.createdAt)}</span>
                </div>
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
