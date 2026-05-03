import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, FileText, Plus } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { businessApis } from "@/lib/sdk";
import { formatMoney } from "@/lib/format";

export default function InvoicesPage() {
  const [page, setPage] = useState(1);
  const query = useQuery({
    queryKey: ["billing", "invoices", page],
    queryFn: () => businessApis.billing.listInvoices({ page, pageSize: 10 }),
  });

  return (
    <PageContainer>
      <PageHeader
        title="发票管理"
        description="申请发票、下载发票文件"
        breadcrumb={[{ label: "财务中心" }, { label: "发票管理" }]}
        extra={<Button leftIcon={<Plus className="size-3.5" />}>申请开票</Button>}
      />
      <Card padded={false}>
        {query.isLoading ? <Loading /> : !query.data?.items.length ? (
          <Empty title="暂无发票记录" description="发票申请通过后，会出现在这里" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>发票号</th>
                  <th>抬头</th>
                  <th>账期</th>
                  <th>金额</th>
                  <th>状态</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((inv) => (
                  <tr key={inv.invoiceNo}>
                    <td className="font-mono text-xs text-brand-600">{inv.invoiceNo}</td>
                    <td>
                      <div className="inline-flex items-center gap-1.5">
                        <FileText className="size-3.5 text-slate-400" />
                        {inv.title}
                      </div>
                    </td>
                    <td>{inv.billingCycle}</td>
                    <td className="font-medium text-slate-900">{formatMoney(inv.amount)}</td>
                    <td><StatusBadge status={inv.status} /></td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" leftIcon={<Download className="size-3.5" />}>下载</Button>
                    </td>
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
