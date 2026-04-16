# Business Tools Starter Catalog

## Domains
- product-tech
- finance-order
- icp-service
- ops-marketing
- deep-research

## Spec-aligned starter tools
- `product.catalog_lookup`
- `support.playbook_search`
- `billing.query_statement`
- `order.query_order`
- `billing.create_invoice`
- `invoice.query_invoice`
- `order.create_refund`
- `ticket.create`
- `ticket.reply`
- `icp.material_check`
- `icp.verify_subject`
- `icp.submit_application`
- `marketing.campaign_lookup`
- `marketing.poster_brief`
- `marketing.generate_copy`
- `marketing.generate_promotion_link`
- `marketing.generate_poster`
- `research.generate_report`
- `research.reference_search`
- `research.export_report`

## Legacy compatibility aliases
- `product_catalog.lookup`
- `billing.summary`
- `orders.status_lookup`
- `icp.checklist`
- `icp.status_lookup`
- `research.outline`

## Notes
- 查询类工具默认以 `execute` 基线返回 mock 数据，并声明 `cache_ttl_seconds`
- 高风险写工具在未显式确认时返回 `confirmation-required`
- 已确认的写工具会返回 `compensation` 元数据，供 orchestrator 组装 Saga 补偿栈
- 工具执行结果会额外返回 `session_context_patch`，用于把账单编号、工单编号、发票编号、备案申请号等上下文自动带入后续会话
- `order.query_order` 会回写最近订单号、退款单号与退款进度，方便后续继续追踪退款
- `invoice.query_invoice` 会复用并回写 `invoice_no` / `invoice_status`，用于开票后的连续追问
- `icp.verify_subject` 会回写备案主体、联系人与实名认证状态，便于后续继续做材料检查或直接提交备案申请
- `icp.verify_subject` / `icp.submit_application` 会额外保留 `certificate_no`、`contact_email` 与聚合后的 `contacts` 对象，方便 `/continue` 用扁平字段或 `contacts.*` 形式逐步补齐备案联系人资料
- `marketing.generate_promotion_link` 会返回可补偿的推广链接元数据，供 orchestrator 在营销写操作回滚时停用短链
- `marketing.generate_copy` 会把最近一次生成的文案标题、正文、活动名和渠道写回 `session_context`，便于后续继续生成海报或推广链接
- `marketing.generate_poster` 会依赖 `marketing.poster_brief` 生成海报资产，并把资产编号、预览地址与下载路径写回 `session_context` 以支持后续展示或回滚
- `research.export_report` 会把导出产物路径和格式写回 `session_context`，便于后续消息继续引用导出结果
- 工具定义额外提供 `input_field_hints`，供 tool-hub / orchestrator 在缺少必填字段时发起澄清式追问
- `tool-hub-service` 负责 registry / MCP / internal tool-call 协议，`business-tools` 负责统一执行入口
