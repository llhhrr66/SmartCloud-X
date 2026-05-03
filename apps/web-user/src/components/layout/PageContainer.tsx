import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PageContainerProps {
  children: ReactNode;
  className?: string;
  size?: "default" | "narrow" | "wide";
}

export function PageContainer({ children, className, size = "default" }: PageContainerProps) {
  const sizeCls = size === "narrow" ? "max-w-3xl" : size === "wide" ? "max-w-[1600px]" : "max-w-[1400px]";
  return (
    <div className={cn("mx-auto px-6 py-6", sizeCls, className)}>
      {children}
    </div>
  );
}
