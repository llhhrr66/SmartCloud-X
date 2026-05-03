import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Bot, Clock, MessageSquare, Paperclip, Send } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card, CardHeader } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Avatar } from "@/components/ui/Avatar";
import { businessApis } from "@/lib/sdk";
import { formatDate } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/errors";
import { useAuthStore, selectCurrentUser } from "@/stores/auth";

export default function TicketDetailPage() {
  const { ticketNo } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const user = useAuthStore(selectCurrentUser);
  const [reply, setReply] = useState("");

  const detail = useQuery({
    queryKey: ["tickets", "detail", ticketNo],
    enabled: !!ticketNo,
    queryFn: () => businessApis.tickets.getTicketDetail(ticketNo!),
  });

  const replyMut = useMutation({
    mutationFn: () => businessApis.tickets.replyTicket(ticketNo!, { content: reply, attachments: [] }),
    onSuccess: () => {
      setReply("");
      notifySuccess("已发送");
      qc.invalidateQueries({ queryKey: ["tickets", "detail", ticketNo] });
    },
    onError: (e) => notifyError(e, "发送失败"),
  });

  if (detail.isLoading) return <PageContainer><Loading /></PageContainer>;
  if (!detail.data) return <PageContainer><Empty title="工单不存在" /></PageContainer>;

  const { ticket, replies } = detail.data;

  return (
    <PageContainer>
      <PageHeader
        title={ticket.subject}
        description={
          <span className="inline-flex items-center gap-2 font-mono text-xs">
            工单号 <span className="text-brand-600">{ticket.ticketNo}</span>
            <StatusBadge status={ticket.status} />
            {ticket.priority && <StatusBadge status={ticket.priority} />}
          </span>
        }
        breadcrumb={[{ label: "业务中心" }, { label: "工单中心", to: "/tickets" }, { label: ticket.ticketNo }]}
        extra={<Button variant="secondary" leftIcon={<ArrowLeft className="size-3.5" />} onClick={() => navigate("/tickets")}>返回</Button>}
      />

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="对话记录" description="按时间顺序，最新回复在底部" />
          <div className="space-y-4">
            <ReplyBlock
              who="me"
              name={user?.name ?? "我"}
              time={ticket.createdAt}
              content={ticket.content || "—"}
              isFirst
            />
            {replies.map((r) => (
              <ReplyBlock
                key={r.replyNo}
                who={r.operatorType === "support" ? "support" : r.operatorType === "system" ? "system" : "me"}
                name={r.operatorType === "support" ? "客服支持" : r.operatorType === "system" ? "系统" : (user?.name ?? "我")}
                time={r.createdAt}
                content={r.content}
              />
            ))}

            <div className="pt-4 border-t border-slate-100">
              <div className="rounded-xl border border-slate-200 bg-white p-3 focus-within:border-brand-500 focus-within:shadow-[0_0_0_3px_rgba(61,110,248,0.12)]">
                <textarea
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="补充更多信息或回复客服…"
                  className="min-h-[80px] w-full resize-none bg-transparent text-sm placeholder:text-slate-400 focus:outline-none"
                />
                <div className="flex items-center justify-between border-t border-slate-100 pt-2">
                  <button className="inline-flex items-center gap-1 rounded-md p-1.5 text-xs text-slate-500 hover:bg-slate-50">
                    <Paperclip className="size-3.5" />添加附件
                  </button>
                  <Button
                    size="sm"
                    onClick={() => replyMut.mutate()}
                    loading={replyMut.isPending}
                    disabled={!reply.trim()}
                    rightIcon={<Send className="size-3.5" />}
                  >发送回复</Button>
                </div>
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="工单信息" />
          <Field label="主题" value={ticket.subject} />
          <Field label="分类" value={ticket.category} />
          <Field label="优先级" value={<StatusBadge status={ticket.priority ?? "low"} />} />
          <Field label="状态" value={<StatusBadge status={ticket.status} />} />
          <Field label="创建时间" value={formatDate(ticket.createdAt)} />
          <Field label="最后更新" value={formatDate(ticket.updatedAt)} />
          {ticket.slaMinutes !== undefined && (
            <Field
              label="SLA 响应"
              value={<span className="inline-flex items-center gap-1"><Clock className="size-3" />{ticket.slaMinutes} 分钟内</span>}
            />
          )}
          {ticket.attachments && ticket.attachments.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="mb-1.5 text-xs font-medium text-slate-500">附件</div>
              <ul className="space-y-1.5">
                {ticket.attachments.map((a) => (
                  <li key={a.fileId} className="inline-flex items-center gap-1.5 rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-700">
                    <Paperclip className="size-3" />{a.fileName}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </PageContainer>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <div className="text-slate-500">{label}</div>
      <div className="col-span-2 font-medium text-slate-900">{value}</div>
    </div>
  );
}

function ReplyBlock({
  who, name, time, content, isFirst,
}: {
  who: "me" | "support" | "system";
  name: string;
  time?: string;
  content: string;
  isFirst?: boolean;
}) {
  const isMe = who === "me";
  return (
    <div className={`flex gap-3 ${isMe ? "flex-row-reverse" : ""}`}>
      {who === "support" ? (
        <div className="flex size-9 items-center justify-center rounded-full bg-linear-to-br from-violet-500 to-violet-600 text-white shadow">
          <MessageSquare className="size-4" />
        </div>
      ) : who === "system" ? (
        <div className="flex size-9 items-center justify-center rounded-full bg-slate-100 text-slate-500">
          <Bot className="size-4" />
        </div>
      ) : (
        <Avatar name={name} size="md" />
      )}
      <div className={`flex-1 ${isMe ? "flex flex-col items-end" : ""}`}>
        <div className="mb-1 flex items-center gap-2 text-xs text-slate-400">
          <span>{name}</span>
          {time && <span>{formatDate(time)}</span>}
          {isFirst && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-500">首次提交</span>}
        </div>
        <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 ${
          isMe ? "bg-brand-500 text-white" : "bg-slate-50 text-slate-700"
        }`}>
          <div className="whitespace-pre-wrap">{content}</div>
        </div>
      </div>
    </div>
  );
}
