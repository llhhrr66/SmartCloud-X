import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Filter, Plus, Search } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Pagination } from "@/components/ui/Pagination";
import { Empty, Loading } from "@/components/ui/Empty";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs } from "@/components/ui/Tabs";
import { businessApis, chatApi } from "@/lib/sdk";
import { notifyError } from "@/lib/errors";
import { formatDate, formatMoney } from "@/lib/format";

const STATUS_TABS = [
  { key: "all",            label: "全部" },
  { key: "pending_payment", label: "待支付" },
  { key: "paid",            label: "已支付" },
  { key: "processing",      label: "处理中" },
  { key: "completed",       label: "已完成" },
  { key: "cancelled",       label: "已取消" },
];

export default function OrderListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [tab, setTab] = useState("all");
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["orders", page],
    queryFn: () => businessApis.orders.listOrders({ page, pageSize: 10 }),
  });

  const createPurchaseConversation = useMutation({
    mutationFn: () => chatApi.createSession({
      scene: "billing",
      title: "云资源订购咨询",
      initialContext: "我想订购云产品，请根据我的业务需求推荐合适的产品配置，并说明下单流程。",
    }),
    onSuccess: (conversation) => {
      navigate("/chat/" + conversation.conversationId);
    },
    onError: (error) => {
      notifyError(error, "打开订购入口失败");
    },
  });

  const items = (query.data?.items ?? []).filter((o) => {
    if (tab !== "all" && o.status?.toLowerCase() !== tab) return false;
    if (keyword && !(o.orderNo.includes(keyword) || o.productType.includes(keyword))) return false;
    return true;
  });

  return (
    <PageContainer>
      <PageHeader
        title="我的订单"
        description="查看历史订单、支付状态、退款情况"
        breadcrumb={[{ label: "业务中心" }, { label: "我的订单" }]}
        extra={
          <Button leftIcon={<Plus className="size-3.5" />} loading={createPurchaseConversation.isPending} onClick={() => createPurchaseConversation.mutate()}>
            订购产品
          </Button>
        }
      />
      <Card>
        <div className="mb-4 flex items-center justify-between gap-3">
          <Tabs value={tab} onChange={setTab} items={STATUS_TABS} variant="pill" />
          <Input
            containerClassName="w-72"
            prefix={<Search className="size-3.5" />}
            placeholder="搜索订单号 / 产品"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>
        {query.isLoading ? <Loading /> : items.length === 0 ? (
          <Empty title="暂无订单" description="还没有匹配的订单记录" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>订单号</th>
                  <th>产品</th>
                  <th>金额</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((o) => (
                  <tr key={o.orderNo} className="cursor-pointer" onClick={() => navigate(`/orders/${o.orderNo}`)}>
                    <td className="font-mono text-xs text-brand-600">{o.orderNo}</td>
                    <td>{o.productType}</td>
                    <td className="font-medium text-slate-900">{formatMoney(o.amount)}</td>
                    <td><StatusBadge status={o.status} /></td>
                    <td className="text-slate-500">{formatDate(o.createdAt)}</td>
                    <td className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => { e.stopPropagation(); navigate(`/orders/${o.orderNo}`); }}
                      >查看详情</Button>
                      {o.eligibleForRefund && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => { e.stopPropagation(); navigate(`/orders/${o.orderNo}/refund`); }}
                        >申请退款</Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {query.data && query.data.total > 0 && (
          <Pagination
            page={query.data.page}
            pageSize={query.data.pageSize}
            total={query.data.total}
            onChange={setPage}
          />
        )}
      </Card>
    </PageContainer>
  );
}
