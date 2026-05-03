import { useMemo } from "react";
import { cn } from "@/lib/cn";

interface AvatarProps {
  name?: string;
  src?: string;
  size?: "sm" | "md" | "lg" | "xl";
  className?: string;
}

const sizeCls = {
  sm: "size-7 text-xs",
  md: "size-9 text-sm",
  lg: "size-12 text-base",
  xl: "size-16 text-xl",
};

const palette = ["#3D6EF8", "#10B981", "#F59E0B", "#8B5CF6", "#EC4899", "#06B6D4", "#84CC16"];

export function Avatar({ name = "用户", src, size = "md", className }: AvatarProps) {
  const initials = useMemo(() => {
    const trimmed = name.trim();
    if (!trimmed) return "U";
    if (/[一-龥]/.test(trimmed)) return trimmed.slice(-2);
    const parts = trimmed.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }, [name]);

  const color = useMemo(() => {
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = (hash << 5) - hash + name.charCodeAt(i);
    return palette[Math.abs(hash) % palette.length];
  }, [name]);

  if (src) {
    return <img src={src} alt={name} className={cn("rounded-full object-cover ring-1 ring-white/40", sizeCls[size], className)} />;
  }
  return (
    <span
      className={cn("inline-flex items-center justify-center rounded-full font-medium text-white", sizeCls[size], className)}
      style={{ backgroundColor: color }}
    >
      {initials}
    </span>
  );
}
