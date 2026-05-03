import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  ShoppingBag, HeadphonesIcon, FileText, DollarSign,
  ArrowUpRight, Sparkles, Bot, Globe, Wallet, Activity, ChevronRight,
} from "lucide-react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Empty, Loading } from "@/components/ui/Empty";
import { businessApis } from "@/lib/sdk";
import { useAuthStore, selectCurrentUser } from "@/stores/auth";
import { formatDate, formatMoney } from "@/lib/format";
import { cn } from "@/lib/cn";

const STATS_PALETTE = [
  { icon: ShoppingBag,    bg: "from-blue-500 to-blue-600",    label: "进行中订单", key: "orders"  },
  { icon: HeadphonesIcon, bg: "from-violet-500 to-violet-600", label: "待处理工单", key: "tickets" },
  { icon: FileText,       bg: "from-emerald-500 to-emerald-600", label: "本月调用", key: "calls"  },
  { icon: DollarSign,     bg: "from-amber-500 to-amber-600",   label: "本月消费",   key: "spend"  },
] as const;

const QUICK_ACTIONS = [
  { icon: Bot,       label: "AI 助手",     desc: "智能问答 / 工具编排", to: "/chat",            tone: "bg-brand-50 text-brand-600" },
  { icon: Sparkles,  label: "新建会话",   desc: "选择智能体开始对话",  to: "/chat?new=1",       tone: "bg-violet-50 text-violet-600" },
  { icon: Globe,     label: "ICP 备案",   desc: "材料校验 + 提交申请", to: "/icp/precheck",     tone: "bg-emerald-50 text-emerald-600" },
  { icon: Wallet,    label: "查看账单",   desc: "本月费用、明细、发票", to: "/billing",          tone: "bg-amber-50 text-amber-600" },
] as const;

const SERVICE_HEALTH = [
  { name: "网关服务",     status: "ok",      latency: "12 ms" },
  { name: "AI 编排",       status: "ok",      latency: "78 ms" },
  { name: "工具中心",     status: "ok",      latency: "24 ms" },
  { name: "知识库",       status: "ok",      latency: "32 ms" },
  { name: "RAG 检索",      status: "ok",      latency: "56 ms" },
  { name: "营销服务",     status: "ok",      latency: "18 ms" },
];

export default function DashboardPage() {
  const user = useAuthStore(selectCurrentUser);
  const navigate = useNavigate();

  const dashboardQuery = useQuery({
    queryKey: ["billing", "dashboard"],
    queryFn: () => businessApis.billing.getDashboard(),
  });

  const data = dashboardQuery.data;

  const stats = [
    { key: "orders",  value: String(data?.orders?.length ?? 0),    sub: "进行中订单" },
    { key: "tickets", value: String(data?.tickets?.length ?? 0),   sub: "待处理工单" },
    { key: "calls",   value: "—",                                   sub: "本月调用" },
    { key: "spend",   value: formatMoney(data?.summary?.totalAmount, data?.summary?.currency ?? "CNY"), sub: "本月消费" },
  ];

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">
            早上好，<span className="text-gradient-brand">{user?.name ?? "用户"}</span> 👋
          </h1>
          <p className="mt-1.5 text-sm text-slate-500">欢迎回到 SmartCloud-X · 企业智能云服务平台</p>
        </div>
        <Badge tone="brand">最近 24 小时一切正常</Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {STATS_PALETTE.map((p, idx) => {
          const stat = stats[idx];
          return (
            <div key={p.key} className="stat-card">
              <div className={cn("absolute -right-6 -top-6 size-24 rounded-full bg-linear-to-br opacity-15 blur-2xl", p.bg)} />
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm text-slate-500">{p.label}</div>
                  <div className="mt-2 text-2xl font-semibold text-slate-900">{stat.value}</div>
                </div>
                <div className={cn("flex size-10 items-center justify-center rounded-xl bg-linear-to-br text-white shadow-sm", p.bg)}>
                  <p.icon className="size-5" />
                </div>
              </div>
              <div className="mt-3 flex items-center gap-1 text-xs text-success-600">
                <ArrowUpRight className="size-3" />环比稳定
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="最近订单"
            description="最近 5 条订单与处理状态"
            extra={
              <button onClick={() => navigate("/orders")} className="inline-flex items-center gap-0.5 text-sm text-brand-600 hover:underline">
                查看全部 <ChevronRight className="size-3.5" />
              </button>
            }
          />
          {dashboardQuery.isLoading ? (
            <Loading />
          ) : !data?.orders?.length ? (
            <Empty title="暂无订单" description="还没有订单记录，去看看可订阅的产品吧" />
          ) : (
            <div className="-mx-1 overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>订单号</th>
                    <th>产品</th>
                    <th>金额</th>
                    <th>状态</th>
                    <th>下单时间</th>
                  </tr>
                </thead>
                <tbody>
                  {data.orders.slice(0, 5).map((o) => (
                    <tr key={o.orderNo} className="cursor-pointer" onClick={() => navigate(`/orders/${o.orderNo}`)}>
                      <td className="font-mono text-xs text-brand-600">{o.orderNo}</td>
                      <td>{o.productType}</td>
                      <td className="font-medium text-slate-900">{formatMoney(o.amount)}</td>
                      <td><StatusBadge status={o.status} /></td>
                      <td className="text-slate-500">{formatDate(o.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="快捷操作" description="高频功能直达" />
          <div className="grid grid-cols-2 gap-3">
            {QUICK_ACTIONS.map((q) => (
              <button
                key={q.label}
                onClick={() => navigate(q.to)}
                className="group flex flex-col gap-2 rounded-xl border border-slate-100 bg-white p-3 text-left transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md"
              >
                <span className={cn("inline-flex size-9 items-center justify-center rounded-lg", q.tone)}>
                  <q.icon className="size-[18px]" />
                </span>
                <div>
                  <div className="text-sm font-medium text-slate-900 group-hover:text-brand-600">{q.label}</div>
                  <div className="mt-0.5 text-xs text-slate-500">{q.desc}</div>
                </div>
              </button>
            ))}
          </div>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title={<span className="inline-flex items-center gap-2"><Activity className="size-4 text-success-500" />系统服务状态</span>}
          description="实时监测各服务运行情况"
          extra={<Badge tone="success" dot>全部正常</Badge>}
        />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {SERVICE_HEALTH.map((s) => (
            <div key={s.name} className="rounded-xl border border-slate-100 bg-slate-50/40 p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-700">{s.name}</span>
                <span className="size-2 rounded-full bg-success-500" />
              </div>
              <div className="mt-2 text-lg font-semibold text-slate-900">{s.latency}</div>
              <div className="text-[11px] text-slate-400">平均响应</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
