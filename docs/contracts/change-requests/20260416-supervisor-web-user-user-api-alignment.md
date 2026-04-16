# Change Request

## Summary
- requester: supervisor-web-user
- date: 2026-04-16
- affected frozen path: docs/contracts/shared/api-conventions.md, openapi/*
- blocking: no

## Background
在搭建 `apps/web-user/` 用户端 baseline 时，前端需要同时支持：
1. 用户主规范中的统一响应结构与 SSE 事件。
2. 研究任务、营销海报等异步结果页的历史展示能力。

## Current Gap
1. `docs/contracts/shared/api-conventions.md` 当前推荐共享 `ApiEnvelope<T>`（`success/data/requestId/error`），但主规范 20.5.5 / 20.5.6 使用的是 `code/message/data/request_id/timestamp`。
2. 用户端前端设计包含“调研报告页”“营销海报结果页”，但现有主规范仅定义：
   - `POST /api/v1/research/tasks`
   - `GET /api/v1/research/tasks/{task_id}`
   - `POST /api/v1/marketing/posters`
   - `GET /api/v1/marketing/posters/{task_id}`
   缺少历史列表 / 最近任务查询合同，导致用户端 live 模式无法稳定回填任务历史。

## Proposed Change
1. 由 foundation 明确用户侧 HTTP 响应的最终 canonical contract：
   - 统一迁移到 `ApiEnvelope<T>`，或
   - 在 shared contract 中补充 `code/message/data/request_id/timestamp` 兼容约定与网关归一化规则。
2. 为用户端补充最小历史查询合同与 OpenAPI 占位，建议至少增加：
   - `GET /api/v1/research/tasks`
   - `GET /api/v1/marketing/posters`
   并明确分页、排序、状态字段与最小展示 DTO。
3. 在 shared / OpenAPI 文档中补充 SSE 事件字段的前端友好命名映射说明（snake_case -> camelCase 可由客户端自行处理，但字段集合应冻结）。

## Impacted Consumers
- supervisor(s): supervisor-web-user, supervisor-orchestrator, supervisor-knowledge-rag, supervisor-foundation
- service(s) or surface(s): apps/web-user, research-service, marketing-service, gateway/openapi docs
- required follow-up work:
  - foundation 发布最终共享合同 / OpenAPI 占位
  - research / marketing 服务补齐列表读接口或明确替代方案
  - web-user 在 live 模式中切换掉当前 mock / 空列表降级逻辑

## Compatibility
- breaking or non-breaking: non-breaking if introduced as additive contract + gateway normalization note
- fallback or migration plan: 当前 web-user 已在 `apps/web-user/src/api/client.ts` 中兼容两种 envelope，并在 `research.ts` / `marketing.ts` 中对缺失列表接口做空列表降级
- temporary workaround already in use: 默认启用 mock 数据；live 模式下保留 typed placeholders

## Evidence
- code reference(s):
  - `apps/web-user/src/api/client.ts`
  - `apps/web-user/src/api/services/research.ts`
  - `apps/web-user/src/api/services/marketing.ts`
- mock/example/stub reference(s):
  - `apps/web-user/src/api/mock.ts`
  - `apps/web-user/src/pages/ResearchPage.tsx`
  - `apps/web-user/src/pages/MarketingPage.tsx`
- log or failing validation reference(s):
  - `logs/supervisor-web-user/decisions.log`
  - `logs/supervisor-web-user/blockers.log`

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - 在共享文档中明确：内部服务继续使用 `ApiEnvelope<T>`，外部用户接口统一发布 canonical `code/message/data/request_id/timestamp` 合同
  - 在 `packages/common-schemas` 中新增 canonical external envelope、分页、SSE envelope、研究/营销任务 DTO schema
  - 在 `openapi/marketing-service.openapi.yaml` 与 `openapi/research-service.openapi.yaml` 中新增用户侧历史列表与详情占位合同
  - 在 `docs/contracts/shared/api-conventions.md` 中补充 SSE canonical 事件名与 legacy alias 映射说明
