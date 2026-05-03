import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";
import { MessageSquare, History, Filter } from "lucide-react";
import { PageContainer } from "@/components/layout/PageContainer";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Empty, Loading } from "@/components/ui/Empty";
import { Input } from "@/components/ui/Input";
import { chatApi } from "@/lib/sdk";
import { formatDate } from "@/lib/format";

export default function ChatMessagesPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState("");

  const query = useQuery({
    queryKey: ["chat", "sessions", "all-for-history"],
    queryFn: () => chatApi.listSessions({ page: 1, pageSize: 100 }),
  });

  const filtered = useMemo(() => {
    const list = query.data?.items ?? [];
    return keyword
      ? list.filter((c) => c.title.includes(keyword) || c.summary?.includes(keyword) || c.currentAgent.includes(keyword))
      : list;
  }, [query.data, keyword]);

  return (
    <PageContainer>
      <PageHeader
        title="消息历史"
        description="检索全部会话与消息，便于复盘"
        breadcrumb={[{ label: "AI 智能助手" }, { label: "消息历史" }]}
      />
      <Card>
        <div className="mb-4 flex items-center gap-3">
          <Input
            containerClassName="max-w-md"
            prefix={<Filter className="size-3.5" />}
            placeholder="按标题 / 摘要 / 智能体过滤…"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <span className="text-xs text-slate-500">共 {filtered.length} 个会话</span>
        </div>
        {query.isLoading ? <Loading /> : filtered.length === 0 ? (
          <Empty title="未找到匹配的会话" description="尝试调整关键词" />
        ) : (
          <ul className="divide-y divide-slate-100">
            {filtered.map((c) => (
              <li key={c.conversationId} className="cursor-pointer py-3 transition hover:bg-slate-50/60" onClick={() => navigate(`/chat/${c.conversationId}`)}>
                <div className="flex items-start gap-3 px-3">
                  <div className="mt-1 flex size-8 items-center justify-center rounded-md bg-brand-50 text-brand-500">
                    <MessageSquare className="size-4" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center justify-between">
                      <div className="font-medium text-slate-900">{c.title || "未命名会话"}</div>
                      <div className="inline-flex items-center gap-1 text-xs text-slate-400">
                        <History className="size-3" />
                        {formatDate(c.lastMessageAt || c.updatedAt)}
                      </div>
                    </div>
                    <div className="mt-1 line-clamp-2 max-w-2xl text-sm text-slate-500">{c.summary || "—"}</div>
                    <div className="mt-2 flex items-center gap-3 text-xs text-slate-400">
                      <span>智能体：{c.currentAgent || "—"}</span>
                      <span>消息：{c.messageCount} 条</span>
                      {c.totalTokens ? <span>Tokens：{c.totalTokens.toLocaleString()}</span> : null}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </PageContainer>
  );
}
