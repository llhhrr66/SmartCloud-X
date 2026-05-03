import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, AlertCircle, Code, FileText, HeadphonesIcon, ShoppingBag, Globe, Paperclip, Send } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { businessApis } from "@/lib/sdk";
import { notifyError, notifySuccess } from "@/lib/errors";
import type { TicketCategory, TicketPriority } from "@smartcloud-x/frontend-sdk/web-user";

const CATEGORY_OPTIONS: { value: TicketCategory; label: string; icon: any; desc: string }[] = [
  { value: "technical_support", label: "技术问题",  icon: Code,      desc: "服务异常 / 接口报错 / 部署问题" },
  { value: "billing",            label: "费用账单",  icon: HeadphonesIcon, desc: "费用咨询 / 账单异常 / 退款" },
  { value: "order",              label: "订单问题",  icon: ShoppingBag, desc: "购买咨询 / 订单异常 / 续费" },
  { value: "icp",                label: "ICP 备案",  icon: Globe,      desc: "备案咨询 / 材料问题 / 状态查询" },
];

const PRIORITY_OPTIONS: { value: TicketPriority; label: string; tone: string; desc: string }[] = [
  { value: "low",     label: "低",   tone: "bg-slate-50 text-slate-600 border-slate-200",        desc: "可延后处理" },
  { value: "medium",  label: "中",   tone: "bg-info-50 text-info-600 border-info-200",            desc: "正常响应" },
  { value: "high",    label: "高",   tone: "bg-warning-50 text-warning-600 border-warning-200",   desc: "影响业务" },
  { value: "urgent",  label: "紧急", tone: "bg-danger-50 text-danger-600 border-danger-200",      desc: "服务中断" },
];

export default function NewTicketPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [category, setCategory] = useState<TicketCategory>(CATEGORY_OPTIONS[0].value);
  const [priority, setPriority] = useState<TicketPriority>("medium");
  const [subject, setSubject] = useState("");
  const [content, setContent] = useState("");

  useEffect(() => {
    const c = params.get("category") as TicketCategory | null;
    if (c) setCategory(c);
    const p = params.get("priority") as TicketPriority | null;
    if (p) setPriority(p);
    const s = params.get("subject");
    if (s) setSubject(s);
    const t = params.get("content");
    if (t) setContent(t);
  }, [params]);

  const createMut = useMutation({
    mutationFn: () => businessApis.tickets.createTicket({ category, priority, subject, content, attachments: [] }),
    onSuccess: (t) => {
      notifySuccess("工单已提交");
      navigate(`/tickets/${t.ticketNo}`);
    },
    onError: (e) => notifyError(e, "提交工单失败"),
  });

  return (
    <PageContainer size="narrow">
      <PageHeader
        title="新建工单"
        description="详细描述问题，团队会尽快与你联系"
        breadcrumb={[{ label: "业务中心" }, { label: "工单中心", to: "/tickets" }, { label: "新建工单" }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/tickets")}>返回</Button>}
      />

      <Card>
        <CardHeader title="选择问题分类" description="不同分类对应不同的支持团队，请选择最贴合的一项" />
        <div className="grid grid-cols-2 gap-3">
          {CATEGORY_OPTIONS.map((c) => {
            const active = c.value === category;
            const Icon = c.icon;
            return (
              <button
                key={c.value as string}
                type="button"
                onClick={() => setCategory(c.value)}
                className={`flex items-start gap-3 rounded-xl border p-4 text-left transition ${
                  active ? "border-brand-500 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <div className={`flex size-9 items-center justify-center rounded-lg ${active ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-500"}`}>
                  <Icon className="size-4" />
                </div>
                <div>
                  <div className="text-sm font-medium text-slate-900">{c.label}</div>
                  <div className="mt-0.5 text-xs text-slate-500">{c.desc}</div>
                </div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="紧急程度" description="紧急工单会被快速派发，请合理使用" />
        <div className="grid grid-cols-4 gap-2">
          {PRIORITY_OPTIONS.map((p) => {
            const active = p.value === priority;
            return (
              <button
                key={p.value}
                type="button"
                onClick={() => setPriority(p.value)}
                className={`rounded-lg border px-3 py-3 text-left transition ${
                  active ? p.tone : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <div className="text-sm font-medium">{p.label}</div>
                <div className="mt-0.5 text-[11px] text-slate-500">{p.desc}</div>
              </button>
            );
          })}
        </div>
      </Card>

      <Card className="mt-5">
        <CardHeader title="问题详情" />
        <div className="space-y-4">
          <Input
            label="工单标题"
            placeholder="一句话描述你的问题，便于团队快速识别"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            hint="建议不少于 5 个字"
          />
          <div>
            <label className="label">问题描述</label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="请详细描述：&#10;1. 你想做什么 / 期望的效果&#10;2. 实际发生了什么 / 错误现象&#10;3. 你已经尝试过的步骤&#10;4. 相关日志、截图或资源 ID"
              rows={8}
              className="input min-h-[160px] font-mono text-[13px] leading-6"
            />
          </div>
          <div>
            <label className="label">附件（可选）</label>
            <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50/40 px-6 py-6 text-center">
              <Paperclip className="mx-auto mb-2 size-6 text-slate-400" />
              <div className="text-sm text-slate-600">点击上传或拖拽文件</div>
              <div className="mt-1 text-xs text-slate-400">支持图片、日志、PDF，最多 10 个文件</div>
            </div>
          </div>

          <div className="rounded-lg bg-info-50 p-4 text-xs text-info-600">
            <div className="mb-1 inline-flex items-center gap-1 font-medium"><AlertCircle className="size-3.5" />提示</div>
            <ul className="ml-5 list-disc space-y-1">
              <li>详细的问题描述能让客服更快定位问题</li>
              <li>紧急问题建议同时联系销售或客户经理</li>
              <li>提交后会在工单详情页与客服持续沟通</li>
            </ul>
          </div>

          <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
            <Button variant="secondary" onClick={() => navigate("/tickets")}>取消</Button>
            <Button
              loading={createMut.isPending}
              disabled={!subject.trim() || !content.trim()}
              onClick={() => createMut.mutate()}
              leftIcon={<Send className="size-3.5" />}
            >提交工单</Button>
          </div>
        </div>
      </Card>
    </PageContainer>
  );
}
