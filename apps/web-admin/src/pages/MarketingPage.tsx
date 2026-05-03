import { useEffect, useState } from "react";
import { DataTable } from "../components/DataTable";
import { Field, FormGrid, SelectInput, TextInput } from "../components/FormControls";
import { Modal } from "../components/Modal";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toast";
import { adminApi } from "../lib/api";
import type { MarketingCampaign } from "../types";

const blank: Partial<MarketingCampaign> = { name: "", product_type: "cloud", status: "draft", start_at: "", end_at: "", landing_page_url: "", highlights: [] };

export function MarketingPage() {
  const [items, setItems] = useState<MarketingCampaign[]>([]);
  const [form, setForm] = useState<Partial<MarketingCampaign>>(blank);
  const [editing, setEditing] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<MarketingCampaign | null>(null);
  const [loading, setLoading] = useState(false);
  const toast = useToast();

  useEffect(() => { void load(); }, []);

  async function load() {
    setLoading(true);
    try { setItems((await adminApi.campaigns()).items ?? []); }
    catch (err) { toast.push(err instanceof Error ? err.message : "加载营销活动失败", "error"); }
    finally { setLoading(false); }
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try { await adminApi.saveCampaign(form); setForm(blank); setEditing(false); await load(); toast.push("营销活动已保存", "success"); }
    catch (err) { toast.push(err instanceof Error ? err.message : "保存营销活动失败", "error"); }
    finally { setLoading(false); }
  }

  async function remove() {
    if (!deleteTarget) return;
    setLoading(true);
    try { await adminApi.deleteCampaign(deleteTarget.campaign_id); setDeleteTarget(null); await load(); toast.push("营销活动已删除", "success"); }
    catch (err) { toast.push(err instanceof Error ? err.message : "删除营销活动失败", "error"); }
    finally { setLoading(false); }
  }

  return (
    <section className="max-w-[1500px] mx-auto grid gap-5 animate-fade-in">
      <div className="page-heading">
        <div>
          <p className="eyebrow">营销</p>
          <h1>营销活动管理</h1>
          <span className="muted text-sm">发布、编辑和软删除运营活动。</span>
        </div>
        <button className="btn-primary" onClick={() => { setEditing(true); setForm(blank); }}>新建活动</button>
      </div>

      <article className="panel animate-slide-up stagger-1">
        <h2 className="text-base font-semibold mb-3">活动列表</h2>
        <DataTable rows={items} keyOf={(row) => row.campaign_id} columns={[
          { key: "name", title: "活动", render: (row) => <button className="btn-link" onClick={() => { setForm(row); setEditing(true); }}>{row.name}</button> },
          { key: "status", title: "状态", render: (row) => <StatusBadge status={row.status} /> },
          { key: "product", title: "产品", render: (row) => row.product_type },
          { key: "time", title: "周期", render: (row) => `${row.start_at} → ${row.end_at}` },
          { key: "actions", title: "操作", render: (row) => <button className="btn-ghost" onClick={() => setDeleteTarget(row)}>删除</button> },
        ]} />
      </article>

      <Modal open={editing} title={form.campaign_id ? "编辑活动" : "新建活动"} onClose={() => setEditing(false)} footer={
        <>
          <button className="btn-ghost" onClick={() => setEditing(false)}>取消</button>
          <button className="btn-primary" disabled={loading} onClick={() => document.getElementById("campaign-form-submit")?.click()}>保存</button>
        </>
      }>
        <form id="campaign-form" onSubmit={save}>
          <FormGrid>
            <Field label="名称"><TextInput value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></Field>
            <Field label="产品类型"><TextInput value={form.product_type ?? ""} onChange={(e) => setForm({ ...form, product_type: e.target.value })} required /></Field>
            <Field label="状态">
              <SelectInput value={form.status ?? "draft"} onChange={(e) => setForm({ ...form, status: e.target.value as MarketingCampaign["status"] })}>
                <option value="draft">草稿</option><option value="published">已发布</option><option value="expired">已过期</option>
              </SelectInput>
            </Field>
            <Field label="落地页"><TextInput value={form.landing_page_url ?? ""} onChange={(e) => setForm({ ...form, landing_page_url: e.target.value })} required /></Field>
            <Field label="开始时间"><TextInput value={form.start_at ?? ""} onChange={(e) => setForm({ ...form, start_at: e.target.value })} required /></Field>
            <Field label="结束时间"><TextInput value={form.end_at ?? ""} onChange={(e) => setForm({ ...form, end_at: e.target.value })} required /></Field>
            <Field label="亮点（逗号分隔）"><TextInput value={(form.highlights ?? []).join(",")} onChange={(e) => setForm({ ...form, highlights: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></Field>
          </FormGrid>
          <button hidden id="campaign-form-submit" />
        </form>
      </Modal>

      <Modal open={Boolean(deleteTarget)} title="确认删除活动" onClose={() => setDeleteTarget(null)} footer={
        <>
          <button className="btn-ghost" onClick={() => setDeleteTarget(null)}>取消</button>
          <button className="btn-danger" onClick={remove}>删除</button>
        </>
      }>
        <p className="text-sm">即将软删除：<strong>{deleteTarget?.name}</strong></p>
      </Modal>
    </section>
  );
}
