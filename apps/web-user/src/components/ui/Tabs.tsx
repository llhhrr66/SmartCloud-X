import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface TabItem {
  key: string;
  label: ReactNode;
  badge?: ReactNode;
  disabled?: boolean;
}

interface TabsProps {
  value: string;
  onChange: (key: string) => void;
  items: TabItem[];
  className?: string;
  variant?: "underline" | "pill" | "card";
}

export function Tabs({ value, onChange, items, className, variant = "underline" }: TabsProps) {
  if (variant === "pill") {
    return (
      <div className={cn("inline-flex gap-1 rounded-lg bg-slate-100 p-1", className)}>
        {items.map((it) => {
          const active = it.key === value;
          return (
            <button
              key={it.key}
              type="button"
              disabled={it.disabled}
              onClick={() => onChange(it.key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition focus-ring",
                active ? "bg-white text-brand-600 shadow-sm" : "text-slate-500 hover:text-slate-700",
                it.disabled && "opacity-50 cursor-not-allowed",
              )}
            >
              {it.label}
              {it.badge && <span className="ml-1.5">{it.badge}</span>}
            </button>
          );
        })}
      </div>
    );
  }
  if (variant === "card") {
    return (
      <div className={cn("flex gap-2 rounded-lg border border-slate-200 bg-white p-1", className)}>
        {items.map((it) => {
          const active = it.key === value;
          return (
            <button
              key={it.key}
              type="button"
              disabled={it.disabled}
              onClick={() => onChange(it.key)}
              className={cn(
                "flex-1 rounded-md px-4 py-2 text-sm font-medium transition focus-ring",
                active ? "bg-brand-50 text-brand-700" : "text-slate-500 hover:bg-slate-50",
              )}
            >
              {it.label}
              {it.badge && <span className="ml-1.5">{it.badge}</span>}
            </button>
          );
        })}
      </div>
    );
  }
  return (
    <div className={cn("flex items-center gap-6 border-b border-slate-200", className)}>
      {items.map((it) => {
        const active = it.key === value;
        return (
          <button
            key={it.key}
            type="button"
            disabled={it.disabled}
            onClick={() => onChange(it.key)}
            className={cn(
              "relative -mb-px py-3 text-sm font-medium transition focus-ring",
              active ? "text-brand-600" : "text-slate-500 hover:text-slate-700",
            )}
          >
            <span className="inline-flex items-center gap-1.5">
              {it.label}
              {it.badge}
            </span>
            {active && <span className="absolute inset-x-0 -bottom-px h-0.5 bg-brand-500" />}
          </button>
        );
      })}
    </div>
  );
}
