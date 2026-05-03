import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronDown, CloudCog } from "lucide-react";
import { MENU, findActiveKeys, type MenuItem } from "./menu-config";
import { cn } from "@/lib/cn";

export function Sidebar() {
  const location = useLocation();
  const { topKey, childKey } = findActiveKeys(location.pathname);
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set([topKey].filter(Boolean) as string[]));

  useEffect(() => {
    if (topKey) {
      setOpenKeys((prev) => {
        if (prev.has(topKey)) return prev;
        const next = new Set(prev);
        next.add(topKey);
        return next;
      });
    }
  }, [topKey]);

  function toggle(key: string) {
    setOpenKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <aside className="flex w-60 shrink-0 flex-col gradient-sidebar text-sidebar-text">
      <div className="flex h-16 items-center gap-2.5 px-5 border-b border-white/5">
        <div className="flex size-9 items-center justify-center rounded-lg bg-linear-to-br from-brand-400 to-brand-600 shadow-lg shadow-brand-600/30">
          <CloudCog className="size-5 text-white" />
        </div>
        <div className="leading-tight">
          <div className="font-semibold text-white text-[15px]">SmartCloud-X</div>
          <div className="text-[10.5px] text-sidebar-text-muted">企业智能云服务平台</div>
        </div>
      </div>

      <nav className="scrollbar-thin flex-1 overflow-y-auto px-3 py-4 space-y-1">
        {MENU.map((item) => (
          <SidebarItem
            key={item.key}
            item={item}
            isTopActive={item.key === topKey}
            childKey={childKey}
            open={openKeys.has(item.key)}
            onToggle={() => toggle(item.key)}
          />
        ))}
      </nav>

      <div className="border-t border-white/5 px-5 py-3 text-[11px] text-sidebar-text-muted">
        © 2026 SmartCloud-X
      </div>
    </aside>
  );
}

function SidebarItem({
  item,
  isTopActive,
  childKey,
  open,
  onToggle,
}: {
  item: MenuItem;
  isTopActive: boolean;
  childKey?: string;
  open: boolean;
  onToggle: () => void;
}) {
  const Icon = item.icon;

  if (item.children && item.children.length > 0) {
    return (
      <div>
        <button
          type="button"
          onClick={onToggle}
          className={cn(
            "flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition focus-ring",
            isTopActive ? "text-white" : "text-sidebar-text hover:bg-white/5 hover:text-white",
          )}
        >
          {Icon && <Icon className="size-4 shrink-0 opacity-90" />}
          <span className="flex-1 text-left">{item.label}</span>
          <ChevronDown className={cn("size-3.5 transition-transform", open ? "rotate-0" : "-rotate-90")} />
        </button>
        {open && (
          <div className="mt-1 ml-2 space-y-0.5 border-l border-white/5 pl-3">
            {item.children.map((child) => {
              const ChildIcon = child.icon;
              const active = child.key === childKey;
              return (
                <Link
                  key={child.key}
                  to={child.to ?? "#"}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-1.5 text-[13px] transition",
                    active
                      ? "bg-sidebar-active text-white shadow-[0_1px_0_0_rgba(61,110,248,0.4)_inset]"
                      : "text-sidebar-text hover:bg-white/5 hover:text-white",
                  )}
                >
                  {ChildIcon && <ChildIcon className="size-3.5 shrink-0" />}
                  <span className="flex-1">{child.label}</span>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <Link
      to={item.to ?? "#"}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition",
        isTopActive
          ? "bg-sidebar-active text-white"
          : "text-sidebar-text hover:bg-white/5 hover:text-white",
      )}
    >
      {Icon && <Icon className="size-4 shrink-0 opacity-90" />}
      <span className="flex-1">{item.label}</span>
    </Link>
  );
}
