import { useEffect, useState } from "react";
import { StatusBadge } from "../components/StatusBadge";
import { SkeletonCard } from "../components/LoadingSkeleton";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import { formatInteger } from "../lib/presenter";
import type { DashboardSummary, HealthPayload } from "../types";

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [health, setHealth] = useState<HealthPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const toast = useToast();

  useEffect(() => { void refresh(); }, []);

  async function refresh() {
    setLoading(true);
    try {
      const [nextSummary, nextHealth] = await Promise.all([adminApi.dashboard(), adminApi.knowledgeHealth().catch(() => null)]);
      setSummary(nextSummary);
      setHealth(nextHealth);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "加载总览失败", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">运营</p>
          <h1>运营总览</h1>
          <span className="muted text-sm">网关统一聚合的管理端核心指标。</span>
        </div>
        <button className="btn-secondary" onClick={refresh} disabled={loading}>刷新</button>
      </div>

      <div className="grid grid-cols-4 gap-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
        ) : (
          <>
            <MetricCard label="会话总数" value={formatInteger(summary?.conversation_count)} spark={[3,5,8,12,9,15,18,summary?.conversation_count ?? 0]} />
            <MetricCard label="错误服务" value={formatInteger(summary?.error_count)} spark={[2,1,3,0,2,1,0,summary?.error_count ?? 0]} tone={summary?.error_count ? "danger" : "ok"} />
            <MetricCard label="活跃告警" value={formatInteger(summary?.active_alert_count)} spark={[0,1,2,1,0,1,2,summary?.active_alert_count ?? 0]} tone={summary?.active_alert_count ? "warning" : "ok"} />
            <MetricCard label="P95 延迟" value={summary ? `${summary.p95_latency_ms}ms` : "—"} spark={[120,98,145,110,95,130,105,summary?.p95_latency_ms ?? 0]} />
          </>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        <article className="panel animate-slide-up stagger-1">
          <h2 className="text-base font-semibold mb-4">管理端健康</h2>
          <div className="kv-list">
            <span>服务</span><strong>{health?.service ?? "gateway"}</strong>
            <span>状态</span><StatusBadge status={health?.status ?? (loading ? "loading" : "unknown")} />
            <span>就绪</span><StatusBadge status={health?.ready ?? false} />
          </div>
        </article>
        <article className="panel panel-accent animate-slide-up stagger-2">
          <h2 className="text-base font-semibold mb-3">下一步建议</h2>
          <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            优先检查知识库、RAG 诊断和 Agent 编排页面，确认后台链路都通过 gateway 暴露。
          </p>
          <div className="mt-4 flex gap-2">
            <span className="badge badge-success">Gateway OK</span>
            <span className="badge badge-neutral">Strict Gate</span>
          </div>
        </article>
      </div>
    </section>
  );
}

function MetricCard({ label, value, spark, tone = "ok" }: { label: string; value: string; spark: number[]; tone?: "ok" | "danger" | "warning" }) {
  const max = Math.max(...spark, 1);
  const color = tone === "danger" ? "var(--accent-danger)" : tone === "warning" ? "var(--accent-ember)" : "var(--accent-frost)";
  const glowClass = tone === "danger" ? "shadow-glow-ember" : tone === "warning" ? "shadow-glow-ember" : "shadow-glow";

  return (
    <article className={`metric-card ${glowClass}`}>
      <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>{label}</span>
      <strong className="text-3xl font-bold tracking-tight" style={{ color }}>{value}</strong>
      <div className="flex items-end gap-[3px] h-8 mt-1">
        {spark.map((v, i) => (
          <div
            key={i}
            className="rounded-sm transition-all duration-300"
            style={{
              width: 6,
              height: `${Math.max((v / max) * 100, 8)}%`,
              background: i === spark.length - 1 ? color : `${color}33`,
            }}
          />
        ))}
      </div>
    </article>
  );
}
