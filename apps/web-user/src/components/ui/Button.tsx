import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg" | "xl";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, disabled, leftIcon, rightIcon, block, className, children, type = "button", ...rest },
  ref
) {
  const variantCls =
    variant === "primary" ? "btn-primary" :
    variant === "secondary" ? "btn-secondary" :
    variant === "danger" ? "btn-danger" : "btn-ghost";
  const sizeCls = size === "sm" ? "btn-sm" : size === "lg" ? "btn-lg" : size === "xl" ? "btn-xl" : "btn-md";
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      className={cn("btn focus-ring", variantCls, sizeCls, block && "w-full", className)}
      {...rest}
    >
      {loading ? (
        <span className="inline-block size-4 animate-spin rounded-full border-2 border-current border-r-transparent" />
      ) : leftIcon}
      {children}
      {!loading && rightIcon}
    </button>
  );
});
