import type { ReactNode } from "react";
import { CloudCog, ShieldCheck, Sparkles, Zap } from "lucide-react";

interface AuthLayoutProps {
  children: ReactNode;
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen w-full bg-slate-50">
      <aside className="relative hidden w-1/2 flex-col justify-between overflow-hidden p-10 text-white lg:flex">
        <div className="absolute inset-0 bg-linear-to-br from-[#1a3a8c] via-[#2a55de] to-[#3d6ef8]" />
        <div className="pointer-events-none absolute -top-32 -right-32 size-[420px] rounded-full bg-white/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-20 size-[480px] rounded-full bg-cyan-300/20 blur-3xl" />

        <div className="relative z-10 flex items-center gap-2.5">
          <div className="flex size-10 items-center justify-center rounded-xl bg-white/15 backdrop-blur ring-1 ring-white/20">
            <CloudCog className="size-5" />
          </div>
          <div>
            <div className="font-semibold text-lg">SmartCloud-X</div>
            <div className="text-[11px] text-white/60">企业智能云服务平台</div>
          </div>
        </div>

        <div className="relative z-10 max-w-md">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-white/80 backdrop-blur ring-1 ring-white/20">
            <Sparkles className="size-3.5" />
            企业级 AI · RAG · 工具编排
          </div>
          <h1 className="text-3xl font-semibold leading-tight">
            一站式智能云服务<br />
            <span className="text-white/70">让业务和团队跑得更快</span>
          </h1>
          <p className="mt-3 text-sm leading-6 text-white/70">
            订单、工单、备案、营销、调研全场景集成；AI 智能助手全程协同，可观测、可解释、可治理。
          </p>

          <div className="mt-8 grid grid-cols-2 gap-3">
            <div className="rounded-xl bg-white/10 p-4 backdrop-blur ring-1 ring-white/15">
              <Zap className="size-4 text-white/80" />
              <div className="mt-2 text-sm font-medium">敏捷部署</div>
              <div className="mt-0.5 text-[11px] text-white/60">分钟级开通</div>
            </div>
            <div className="rounded-xl bg-white/10 p-4 backdrop-blur ring-1 ring-white/15">
              <ShieldCheck className="size-4 text-white/80" />
              <div className="mt-2 text-sm font-medium">合规可信</div>
              <div className="mt-0.5 text-[11px] text-white/60">数据全链路审计</div>
            </div>
          </div>
        </div>

        <div className="relative z-10 text-xs text-white/50">© 2026 SmartCloud-X · All rights reserved</div>
      </aside>

      <main className="flex flex-1 items-center justify-center p-6 sm:p-10">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
