import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Plus, ShieldCheck } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Pagination } from "@/components/ui/Pagination";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Badge } from "@/components/ui/Badge";
import { businessApis } from "@/lib/sdk";
import { formatDate } from "@/lib/format";

export default function IcpListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);

  const query = useQuery({
    queryKey: ["icp", "applications", page],
    queryFn: () => businessApis.icp.listIcpApplicationPage({ page, pageSize: 10 }),
  });

  const fallbackUsed = Boolean(query.data?.loadState?.failedDomains?.length);

  return (
    <PageContainer>
      <PageHeader
        title="ICP 备案"
        description="申请、跟踪与管理网站 ICP 备案"
        breadcrumb={[{ label: "业务中心" }, { label: "ICP 备案" }]}
        extra={
          <>
            <Button variant="secondary" leftIcon={<ShieldCheck className="size-3.5" />} onClick={() => navigate("/icp/precheck")}>
              材料预校验
            </Button>
            <Button leftIcon={<Plus className="size-3.5" />} onClick={() => navigate("/icp/new")}>新建申请</Button>
          </>
        }
      />

      {fallbackUsed && (
        <Card className="mb-4 border-warning-200 bg-warning-50/40">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warning-500" />
            <div className="text-sm text-warning-700">
              <div className="font-medium">浏览器跟踪回填</div>
              <div className="mt-0.5 text-xs">后端的 ICP 列表接口暂时不可用，正在用本地记录的申请号回填详情。新建的申请仍会被记住，等接口恢复后会自动切换。</div>
            </div>
          </div>
        </Card>
      )}

      <Card padded={false}>
        {query.isLoading ? <Loading /> : !query.data?.items.length ? (
          <Empty
            title="尚未提交任何 ICP 申请"
            description="备案是网站合规的必备流程，建议先做一次材料预校验"
            action={<Button onClick={() => navigate("/icp/precheck")}>开始预校验</Button>}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>申请号</th>
                  <th>网站名称</th>
                  <th>域名</th>
                  <th>主体类型</th>
                  <th>当前阶段</th>
                  <th>状态</th>
                  <th>提交时间</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((a) => (
                  <tr key={a.applicationNo} className="cursor-pointer" onClick={() => navigate(`/icp/${a.applicationNo}`)}>
                    <td className="font-mono text-xs text-brand-600">{a.applicationNo}</td>
                    <td>{a.websiteName || "—"}</td>
                    <td className="font-mono text-xs">{a.domain || "—"}</td>
                    <td><Badge tone={a.subjectType === "enterprise" ? "brand" : "neutral"}>{a.subjectType === "enterprise" ? "企业" : "个人"}</Badge></td>
                    <td className="text-slate-600 text-sm">{a.currentStep || "—"}</td>
                    <td><StatusBadge status={a.status} /></td>
                    <td className="text-slate-500">{formatDate(a.submittedAt)}</td>
                    <td className="text-right">
                      <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); navigate(`/icp/${a.applicationNo}`); }}>查看</Button>
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
    </PageContainer>
  );
}
