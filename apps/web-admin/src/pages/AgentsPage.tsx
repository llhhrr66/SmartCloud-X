import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, TextInput } from "../components/FormControls";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { AgentRecord } from "../types";

export function AgentsPage() {
  const [agents, setAgents] = useState<AgentRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try { setAgents((await adminApi.agents()).items ?? []); }
    catch (err) { toast.push(err instanceof Error ? err.message : "加载 Agent 失败", "error"); }
    finally { setLoading(false); }
  }

  async function patch(agent: AgentRecord, patch: Partial<AgentRecord>) {
    setLoading(true);
    try { await adminApi.updateAgent(agent.code, patch); await load(); }
    catch (err) { toast.push(err instanceof Error ? err.message : "更新 Agent 失败", "error"); }
    finally { setLoading(false); }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">编排</p>
          <h1>Agent 编排管理</h1>
          <span className="muted text-sm">管理 Agent 启用状态、超时和工具调用上限。</span>
        </div>
        <button className="btn-secondary" onClick={load} disabled={loading}>刷新</button>
      </div>

      <article className="panel animate-slide-up stagger-1">
        <h2 className="text-base font-semibold mb-3">Agent 列表</h2>
        <DataTable rows={agents} keyOf={(row) => row.code} columns={[
          { key: "name", title: "Agent", render: (row) => <div><strong>{row.display_name}</strong><small>{row.code}</small></div> },
          { key: "enabled", title: "状态", render: (row) => <StatusBadge status={row.enabled ? "active" : "inactive"} /> },
          { key: "calls", title: "工具上限", render: (row) => <TextInput type="number" value={row.max_tool_calls} onChange={(e) => patch(row, { max_tool_calls: Number(e.target.value) })} /> },
          { key: "timeout", title: "超时秒", render: (row) => <TextInput type="number" value={row.timeout_seconds} onChange={(e) => patch(row, { timeout_seconds: Number(e.target.value) })} /> },
          { key: "actions", title: "操作", render: (row) => (
            <button className={`btn-ghost ${row.enabled ? "text-ember" : "text-volt"}`} disabled={loading} onClick={() => patch(row, { enabled: !row.enabled })}>
              {row.enabled ? "禁用" : "启用"}
            </button>
          )},
        ]} />
      </article>

      <article className="panel animate-slide-up stagger-2">
        <h2 className="text-base font-semibold mb-4">Fallback 设置</h2>
        <FormGrid>
          {agents.map((agent) => <Field key={agent.code} label={agent.display_name}><TextInput value={agent.fallback_agent} onChange={(e) => patch(agent, { fallback_agent: e.target.value })} /></Field>)}
        </FormGrid>
      </article>
    </section>
  );
}
