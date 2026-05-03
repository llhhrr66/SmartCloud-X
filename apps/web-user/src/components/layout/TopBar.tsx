import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bell, ChevronDown, LogOut, Search, Settings, User } from "lucide-react";
import { Avatar } from "@/components/ui/Avatar";
import { useAuthStore, selectCurrentUser } from "@/stores/auth";
import { authService } from "@/lib/auth-service";
import { notifyError, notifySuccess } from "@/lib/errors";
import { cn } from "@/lib/cn";

export function TopBar() {
  const user = useAuthStore(selectCurrentUser);
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (menuOpen && menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  async function handleLogout() {
    try {
      await authService.logout();
      notifySuccess("已退出登录");
    } catch (err) {
      notifyError(err, "退出失败");
    } finally {
      navigate("/login", { replace: true });
    }
  }

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-slate-200 bg-white/85 px-6 backdrop-blur">
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <input
          type="search"
          placeholder="搜索订单、工单、文档…"
          className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm placeholder:text-slate-400 focus:bg-white focus:outline-none focus:border-brand-500 focus:shadow-[0_0_0_3px_rgba(61,110,248,0.12)]"
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="relative inline-flex size-9 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-700 focus-ring"
          aria-label="通知"
        >
          <Bell className="size-[18px]" />
          <span className="absolute right-2 top-2 size-1.5 rounded-full bg-danger-500" />
        </button>

        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            className={cn(
              "flex items-center gap-2 rounded-full p-1 pr-2 transition",
              menuOpen ? "bg-slate-100" : "hover:bg-slate-100",
            )}
          >
            <Avatar name={user?.name ?? "用户"} src={user?.avatarUrl} size="sm" />
            <span className="text-sm font-medium text-slate-700">{user?.name ?? "未登录"}</span>
            <ChevronDown className="size-3.5 text-slate-400" />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-full mt-2 w-56 rounded-lg bg-white shadow-[var(--shadow-popover)] border border-slate-100 py-1.5 text-sm">
              <div className="px-3 py-2 border-b border-slate-100">
                <div className="font-medium text-slate-900">{user?.name ?? "未登录"}</div>
                <div className="mt-0.5 truncate text-xs text-slate-500">{user?.email ?? "—"}</div>
              </div>
              <button
                type="button"
                onClick={() => { setMenuOpen(false); navigate("/profile"); }}
                className="flex w-full items-center gap-2 px-3 py-2 text-slate-700 hover:bg-slate-50"
              >
                <User className="size-4 text-slate-400" />个人资料
              </button>
              <button
                type="button"
                onClick={() => { setMenuOpen(false); navigate("/profile/security"); }}
                className="flex w-full items-center gap-2 px-3 py-2 text-slate-700 hover:bg-slate-50"
              >
                <Settings className="size-4 text-slate-400" />安全设置
              </button>
              <div className="my-1 border-t border-slate-100" />
              <button
                type="button"
                onClick={() => { setMenuOpen(false); handleLogout(); }}
                className="flex w-full items-center gap-2 px-3 py-2 text-danger-600 hover:bg-danger-50"
              >
                <LogOut className="size-4" />退出登录
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
