import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/cn";

export interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  breadcrumb?: BreadcrumbItem[];
  extra?: ReactNode;
  className?: string;
}

export function PageHeader({ title, description, breadcrumb, extra, className }: PageHeaderProps) {
  return (
    <div className={cn("mb-5 flex flex-col gap-2 lg:flex-row lg:items-end lg:justify-between", className)}>
      <div>
        {breadcrumb && breadcrumb.length > 0 && (
          <div className="mb-2 flex items-center gap-1 text-xs text-slate-400">
            {breadcrumb.map((b, idx) => (
              <span key={idx} className="inline-flex items-center gap-1">
                {b.to ? (
                  <Link to={b.to} className="hover:text-brand-600">{b.label}</Link>
                ) : (
                  <span className="text-slate-500">{b.label}</span>
                )}
                {idx < breadcrumb.length - 1 && <ChevronRight className="size-3" />}
              </span>
            ))}
          </div>
        )}
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {extra && <div className="flex items-center gap-2">{extra}</div>}
    </div>
  );
}
