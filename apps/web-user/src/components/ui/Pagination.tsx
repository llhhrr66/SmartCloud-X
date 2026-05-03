import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onChange: (page: number) => void;
  className?: string;
}

export function Pagination({ page, pageSize, total, onChange, className }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  const canPrev = page > 1;
  const canNext = page < totalPages;

  function pages(): (number | "...")[] {
    const result: (number | "...")[] = [];
    const window = 2;
    for (let i = 1; i <= totalPages; i++) {
      if (i === 1 || i === totalPages || (i >= page - window && i <= page + window)) {
        result.push(i);
      } else if (result[result.length - 1] !== "...") {
        result.push("...");
      }
    }
    return result;
  }

  return (
    <div className={cn("flex items-center justify-between gap-4 py-3 text-sm text-slate-500", className)}>
      <div>共 {total} 条，{start}–{end}</div>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={!canPrev}
          onClick={() => canPrev && onChange(page - 1)}
          className={cn(
            "inline-flex size-8 items-center justify-center rounded-md border border-slate-200 transition",
            canPrev ? "bg-white hover:bg-slate-50" : "bg-slate-50 text-slate-300 cursor-not-allowed",
          )}
        >
          <ChevronLeft className="size-4" />
        </button>
        {pages().map((p, idx) =>
          p === "..." ? (
            <span key={`gap-${idx}`} className="px-1 text-slate-400">…</span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onChange(p)}
              className={cn(
                "inline-flex h-8 min-w-8 items-center justify-center rounded-md border px-2 text-sm transition",
                p === page
                  ? "border-brand-500 bg-brand-50 text-brand-600"
                  : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
              )}
            >
              {p}
            </button>
          )
        )}
        <button
          type="button"
          disabled={!canNext}
          onClick={() => canNext && onChange(page + 1)}
          className={cn(
            "inline-flex size-8 items-center justify-center rounded-md border border-slate-200 transition",
            canNext ? "bg-white hover:bg-slate-50" : "bg-slate-50 text-slate-300 cursor-not-allowed",
          )}
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
    </div>
  );
}
