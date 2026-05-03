import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "prefix"> {
  label?: string;
  hint?: string;
  error?: string;
  prefix?: ReactNode;
  suffix?: ReactNode;
  containerClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hint, error, prefix, suffix, containerClassName, className, id, ...rest },
  ref
) {
  const autoId = useId();
  const inputId = id ?? autoId;
  return (
    <div className={cn("w-full", containerClassName)}>
      {label && <label htmlFor={inputId} className="label">{label}</label>}
      <div className={cn(
        "relative flex items-center rounded-lg border border-slate-200 bg-white",
        "transition-shadow focus-within:border-brand-500 focus-within:shadow-[0_0_0_3px_rgba(61,110,248,0.12)]",
        error && "border-danger-500 focus-within:border-danger-500 focus-within:shadow-[0_0_0_3px_rgba(239,68,68,0.12)]",
      )}>
        {prefix && <span className="pl-3 text-slate-400">{prefix}</span>}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-slate-400",
            prefix && "pl-2",
            suffix && "pr-2",
            className
          )}
          {...rest}
        />
        {suffix && <span className="pr-3 text-slate-400">{suffix}</span>}
      </div>
      {(hint || error) && (
        <p className={cn("mt-1 text-xs", error ? "text-danger-600" : "text-slate-500")}>{error || hint}</p>
      )}
    </div>
  );
});
