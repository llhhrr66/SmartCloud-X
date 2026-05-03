import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, TextInput } from "../components/FormControls";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { AuditRecord, RuntimeSnapshot } from "../types";

export function AuditRuntimePage() {
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot | null>(null);
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [filters, setFilters] = useState({ resourceType: "", action: "", operatorId: "" });
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const [audit, nextSnapshot, nextOverview] = await Promise.all([
        adminApi.auditRecords(filters),
        adminApi.snapshot().catch(() => null),
        adminApi.overview().catch(() => null),
      ]);
      setRecords(audit.items ?? []); setSnapshot(nextSnapshot); setOverview(nextOverview);
    } catch (err) { toast.push(err instanceof Error ? err.message : "加载审计失败", "error"); }
    finally { setLoading(false); }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">审计</p>
          <h1>审计与运行时状态</h1>
          <span className="muted text-sm">追踪管理员写操作和知识服务运行时后端。</span>
        </div>
        <button className="btn-secondary" disabled={loading} onClick={load}>刷新</button>
      </div>

      <article className="panel animate-slide-up stagger-1">
        <FormGrid>
          <Field label="资源类型"><TextInput value={filters.resourceType} onChange={(e) => setFilters({ ...filters, resourceType: e.target.value })} /></Field>
          <Field label="动作"><TextInput value={filters.action} onChange={(e) => setFilters({ ...filters, action: e.target.value })} /></Field>
          <Field label="操作人"><TextInput value={filters.operatorId} onChange={(e) => setFilters({ ...filters, operatorId: e.target.value })} /></Field>
        </FormGrid>
      </article>

      <article className="panel animate-slide-up stagger-2">
        <h2 className="text-base font-semibold mb-3">审计记录</h2>
        <DataTable rows={records} keyOf={(row) => row.audit_id} columns={[
          { key: "time", title: "时间", render: (row) => row.created_at },
          { key: "operator", title: "操作人", render: (row) => row.operator_id },
          { key: "resource", title: "资源", render: (row) => `${row.resource_type}/${row.resource_id}` },
          { key: "action", title: "动作", render: (row) => <StatusBadge status={row.action} /> },
          { key: "reason", title: "原因", render: (row) => row.reason },
        ]} />
      </article>

      <div className="grid grid-cols-2 gap-4">
        <article className="panel animate-slide-up stagger-3">
          <h2 className="text-base font-semibold mb-3">运行时快照</h2>
          <pre className="json-panel">{snapshot ? JSON.stringify(snapshot.integrations ?? snapshot, null, 2) : "暂无快照"}</pre>
        </article>
        <article className="panel animate-slide-up stagger-4">
          <h2 className="text-base font-semibold mb-3">知识库概览</h2>
          <pre className="json-panel">{overview ? JSON.stringify(overview, null, 2) : "暂无概览"}</pre>
        </article>
      </div>
    </section>
  );
}
