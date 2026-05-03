import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padded?: boolean;
  hoverable?: boolean;
}

export function Card({ padded = true, hoverable, className, children, ...rest }: CardProps) {
  return (
    <div className={cn("card", hoverable && "card-hover", padded && "p-5", className)} {...rest}>
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  extra?: ReactNode;
  className?: string;
}

export function CardHeader({ title, description, extra, className }: CardHeaderProps) {
  return (
    <div className={cn("flex items-start justify-between gap-3 pb-3 border-b border-slate-100 mb-4", className)}>
      <div>
        <div className="text-base font-semibold text-slate-900">{title}</div>
        {description && <div className="mt-0.5 text-xs text-slate-500">{description}</div>}
      </div>
      {extra && <div className="shrink-0">{extra}</div>}
    </div>
  );
}
