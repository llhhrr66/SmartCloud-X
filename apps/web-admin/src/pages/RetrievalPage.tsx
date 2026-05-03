import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, TextInput } from "../components/FormControls";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { KnowledgeBaseRecord, RetrievalDiagnosticResult, SearchPreviewResult } from "../types";

export function RetrievalPage() {
  const [bases, setBases] = useState<KnowledgeBaseRecord[]>([]);
  const [kbId, setKbId] = useState("");
  const [query, setQuery] = useState("GPU 部署前需要确认什么");
  const [preview, setPreview] = useState<SearchPreviewResult | null>(null);
  const [diagnostic, setDiagnostic] = useState<RetrievalDiagnosticResult | null>(null);
  const [answer, setAnswer] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { adminApi.knowledgeBases().then((res) => { setBases(res.items ?? []); setKbId(res.items?.[0]?.kb_id ?? ""); }).catch(() => {}); }, []);

  async function run() {
    setLoading(true);
    try {
      const [nextPreview, nextDiagnostic, nextAnswer] = await Promise.all([
        adminApi.searchPreview({ query, kb_id: kbId || undefined, top_k: 5 }),
        adminApi.retrievalDiagnostics({ query, kb_id: kbId || undefined, top_k: 5, include_citations: true }),
        adminApi.ragAnswer({ query, topK: 5, style: "detailed" }).catch((err) => ({ error: err instanceof Error ? err.message : "RAG answer failed" })),
      ]);
      setPreview(nextPreview); setDiagnostic(nextDiagnostic); setAnswer(nextAnswer);
    } catch (err) { toast.push(err instanceof Error ? err.message : "检索诊断失败", "error"); }
    finally { setLoading(false); }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">检索</p>
          <h1>检索与 RAG 诊断</h1>
          <span className="muted text-sm">预览召回结果、诊断覆盖率并验证回答链路。</span>
        </div>
        <button className="btn-primary" disabled={loading} onClick={run}>运行诊断</button>
      </div>

      <article className="panel">
        <FormGrid>
          <Field label="查询"><TextInput value={query} onChange={(e) => setQuery(e.target.value)} /></Field>
          <Field label="知识库">
            <select className="control" value={kbId} onChange={(e) => setKbId(e.target.value)}>
              <option value="">全部</option>
              {bases.map((base) => <option key={base.kb_id} value={base.kb_id}>{base.name}</option>)}
            </select>
          </Field>
        </FormGrid>
      </article>

      <div className="grid grid-cols-2 gap-4">
        <article className="panel animate-slide-up stagger-1">
          <h2 className="text-base font-semibold mb-3">搜索预览</h2>
          <DataTable rows={preview?.items ?? []} keyOf={(row) => row.chunk_id} columns={[
            { key: "title", title: "文档", render: (row) => row.title },
            { key: "score", title: "分数", render: (row) => row.score.toFixed(3) },
            { key: "content", title: "内容", render: (row) => row.content_preview },
          ]} />
        </article>
        <article className="panel animate-slide-up stagger-2">
          <h2 className="text-base font-semibold mb-3">诊断结果</h2>
          <pre className="json-panel">{diagnostic ? JSON.stringify(diagnostic, null, 2) : "等待运行"}</pre>
        </article>
      </div>

      <article className="panel animate-slide-up stagger-3">
        <h2 className="text-base font-semibold mb-3">RAG 回答预览</h2>
        <pre className="json-panel">{answer ? JSON.stringify(answer, null, 2) : "等待运行"}</pre>
      </article>
    </section>
  );
}
