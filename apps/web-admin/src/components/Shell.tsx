import type { ReactNode } from "react";
import type { AdminProfile } from "../types";

export type AdminView = "dashboard" | "knowledge" | "documents" | "imports" | "retrieval" | "agents" | "marketing" | "audit" | "llm-providers" | "document-viewer";

const navItems: Array<{ id: AdminView; label: string; icon: string; permission?: string }> = [
  { id: "dashboard", label: "运营总览", icon: "◉", permission: "admin:ops.read" },
  { id: "knowledge", label: "知识库", icon: "◈", permission: "admin:kb.read" },
  { id: "documents", label: "文档索引", icon: "⊞", permission: "admin:kb.read" },
  { id: "imports", label: "导入上传", icon: "▲", permission: "admin:kb.write" },
  { id: "retrieval", label: "检索诊断", icon: "◎", permission: "admin:kb.read" },
  { id: "agents", label: "Agent 编排", icon: "✦", permission: "admin:ops.read" },
  { id: "marketing", label: "营销活动", icon: "◆", permission: "admin:marketing.read" },
  { id: "llm-providers", label: "LLM 配置", icon: "⟐", permission: "admin:ops.read" },
  { id: "audit", label: "审计运行时", icon: "▤", permission: "admin:kb.read" },
];

function canSee(admin: AdminProfile, permission?: string) {
  return !permission || admin.permissions.includes(permission) || admin.permissions.includes("admin:manage");
}

export function Shell({ admin, active, onNavigate, onLogout, children }: {
  admin: AdminProfile;
  active: AdminView;
  onNavigate: (view: AdminView) => void;
  onLogout: () => void;
  children: ReactNode;
}) {
  const visibleItems = navItems.filter((item) => canSee(admin, item.permission));

  return (
    <div className="admin-shell">
      <aside className="admin-shell-sidebar">
        <div className="flex items-center gap-3 px-3 pb-5 mb-2 border-b border-white/[0.06]">
          <div className="w-10 h-10 rounded-xl grid place-items-center text-sm font-black"
            style={{ background: "linear-gradient(135deg, #53a7ff, #33d26e)", color: "#0d1127" }}>
            SC
          </div>
          <div>
            <p className="text-[0.68rem] font-bold tracking-widest uppercase text-white/40 mb-0.5">SmartCloud-X</p>
            <strong className="text-sm text-white/90">管理控制台</strong>
          </div>
        </div>
        <nav className="flex flex-col gap-1 flex-1 px-2" aria-label="管理端导航">
          {visibleItems.map((item) => (
            <button
              key={item.id}
              className={`sidebar-nav-item ${item.id === active ? "active" : ""}`}
              onClick={() => onNavigate(item.id)}
              type="button"
            >
              <span className="sidebar-nav-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="mt-auto flex flex-col gap-2.5 px-2 pt-4">
          <div className="rounded-xl p-3.5" style={{ background: "var(--sidebar-surface)", border: "1px solid var(--border-subtle)" }}>
            <span className="text-[0.72rem] text-white/30">当前管理员</span>
            <strong className="block mt-1 text-sm text-white/90">{admin.name}</strong>
            <small className="text-[0.72rem] text-white/40">{admin.roles.join(" / ") || "admin"}</small>
          </div>
          <button className="btn-ghost btn-full" onClick={onLogout} type="button">退出登录</button>
        </div>
      </aside>
      <main className="admin-shell-main">{children}</main>
    </div>
  );
}
