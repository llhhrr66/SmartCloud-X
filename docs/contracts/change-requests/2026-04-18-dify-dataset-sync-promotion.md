# Change Request: Dify dataset sync promotion beside external knowledge adapter

- **Date**: 2026-04-18
- **Requester**: backend-alignment closeout
- **Owned services impacted**:
  - `apps/knowledge-service`
  - `deploy`
- **Frozen areas requiring follow-up**:
  - `docs/contracts/shared/runtime-health.md`
  - `openapi/knowledge-service.openapi.yaml`

## Background

仓库此前只拥有 Dify External Knowledge adapter（`POST /retrieval`），还没有 dataset push/sync 主链，也没有把 `disabled / configured / verified-live / blocked-external` 这套状态词汇统一到 health/snapshot。

## 本次 owner 实现

- 新增 `apps/knowledge-service/app/services/dify_dataset_sync.py`
- 新增 admin route：
  - `POST /api/v1/admin/dify/datasets/sync/{kb_id}`
- dataset sync 使用现有知识文档正文，按 deterministic remote name `{kb_code}-{document_id}` 执行：
  - `create-by-text`
  - `update-by-text`
- `healthz` 与 runtime snapshot 现在同时暴露：
  - `difyExternalKnowledge`
  - `difyDatasetSync`
- 状态词汇统一为：
  - `disabled`
  - `configured`
  - `verified-live`
  - `blocked-external`

## 兼容性说明

- external adapter 仍保留，dataset sync 作为第二条正式路径并存
- 当前环境没有真实 Dify endpoint / key / dataset id，因此 owner 测试只能做到 fake-remote proof，live verification 仍是 external blocker

## 建议后续冻结项

1. 在 shared runtime health guidance 中冻结 Dify 两条路径的状态字段
2. 在 OpenAPI 中冻结 dataset sync admin route
3. 明确 external adapter 与 dataset sync 的 shared ownership and enablement rules
