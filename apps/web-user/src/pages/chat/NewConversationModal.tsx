import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useChatStore } from "@/stores/chat";
import { chatApi } from "@/lib/sdk";
import { notifyError } from "@/lib/errors";
import { cn } from "@/lib/cn";
import type { Scene } from "@smartcloud-x/frontend-sdk/web-user";
import { CHAT_AGENTS } from "./agentMeta";

interface Props {
  open: boolean;
  onClose: () => void;
  initialScene?: Scene;
}

export function NewConversationModal({ open, onClose, initialScene }: Props) {
  const navigate = useNavigate();
  const upsert = useChatStore((s) => s.upsertConversation);
  const select = useChatStore((s) => s.selectConversation);
  const [scene, setScene] = useState<Scene>("customer_service");
  const [title, setTitle] = useState("");
  const [initialContext, setInitialContext] = useState("");

  const selected = CHAT_AGENTS.find((a) => a.scene === scene)!;

  useEffect(() => {
    if (!open) return;
    setScene(initialScene ?? "customer_service");
    setTitle("");
    setInitialContext("");
  }, [open, initialScene]);

  const createMut = useMutation({
    mutationFn: () =>
      chatApi.createSession({
        scene,
        title: title.trim() || (selected?.name ? selected.name + " 会话" : "AI 会话"),
        initialContext: initialContext.trim() || undefined,
      }),
    onSuccess: async (conv) => {
      upsert(conv);
      select(conv.conversationId);
      onClose();
      navigate("/chat/" + conv.conversationId);
    },
    onError: (err) => notifyError(err, "创建会话失败"),
  });

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="xl"
      title="新建 AI 会话"
      description="选择最适合你需求的智能体，开始对话"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button
            onClick={() => createMut.mutate()}
            loading={createMut.isPending}
          >
            开始会话
          </Button>
        </>
      }
    >
      <div className="mb-4">
        <Input
          prefix={<Search className="size-4" />}
          placeholder="输入关键词筛选智能体…"
        />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        {CHAT_AGENTS.map((a) => {
          const active = a.scene === scene;
          return (
            <button
              key={a.scene as string}
              type="button"
              onClick={() => { setScene(a.scene); }}
              className={cn(
                "card relative flex flex-col gap-2 p-4 text-left transition",
                active ? "ring-2 ring-brand-500 ring-offset-2 ring-offset-white" : "card-hover",
              )}
            >
              <div className={cn("flex size-10 items-center justify-center rounded-xl bg-linear-to-br text-white shadow-sm", a.tone)}>
                <a.icon className="size-5" />
              </div>
              <div className="text-sm font-medium text-slate-900">{a.name}</div>
              <div className="text-xs text-slate-500 leading-5">{a.desc}</div>
              {active && (
                <span className="absolute right-3 top-3 size-2 rounded-full bg-brand-500 ring-2 ring-brand-100" />
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Input
          label="会话标题（可选）"
          placeholder="例如：双 11 营销海报设计"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <Input
          label="初始上下文（可选）"
          placeholder="提供背景信息，AI 会更精准"
          value={initialContext}
          onChange={(e) => setInitialContext(e.target.value)}
        />
      </div>
    </Modal>
  );
}
