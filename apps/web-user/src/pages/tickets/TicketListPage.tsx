import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search, Filter } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Tabs } from "@/components/ui/Tabs";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { businessApis } from "@/lib/sdk";
import { formatDate } from "@/lib/format";

const TABS = [
  { key: "all",        label: "全部" },
  { key: "open",       label: "待处理" },
  { key: "processing", label: "处理中" },
  { key: "resolved",   label: "已解决" },
  { key: "closed",     label: "已关闭" },
];

const CATEGORY_LABEL: Record<string, string> = {
  technical_support: "技术支持",
  billing: "费用账单",
  order: "订单",
  icp: "ICP 备案",
};

export default function TicketListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [tab, setTab] = useState("all");
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["tickets", page],
    queryFn: () => businessApis.tickets.listTickets({ page, pageSize: 10 }),
  });

  const items = (query.data?.items ?? []).filter((t) => {
    if (tab !== "all" && t.status !== tab) return false;
    if (keyword && !(t.ticketNo.includes(keyword) || t.subject.includes(keyword))) return false;
    return true;
  });

  return (
    <PageContainer>
      <PageHeader
        title="工单中心"
        description="提交问题、跟进处理进度、与客服协作"
        breadcrumb={[{ label: "业务中心" }, { label: "工单中心" }]}
        extra={
          <Button leftIcon={<Plus className="size-3.5" />} onClick={() => navigate("/tickets/new")}>新建工单</Button>
        }
      />
      <Card>
        <div className="mb-4 flex items-center justify-between gap-3">
          <Tabs value={tab} onChange={setTab} items={TABS} variant="pill" />
          <Input
            containerClassName="w-72"
            prefix={<Search className="size-3.5" />}
            placeholder="搜索工单号 / 标题"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>
        {query.isLoading ? <Loading /> : items.length === 0 ? (
          <Empty title="暂无工单" action={<Button onClick={() => navigate("/tickets/new")}>新建工单</Button>} />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>工单号</th>
                  <th>主题</th>
                  <th>分类</th>
                  <th>优先级</th>
                  <th>状态</th>
                  <th>更新时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((t) => (
                  <tr key={t.ticketNo} className="cursor-pointer" onClick={() => navigate(`/tickets/${t.ticketNo}`)}>
                    <td className="font-mono text-xs text-brand-600">{t.ticketNo}</td>
                    <td className="max-w-md">
                      <div className="truncate font-medium text-slate-900">{t.subject}</div>
                      {t.content && <div className="mt-0.5 truncate text-xs text-slate-500">{t.content}</div>}
                    </td>
                    <td><span className="text-sm text-slate-600">{CATEGORY_LABEL[t.category as string] ?? t.category}</span></td>
                    <td>{t.priority ? <StatusBadge status={t.priority} /> : "—"}</td>
                    <td><StatusBadge status={t.status} /></td>
                    <td className="text-slate-500">{formatDate(t.updatedAt)}</td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); navigate(`/tickets/${t.ticketNo}`); }}>查看</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {query.data && query.data.total > 0 && (
          <Pagination page={query.data.page} pageSize={query.data.pageSize} total={query.data.total} onChange={setPage} />
        )}
      </Card>
    </PageContainer>
  );
}
