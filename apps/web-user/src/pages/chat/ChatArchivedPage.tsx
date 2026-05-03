import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Archive, RotateCcw, Trash2 } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { chatApi } from "@/lib/sdk";
import { formatDate } from "@/lib/format";
import { notifyError, notifySuccess } from "@/lib/errors";

export default function ChatArchivedPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["chat", "sessions", "archived"],
    queryFn: () => chatApi.listSessions({ status: "archived", page: 1, pageSize: 50 }),
  });

  async function handleRestore(id: string) {
    try {
      await chatApi.restoreSession(id);
      notifySuccess("已恢复会话");
      qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
    } catch (e) { notifyError(e); }
  }
  async function handleDelete(id: string) {
    if (!confirm("确认彻底删除这个会话？此操作不可恢复")) return;
    try {
      await chatApi.deleteSession(id);
      notifySuccess("已删除");
      qc.invalidateQueries({ queryKey: ["chat", "sessions"] });
    } catch (e) { notifyError(e); }
  }

  return (
    <PageContainer>
      <PageHeader
        title="已归档会话"
        description="归档的会话不影响日常使用，可随时恢复"
        breadcrumb={[{ label: "AI 智能助手" }, { label: "已归档会话" }]}
      />
      <Card padded={false}>
        {query.isLoading ? <Loading /> : !query.data?.items.length ? (
          <Empty title="暂无归档会话" description="归档的会话会出现在这里" />
        ) : (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>标题</th>
                  <th>智能体</th>
                  <th>状态</th>
                  <th>最后活跃</th>
                  <th className="text-right">操作</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((c) => (
                  <tr key={c.conversationId}>
                    <td>
                      <button className="text-left text-brand-600 hover:underline" onClick={() => navigate(`/chat/${c.conversationId}`)}>
                        <Archive className="mr-1.5 inline size-3.5 text-slate-400" />
                        {c.title || "未命名会话"}
                      </button>
                      <div className="mt-0.5 max-w-md truncate text-xs text-slate-400">{c.summary || "—"}</div>
                    </td>
                    <td>{c.currentAgent || "—"}</td>
                    <td><StatusBadge status={c.status} /></td>
                    <td className="text-slate-500">{formatDate(c.lastMessageAt || c.updatedAt)}</td>
                    <td className="text-right">
                      <Button variant="ghost" size="sm" leftIcon={<RotateCcw className="size-3.5" />} onClick={() => handleRestore(c.conversationId)}>恢复</Button>
                      <Button variant="ghost" size="sm" leftIcon={<Trash2 className="size-3.5" />} onClick={() => handleDelete(c.conversationId)}>删除</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </PageContainer>
  );
}
