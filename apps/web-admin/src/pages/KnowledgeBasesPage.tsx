import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, SelectInput, TextArea, TextInput } from "../components/FormControls";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { KnowledgeBaseRecord } from "../types";

const emptyForm = {
  name: "",
  code: "",
  scene: "customer_service",
  language: "zh-CN",
  retrieval_mode: "hybrid-baseline",
  embedding_model: "baseline-keyword",
  description: "",
  operatorReason: "admin-console-change",
};

export function KnowledgeBasesPage() {
  const [items, setItems] = useState<KnowledgeBaseRecord[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [selected, setSelected] = useState<KnowledgeBaseRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try { setItems((await adminApi.knowledgeBases()).items ?? []); }
    catch (err) { toast.push(err instanceof Error ? err.message : "加载知识库失败", "error"); }
    finally { setLoading(false); }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      if (selected) {
        await adminApi.updateKnowledgeBase(selected.kb_id, form);
        toast.push("知识库已更新", "success");
      } else {
        await adminApi.createKnowledgeBase(form);
        toast.push("知识库已创建", "success");
      }
      setForm(emptyForm);
      setSelected(null);
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "保存知识库失败", "error");
    } finally {
      setLoading(false);
    }
  }

  function edit(item: KnowledgeBaseRecord) {
    setSelected(item);
    setForm({
      name: item.name,
      code: item.code,
      scene: item.scene,
      language: item.language,
      retrieval_mode: item.retrieval_mode,
      embedding_model: "baseline-keyword",
      description: item.description ?? "",
      operatorReason: "admin-console-update",
    });
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">知识库</p>
          <h1>知识库管理</h1>
          <span className="muted text-sm">管理知识库元数据、检索模式和启用状态。</span>
        </div>
        <button className="btn-secondary" onClick={load} disabled={loading}>刷新</button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <form className="panel" onSubmit={submit}>
          <h2 className="text-base font-semibold mb-4">{selected ? "编辑知识库" : "创建知识库"}</h2>
          <FormGrid>
            <Field label="名称"><TextInput value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
            <Field label="编码"><TextInput value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required disabled={Boolean(selected)} /></Field>
            <Field label="场景"><TextInput value={form.scene} onChange={(e) => setForm({ ...form, scene: e.target.value })} required /></Field>
            <Field label="语言"><TextInput value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} required /></Field>
            <Field label="检索模式"><TextInput value={form.retrieval_mode} onChange={(e) => setForm({ ...form, retrieval_mode: e.target.value })} required /></Field>
            <Field label="状态"><SelectInput value={selected?.status ?? "ready"} onChange={(e) => setForm({ ...form, status: e.target.value } as typeof form)}><option value="ready">已就绪</option><option value="disabled">已停用</option></SelectInput></Field>
          </FormGrid>
          <Field label="描述"><TextArea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
          <Field label="操作原因"><TextInput value={form.operatorReason} onChange={(e) => setForm({ ...form, operatorReason: e.target.value })} required /></Field>
          <div className="action-row">
            <button className="btn-primary" disabled={loading}>{loading ? "保存中…" : "保存"}</button>
            {selected && <button className="btn-ghost" type="button" onClick={() => { setSelected(null); setForm(emptyForm); }}>取消编辑</button>}
          </div>
        </form>
        <article className="panel">
          <h2 className="text-base font-semibold mb-4">知识库列表</h2>
          <DataTable
            rows={items}
            keyOf={(row) => row.kb_id}
            columns={[
              { key: "name", title: "名称", render: (row) => <button className="btn-link" onClick={() => edit(row)}>{row.name}</button> },
              { key: "status", title: "状态", render: (row) => <StatusBadge status={row.status} /> },
              { key: "docs", title: "文档/分块", render: (row) => `${row.document_count}/${row.chunk_count}` },
              { key: "mode", title: "检索", render: (row) => row.retrieval_mode },
            ]}
          />
        </article>
      </div>
    </section>
  );
}
