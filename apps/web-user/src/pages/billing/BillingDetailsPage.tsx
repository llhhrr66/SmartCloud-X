import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import dayjs from "dayjs";
import { Calendar, Download } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { businessApis } from "@/lib/sdk";
import { formatMoney } from "@/lib/format";

export default function BillingDetailsPage() {
  const [page, setPage] = useState(1);
  const [billingCycle, setBillingCycle] = useState<string>(dayjs().format("YYYY-MM"));

  const query = useQuery({
    queryKey: ["billing", "details", billingCycle, page],
    queryFn: () => businessApis.billing.listBillingDetails({ page, pageSize: 15, billingCycle }),
  });

  return (
    <PageContainer>
      <PageHeader
        title="账单明细"
        description="按账期查看每条消费记录"
        breadcrumb={[{ label: "财务中心" }, { label: "账单明细" }]}
        extra={
          <>
            <div className="relative">
              <Calendar className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-slate-400" />
              <input
                type="month"
                value={billingCycle}
                onChange={(e) => { setBillingCycle(e.target.value); setPage(1); }}
                className="h-9 rounded-lg border border-slate-200 bg-white pl-8 pr-3 text-sm focus:border-brand-500 focus:outline-none"
              />
            </div>
            <Button variant="secondary" leftIcon={<Download className="size-3.5" />}>导出 CSV</Button>
          </>
        }
      />
      <Card padded={false}>
        {query.isLoading ? <Loading /> : !query.data?.items.length ? (
          <Empty title="该账期暂无账单明细" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>对账单号</th>
                  <th>账期</th>
                  <th>产品</th>
                  <th>实例</th>
                  <th>金额</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((d) => (
                  <tr key={d.statementNo}>
                    <td className="font-mono text-xs text-brand-600">{d.statementNo}</td>
                    <td>{d.billingCycle}</td>
                    <td>{d.productType}</td>
                    <td>
                      <div className="text-sm">{d.instanceName || "—"}</div>
                      <div className="font-mono text-[11px] text-slate-400">{d.instanceId}</div>
                    </td>
                    <td className="font-medium text-slate-900">{formatMoney(d.amount)}</td>
                    <td><StatusBadge status={d.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {query.data && query.data.total > 0 && (
          <div className="px-4">
            <Pagination page={query.data.page} pageSize={query.data.pageSize} total={query.data.total} onChange={setPage} />
          </div>
        )}
      </Card>
    </PageContainer>
  );
}
