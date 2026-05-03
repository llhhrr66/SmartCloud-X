import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Box, Calendar, Clock, FileText, RefreshCw, Server, Wallet } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Empty, Loading } from "@/components/ui/Empty";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { businessApis } from "@/lib/sdk";
import { formatDate, formatMoney } from "@/lib/format";

export default function OrderDetailPage() {
  const { orderNo } = useParams();
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: ["orders", "detail", orderNo],
    enabled: !!orderNo,
    queryFn: () => businessApis.orders.getOrderDetail(orderNo!),
  });

  if (query.isLoading) return <PageContainer><Loading /></PageContainer>;
  if (!query.data) return <PageContainer><Empty title="订单不存在" /></PageContainer>;

  const d = query.data;

  return (
    <PageContainer>
      <PageHeader
        title={
          <span className="inline-flex items-center gap-3">
            订单详情
            <StatusBadge status={d.order.status} />
          </span>
        }
        description={
          <span className="font-mono text-xs">
            订单号 <span className="text-brand-600">{d.order.orderNo}</span>
          </span>
        }
        breadcrumb={[{ label: "业务中心" }, { label: "我的订单", to: "/orders" }, { label: d.order.orderNo }]}
        extra={
          <>
            <Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/orders")}>返回</Button>
            {d.order.eligibleForRefund && (
              <Button leftIcon={<RefreshCw className="size-3.5" />} onClick={() => navigate(`/orders/${d.order.orderNo}/refund`)}>
                申请退款
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="产品与配置" description={d.instanceName ?? d.order.productType} />
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Field icon={<Box className="size-3.5" />} label="产品类型" value={d.order.productType} />
            <Field icon={<Server className="size-3.5" />} label="实例名称" value={d.instanceName ?? "—"} />
            <Field icon={<Server className="size-3.5" />} label="区域" value={d.region ?? "—"} />
            <Field icon={<Wallet className="size-3.5" />} label="计费模式" value={d.billingMode ?? "—"} />
            <Field icon={<Clock className="size-3.5" />} label="续费方式" value={d.renewType ?? "—"} />
            <Field icon={<Calendar className="size-3.5" />} label="服务周期" value={d.servicePeriod ?? "—"} />
            <Field icon={<Calendar className="size-3.5" />} label="支付时间" value={formatDate(d.payTime)} />
            <Field icon={<Calendar className="size-3.5" />} label="下单时间" value={formatDate(d.order.createdAt)} />
          </div>
          {d.configurationSummary?.length > 0 && (
            <div className="mt-5 rounded-lg bg-slate-50 p-4">
              <div className="mb-2 text-xs font-medium text-slate-500">配置概要</div>
              <ul className="space-y-1.5 text-sm text-slate-700">
                {d.configurationSummary.map((item, idx) => (
                  <li key={idx} className="flex items-start gap-2">
                    <span className="mt-1.5 size-1 shrink-0 rounded-full bg-brand-500" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="费用" />
          <div className="space-y-4">
            <div className="rounded-xl bg-linear-to-br from-brand-50 to-white p-4 ring-1 ring-brand-100">
              <div className="text-xs text-slate-500">订单金额</div>
              <div className="mt-1 text-2xl font-semibold text-slate-900">{formatMoney(d.order.amount)}</div>
              <div className="mt-2 text-xs text-slate-400">订单状态：<StatusBadge status={d.order.status} dot={false} /></div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between text-slate-500">
                <span>支付方式</span>
                <span className="text-slate-700">在线支付</span>
              </div>
              <div className="flex justify-between text-slate-500">
                <span>合同与发票</span>
                <button className="text-brand-600 hover:underline">查看发票</button>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title={<span className="inline-flex items-center gap-2"><RefreshCw className="size-4 text-slate-400" />退款记录</span>}
          description="该订单关联的退款申请"
        />
        {!d.refunds?.length ? (
          <Empty compact title="暂无退款记录" description="该订单尚未发起退款申请" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>退款单号</th>
                  <th>申请金额</th>
                  <th>状态</th>
                  <th>申请时间</th>
                  <th>完成时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {d.refunds.map((r) => (
                  <tr key={r.refundNo}>
                    <td className="font-mono text-xs text-brand-600">{r.refundNo}</td>
                    <td>{formatMoney(r.requestedAmount, r.currency)}</td>
                    <td><StatusBadge status={r.status} /></td>
                    <td className="text-slate-500">{formatDate(r.createdAt)}</td>
                    <td className="text-slate-500">{formatDate(r.finishedAt)}</td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" onClick={() => navigate(`/orders/refunds/${r.refundNo}`)}>详情</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </PageContainer>
  );
}

function Field({ icon, label, value }: { icon?: React.ReactNode; label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1 text-xs text-slate-500">
        {icon}
        {label}
      </div>
      <div className="mt-1 text-sm font-medium text-slate-900">{value || "—"}</div>
    </div>
  );
}
