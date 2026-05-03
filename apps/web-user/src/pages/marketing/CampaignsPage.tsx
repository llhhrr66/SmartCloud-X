import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { Calendar, ExternalLink, Megaphone, Search, Sparkles, Tag } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Input } from "@/components/ui/Input";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { marketingService } from "@/lib/marketing-service";
import { formatDateOnly } from "@/lib/format";
import { cn } from "@/lib/cn";

export default function CampaignsPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["marketing", "campaigns", page],
    queryFn: () => marketingService.listCampaigns(page, 12),
  });

  const items = (query.data?.items ?? []).filter(
    (c) => !keyword || c.name.includes(keyword) || c.productType.includes(keyword),
  );

  return (
    <PageContainer>
      <PageHeader
        title="营销活动"
        description="查看在线营销活动，结合 AI 工具创作宣传素材"
        breadcrumb={[{ label: "营销中心" }, { label: "营销活动" }]}
        extra={
          <>
            <Button variant="secondary" leftIcon={<Sparkles className="size-3.5" />} onClick={() => navigate("/marketing/copy")}>AI 文案</Button>
            <Button leftIcon={<Megaphone className="size-3.5" />} onClick={() => navigate("/marketing/posters")}>海报工作室</Button>
          </>
        }
      />

      <div className="mb-4 flex items-center justify-between gap-3">
        <Input
          containerClassName="w-72"
          prefix={<Search className="size-3.5" />}
          placeholder="搜索活动名称或产品"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
        />
        <span className="text-xs text-slate-500">共 {items.length} 个活动</span>
      </div>

      {query.isLoading ? <Loading /> : items.length === 0 ? (
        <Empty title="暂无营销活动" description="近期还没有进行中的营销活动" />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((c) => (
            <Card key={c.campaignId} hoverable padded className="cursor-pointer transition" onClick={() => window.open(c.landingPageUrl, "_blank")}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex size-10 items-center justify-center rounded-xl bg-linear-to-br from-pink-500 to-pink-600 text-white">
                  <Megaphone className="size-5" />
                </div>
                <StatusBadge status={c.status} />
              </div>
              <div className="mt-3 line-clamp-1 text-base font-semibold text-slate-900">{c.name}</div>
              <div className="mt-1 inline-flex items-center gap-1 text-xs text-slate-500">
                <Tag className="size-3" />{c.productType}
              </div>
              {c.highlights?.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {c.highlights.slice(0, 3).map((h, i) => (
                    <li key={i} className="line-clamp-1 text-xs text-slate-600">• {h}</li>
                  ))}
                </ul>
              )}
              <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
                <span className="inline-flex items-center gap-1">
                  <Calendar className="size-3" />
                  {formatDateOnly(c.startAt)} → {formatDateOnly(c.endAt)}
                </span>
                <span className="inline-flex items-center gap-1 text-brand-600">
                  详情 <ExternalLink className="size-3" />
                </span>
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
