import { useEffect, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/cn";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  closeOnBackdrop?: boolean;
}

export function Modal({ open, onClose, title, description, children, footer, size = "md", closeOnBackdrop = true }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handler);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  const sizeCls = size === "sm" ? "max-w-md" : size === "lg" ? "max-w-3xl" : size === "xl" ? "max-w-5xl" : "max-w-xl";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal>
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={() => closeOnBackdrop && onClose()}
      />
      <div className={cn(
        "relative z-10 w-full rounded-xl bg-white shadow-[0_24px_48px_-8px_rgba(15,23,42,0.2)]",
        "animate-in fade-in zoom-in-95 duration-150",
        sizeCls,
      )}>
        {(title || description) && (
          <div className="flex items-start justify-between border-b border-slate-100 px-6 py-4">
            <div>
              {title && <div className="text-base font-semibold text-slate-900">{title}</div>}
              {description && <div className="mt-0.5 text-xs text-slate-500">{description}</div>}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus-ring"
              aria-label="关闭"
            >
              <X className="size-4" />
            </button>
          </div>
        )}
        <div className="px-6 py-5 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer && <div className="flex items-center justify-end gap-2 border-t border-slate-100 bg-slate-50/40 px-6 py-3 rounded-b-xl">{footer}</div>}
      </div>
    </div>
  );
}
