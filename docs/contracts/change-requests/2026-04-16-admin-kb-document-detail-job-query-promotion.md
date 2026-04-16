# Change Request: promote admin knowledge document detail + job query placeholders

- Date: 2026-04-16
- Requested by: `supervisor-knowledge-rag`
- Affected frozen area: `docs/contracts/shared/admin-api-baseline.md` and downstream admin OpenAPI publication

## Why
`knowledge-service` now exposes practical baseline implementations for:

1. `GET /api/v1/admin/knowledge-documents/{doc_id}`
2. `GET /api/v1/admin/jobs/{job_id}`

These routes are already required by the primary spec (`20.14.3` and `20.14.8`), but the current frozen admin baseline only covers KB list/create, document list/create, chunk preview, reindex, search preview, and RAG diagnostics. Without promoting these placeholders, `web-admin` can use them only as owner-local integrations instead of stable shared contracts.

## Requested promotion

### 1. Document detail placeholder
- Method: `GET`
- Path: `/api/v1/admin/knowledge-documents/{doc_id}`
- Owner: `knowledge-service`
- Baseline response shape:
  - `document`
  - `chunk_stats.chunk_count`
  - `chunk_stats.token_count`
  - `chunk_stats.average_tokens_per_chunk`
  - `chunk_stats.latest_job_id`
  - `error_message`

### 2. Async job query placeholder
- Method: `GET`
- Path: `/api/v1/admin/jobs/{job_id}`
- Owner: `knowledge-service` for current KB baseline jobs; future gateway aggregation can widen ownership later
- Baseline response shape:
  - `job_id`
  - `type`
  - `status`
  - `progress`
  - `created_at`
  - `finished_at`
  - `params`
  - `result_file_id`
  - `error_code`
  - `error_message`

## Current implementation notes
- `knowledge-service` persists admin jobs in the same runtime JSON store as the KB baseline.
- document create and reindex both register an `AdminAsyncJob` record and attach the latest job id to the document profile.
- `web-admin` already consumes these routes to show selected-document stats and recent job state.

## Requested foundation follow-up
- add both routes to the frozen admin baseline contract and future admin OpenAPI publication
- keep the owner as `knowledge-service` for the current single-service baseline, while documenting that gateway aggregation may expand later when more job types exist

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added shared admin schemas for `AdminKnowledgeChunkStats` and `AdminKnowledgeDocumentDetailData` in `packages/common-schemas`
  - promoted `GET /api/v1/admin/knowledge-documents/{doc_id}` and `GET /api/v1/admin/jobs/{job_id}` into `openapi/admin-api.openapi.yaml` and shared admin baseline docs
  - wired the new admin detail/job-query schemas into `openapi/components.openapi.yaml`, package/type exports, README/docs summaries, and the foundation validator so future regressions fail fast
