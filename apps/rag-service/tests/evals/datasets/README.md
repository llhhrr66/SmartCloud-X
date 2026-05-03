# Retrieval eval datasets

数据来源：service-local 检索/引用回归样本。
脱敏规则：不放真实用户手机号、邮箱、证件号、订单号原值、上传原文链接。
样本量：smoke=2（最小边界内基线，用于 supervisor 自测，不代表发布 full/core 覆盖）。
最近更新时间：2026-04-21 UTC
owner：knowledge-rag supervisor

说明：
- 当前仓库尚未具备文档要求的 core/full 全量样本，本目录先提供 smoke 基线。
- `must_cite=true` 样本若无 citations 或 citationId/backendUsed 缺失，必须判失败。
- 这些样本只验证 knowledge/rag 边界内的检索与引用契约，不覆盖 orchestrator 路由。
