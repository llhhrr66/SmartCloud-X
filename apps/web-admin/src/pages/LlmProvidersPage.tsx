import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, SelectInput, TextInput } from "../components/FormControls";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";

interface LlmProviderRecord {
  provider_id: string;
  name: string;
  api_key: string;
  api_url: string;
  model_name: string;
  provider_type: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface LlmProviderTestResult {
  success: boolean;
  message: string;
  model_id: string | null;
  latency_ms: number | null;
}

interface LlmProviderModelsResult {
  success: boolean;
  message: string;
  models: string[];
}

const emptyForm = {
  name: "",
  api_key: "",
  api_url: "",
  model_name: "",
  provider_type: "openai-compatible",
  is_active: false,
};

export function LlmProvidersPage() {
  const [items, setItems] = useState<LlmProviderRecord[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [selected, setSelected] = useState<LlmProviderRecord | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [testResult, setTestResult] = useState<LlmProviderTestResult | null>(null);
  const [testLoading, setTestLoading] = useState<string | null>(null);
  const [modelsResult, setModelsResult] = useState<LlmProviderModelsResult | null>(null);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [showModelsModal, setShowModelsModal] = useState(false);
  const [rowTestResult, setRowTestResult] = useState<Record<string, LlmProviderTestResult>>({});
  const toast = useToast();

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const res = await adminApi.listLlmProviders();
      setItems(Array.isArray(res) ? res : (res as { items?: LlmProviderRecord[] }).items ?? []);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "加载 LLM 配置失败", "error");
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setSelected(null);
    setForm(emptyForm);
    setTestResult(null);
    setShowModal(true);
  }

  function openEdit(item: LlmProviderRecord) {
    setSelected(item);
    setForm({
      name: item.name,
      api_key: "",
      api_url: item.api_url,
      model_name: item.model_name,
      provider_type: item.provider_type,
      is_active: item.is_active,
    });
    setTestResult(null);
    setShowModal(true);
  }

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    setLoading(true);
    try {
      if (selected) {
        const update: Record<string, unknown> = {};
        if (form.name) update.name = form.name;
        if (form.api_key) update.api_key = form.api_key;
        if (form.api_url) update.api_url = form.api_url;
        if (form.model_name) update.model_name = form.model_name;
        if (form.provider_type) update.provider_type = form.provider_type;
        update.is_active = form.is_active;
        await adminApi.updateLlmProvider(selected.provider_id, update);
      } else {
        await adminApi.createLlmProvider(form);
      }
      setShowModal(false);
      toast.push(selected ? "LLM 配置已更新" : "LLM 配置已创建", "success");
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "保存 LLM 配置失败", "error");
    } finally {
      setLoading(false);
    }
  }

  async function remove(providerId: string) {
    if (!confirm("确认删除此 LLM 配置？")) return;
    setLoading(true);
    try {
      await adminApi.deleteLlmProvider(providerId);
      toast.push("LLM 配置已删除", "success");
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "删除失败", "error");
    } finally {
      setLoading(false);
    }
  }

  function resolveApiKey(row: LlmProviderRecord) {
    return form.api_key || row.api_key;
  }

  async function testConnectionInModal() {
    const key = form.api_key || (selected?.api_key ?? "");
    if (!key || !form.api_url) {
      setTestResult({ success: false, message: "请填写 API Key 和 API URL", model_id: null, latency_ms: null });
      return;
    }
    setTestLoading("modal");
    setTestResult(null);
    try {
      const result = await adminApi.testLlmProvider({
        api_key: key,
        api_url: form.api_url,
        model_name: form.model_name || undefined,
      });
      setTestResult(result);
    } catch (err) {
      setTestResult({ success: false, message: err instanceof Error ? err.message : "测试失败", model_id: null, latency_ms: null });
    } finally {
      setTestLoading(null);
    }
  }

  async function fetchModelsInModal() {
    const key = form.api_key || (selected?.api_key ?? "");
    if (!key || !form.api_url) {
      toast.push("请填写 API Key 和 API URL 后再获取模型列表", "error");
      return;
    }
    setModelsLoading(true);
    setModelsResult(null);
    try {
      const result = await adminApi.fetchLlmProviderModels({
        api_key: key,
        api_url: form.api_url,
      });
      setModelsResult(result);
      setShowModelsModal(true);
    } catch (err) {
      setModelsResult({ success: false, message: err instanceof Error ? err.message : "获取模型列表失败", models: [] });
      setShowModelsModal(true);
    } finally {
      setModelsLoading(false);
    }
  }

  async function testConnectionInRow(row: LlmProviderRecord) {
    setTestLoading(row.provider_id);
    try {
      const result = await adminApi.testLlmProvider({
        api_key: row.api_key,
        api_url: row.api_url,
        model_name: row.model_name || undefined,
      });
      setRowTestResult((prev) => ({ ...prev, [row.provider_id]: result }));
      if (result.success) toast.push(`${row.name} 连接成功 (${result.latency_ms}ms)`, "success");
      else toast.push(`${row.name} 连接失败: ${result.message}`, "error");
    } catch (err) {
      setRowTestResult((prev) => ({ ...prev, [row.provider_id]: { success: false, message: err instanceof Error ? err.message : "测试失败", model_id: null, latency_ms: null } }));
      toast.push("测试失败", "error");
    } finally {
      setTestLoading(null);
    }
  }

  function pickModel(modelId: string) {
    setForm({ ...form, model_name: modelId });
    setShowModelsModal(false);
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">模型配置</p>
          <h1>LLM 供应商管理</h1>
          <span className="muted text-sm">管理 LLM 供应商的 API Key、接口地址和模型配置，支持测试连接与获取可用模型列表。</span>
        </div>
        <button className="btn-primary" onClick={openCreate}>添加供应商</button>
      </div>

      <article className="panel animate-slide-up stagger-1">
        <h2 className="text-base font-semibold mb-3">供应商列表</h2>
        <DataTable
          rows={items}
          keyOf={(row) => row.provider_id}
          columns={[
            { key: "name", title: "名称", render: (row) => <button className="btn-link" onClick={() => openEdit(row)}>{row.name}</button> },
            { key: "status", title: "状态", render: (row) => <StatusBadge status={row.is_active ? "active" : "inactive"} /> },
            { key: "api_url", title: "API URL", render: (row) => <small className="muted">{row.api_url}</small> },
            { key: "model", title: "模型", render: (row) => <code>{row.model_name}</code> },
            { key: "type", title: "类型", render: (row) => row.provider_type },
            { key: "test", title: "连接测试", render: (row) => {
              const result = rowTestResult[row.provider_id];
              return (
                <div className="flex items-center gap-2">
                  <button className="btn-ghost" disabled={testLoading === row.provider_id} onClick={() => testConnectionInRow(row)}>
                    {testLoading === row.provider_id ? "测试中…" : "测试"}
                  </button>
                  {result && (
                    <span className={`text-xs ${result.success ? "text-volt" : "text-danger"}`}>
                      {result.success ? `✓ ${result.latency_ms}ms` : "✗"}
                    </span>
                  )}
                </div>
              );
            }},
            { key: "actions", title: "操作", render: (row) => (
              <div className="flex gap-2">
                <button className="btn-ghost" onClick={() => openEdit(row)}>编辑</button>
                <button className="btn-danger" onClick={() => remove(row.provider_id)} disabled={loading}>删除</button>
              </div>
            )},
          ]}
        />
      </article>

      <Modal
        open={showModal}
        title={selected ? "编辑 LLM 供应商" : "添加 LLM 供应商"}
        onClose={() => setShowModal(false)}
        footer={
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={fetchModelsInModal} disabled={modelsLoading || (!form.api_key && !selected?.api_key) || !form.api_url}>
              {modelsLoading ? "获取中…" : "获取模型列表"}
            </button>
            <button className="btn-secondary" onClick={testConnectionInModal} disabled={testLoading === "modal" || (!form.api_key && !selected?.api_key) || !form.api_url}>
              {testLoading === "modal" ? "测试中…" : "测试连接"}
            </button>
            <button className="btn-primary" disabled={loading} onClick={() => submit()}>
              {loading ? "保存中…" : "保存"}
            </button>
          </div>
        }
      >
        <form onSubmit={submit}>
          <FormGrid>
            <Field label="名称"><TextInput value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="如：SiliconFlow / OpenAI / 自定义" /></Field>
            <Field label="供应商类型">
              <SelectInput value={form.provider_type} onChange={(e) => setForm({ ...form, provider_type: e.target.value })}>
                <option value="openai-compatible">OpenAI Compatible</option>
                <option value="anthropic">Anthropic</option>
                <option value="azure">Azure OpenAI</option>
              </SelectInput>
            </Field>
            <Field label="API URL"><TextInput value={form.api_url} onChange={(e) => setForm({ ...form, api_url: e.target.value })} required placeholder="https://api.siliconflow.cn" /></Field>
            <Field label="模型名称"><TextInput value={form.model_name} onChange={(e) => setForm({ ...form, model_name: e.target.value })} required placeholder="BAAI/bge-m3" /></Field>
            <Field className="field--full" label={selected ? "API Key（留空则不修改）" : "API Key"}>
              <TextInput type="password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} required={!selected} placeholder="sk-xxxx" />
            </Field>
          </FormGrid>
          <label className="form-field mt-3 flex items-center gap-2">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            <span className="text-sm">设为当前激活供应商（同时只允许一个激活）</span>
          </label>

          {testResult && (
            <div className="panel mt-4" style={{ background: testResult.success ? "rgba(51,210,110,0.1)" : "rgba(255,51,102,0.1)", border: `1px solid ${testResult.success ? "var(--volt)" : "var(--danger)"}` }}>
              <strong className="text-sm">{testResult.success ? "连接成功" : "连接失败"}</strong>
              <p className="text-sm mt-1" style={{ margin: 0, color: "var(--text-secondary)" }}>{testResult.message}</p>
              {testResult.model_id && <small className="muted">模型: {testResult.model_id}</small>}
              {testResult.latency_ms != null && <small className="muted"> | 延迟: {testResult.latency_ms}ms</small>}
            </div>
          )}
        </form>
      </Modal>

      <Modal
        open={showModelsModal}
        title="可用模型列表"
        onClose={() => setShowModelsModal(false)}
        footer={<button className="btn-primary" onClick={() => setShowModelsModal(false)}>关闭</button>}
      >
        {modelsResult && (
          <>
            {modelsResult.success ? (
              <div>
                <p className="muted text-sm mb-3">{modelsResult.message} — 点击模型名称可自动填入</p>
                <div style={{ maxHeight: 400, overflow: "auto" }}>
                  {modelsResult.models.map((m) => (
                    <button key={m} className="btn-ghost" style={{ margin: 4 }} onClick={() => pickModel(m)}>
                      {m}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm" style={{ color: "var(--danger)" }}>{modelsResult.message}</p>
            )}
          </>
        )}
      </Modal>
    </section>
  );
}
