import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "success" | "warning" | "danger" | "info" | "neutral" | "brand";

interface BadgeProps {
  tone?: Tone;
  className?: string;
  children?: ReactNode;
  dot?: boolean;
}

const toneCls: Record<Tone, string> = {
  success: "badge-success",
  warning: "badge-warning",
  danger: "badge-danger",
  info: "badge-info",
  neutral: "badge-neutral",
  brand: "badge-brand",
};

const dotCls: Record<Tone, string> = {
  success: "bg-success-500",
  warning: "bg-warning-500",
  danger: "bg-danger-500",
  info: "bg-info-500",
  neutral: "bg-slate-400",
  brand: "bg-brand-500",
};

export function Badge({ tone = "neutral", className, children, dot }: BadgeProps) {
  return (
    <span className={cn("badge", toneCls[tone], className)}>
      {dot && <span className={cn("size-1.5 rounded-full", dotCls[tone])} />}
      {children}
    </span>
  );
}
