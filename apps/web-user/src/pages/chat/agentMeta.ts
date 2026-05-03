import {
  Bot,
  Globe,
  Megaphone,
  ScrollText,
  ShieldCheck,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import type { Scene } from "@smartcloud-x/frontend-sdk/web-user";

export interface AgentMeta {
  scene: Scene;
  name: string;
  desc: string;
  icon: LucideIcon;
  tone: string;
  intro: string;
  prompts: string[];
}

export const CHAT_AGENTS: AgentMeta[] = [
  {
    scene: "customer_service",
    name: "客服助手",
    desc: "通用咨询、订单查询、问题反馈",
    icon: Bot,
    tone: "from-blue-500 to-blue-600",
    intro: "你好，我是 SmartCloud 客服助手，可以帮你查询订单状态、处理售后问题、解答产品使用疑问，以及反馈各类使用问题。",
    prompts: [
      "我的订单 #20260429001 物流一直没更新，能帮我查一下吗？",
      "收到商品有破损，怎么申请退货退款？",
      "你们的企业版和团队版功能有什么区别？",
      "我上个月的充值记录在哪里可以查看？",
    ],
  },
  {
    scene: "billing",
    name: "账单专员",
    desc: "账单查询、费用明细、发票开具、退款跟进",
    icon: Wallet,
    tone: "from-emerald-500 to-emerald-600",
    intro: "你好，我是账单专员，擅长处理账单明细核对、发票开具申请、充值扣费异常查询以及退款进度跟进。",
    prompts: [
      "本月账单总额和上月差异很大，能帮我逐项核对吗？",
      "请帮我开具 4 月份的增值税专用发票，税号在资料里。",
      "3 月 28 日有一笔 680 元的扣费，能查一下是什么服务的吗？",
      "退款申请已经提交 5 天了，进度怎么样了？",
    ],
  },
  {
    scene: "technical_support",
    name: "技术支持",
    desc: "故障排查、部署检查、SLA 响应跟进",
    icon: ShieldCheck,
    tone: "from-violet-500 to-violet-600",
    intro: "你好，我是技术支持工程师，可以帮你排查 API 调用异常、服务部署配置问题、连接超时等故障，并跟进 SLA 响应时效。",
    prompts: [
      "调用 /api/v1/chat/completions 接口返回 502，已持续 20 分钟了，请排查。",
      "刚部署的 orchestrator-service 容器启动失败，日志报 MongoDB 连接超时。",
      "我们的 SLA 约定 P95 延迟 < 2s，但最近一周经常超 5s，怎么处理？",
      "Qdrant 向量库检索延迟突然升高，怎么定位瓶颈？",
    ],
  },
  {
    scene: "icp",
    name: "ICP 备案专员",
    desc: "域名校验、备案申请、进度跟踪、材料准备",
    icon: Globe,
    tone: "from-cyan-500 to-cyan-600",
    intro: "你好，我是 ICP 备案专员，可以帮你核验域名备案资质、准备备案材料、提交申请以及跟踪审核进度。",
    prompts: [
      "新域名 smartcloud-ai.cn 需要备案，请问要准备哪些材料？",
      "备案申请编号 BJ-ICP-2026-0419 目前审核到哪一步了？",
      "我们的营业执照经营范围需要变更才能通过备案，流程是怎样的？",
      "备案被管局驳回，原因是\"网站名称不规范\"，如何修改重新提交？",
    ],
  },
  {
    scene: "marketing",
    name: "营销专员",
    desc: "营销活动策划、文案生成、海报设计、链接生成",
    icon: Megaphone,
    tone: "from-pink-500 to-pink-600",
    intro: "你好，我是营销专员，擅长活动策划、爆款文案撰写、营销海报生成以及推广链接追踪配置。",
    prompts: [
      "为 618 大促活动生成一组限时抢购的微信推文文案，风格活泼有紧迫感。",
      "帮我们设计一张夏日清凉主题的促销海报，主推冷饮系列新品。",
      "生成一批双 11 专用的推广短链接，带渠道标签区分微信和抖音来源。",
      "上个月朋友圈广告的点击率只有 1.2%，能帮我分析下优化方向吗？",
    ],
  },
  {
    scene: "research",
    name: "市场研究专员",
    desc: "行业研究、竞品对比、趋势报告、情报采集",
    icon: ScrollText,
    tone: "from-amber-500 to-amber-600",
    intro: "你好，我是市场研究专员，可以帮你进行行业趋势分析、竞品功能对标、用户需求洞察以及生成结构化研究报告。",
    prompts: [
      "请对比一下我们和竞品 A、竞品 B 在 AI 客服模块的核心功能差异，输出表格。",
      "2026 年 Q1 国内 SaaS 行业融资趋势如何？有哪些值得关注的细分赛道？",
      "帮我们做一份企业用户对智能知识库功能的付费意愿调研框架。",
      "最近三个月行业里有哪些新的数据合规政策会影响我们的产品方向？",
    ],
  },
];

export function getAgentMeta(scene?: Scene | null): AgentMeta {
  return CHAT_AGENTS.find((agent) => agent.scene === scene) ?? CHAT_AGENTS[0];
}
