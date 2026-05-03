import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, TextInput } from "../components/FormControls";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { AdminJob, DocumentDetail, KnowledgeBaseRecord, KnowledgeChunkRecord, KnowledgeDocumentRecord } from "../types";

export function DocumentsPage() {
  const [bases, setBases] = useState<KnowledgeBaseRecord[]>([]);
  const [kbId, setKbId] = useState("");
  const [docs, setDocs] = useState<KnowledgeDocumentRecord[]>([]);
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [chunks, setChunks] = useState<KnowledgeChunkRecord[]>([]);
  const [job, setJob] = useState<AdminJob | null>(null);
  const [password, setPassword] = useState("");
  const [targetDoc, setTargetDoc] = useState<KnowledgeDocumentRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { void init(); }, []);
  useEffect(() => { if (kbId) void loadDocs(kbId); }, [kbId]);

  async function init() {
    try {
      const list = (await adminApi.knowledgeBases()).items ?? [];
      setBases(list);
      setKbId(list[0]?.kb_id ?? "");
    } catch (err) { toast.push(err instanceof Error ? err.message : "加载知识库失败", "error"); }
  }

  async function loadDocs(nextKbId = kbId) {
    setLoading(true);
    try { setDocs((await adminApi.documents(nextKbId)).items ?? []); }
    catch (err) { toast.push(err instanceof Error ? err.message : "加载文档失败", "error"); }
    finally { setLoading(false); }
  }

  async function inspect(doc: KnowledgeDocumentRecord) {
    setLoading(true);
    try {
      const [nextDetail, nextChunks] = await Promise.all([adminApi.documentDetail(doc.doc_id), adminApi.documentChunks(doc.doc_id)]);
      setDetail(nextDetail);
      setChunks(nextChunks.items ?? []);
    } catch (err) { toast.push(err instanceof Error ? err.message : "加载文档详情失败", "error"); }
    finally { setLoading(false); }
  }

  async function reindex() {
    if (!targetDoc) return;
    setLoading(true);
    try {
      const confirmation = await adminApi.createConfirmation("reindex", `reindex:${targetDoc.doc_id}`, password);
      setJob(await adminApi.reindexDocument(targetDoc.doc_id, confirmation.confirm_token, "admin-console-reindex"));
      setTargetDoc(null);
      setPassword("");
      toast.push("重建索引任务已提交", "success");
    } catch (err) { toast.push(err instanceof Error ? err.message : "重建索引失败", "error"); }
    finally { setLoading(false); }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">文档</p>
          <h1>文档与索引管理</h1>
          <span className="muted text-sm">查看文档解析、索引状态、分块和异步任务。</span>
        </div>
        <button className="btn-secondary" onClick={() => loadDocs()}>刷新</button>
      </div>

      <article className="panel">
        <FormGrid>
          <Field label="知识库">
            <select className="control" value={kbId} onChange={(e) => setKbId(e.target.value)}>
              {bases.map((base) => <option key={base.kb_id} value={base.kb_id}>{base.name}</option>)}
            </select>
          </Field>
        </FormGrid>
        <DataTable rows={docs} keyOf={(row) => row.doc_id} columns={[
          { key: "title", title: "文档", render: (row) => <button className="btn-link" onClick={() => inspect(row)}>{row.title}</button> },
          { key: "status", title: "状态", render: (row) => <StatusBadge status={row.status} /> },
          { key: "index", title: "索引", render: (row) => <StatusBadge status={row.index_status} /> },
          { key: "chunks", title: "分块/Tokens", render: (row) => `${row.chunk_count}/${row.token_count}` },
          { key: "actions", title: "操作", render: (row) => <button className="btn-ghost" onClick={() => setTargetDoc(row)}>重建索引</button> },
        ]} />
      </article>

      <div className="grid grid-cols-2 gap-4">
        <article className="panel">
          <h2 className="text-base font-semibold mb-3">文档详情</h2>
          {detail ? (
            <div className="kv-list">
              <span>文档</span><strong>{detail.document.title}</strong>
              <span>分块</span><strong>{detail.chunk_stats.chunk_count}</strong>
              <span>Token</span><strong>{detail.chunk_stats.token_count}</strong>
              <span>最近任务</span><strong>{detail.chunk_stats.latest_job_id ?? "—"}</strong>
            </div>
          ) : <p className="muted text-sm">选择文档查看详情。</p>}
        </article>
        <article className="panel">
          <h2 className="text-base font-semibold mb-3">最近任务</h2>
          {job ? (
            <div className="kv-list">
              <span>任务</span><strong>{job.job_id}</strong>
              <span>状态</span><StatusBadge status={job.status} />
              <span>进度</span><strong>{job.progress}%</strong>
            </div>
          ) : <p className="muted text-sm">暂无任务。</p>}
        </article>
      </div>

      <article className="panel">
        <h2 className="text-base font-semibold mb-3">文档分块</h2>
        <DataTable rows={chunks} keyOf={(row) => row.chunk_id} columns={[
          { key: "pos", title: "位置", render: (row) => row.position },
          { key: "tokens", title: "Tokens", render: (row) => row.token_count },
          { key: "content", title: "内容预览", render: (row) => row.content_preview },
        ]} />
      </article>

      <Modal open={Boolean(targetDoc)} title="确认重建索引" onClose={() => setTargetDoc(null)} footer={
        <>
          <button className="btn-ghost" onClick={() => setTargetDoc(null)}>取消</button>
          <button className="btn-danger" disabled={loading || !password} onClick={reindex}>确认重建</button>
        </>
      }>
        <p className="mb-4 text-sm">重建索引会重新处理文档：<strong>{targetDoc?.title}</strong></p>
        <Field label="管理员密码"><TextInput type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
      </Modal>
    </section>
  );
}
