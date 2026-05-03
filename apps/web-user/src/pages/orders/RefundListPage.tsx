import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { Modal } from "@/components/ui/Modal";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { businessApis } from "@/lib/sdk";
import { formatDate, formatMoney } from "@/lib/format";
import type { RefundRecord } from "@smartcloud-x/frontend-sdk/web-user";

export default function RefundListPage() {
  const { refundNo } = useParams();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["refunds", page],
    queryFn: () => businessApis.serviceDesk.listRefunds({ page, pageSize: 10 }),
  });

  const detailQuery = useQuery({
    queryKey: ["refunds", "detail", refundNo],
    enabled: !!refundNo,
    queryFn: () => businessApis.orders.getRefundDetail(refundNo!),
  });

  return (
    <PageContainer>
      <PageHeader
        title="退款记录"
        description="查看所有退款申请及其处理进度"
        breadcrumb={[{ label: "业务中心" }, { label: "退款管理" }]}
      />
      <Card padded={false}>
        {query.isLoading ? <Loading /> : !query.data?.items.length ? (
          <Empty title="暂无退款记录" description="还没有发起过退款申请" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>退款单号</th>
                  <th>关联订单</th>
                  <th>申请金额</th>
                  <th>实际退款</th>
                  <th>状态</th>
                  <th>申请时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((r) => (
                  <tr key={r.refundNo}>
                    <td className="font-mono text-xs text-brand-600">{r.refundNo}</td>
                    <td className="font-mono text-xs">{r.orderNo}</td>
                    <td>{formatMoney(r.requestedAmount, r.currency)}</td>
                    <td>{formatMoney(r.approvedAmount ?? "", r.currency)}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="text-slate-500">{formatDate(r.createdAt)}</td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => navigate(`/orders/refunds/${r.refundNo}`)}>详情</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {query.data && query.data.total > 0 && (
          <div className="px-4">
            <Pagination
              page={query.data.page}
              pageSize={query.data.pageSize}
              total={query.data.total}
              onChange={setPage}
            />
          </div>
        )}
      </Card>

      <Modal
        open={!!refundNo}
        onClose={() => navigate("/orders/refunds", { replace: true })}
        title={`退款详情 ${refundNo}`}
        size="lg"
      >
        {detailQuery.isLoading ? <Loading /> : detailQuery.data ? (
          <RefundDetail r={detailQuery.data} />
        ) : <Empty title="未找到记录" />}
      </Modal>
    </PageContainer>
  );
}

function RefundDetail({ r }: { r: RefundRecord }) {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-y-3 rounded-lg bg-slate-50 p-4 text-sm">
        <div className="text-slate-500">退款单号</div>
        <div className="font-mono text-brand-600">{r.refundNo}</div>
        <div className="text-slate-500">关联订单</div>
        <div className="font-mono">{r.orderNo}</div>
        <div className="text-slate-500">申请金额</div>
        <div className="font-medium">{formatMoney(r.requestedAmount, r.currency)}</div>
        <div className="text-slate-500">实际退款</div>
        <div className="font-medium">{formatMoney(r.approvedAmount ?? "", r.currency)}</div>
        <div className="text-slate-500">当前状态</div>
        <div><StatusBadge status={r.status} /></div>
        {r.rejectReason && (
          <>
            <div className="text-slate-500">驳回原因</div>
            <div className="text-danger-600">{r.rejectReason}</div>
          </>
        )}
      </div>
      {r.timeline?.length > 0 && (
        <div>
          <div className="mb-3 text-sm font-medium text-slate-700">处理时间线</div>
          <ol className="space-y-3">
            {r.timeline.map((t, idx) => (
              <li key={idx} className="flex gap-3">
                <div className="relative flex flex-col items-center">
                  <div className="size-2 rounded-full bg-brand-500" />
                  {idx < r.timeline.length - 1 && <div className="mt-1 w-px flex-1 bg-slate-200" />}
                </div>
                <div className="flex-1 pb-3">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={t.status} />
                    <span className="text-xs text-slate-400">{formatDate(t.at)}</span>
                  </div>
                  <div className="mt-1 text-sm text-slate-600">{t.note}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
