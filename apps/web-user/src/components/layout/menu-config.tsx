import {
  LayoutDashboard,
  Bot,
  ShoppingBag,
  HeadphonesIcon,
  Wallet,
  Megaphone,
  ScrollText,
  UserCircle,
  Globe,
  type LucideIcon,
  Sparkles,
  Image as ImageIcon,
  FileSearch,
  ListTodo,
  Receipt,
  FileText,
  Inbox,
  Archive,
  History,
} from "lucide-react";

export interface MenuItem {
  key: string;
  label: string;
  to?: string;
  icon?: LucideIcon;
  children?: MenuItem[];
  match?: (pathname: string) => boolean;
}

export const MENU: MenuItem[] = [
  {
    key: "dashboard",
    label: "工作台",
    to: "/",
    icon: LayoutDashboard,
    match: (p) => p === "/" || p === "/dashboard",
  },
  {
    key: "ai",
    label: "AI 智能助手",
    icon: Bot,
    children: [
      { key: "chat", label: "AI 会话", to: "/chat", icon: Sparkles, match: (p) => p === "/chat" || p.startsWith("/chat/") && !p.startsWith("/chat/archived") && !p.startsWith("/chat/messages") },
      { key: "chat-archived", label: "已归档会话", to: "/chat/archived", icon: Archive },
      { key: "chat-messages", label: "消息历史", to: "/chat/messages", icon: History },
    ],
  },
  {
    key: "business",
    label: "业务中心",
    icon: ShoppingBag,
    children: [
      { key: "orders", label: "我的订单", to: "/orders", icon: ShoppingBag, match: (p) => p.startsWith("/orders") && !p.startsWith("/orders/refunds") },
      { key: "refunds", label: "退款管理", to: "/orders/refunds", icon: Receipt },
      { key: "tickets", label: "工单中心", to: "/tickets", icon: HeadphonesIcon },
      { key: "icp", label: "ICP 备案", to: "/icp", icon: Globe, match: (p) => p.startsWith("/icp") },
    ],
  },
  {
    key: "finance",
    label: "财务中心",
    icon: Wallet,
    children: [
      { key: "billing-overview", label: "账单总览", to: "/billing", match: (p) => p === "/billing" },
      { key: "billing-details", label: "账单明细", to: "/billing/details" },
      { key: "billing-invoices", label: "发票管理", to: "/billing/invoices" },
    ],
  },
  {
    key: "marketing",
    label: "营销中心",
    icon: Megaphone,
    children: [
      { key: "campaigns", label: "营销活动", to: "/marketing", match: (p) => p === "/marketing" },
      { key: "marketing-copy", label: "AI 文案生成", to: "/marketing/copy", icon: Sparkles },
      { key: "posters", label: "AI 海报工作室", to: "/marketing/posters", icon: ImageIcon, match: (p) => p.startsWith("/marketing/posters") },
    ],
  },
  {
    key: "research",
    label: "市场调研",
    icon: ScrollText,
    children: [
      { key: "research-list", label: "调研任务", to: "/research", icon: ListTodo, match: (p) => p === "/research" || (p.startsWith("/research/") && !p.startsWith("/research/new")) },
      { key: "research-new", label: "新建调研", to: "/research/new", icon: FileSearch },
    ],
  },
  {
    key: "personal",
    label: "个人中心",
    icon: UserCircle,
    children: [
      { key: "profile", label: "个人资料", to: "/profile" },
      { key: "security", label: "安全设置", to: "/profile/security" },
    ],
  },
];

export function findActiveKeys(pathname: string): { topKey?: string; childKey?: string } {
  for (const top of MENU) {
    if (top.children) {
      for (const child of top.children) {
        if (child.match ? child.match(pathname) : pathname === child.to || pathname.startsWith((child.to ?? "") + "/")) {
          return { topKey: top.key, childKey: child.key };
        }
      }
    } else if (top.match ? top.match(pathname) : pathname === top.to) {
      return { topKey: top.key };
    }
  }
  return {};
}

export const ICON_MAP = {
  LayoutDashboard, Bot, ShoppingBag, HeadphonesIcon, Wallet, Megaphone, ScrollText, UserCircle, Globe,
  Sparkles, ImageIcon, FileSearch, ListTodo, Receipt, FileText, Inbox, Archive, History,
};
