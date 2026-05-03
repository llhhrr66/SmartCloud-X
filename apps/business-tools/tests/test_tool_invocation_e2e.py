"""E2E tool invocation test — simulates conversation-style tool calls for all 32 business tools.

Outputs a markdown table with columns:
  工具名 | 对话时输入内容 | 大模型返回内容 | 调用工具的结果 | 测试结果 | 测试次数

Each tool is invoked 3 times (with fresh stores between attempts).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure src is importable
SRC_PATH = Path(__file__).resolve().parents[1] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from business_tools import (  # noqa: E402
    ToolExecutionContext,
    ToolInvocationRequest,
    build_catalog,
    configure_idempotency_store,
    configure_query_cache,
    get_idempotency_store,
    get_query_cache_store,
)

ATTEMPTS = 3

ALL_PERMISSIONS = [
    "user:billing.read",
    "user:order.read",
    "user:ticket.read",
    "user:ticket.write",
    "user:icp.read",
    "user:icp.write",
    "user:marketing.read",
    "user:marketing.write",
    "user:research.write",
]

BASE_CTX = ToolExecutionContext(
    user_id="u-e2e-001",
    account_id="acct-e2e-001",
    tenant_id="tenant-e2e",
    roles=["user"],
    permissions=ALL_PERMISSIONS,
)


def _reset_stores() -> None:
    configure_idempotency_store(persistence_path=None)
    configure_query_cache(enabled=True, ttl_cap_seconds=300, persistence_path=None)
    get_idempotency_store().clear()
    get_query_cache_store().clear()


def _invoke(
    catalog: dict,
    tool_name: str,
    payload: dict[str, Any],
    context: ToolExecutionContext | None = None,
    operation: str = "execute",
) -> dict[str, Any]:
    result = catalog[tool_name].invoke(
        ToolInvocationRequest(
            tool_name=tool_name,
            operation=operation,
            payload=payload,
            context=context or BASE_CTX,
        )
    )
    return {
        "success": result.success,
        "status": result.status,
        "code": result.code,
        "summary": result.summary,
        "result_keys": list(result.result.keys()) if result.result else [],
    }


def _simulate_model_response(inv_result: dict[str, Any], tool_name: str) -> str:
    if inv_result["success"]:
        if inv_result["status"] == "confirmation-required":
            return "该操作需要确认，是否继续？"
        if inv_result["status"] == "preview-ready":
            return "已为您预览操作结果，确认后可执行。"
        return "已为您查询到相关信息"
    if inv_result["status"] == "auth-required":
        return "该操作需要额外的权限验证。"
    if inv_result["status"] == "invalid-payload":
        return "信息不完整，请补充必要字段。"
    if inv_result["status"] == "confirmation-required":
        return "该操作需要确认，是否继续？"
    return f"抱歉，工具调用失败（{inv_result['status']}）"


def _format_result(inv_result: dict[str, Any]) -> str:
    s = inv_result["success"]
    st = inv_result["status"]
    keys = inv_result["result_keys"][:3]
    keys_str = ", ".join(keys) if keys else "无返回数据"
    return f"success={s}, status={st}, [{keys_str}]"


def _run_tool(catalog: dict, tool_name: str, payload: dict[str, Any],
              user_input: str, context: ToolExecutionContext | None = None,
              operation: str = "execute") -> dict[str, Any]:
    passes = 0
    last_inv: dict[str, Any] = {}
    for i in range(ATTEMPTS):
        _reset_stores()
        inv = _invoke(catalog, tool_name, dict(payload), context, operation)
        last_inv = inv
        if inv["success"]:
            passes += 1
    test_result = "PASS" if passes == ATTEMPTS else "FAIL"
    model_resp = _simulate_model_response(last_inv, tool_name)
    return {
        "tool_name": tool_name,
        "user_input": user_input,
        "model_response": model_resp,
        "tool_result": _format_result(last_inv),
        "test_result": test_result,
        "attempts": f"{passes}/{ATTEMPTS}",
    }


def _run_all() -> list[dict[str, Any]]:
    catalog = build_catalog()
    results: list[dict[str, Any]] = []
    dynamic: dict[str, str] = {}

    # ── Product domain (open, no auth) ──────────────────────────────

    results.append(_run_tool(
        catalog, "product.catalog_lookup",
        {"user_query": "云产品列表"},
        "你们有哪些云产品？",
    ))

    results.append(_run_tool(
        catalog, "product.recommend_instance",
        {"user_query": "GPU推荐", "workload": "training", "model_family": "llm", "budget_level": "balanced"},
        "我想训练一个大模型，推荐什么GPU实例？",
    ))

    results.append(_run_tool(
        catalog, "support.playbook_search",
        {"user_query": "ECS部署SOP", "scene": "deployment"},
        "ECS部署遇到问题，有没有SOP文档？",
    ))

    results.append(_run_tool(
        catalog, "support.query_service_status",
        {"user_query": "实例故障", "instance_id": "i-001", "service": "ECS", "region": "cn-east-1"},
        "我的实例 i-001 好像出故障了，帮我查一下",
    ))

    results.append(_run_tool(
        catalog, "support.handoff_brief",
        {"user_query": "转人工", "scene": "technical_support", "urgency": "high", "reason": "用户无法自行解决"},
        "这个问题我解决不了，帮我转人工",
    ))

    # ── Billing domain ───────────────────────────────────────────────

    results.append(_run_tool(
        catalog, "billing.query_statement",
        {"range": "last_month"},
        "查一下我上个月的账单",
    ))

    results.append(_run_tool(
        catalog, "billing.query_instance_cost",
        {"instance_id": "i-001", "range": "this_month"},
        "实例 i-001 这个月花了多少钱？",
    ))

    results.append(_run_tool(
        catalog, "order.query_order",
        {"order_no": "ORD-001"},
        "帮我查一下订单 ORD-001 的状态",
    ))

    results.append(_run_tool(
        catalog, "billing.create_invoice",
        {"statement_nos": ["stmt_001"], "invoice_type": "vat_special", "title": "上海某某科技有限公司", "_confirmed": True},
        "帮我开一张增值税专用发票",
    ))

    results.append(_run_tool(
        catalog, "invoice.query_invoice",
        {"invoice_no": "INV-001"},
        "发票 INV-001 开好了吗？",
    ))

    results.append(_run_tool(
        catalog, "order.create_refund",
        {"order_no": "ORD-001", "reason": "误购", "amount": 99.00, "_confirmed": True},
        "我要退款，订单 ORD-001",
    ))

    # ── Ticket domain (prereq chain: ticket.create → ticket.reply) ──

    _reset_stores()
    ticket_create_inv = _invoke(catalog, "ticket.create", {
        "subject": "实例无法启动", "content": "ECS实例i-001无法启动，提示错误",
    })
    if ticket_create_inv["success"]:
        dynamic["ticket_no"] = ticket_create_inv.get("result_keys") and "TK-e2e-001"

    results.append(_run_tool(
        catalog, "ticket.create",
        {"subject": "实例无法启动", "content": "ECS实例i-001无法启动，提示错误"},
        "我要提交一个工单",
    ))

    ticket_no = dynamic.get("ticket_no", "tk_e2e_001")
    results.append(_run_tool(
        catalog, "ticket.reply",
        {"ticket_no": ticket_no, "content": "问题仍在继续，请尽快处理"},
        "我的工单有新情况要补充",
    ))

    results.append(_run_tool(
        catalog, "ticket.query_ticket",
        {"ticket_no": ticket_no},
        "帮我查一下我的工单状态",
    ))

    # ── ICP domain (prereq chain: icp.material_check → icp.submit_application) ─

    results.append(_run_tool(
        catalog, "icp.material_check",
        {"subject_type": "enterprise", "materials": [{"name": "营业执照", "status": "ready"}, {"name": "域名证书", "status": "missing"}]},
        "备案需要准备哪些材料？",
    ))

    results.append(_run_tool(
        catalog, "icp.verify_subject",
        {"subject_type": "enterprise", "subject_name": "上海某某科技有限公司", "certificate_no": "91310000MA1FL0XX0X"},
        "帮我验证一下备案主体信息",
    ))

    results.append(_run_tool(
        catalog, "icp.submit_application",
        {
            "subject_type": "enterprise", "domain": "example.cn", "website_name": "示例网站",
            "contacts": {"name": "张三", "phone": "13800000001", "email": "zhangsan@example.cn"},
            "materials": [{"name": "营业执照", "status": "ready"}], "_confirmed": True,
        },
        "提交ICP备案申请",
    ))

    results.append(_run_tool(
        catalog, "icp.query_application",
        {"application_no": "icp_e2e_001"},
        "查一下我的备案申请进度",
    ))

    # ── Marketing domain (prereq: campaign_lookup → generate_copy/promotion_link, poster_brief → generate_poster) ─

    results.append(_run_tool(
        catalog, "marketing.campaign_lookup",
        {"product": "GPU", "user_query": "AI算力营销活动"},
        "有什么AI算力相关的营销活动？",
    ))

    results.append(_run_tool(
        catalog, "marketing.poster_brief",
        {"theme": "AI算力起量", "product_summary": "GPU云服务器"},
        "帮我准备一张AI算力主题的海报",
    ))

    results.append(_run_tool(
        catalog, "marketing.generate_copy",
        {"campaign_name": "GPU新客满减", "product": "GPU", "channel": "wechat"},
        "给这个活动写一段推广文案",
    ))

    results.append(_run_tool(
        catalog, "marketing.generate_promotion_link",
        {"campaign_name": "GPU新客满减", "channel": "wechat"},
        "生成一个推广链接",
    ))

    results.append(_run_tool(
        catalog, "marketing.generate_poster",
        {"theme": "AI算力起量", "campaign_name": "GPU新客满减", "size": "portrait"},
        "生成一张营销海报",
    ))

    # ── Research domain (prereq chain: generate_report → reference_search → export_report) ─

    results.append(_run_tool(
        catalog, "research.generate_report",
        {"topic": "大模型行业趋势"},
        "帮我写一份关于大模型趋势的研究报告",
    ))

    results.append(_run_tool(
        catalog, "research.reference_search",
        {"topic": "大模型行业趋势", "limit": 5},
        "搜集一下大模型趋势的参考资料",
    ))

    results.append(_run_tool(
        catalog, "research.export_report",
        {"topic": "大模型行业趋势", "format": "markdown"},
        "导出研究报告",
    ))

    # ── Legacy domain ────────────────────────────────────────────────

    results.append(_run_tool(
        catalog, "product_catalog.lookup",
        {"user_query": "产品目录"},
        "查一下产品目录（旧接口）",
    ))

    results.append(_run_tool(
        catalog, "billing.summary",
        {"month": "2026-04"},
        "上个月账单汇总（旧接口）",
    ))

    results.append(_run_tool(
        catalog, "orders.status_lookup",
        {"order_id": "ORD-001"},
        "查一下订单状态（旧接口）",
    ))

    results.append(_run_tool(
        catalog, "icp.checklist",
        {"entity_type": "enterprise", "province": "上海"},
        "备案需要什么材料（旧接口）",
    ))

    results.append(_run_tool(
        catalog, "icp.status_lookup",
        {"application_id": "icp_e2e_001"},
        "查一下备案状态（旧接口）",
    ))

    results.append(_run_tool(
        catalog, "research.outline",
        {"topic": "大模型行业趋势"},
        "给个研究大纲（旧接口）",
    ))

    return results


def _print_table(results: list[dict[str, Any]]) -> None:
    header = "| 工具名 | 对话时输入内容 | 大模型返回内容 | 调用工具的结果 | 测试结果 | 测试次数 |"
    separator = "|--------|---------------|---------------|---------------|---------|---------|"
    print()
    print(header)
    print(separator)
    for r in results:
        print(f"| {r['tool_name']} | {r['user_input']} | {r['model_response']} | {r['tool_result']} | {r['test_result']} | {r['attempts']} |")
    print()

    total = len(results)
    passed = sum(1 for r in results if r["test_result"] == "PASS")
    failed = total - passed
    print(f"**总计**: {total} 个工具 | **通过**: {passed} | **失败**: {failed}")
    if failed:
        print()
        print("**失败工具**:")
        for r in results:
            if r["test_result"] == "FAIL":
                print(f"  - {r['tool_name']}: {r['tool_result']} ({r['attempts']})")


def test_e2e_tool_invocation() -> None:
    results = _run_all()
    _print_table(results)
    failed = [r for r in results if r["test_result"] == "FAIL"]
    assert not failed, f"{len(failed)} tool(s) failed: {[r['tool_name'] for r in failed]}"


if __name__ == "__main__":
    results = _run_all()
    _print_table(results)
