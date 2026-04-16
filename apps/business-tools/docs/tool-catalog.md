# Business Tools Starter Catalog

## Domains
- product-tech
- customer-service
- finance-order
- icp-service
- ops-marketing
- deep-research

## Spec-aligned starter tools
- `product.catalog_lookup`
- `product.recommend_instance`
- `support.playbook_search`
- `support.query_service_status`
- `support.handoff_brief`
- `billing.query_statement`
- `billing.query_instance_cost`
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
- `billing.query_statement` 会额外回写 `primary_instance_id`，配合 `billing.query_instance_cost` 支持“这台实例花了多少”之类的账单续问
- `product.recommend_instance` 会回写推荐工作负载、机型、GPU 型号和规格摘要，方便后续营销活动推荐或继续技术追问直接复用实例建议
- `support.handoff_brief` 会生成转人工交接摘要并回写 `human_handoff_queue` / `human_handoff_severity` / `human_handoff_summary` 等上下文字段，便于 orchestrator 或人工坐席继续处理投诉/故障升级
- `support.query_service_status` 会回写 `service_status` / `service_incident_code` / `service_status_summary` / `service_recommended_action` 等诊断上下文，便于后续追问或转人工复用同一份基线状态检查结果
- `support.handoff_brief` 现在还能吸收上一步状态巡检的 `service_status` / `incident_code` / `status_summary` / `recommended_action`，让人工交接摘要保留结构化故障信息
- `ticket.create` 现在也能吸收 `human_handoff_*` / `service_*` 上下文，生成携带队列、事件号、服务状态与关联资源的工单结果，并把 `ticket_queue` / `ticket_incident_code` / `ticket_related_resources` 写回 `session_context`
- `marketing.campaign_lookup` / `marketing.generate_copy` / `marketing.poster_brief` / `marketing.generate_poster` 会复用 `recommended_instance_summary` 或 `last_marketing_product_summary`，让“把刚才推荐的实例写成营销文案/海报”之类的续问保留具体机型上下文
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
