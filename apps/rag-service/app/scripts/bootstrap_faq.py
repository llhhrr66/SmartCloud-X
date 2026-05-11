"""Bootstrap FAQ cache with data derived from the production database.

Run inside rag-service container:
    python -m app.scripts.bootstrap_faq
"""
from __future__ import annotations

import json
import sys
from urllib.parse import quote

from app.services.faq_cache import FaqDocumentRef, FaqEntry, get_faq_cache


def build_faq_from_document(document: dict) -> FaqEntry | None:
    title = str(document.get("title") or "").strip()
    content = str(document.get("content") or "").strip()
    doc_id = str(document.get("id") or "").strip()
    if not title or not content or not doc_id:
        return None

    aliases = [
        title,
        title.replace("云服务器", "服务器"),
        title.replace("云服务器", "云主机"),
        f"如何{title}" if not title.startswith("如何") else title[2:],
        f"怎么{title}" if not title.startswith("怎么") else title[2:],
        title.replace("实例", "示例"),
        title.replace("云服务器实例", "服务器示例"),
        f"{title}教程",
        f"{title}步骤",
    ]
    tags = document.get("tags") if isinstance(document.get("tags"), list) else []
    aliases.extend(str(tag) for tag in tags if str(tag).strip())

    answer = _compose_document_answer(title, content)
    if title == "如何创建云服务器实例":
        answer = _cloud_instance_creation_answer()
    doc_url = f"/document-viewer?docId={quote(doc_id)}&title={quote(title)}"
    answer = f"{answer}\n\n**参考文档：** [{title}]({doc_url})"
    return FaqEntry(
        question=title,
        aliases=list(dict.fromkeys(item for item in aliases if item and item != title)),
        answer=answer,
        token_estimate=max(len(content) // 2, 120),
        confidence=1.0,
        category=_category_from_tags(tags),
        prerequisites=_extract_section_items(content, "前置条件"),
        related_topics=[],
        document_refs=[FaqDocumentRef(doc_id=doc_id, title=title, url=doc_url)],
    )


def _compose_document_answer(title: str, content: str) -> str:
    text = content.strip()
    if text.startswith(title):
        text = text[len(title):].lstrip("\n #")
    if len(text) > 2400:
        text = text[:2400].rstrip() + "\n\n更多细节请打开底部参考文档查看完整内容。"
    return f"{title}\n\n{text}"


def _cloud_instance_creation_answer() -> str:
    return (
        "创建云服务器实例的步骤如下：\n\n"
        "**1. 进入 ECS 控制台**\n"
        "- 登录 SmartCloud 控制台\n"
        "- 点击顶部导航栏的「产品与服务」\n"
        "- 选择「云服务器 ECS」\n"
        "- 点击「创建实例」按钮\n\n"
        "**2. 选择实例配置**\n"
        "- 选择地域和可用区：建议选择离用户最近的地域，生产环境推荐多可用区部署\n"
        "- 选择实例规格：\n"
        "  - 通用型：适合中小型应用、Web 服务器\n"
        "  - 计算型：适合 CPU 密集型应用\n"
        "  - 内存型：适合内存密集型应用、数据库\n"
        "  - 推荐配置：小型应用 2 核 4GB，中型应用 4 核 8GB，大型应用 8 核 16GB 或更高\n"
        "- 选择镜像：\n"
        "  - 公共镜像：官方操作系统，例如 CentOS、Ubuntu、Windows 等\n"
        "  - 自定义镜像：基于已有实例创建，适合复制已有环境\n"
        "  - 市场镜像：第三方预装软件镜像，适合快速部署应用\n\n"
        "**3. 配置网络**\n"
        "- 选择网络类型：专有网络 VPC（推荐）或经典网络\n"
        "- 配置安全组（虚拟防火墙）：\n"
        "  - 默认禁止所有入站流量，需要手动添加规则\n"
        "  - 常用规则：SSH 22 端口、HTTP 80 端口、HTTPS 443 端口\n"
        "  - 生产环境建议限制 SSH 来源 IP，不要直接对全网开放\n\n"
        "**4. 配置存储**\n"
        "- 系统盘：建议使用 SSD 云盘，容量 40GB 以上；GPU 镜像建议 100GB 以上\n"
        "- 数据盘（可选）：按需添加，支持在线扩容和快照备份\n"
        "- 建议将业务数据、日志、模型文件等放在数据盘，避免和系统盘混用\n\n"
        "**5. 设置登录方式**\n"
        "- 密钥对登录（推荐）：更安全，适用于 Linux 系统\n"
        "- 密码登录：设置符合复杂度要求的密码\n"
        "- Windows 实例可通过远程桌面 RDP 登录\n\n"
        "**6. 确认并创建**\n"
        "- 检查地域、规格、镜像、网络、安全组、云盘和计费方式\n"
        "- 确认订单并完成支付\n"
        "- 等待实例创建完成，通常需要 1-3 分钟\n"
        "- 实例状态变为「运行中」后，即可远程连接并开始使用\n\n"
        "**前置条件：**\n"
        "- 已注册 SmartCloud 账号并完成实名认证\n"
        "- 账户余额充足或已绑定支付方式\n"
        "- 已了解所需实例规格和配置\n"
        "- 如面向中国大陆公众提供服务，请提前确认 ICP 备案和地域要求"
    )


def _extract_section_items(content: str, heading: str) -> list[str]:
    lines = content.splitlines()
    items: list[str] = []
    in_section = False
    for raw_line in lines:
        line = raw_line.strip()
        normalized = line.strip("#：:")
        if normalized == heading:
            in_section = True
            continue
        if in_section and line and not line.startswith("-") and not line[:1].isdigit():
            break
        if in_section and line.startswith("-"):
            items.append(line.lstrip("- ").strip())
    return items


def _category_from_tags(tags: list) -> str:
    lowered = {str(tag).lower() for tag in tags}
    if {"billing", "refund", "invoice", "pricing"} & lowered:
        return "billing"
    if {"icp", "compliance"} & lowered:
        return "compliance"
    if {"marketing", "campaign"} & lowered:
        return "operations"
    if {"operations", "troubleshooting", "security"} & lowered:
        return "operations"
    return "product"


def build_faqs() -> list[FaqEntry]:
    return [
        # ── 产品咨询 ──────────────────────────────────────────────
        FaqEntry(
            question="你们有哪些云服务器",
            aliases=["云服务器", "ECS", "有哪些服务器", "云主机", "弹性计算"],
            answer=(
                "我们提供 5 大类云服务器（ECS）：\n\n"
                "1. **通用型** — 均衡 CPU/内存，适合 Web 应用、轻量数据库、企业办公。入门 ecs.g4.micro（1核2G，¥40/月）到 ecs.g4.12xlarge（48核192G，¥3840/月）。\n"
                "2. **计算型** — 高 CPU 配比，适合批量计算、视频编码、科学计算。ecs.c5.large（2核4G，¥160/月）起。\n"
                "3. **内存型** — 超大内存，适合内存数据库、大数据分析。ecs.r5.large（2核16G，¥240/月）起。\n"
                "4. **存储增强型** — 大容量本地盘，适合数据仓库、日志分析。ecs.d3.large（2核8G+500GB 本地盘，¥200/月）起。\n"
                "5. **突发性能型** — 低成本基准+突发能力，适合轻量 Web、开发测试。ecs.t5.micro（1核1G，¥20/月）起。\n\n"
                "另有 GPU 实例（H100/A10/L40S）、容器服务（CCE）、对象存储（OSS）、CDN、EIP、SLB 等配套产品。"
            ),
            token_estimate=250,
        ),
        FaqEntry(
            question="ECS 通用型有哪些规格",
            aliases=["通用型规格", "通用型多少钱", "g4规格", "通用云服务器配置"],
            answer=(
                "ECS 通用型（g4 系列）提供 11 种规格：\n\n"
                "| 规格 | vCPU | 内存 | 网络带宽 | 按量月价 |\n"
                "|------|------|------|---------|--------|\n"
                "| ecs.g4.micro | 1核 | 2G | 2Gbps | ¥40 |\n"
                "| ecs.g4.small | 1核 | 4G | 1Gbps | ¥80 |\n"
                "| ecs.g4.medium | 2核 | 4G | 2Gbps | ¥120 |\n"
                "| ecs.g4.large | 2核 | 8G | 2Gbps | ¥160 |\n"
                "| ecs.g4.xlarge | 4核 | 16G | 3Gbps | ¥320 |\n"
                "| ecs.g4.2xlarge | 8核 | 32G | 5Gbps | ¥640 |\n"
                "| ecs.g4.3xlarge | 12核 | 48G | 8Gbps | ¥960 |\n"
                "| ecs.g4.4xlarge | 16核 | 64G | 10Gbps | ¥1280 |\n"
                "| ecs.g4.6xlarge | 24核 | 96G | 12Gbps | ¥1920 |\n"
                "| ecs.g4.8xlarge | 32核 | 128G | 15Gbps | ¥2560 |\n"
                "| ecs.g4.12xlarge | 48核 | 192G | 20Gbps | ¥3840 |\n\n"
                "包年享 85 折，3 年付享 7 折。"
            ),
            token_estimate=300,
        ),
        FaqEntry(
            question="ECS 计算型有哪些规格",
            aliases=["计算型规格", "计算型多少钱", "c5规格", "计算型云服务器配置"],
            answer=(
                "ECS 计算型（c5 系列）提供 9 种规格：\n\n"
                "| 规格 | vCPU | 内存 | 网络带宽 | 按量月价 |\n"
                "|------|------|------|---------|--------|\n"
                "| ecs.c5.large | 2核 | 4G | 2Gbps | ¥160 |\n"
                "| ecs.c5.xlarge | 4核 | 8G | 3Gbps | ¥320 |\n"
                "| ecs.c5.2xlarge | 8核 | 16G | 5Gbps | ¥640 |\n"
                "| ecs.c5.3xlarge | 12核 | 24G | 8Gbps | ¥960 |\n"
                "| ecs.c5.4xlarge | 16核 | 32G | 10Gbps | ¥1280 |\n"
                "| ecs.c5.6xlarge | 24核 | 48G | 12Gbps | ¥1920 |\n"
                "| ecs.c5.8xlarge | 32核 | 64G | 15Gbps | ¥2560 |\n"
                "| ecs.c5.12xlarge | 48核 | 96G | 20Gbps | ¥3840 |\n"
                "| ecs.c5.16xlarge | 64核 | 128G | 25Gbps | ¥5120 |\n\n"
                "适合批量计算、视频编码、科学计算等 CPU 密集型场景。"
            ),
            token_estimate=280,
        ),
        FaqEntry(
            question="ECS 内存型有哪些规格",
            aliases=["内存型规格", "内存型多少钱", "r5规格", "内存型云服务器配置"],
            answer=(
                "ECS 内存型（r5 系列）提供 9 种规格：\n\n"
                "| 规格 | vCPU | 内存 | 网络带宽 | 按量月价 |\n"
                "|------|------|------|---------|--------|\n"
                "| ecs.r5.large | 2核 | 16G | 2Gbps | ¥240 |\n"
                "| ecs.r5.xlarge | 4核 | 32G | 3Gbps | ¥480 |\n"
                "| ecs.r5.2xlarge | 8核 | 64G | 5Gbps | ¥960 |\n"
                "| ecs.r5.3xlarge | 12核 | 96G | 8Gbps | ¥1440 |\n"
                "| ecs.r5.4xlarge | 16核 | 128G | 10Gbps | ¥1920 |\n"
                "| ecs.r5.6xlarge | 24核 | 192G | 12Gbps | ¥2880 |\n"
                "| ecs.r5.8xlarge | 32核 | 256G | 15Gbps | ¥3840 |\n"
                "| ecs.r5.12xlarge | 48核 | 384G | 20Gbps | ¥5760 |\n"
                "| ecs.r5.16xlarge | 64核 | 512G | 25Gbps | ¥7680 |\n\n"
                "适合 Redis/MongoDB 等内存数据库、大数据分析、实时计算。"
            ),
            token_estimate=280,
        ),
        FaqEntry(
            question="GPU 实例有哪些型号",
            aliases=["GPU服务器", "GPU型号", "GPU多少钱", "H100", "A10", "L40S", "GPU规格", "显卡服务器"],
            answer=(
                "我们提供 3 个 GPU 产品族：\n\n"
                "**GI4（推理优先）** — NVIDIA L40S\n"
                "- gi4.xlarge：16核 64G + L40S×1，¥21,000/月\n"
                "- gi4.2xlarge：32核 128G + L40S×2，¥42,000/月\n"
                "- gi4.4xlarge：64核 256G + L40S×4，¥84,000/月\n\n"
                "**GN6i（入门级）** — NVIDIA A10\n"
                "- gn6i.xlarge：16核 64G + A10×1，¥18,000/月\n"
                "- gn6i.2xlarge：32核 128G + A10×2，¥36,000/月\n\n"
                "**GN8（高端训练）** — NVIDIA H100\n"
                "- gn8.xlarge：16核 128G + H100×1，¥24,750/月\n"
                "- gn8.2xlarge：32核 256G + H100×2，¥49,500/月\n"
                "- gn8.4xlarge：64核 512G + H100×4，¥99,000/月\n"
                "- gn8.8xlarge：128核 1024G + H100×8，¥198,000/月\n\n"
                "L40S 适合 7B-70B 量化模型推理，A10 适合 PoC 验证，H100 适合大规模训练。\n\n"
                "**参考文档：** [GPU 云主机部署检查清单](/document-viewer?docId=doc-3b827aafcdff&title=GPU%20%E4%BA%91%E4%B8%BB%E6%9C%BA%E9%83%A8%E7%BD%B2%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95)"
            ),
            token_estimate=350,
            document_refs=[
                FaqDocumentRef(doc_id="doc-3b827aafcdff", title="GPU 云主机部署检查清单", url="/document-viewer?docId=doc-3b827aafcdff&title=GPU%20%E4%BA%91%E4%B8%BB%E6%9C%BA%E9%83%A8%E7%BD%B2%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95"),
                FaqDocumentRef(doc_id="doc-06b6fb231fd3", title="GPU Release Checklist", url="/document-viewer?docId=doc-06b6fb231fd3&title=GPU%20Release%20Checklist"),
            ],
        ),
        FaqEntry(
            question="最便宜的云服务器多少钱",
            aliases=["最便宜服务器", "最低价格", "便宜ECS", "入门服务器", "低成本云服务器"],
            answer=(
                "最便宜的是 **突发性能型 ecs.t5.micro**：1核1G，按量付费仅 **¥20/月**。\n\n"
                "其他低价选择：\n- ecs.t5.small（1核2G）：¥40/月\n- ecs.g4.micro 通用型（1核2G）：¥40/月\n- ecs.g4.small 通用型（1核4G）：¥80/月\n\n"
                "突发性能型适合轻量 Web、开发测试；如需稳定性能，建议选通用型。包年还有折扣。"
            ),
            token_estimate=150,
        ),
        FaqEntry(
            question="你们有哪些优惠活动",
            aliases=["优惠", "促销", "折扣", "活动", "有什么优惠", "优惠活动", "打折"],
            answer=(
                "当前在售活动：\n\n"
                "1. **ECS 新客首购 5 折** — 新用户首次购买任意 ECS 规格享 5 折\n"
                "2. **ECS 包年狂欢节** — 1年85折 / 2年7折 / 3年6折，全线规格\n"
                "3. **突发性能型限时秒杀** — ecs.t5.micro 月费低至 ¥9.9（原价¥20）\n"
                "4. **GPU+ECS 混合算力套餐** — GPU+控制节点套餐 8 折\n"
                "5. **GPU 云主机上新季** — 新客首购 GPU 7 折，老客续费 85 折\n"
                "6. **AI 创业加速计划** — AI 团队 ¥10,000 算力补贴\n"
                "7. **存储增强型迁移补贴** — 购买 d3 系列获 ¥5,000 迁移补贴\n"
                "8. **学生开发者计划** — 在校生免费领 1核2G ECS + 50GB OSS（6个月）\n"
                "9. **网络方案限时特惠** — SLB/VPN/EIP 8 折\n"
                "10. **弹性云服务器增长计划** — 企业新用户 ¥3,000 代金券\n\n"
                "活动详情和领取方式可咨询我。"
            ),
            token_estimate=350,
        ),

        # ── 计费 ────────────────────────────────────────────────────
        FaqEntry(
            question="按量付费和包年包月有什么区别",
            aliases=["计费方式", "按量计费", "包年包月", "付费模式", "怎么计费", "收费方式"],
            answer=(
                "我们支持两种计费模式：\n\n"
                "**按量付费（后付费）**：按实际使用时长计费，随时创建/释放，适合短期、弹性场景。例：ecs.g4.large ¥160/月，用几天算几天。\n\n"
                "**包年包月（预付费）**：预先购买 1/2/3 年，享受折扣，适合长期稳定负载。折扣力度：\n- 1 年付：85 折（约省 15%）\n- 2 年付：7 折（约省 30%）\n- 3 年付：6 折（约省 40%）\n\n"
                "例：ecs.g4.4xlarge 按量 ¥1280/月，1 年付 ¥1088/月，3 年付更低。"
            ),
            token_estimate=200,
        ),
        FaqEntry(
            question="GPU 实例怎么收费",
            aliases=["GPU价格", "GPU计费", "GPU多少钱一个月", "GPU收费"],
            answer=(
                "GPU 实例支持按量付费和包年包月：\n\n"
                "| 型号 | 按量月价 | 包年月价 | GPU 卡 |\n"
                "|------|---------|---------|-------|\n"
                "| gi4.xlarge (L40S×1) | ¥21,000 | — | L40S |\n"
                "| gi4.2xlarge (L40S×2) | ¥42,000 | ¥35,280 | L40S |\n"
                "| gn6i.xlarge (A10×1) | ¥18,000 | ¥15,120 | A10 |\n"
                "| gn8.xlarge (H100×1) | ¥24,750 | — | H100 |\n"
                "| gn8.4xlarge (H100×4) | ¥99,000 | ¥83,160 | H100 |\n"
                "| gn8.8xlarge (H100×8) | ¥198,000 | ¥166,320 | H100 |\n\n"
                "当前 GPU 新客首购享 7 折优惠，可与包年折扣叠加。\n\n"
                "**参考文档：** [GPU Release Checklist](/document-viewer?docId=doc-06b6fb231fd3&title=GPU%20Release%20Checklist) · [GPU 发布检查清单](/document-viewer?docId=doc-2e00bc4bbfb6&title=GPU%20%E5%8F%91%E5%B8%83%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95)"
            ),
            token_estimate=250,
            document_refs=[
                FaqDocumentRef(doc_id="doc-06b6fb231fd3", title="GPU Release Checklist", url="/document-viewer?docId=doc-06b6fb231fd3&title=GPU%20Release%20Checklist"),
                FaqDocumentRef(doc_id="doc-2e00bc4bbfb6", title="GPU 发布检查清单", url="/document-viewer?docId=doc-2e00bc4bbfb6&title=GPU%20%E5%8F%91%E5%B8%83%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95"),
            ],
        ),

        # ── 产品对比/选型 ───────────────────────────────────────────
        FaqEntry(
            question="通用型和计算型有什么区别",
            aliases=["通用型vs计算型", "通用计算区别", "选通用还是计算", "g4和c5区别"],
            answer=(
                "核心区别在 CPU/内存配比：\n\n"
                "- **通用型（g4）**：CPU:内存 ≈ 1:4（如 4核16G），均衡配置，适合 Web 应用、数据库、企业办公\n"
                "- **计算型（c5）**：CPU:内存 ≈ 1:2（如 4核8G），CPU 配比更高，适合计算密集型场景\n\n"
                "价格对比（4核规格）：\n- 通用型 ecs.g4.xlarge（4核16G）：¥320/月\n- 计算型 ecs.c5.xlarge（4核8G）：¥320/月\n\n"
                "同价但通用型内存翻倍，计算型 CPU 更纯粹。如果跑 Web 服务/数据库选通用型，跑编码/批处理选计算型。"
            ),
            token_estimate=200,
        ),
        FaqEntry(
            question="想做 AI 训练应该选什么机器",
            aliases=["AI训练选型", "大模型训练", "模型训练服务器", "深度学习服务器", "炼丹选什么"],
            answer=(
                "AI 训练选型建议：\n\n"
                "**小规模训练 / PoC（7B 以下模型）**\n- GN6i + A10：¥18,000/月起，适合快速验证\n\n"
                "**中等规模训练（7B-70B 模型）**\n- GI4 + L40S：¥21,000/月起，L40S 推理和训练兼顾\n\n"
                "**大规模训练（70B+ 模型）**\n- GN8 + H100：¥24,750/月起，NVLink 高速互联，8×H100 可达 198k/月\n\n"
                "推荐搭配：1 台 GPU 做训练 + 2 台通用型 ECS 做数据预处理/控制节点，混合套餐享 8 折。\n\n"
                "AI 创业团队可申请 ¥10,000 算力补贴。\n\n"
                "**参考文档：** [GPU 云主机部署检查清单](/document-viewer?docId=doc-3b827aafcdff&title=GPU%20%E4%BA%91%E4%B8%BB%E6%9C%BA%E9%83%A8%E7%BD%B2%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95) · [GPU 发布检查清单](/document-viewer?docId=doc-2e00bc4bbfb6&title=GPU%20%E5%8F%91%E5%B8%83%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95)"
            ),
            token_estimate=250,
            document_refs=[
                FaqDocumentRef(doc_id="doc-3b827aafcdff", title="GPU 云主机部署检查清单", url="/document-viewer?docId=doc-3b827aafcdff&title=GPU%20%E4%BA%91%E4%B8%BB%E6%9C%BA%E9%83%A8%E7%BD%B2%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95"),
                FaqDocumentRef(doc_id="doc-2e00bc4bbfb6", title="GPU 发布检查清单", url="/document-viewer?docId=doc-2e00bc4bbfb6&title=GPU%20%E5%8F%91%E5%B8%83%E6%A3%80%E6%9F%A5%E6%B8%85%E5%8D%95"),
            ],
        ),
        FaqEntry(
            question="建网站用什么服务器",
            aliases=["网站服务器", "建站选型", "博客服务器", "小型网站", "WordPress服务器"],
            answer=(
                "建站推荐：\n\n"
                "**个人博客 / 小型展示站**\n- 突发性能型 ecs.t5.small（1核2G，¥40/月）+ OSS 静态托管\n\n"
                "**企业官网 / 中型网站**\n- 通用型 ecs.g4.large（2核8G，¥160/月）+ SLB + OSS\n\n"
                "**电商 / 高并发网站**\n- 通用型 ecs.g4.2xlarge（8核32G，¥640/月）+ SLB + RDS + OSS\n\n"
                "另外需要配 EIP 弹性公网 IP（按带宽 ¥80/Mbps/月）。\n新客首购 ECS 享 5 折，学生可免费领 1核2G。"
            ),
            token_estimate=200,
        ),

        # ── 网络/存储/容器 ──────────────────────────────────────────
        FaqEntry(
            question="对象存储怎么收费",
            aliases=["OSS价格", "存储怎么计费", "OSS多少钱", "对象存储费用"],
            answer=(
                "对象存储（OSS）三种类型，按存储量计费：\n\n"
                "- **标准型**：¥0.12/GB/月 — 频繁访问的热数据、网站托管\n"
                "- **低频型**：¥0.08/GB/月 — 月访问 1-2 次的温数据\n"
                "- **归档型**：¥0.03/GB/月 — 合规保留、灾备（解冻需 1-12 小时）\n\n"
                "100GB 标准存储约 ¥12/月，非常经济。另有 CDN 加速 ¥0.24/GB 流量费。"
            ),
            token_estimate=150,
        ),
        FaqEntry(
            question="CDN 怎么收费",
            aliases=["CDN价格", "CDN加速", "内容分发多少钱", "CDN费用"],
            answer=(
                "CDN 按流量计费：**¥0.24/GB**，覆盖 200+ 全球节点，支持动态加速和 WebSocket。\n\n"
                "推荐搭配 OSS 使用：静态资源放 OSS + CDN 加速，访问速度更快，费用更低。"
            ),
            token_estimate=80,
        ),
        FaqEntry(
            question="EIP 弹性公网 IP 怎么收费",
            aliases=["公网IP", "EIP价格", "弹性IP", "带宽费用", "EIP多少钱"],
            answer=(
                "EIP 支持两种计费：\n\n"
                "- **按带宽计费**：¥80/Mbps/月，适合流量稳定的场景\n- **按流量计费**：按实际出网流量，适合流量波动大的场景\n\n"
                "EIP 可独立持有，随时绑定/解绑 ECS、SLB 等资源。"
            ),
            token_estimate=100,
        ),
        FaqEntry(
            question="SLB 负载均衡怎么收费",
            aliases=["负载均衡价格", "SLB多少钱", "SLB费用"],
            answer=(
                "SLB 按实例+带宽计费：**¥36/天/实例**。\n\n"
                "支持四层/七层负载均衡，健康检查、会话保持、SSL 卸载。高可用网络方案活动期间新购享 8 折。"
            ),
            token_estimate=80,
        ),
        FaqEntry(
            question="容器服务 CCE 怎么用",
            aliases=["CCE容器", "K8s托管", "Kubernetes", "容器集群", "CCE价格"],
            answer=(
                "容器服务（CCE）提供两种模式：\n\n"
                "- **标准版** — 完整 Kubernetes 托管集群，适合中大规模微服务和 CI/CD\n- **Serverless** — 按需弹性，适合事件驱动和弹性扩缩场景\n\n"
                "容器化转型企业可参加免费试用活动：60 天免费托管 K8s 集群（3 节点 + 8C16G）。"
            ),
            token_estimate=120,
        ),

        # ── 备案 ────────────────────────────────────────────────────
        FaqEntry(
            question="ICP 备案怎么办理",
            aliases=["备案", "ICP备案", "网站备案", "备案流程", "如何备案"],
            answer=(
                "ICP 备案流程：\n\n"
                "1. 准备材料：企业营业执照/个人身份证、域名证书、幕布照片\n"
                "2. 在控制台提交备案申请，填写主体信息、网站信息、联系方式\n"
                "3. 提交后进入审核，通常 5-20 个工作日\n"
                "4. 审核通过后获得 ICP 备案号，需在网站底部展示\n\n"
                "注意事项：\n- 域名需已完成实名认证\n- 服务器需在大陆地域（上海/北京/广州）\n- 备案期间网站不可访问\n\n"
                "如需帮助可在控制台直接提交 ICP 申请。\n\n"
                "**参考文档：** [ICP 备案交接说明](/document-viewer?docId=doc-cfedf30701b9&title=ICP%20%E5%A4%87%E6%A1%88%E4%BA%A4%E6%8E%A5%E8%AF%B4%E6%98%8E) · [ICP备案资料准备说明](/document-viewer?docId=doc-d57a0b6774e1&title=ICP%E5%A4%87%E6%A1%88%E8%B5%84%E6%96%99%E5%87%86%E5%A4%87%E8%AF%B4%E6%98%8E)"
            ),
            token_estimate=200,
            document_refs=[
                FaqDocumentRef(doc_id="doc-cfedf30701b9", title="ICP 备案交接说明", url="/document-viewer?docId=doc-cfedf30701b9&title=ICP%20%E5%A4%87%E6%A1%88%E4%BA%A4%E6%8E%A5%E8%AF%B4%E6%98%8E"),
                FaqDocumentRef(doc_id="doc-d57a0b6774e1", title="ICP备案资料准备说明", url="/document-viewer?docId=doc-d57a0b6774e1&title=ICP%E5%A4%87%E6%A1%88%E8%B5%84%E6%96%99%E5%87%86%E5%A4%87%E8%AF%B4%E6%98%8E"),
            ],
        ),

        # ── 运维/技术 ───────────────────────────────────────────────
        FaqEntry(
            question="怎么重置服务器密码",
            aliases=["重置密码", "忘记密码", "ECS密码", "服务器密码"],
            answer=(
                "重置 ECS 实例密码：\n\n"
                "1. 登录控制台，进入「云服务器」页面\n"
                "2. 找到目标实例，点击「更多」→「重置密码」\n"
                "3. 设置新密码（8-30 位，需含大小写字母+数字+特殊字符）\n"
                "4. 提交后需重启实例生效\n\n"
                "Linux 实例也可通过 SSH 密钥对登录，无需密码。"
            ),
            token_estimate=120,
        ),
        FaqEntry(
            question="怎么升级服务器配置",
            aliases=["升配", "扩容", "升级配置", "增加CPU", "增加内存", "变更配置"],
            answer=(
                "ECS 配置变更：\n\n"
                "**按量付费实例**：\n1. 控制台 → 云服务器 → 选择实例 → 「变更配置」\n2. 选择目标规格，确认后自动重启生效\n\n"
                "**包年包月实例**：\n1. 同上操作，升配需补差价\n2. 降配不退费，到期后按新配置续费\n\n"
                "注意：变更配置会导致短暂重启（约 1-2 分钟），建议在业务低峰操作。"
            ),
            token_estimate=130,
        ),
        FaqEntry(
            question="数据盘怎么挂载",
            aliases=["挂载磁盘", "数据盘", "云盘挂载", "扩容磁盘", "添加硬盘"],
            answer=(
                "挂载数据盘：\n\n"
                "1. 控制台 → 云磁盘 → 创建磁盘（选同地域可用区）\n"
                "2. 创建后点击「挂载」，选择目标 ECS 实例\n"
                "3. SSH 登录实例，执行 `fdisk -l` 查看新磁盘\n"
                "4. 格式化：`mkfs.ext4 /dev/vdb`\n"
                "5. 挂载：`mount /dev/vdb /data`\n"
                "6. 写入 fstab 实现开机自动挂载：`echo '/dev/vdb /data ext4 defaults 0 0' >> /etc/fstab`\n\n"
                "存储增强型 ECS 自带大容量本地盘，无需额外购买。"
            ),
            token_estimate=150,
        ),
        FaqEntry(
            question="你们有哪些地域节点",
            aliases=["地域", "节点", "哪个城市", "区域", "可用区", "机房"],
            answer=(
                "当前开通的地域节点：\n\n"
                "- **华东**：cn-shanghai-2（上海）\n"
                "- **华北**：cn-beijing-1（北京）\n"
                "- **华南**：cn-guangzhou-1（广州）\n\n"
                "通用型、突发性能型、存储增强型、EIP、SLB、CDN、OSS 在全部地域可用。\n"
                "计算型、内存型、GPU 实例在上海和北京可用。\n"
                "容器服务（CCE）在上海可用。"
            ),
            token_estimate=120,
        ),

        # ── 退款/发票（保留原有的并增强）──────────────────────────────
        FaqEntry(
            question="怎么开发票",
            aliases=["发票", "开票", "如何开发票", "开发票流程", "增值税发票"],
            answer=(
                "开发票流程：\n\n"
                "1. 登录账户，进入「订单管理」页面\n"
                "2. 找到需要开票的订单，点击「申请发票」\n"
                "3. 填写发票抬头（个人/企业）和税号\n"
                "4. 提交后，电子发票将在 1-3 个工作日内发送至您的邮箱\n\n"
                "如需增值税专用发票，请联系客服提供企业资质。\n\n"
                "**参考文档：** [账单与发票处理基线](/document-viewer?docId=doc-bd52914b7ccb&title=%E8%B4%A6%E5%8D%95%E4%B8%8E%E5%8F%91%E7%A5%A8%E5%A4%84%E7%90%86%E5%9F%BA%E7%BA%BF)"
            ),
            token_estimate=120,
            document_refs=[
                FaqDocumentRef(doc_id="doc-bd52914b7ccb", title="账单与发票处理基线", url="/document-viewer?docId=doc-bd52914b7ccb&title=%E8%B4%A6%E5%8D%95%E4%B8%8E%E5%8F%91%E7%A5%A8%E5%A4%84%E7%90%86%E5%9F%BA%E7%BA%BF"),
            ],
        ),
        FaqEntry(
            question="如何退款",
            aliases=["退款", "退款流程", "怎么退款", "申请退款", "退货"],
            answer=(
                "退款流程：\n\n"
                "1. 登录账户，进入「订单管理」\n"
                "2. 选择需要退款的订单，点击「申请退款」\n"
                "3. 选择退款原因并提交\n"
                "4. 审核通过后，款项将在 3-5 个工作日内退回原支付方式\n\n"
                "- 按量付费：余额实时退还\n- 包年包月：按剩余天数折算退费\n- 超过 5 个工作日未到账请联系客服"
            ),
            token_estimate=120,
        ),
        FaqEntry(
            question="如何联系客服",
            aliases=["客服", "联系客服", "人工客服", "在线客服", "客服电话", "技术支持"],
            answer=(
                "联系方式：\n\n"
                "- **在线客服**：点击页面右下角「在线咨询」按钮\n"
                "- **工单系统**：控制台 → 「工单管理」→ 提交技术/账务工单\n"
                "- **客服热线**：工作日 9:00-18:00\n\n"
                "我们会在 24 小时内回复您的咨询。紧急问题请提交工单并标记为「紧急」。"
            ),
            token_estimate=100,
        ),

        # ── 活动相关高频 ───────────────────────────────────────────
        FaqEntry(
            question="新用户有什么优惠",
            aliases=["新客优惠", "新用户折扣", "首次购买优惠", "注册优惠"],
            answer=(
                "新用户专享：\n\n"
                "1. **ECS 新客首购 5 折** — 首次购买任意 ECS 规格（通用/计算/内存/存储/突发）享 5 折，限 3 台\n"
                "2. **GPU 新客首购 7 折** — 首次购买 GPU 实例享 7 折，最高减免 ¥5,000/月\n"
                "3. **企业新用户 ¥3,000 代金券** — 注册企业账号获 ¥3,000 代金券，6 个月有效\n"
                "4. **学生免费领** — 在校生凭 .edu 邮箱免费领 1核2G ECS + 50GB OSS（6个月）"
            ),
            token_estimate=180,
        ),
        FaqEntry(
            question="包年有什么折扣",
            aliases=["包年折扣", "年付优惠", "包月还是包年", "长期优惠", "预付费折扣"],
            answer=(
                "包年包月阶梯折扣：\n\n"
                "- **1 年付**：85 折（省 15%）\n- **2 年付**：7 折（省 30%）\n- **3 年付**：6 折（省 40%）\n\n"
                "示例（ecs.g4.4xlarge，16核64G）：\n- 按量：¥1,280/月\n- 1 年付：¥1,088/月\n- 3 年付：约 ¥768/月\n\n"
                "当前还有「ECS 包年狂欢节」活动，可叠加使用。"
            ),
            token_estimate=150,
        ),
        FaqEntry(
            question="如何创建云服务器实例",
            aliases=[
                "创建ECS",
                "创建云服务器",
                "新建实例",
                "创建服务器",
                "创建服务器实例",
                "如何创建服务器实例",
                "如何创建服务器示例",
                "开机器",
                "创建实例",
            ],
            answer=(
                "创建云服务器实例步骤：\n\n"
                "1. 登录 SmartCloud 控制台，进入「云服务器」页面\n"
                "2. 点击「创建实例」按钮\n"
                "3. 选择地域和可用区（如华东-上海 cn-shanghai-2）\n"
                "4. 选择实例规格：通用型/计算型/内存型/存储增强型/突发性能型\n"
                "5. 选择镜像（公共镜像/自定义镜像/市场镜像）\n"
                "6. 配置存储：系统盘（高效云盘/SSD）+ 可选数据盘\n"
                "7. 配置网络：VPC → 子网 → 分配公网 IP（EIP）\n"
                "8. 设置登录方式：密钥对或密码\n"
                "9. 确认配置和费用，点击「确认创建」\n"
                "10. 等待实例状态变为「运行中」，即可远程连接使用\n\n"
                "创建完成后建议：设置安全组规则、配置自动快照策略、绑定 SLB 实现高可用。\n\n"
                "**参考文档：** [如何创建云服务器实例](/document-viewer?docId=doc-910a1aca4b50&title=%E5%A6%82%E4%BD%95%E5%88%9B%E5%BB%BA%E4%BA%91%E6%9C%8D%E5%8A%A1%E5%99%A8%E5%AE%9E%E4%BE%8B)"
            ),
            token_estimate=280,
            category="operations",
            prerequisites=["已注册 SmartCloud 账户并完成实名认证", "账户余额充足或已开通按量付费"],
            related_topics=["最便宜的云服务器多少钱", "你们有哪些云服务器", "怎么重置服务器密码", "数据盘怎么挂载"],
            document_refs=[
                FaqDocumentRef(doc_id="doc-910a1aca4b50", title="如何创建云服务器实例", url="/document-viewer?docId=doc-910a1aca4b50&title=%E5%A6%82%E4%BD%95%E5%88%9B%E5%BB%BA%E4%BA%91%E6%9C%8D%E5%8A%A1%E5%99%A8%E5%AE%9E%E4%BE%8B"),
            ],
        ),

        FaqEntry(
            question="学生有什么优惠",
            aliases=["学生优惠", "学生免费", "学生计划", "高校优惠", "edu优惠"],
            answer=(
                "学生开发者云上起航计划：\n\n"
                "在校大学生通过 .edu 邮箱认证后可免费领取：\n- 1 台 ecs.t5.small（1核2G）× 6 个月\n- 50GB OSS 标准存储 × 6 个月\n- 5Mbps EIP 弹性公网 IP × 3 个月\n- 10 节云计算入门课程 + 3 次技术答疑\n\n"
                "每人限领 1 次，不可转让。活动长期有效。"
            ),
            token_estimate=150,
            category="billing",
        ),
    ]


def main() -> None:
    cache = get_faq_cache()
    faqs = build_faqs()

    # Remove old bootstrap entries first
    for entry in cache.list_entries():
        cache.remove_entry(entry["question"])

    # Add new entries
    for faq in faqs:
        cache.add_entry(faq)

    result = cache.list_entries()
    print(f"Loaded {len(result)} FAQ entries into cache")
    for entry in result:
        print(f"  - {entry['question']} (aliases: {len(entry['aliases'])})")


if __name__ == "__main__":
    main()
