import type { ReactNode } from "react";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/cn";

interface EmptyProps {
  title?: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
  compact?: boolean;
}

export function Empty({ title = "暂无数据", description, action, icon, className, compact }: EmptyProps) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", compact ? "py-8" : "py-16", className)}>
      <div className="mb-3 flex size-16 items-center justify-center rounded-full bg-slate-50 text-slate-300">
        {icon ?? <Inbox className="size-7" />}
      </div>
      <div className="text-sm font-medium text-slate-700">{title}</div>
      {description && <div className="mt-1 max-w-md text-xs text-slate-500">{description}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Loading({ tip = "加载中…", className }: { tip?: string; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-16 text-slate-500", className)}>
      <div className="mb-3 inline-block size-6 animate-spin rounded-full border-2 border-brand-500 border-r-transparent" />
      <div className="text-sm">{tip}</div>
    </div>
  );
}
