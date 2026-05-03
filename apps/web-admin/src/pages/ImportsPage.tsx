import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, TextInput } from "../components/FormControls";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { LegacySource, UploadRecord } from "../types";

export function ImportsPage() {
  const [sources, setSources] = useState<LegacySource[]>([]);
  const [directory, setDirectory] = useState("starter");
  const [glob, setGlob] = useState("**/*");
  const [operatorReason, setOperatorReason] = useState("admin-console-upload");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [upload, setUpload] = useState<UploadRecord | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { adminApi.sources().then(setSources).catch(() => setSources([])); }, []);

  async function previewFiles() {
    setLoading(true);
    try { setPreview(await adminApi.previewImports(directory, glob)); }
    catch (err) { toast.push(err instanceof Error ? err.message : "预览失败", "error"); }
    finally { setLoading(false); }
  }

  async function uploadFile() {
    if (!file) return;
    setLoading(true);
    try {
      const init = await adminApi.initUpload(file.name, file.type, operatorReason);
      await adminApi.uploadContent(init.upload_id, file, operatorReason);
      setUpload(await adminApi.completeUpload(init.upload_id, operatorReason));
      toast.push("文件上传完成", "success");
    } catch (err) { toast.push(err instanceof Error ? err.message : "上传失败", "error"); }
    finally { setLoading(false); }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">导入</p>
          <h1>文件导入与上传</h1>
          <span className="muted text-sm">支持目录导入预览和 canonical 文件上传流程。</span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <article className="panel">
          <h2 className="text-base font-semibold mb-4">目录导入预览</h2>
          <FormGrid>
            <Field label="目录"><TextInput value={directory} onChange={(e) => setDirectory(e.target.value)} /></Field>
            <Field label="Glob"><TextInput value={glob} onChange={(e) => setGlob(e.target.value)} /></Field>
          </FormGrid>
          <button className="btn-primary" disabled={loading} onClick={previewFiles}>预览文件</button>
          {preview && <pre className="json-panel mt-4">{JSON.stringify(preview, null, 2)}</pre>}
        </article>
        <article className="panel">
          <h2 className="text-base font-semibold mb-4">上传文件</h2>
          <Field label="选择文件"><input className="control" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
          <Field label="操作原因"><TextInput value={operatorReason} onChange={(e) => setOperatorReason(e.target.value)} /></Field>
          <button className="btn-primary" disabled={loading || !file} onClick={uploadFile}>上传并完成</button>
          {upload && (
            <div className="kv-list mt-4">
              <span>文件 ID</span><strong>{upload.file_id}</strong>
              <span>状态</span><StatusBadge status={upload.status} />
              <span>存储路径</span><strong>{upload.object_key}</strong>
            </div>
          )}
        </article>
      </div>

      <article className="panel">
        <h2 className="text-base font-semibold mb-3">知识源</h2>
        <DataTable rows={sources} keyOf={(row, index) => String(row.source_id ?? row.sourceId ?? index)} columns={[
          { key: "name", title: "名称", render: (row) => row.name },
          { key: "kind", title: "类型", render: (row) => String(row.kind ?? "—") },
          { key: "uri", title: "URI", render: (row) => String(row.uri ?? "—") },
        ]} />
      </article>
    </section>
  );
}
