import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowUpRight, CreditCard, FileText, Receipt, ShoppingBag, Wallet } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Tabs } from "@/components/ui/Tabs";
import { Button } from "@/components/ui/Button";
import { businessApis } from "@/lib/sdk";
import { formatDate, formatMoney, formatPercent } from "@/lib/format";
import type { BillingSummaryRange } from "@smartcloud-x/frontend-sdk/web-user";

const RANGE_TABS: { key: BillingSummaryRange; label: string }[] = [
  { key: "this_month",    label: "本月" },
  { key: "last_month",    label: "上月" },
  { key: "last_3_months", label: "近 3 月" },
];

export default function BillingOverviewPage() {
  const navigate = useNavigate();
  const [range, setRange] = useState<BillingSummaryRange>("this_month");

  const summary = useQuery({
    queryKey: ["billing", "summary", range],
    queryFn: () => businessApis.billing.getSummary({ range }),
  });

  const dashboard = useQuery({
    queryKey: ["billing", "dashboard"],
    queryFn: () => businessApis.billing.getDashboard(),
  });

  const total = summary.data?.totalAmount;

  return (
    <PageContainer>
      <PageHeader
        title="账单总览"
        description="实时掌握云资源消费情况"
        breadcrumb={[{ label: "财务中心" }, { label: "账单总览" }]}
        extra={
          <Tabs
            variant="pill"
            value={range}
            onChange={(v) => setRange(v as BillingSummaryRange)}
            items={RANGE_TABS as unknown as { key: string; label: string }[]}
          />
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={<Wallet className="size-5" />}
          label="本期消费总额"
          value={summary.isLoading ? "—" : formatMoney(total, summary.data?.currency ?? "CNY")}
          tone="from-brand-500 to-brand-600"
          accent
        />
        <SummaryCard
          icon={<CreditCard className="size-5" />}
          label="可用余额"
          value="—"
          tone="from-emerald-500 to-emerald-600"
        />
        <SummaryCard
          icon={<Receipt className="size-5" />}
          label="待开发票"
          value={String(dashboard.data?.invoices?.filter((i) => i.status === "pending").length ?? 0)}
          tone="from-amber-500 to-amber-600"
        />
        <SummaryCard
          icon={<ShoppingBag className="size-5" />}
          label="进行中订单"
          value={String(dashboard.data?.orders?.length ?? 0)}
          tone="from-violet-500 to-violet-600"
        />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="产品消费 Top"
            description="按产品类型统计的消费占比"
          />
          {summary.isLoading ? (
            <Loading />
          ) : !summary.data?.topProducts?.length ? (
            <Empty title="暂无消费记录" />
          ) : (
            <ul className="space-y-3">
              {summary.data.topProducts.map((p) => (
                <li key={p.productType}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-700">{p.productType}</span>
                    <span className="font-medium text-slate-900">{formatMoney(p.amount)}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-linear-to-r from-brand-400 to-brand-600" style={{ width: `${Math.min(100, p.ratio * 100)}%` }} />
                  </div>
                  <div className="mt-1 text-right text-xs text-slate-400">{formatPercent(p.ratio)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            title="实例消费 Top"
            description="单实例消费金额排名"
          />
          {summary.isLoading ? (
            <Loading />
          ) : !summary.data?.topInstances?.length ? (
            <Empty title="暂无消费记录" />
          ) : (
            <ul className="divide-y divide-slate-100">
              {summary.data.topInstances.map((i, idx) => (
                <li key={i.instanceId} className="flex items-center justify-between py-2.5">
                  <div className="flex items-center gap-3">
                    <div className="flex size-7 items-center justify-center rounded-md bg-brand-50 text-xs font-semibold text-brand-600">
                      {idx + 1}
                    </div>
                    <div>
                      <div className="text-sm text-slate-900">{i.instanceName}</div>
                      <div className="font-mono text-[11px] text-slate-400">{i.instanceId}</div>
                    </div>
                  </div>
                  <div className="text-sm font-medium text-slate-900">{formatMoney(i.amount)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="最近订单"
            extra={<button onClick={() => navigate("/orders")} className="inline-flex items-center gap-0.5 text-sm text-brand-600 hover:underline">查看全部<ArrowUpRight className="size-3" /></button>}
          />
          {!dashboard.data?.orders?.length ? <Empty compact title="暂无订单" /> : (
            <ul className="divide-y divide-slate-100">
              {dashboard.data.orders.slice(0, 5).map((o) => (
                <li key={o.orderNo} className="flex cursor-pointer items-center justify-between py-2.5 hover:bg-slate-50/60" onClick={() => navigate(`/orders/${o.orderNo}`)}>
                  <div>
                    <div className="font-mono text-xs text-brand-600">{o.orderNo}</div>
                    <div className="mt-0.5 text-sm text-slate-700">{o.productType}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-medium text-slate-900">{formatMoney(o.amount)}</div>
                    <div className="mt-0.5"><StatusBadge status={o.status} dot={false} /></div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader
            title="最近发票"
            extra={<button onClick={() => navigate("/billing/invoices")} className="inline-flex items-center gap-0.5 text-sm text-brand-600 hover:underline">查看全部<ArrowUpRight className="size-3" /></button>}
          />
          {!dashboard.data?.invoices?.length ? <Empty compact title="暂无发票" /> : (
            <ul className="divide-y divide-slate-100">
              {dashboard.data.invoices.slice(0, 5).map((inv) => (
                <li key={inv.invoiceNo} className="flex items-center justify-between py-2.5">
                  <div>
                    <div className="text-sm text-slate-700">{inv.title}</div>
                    <div className="mt-0.5 font-mono text-xs text-slate-400">{inv.invoiceNo}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-medium text-slate-900">{formatMoney(inv.amount)}</div>
                    <div className="mt-0.5"><StatusBadge status={inv.status} dot={false} /></div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </PageContainer>
  );
}

function SummaryCard({ icon, label, value, tone, accent }: { icon: React.ReactNode; label: string; value: string; tone: string; accent?: boolean }) {
  return (
    <Card className="relative overflow-hidden" padded>
      <div className={`absolute -right-6 -top-6 size-20 rounded-full bg-linear-to-br ${tone} opacity-15 blur-2xl`} />
      <div className="flex items-center justify-between">
        <div className="text-xs text-slate-500">{label}</div>
        <div className={`flex size-9 items-center justify-center rounded-xl bg-linear-to-br text-white shadow-sm ${tone}`}>{icon}</div>
      </div>
      <div className={`mt-3 ${accent ? "text-3xl" : "text-2xl"} font-semibold text-slate-900`}>{value}</div>
    </Card>
  );
}
