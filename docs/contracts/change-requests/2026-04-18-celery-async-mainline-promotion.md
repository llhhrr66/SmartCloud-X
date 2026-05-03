# Change Request: Celery + Redis promotion for marketing poster background tasks

- **Date**: 2026-04-18
- **Requester**: backend-alignment closeout
- **Owned services impacted**:
  - `apps/marketing-service`
  - `deploy/docker-compose`
- **Frozen areas requiring follow-up**:
  - `docs/contracts/shared/persistence-backends.md`
  - `docs/contracts/shared/runtime-health.md`
  - `openapi/*`

## Background

SmartCloud 开发文档要求正式异步体系为 `Celery + Redis`。此前仓库中的营销海报任务仍走“请求创建 -> 读路径自动补完”的 owner-local 伪异步路径，不是正式 worker mainline。

## 本次 owner 实现

- 新增 `apps/marketing-service/app/celery_app.py`
- 新增 `apps/marketing-service/app/tasks.py`
- `POST /api/v1/marketing/posters` 在 Celery broker/result backend 已配置时改为正式入队，而不是继续依赖读路径自动完成
- 新增 `marketing-worker` compose 入口
- 任务配置包含：
  - `acks_late=True`
  - `task_reject_on_worker_lost=True`
  - `autoretry_for=(RuntimeError,)`
  - `retry_backoff=True`
  - `worker_prefetch_multiplier=1`
  - soft/hard time limit

## 当前边界

### 已正式进入 Celery 的主线

- 营销海报生成任务 `marketing.generate_poster_task`

### 仍未迁入 Celery 的路径

- research 深度研究任务
- knowledge indexing/outbox worker

## 兼容性说明

- 当 `MARKETING_SERVICE_CELERY_BROKER_URL` 与 `MARKETING_SERVICE_CELERY_RESULT_BACKEND` 未配置时，当前仓库仍保留非 Celery fallback，避免破坏已有 local/test 基线。
- 当上述配置存在时，读路径不再自动把海报任务补完为 completed，正式结果由 worker 写回。

## 建议后续冻结项

1. shared runtime health 文档增加 Celery queue 运行态表达
2. shared persistence/backend matrix 增加 Celery + Redis 队列主线说明
3. 将 research / knowledge 的长耗时任务继续迁入同一正式 async story
