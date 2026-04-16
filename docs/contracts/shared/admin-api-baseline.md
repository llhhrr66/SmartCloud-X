# Admin API Baseline

This document freezes the current external admin-surface baseline required by spec sections `20.14` and `20.15`.

## Canonical surface
- admin HTTP routes publish under `/api/v1/admin/**`
- admin routes use the canonical external envelope family (`code/message/data/request_id/timestamp`)
- route ownership is explicit per operation via `x-owner-service`, even when the public admin surface is gateway-published

## Current frozen placeholder ownership
- `GET /api/v1/admin/dashboard/summary` -> `gateway-service` aggregate read
- `GET/POST /api/v1/admin/knowledge-bases` -> `knowledge-service`
- `PATCH /api/v1/admin/knowledge-bases/{kb_id}` -> `knowledge-service`
- `GET/POST /api/v1/admin/knowledge-bases/{kb_id}/documents` -> `knowledge-service`
- `GET /api/v1/admin/knowledge-documents/{doc_id}` -> `knowledge-service`
- `GET /api/v1/admin/knowledge-documents/{doc_id}/chunks` -> `knowledge-service`
- `POST /api/v1/admin/knowledge-documents/{doc_id}/reindex` -> `knowledge-service`
- `GET /api/v1/admin/jobs/{job_id}` -> `knowledge-service` for the current knowledge-base async-job baseline
- `POST /api/v1/admin/retrieval/search-preview` -> gateway-published path currently backed by `knowledge-service`
- `POST /api/v1/admin/retrieval/diagnostics` -> gateway-published path currently backed by `rag-service`

## RBAC baseline for this phase
- dashboard summary: `admin:ops.read`
- knowledge read flows: `admin:kb.read`
- knowledge write flows: `admin:kb.write`
- legacy `admin:knowledge.read/write` strings remain accepted only as compatibility aliases and normalize to `admin:kb.read/write`

## Audit and operator-reason minimums
- all admin write routes in the current baseline must require `X-Operator-Reason`
- all admin write routes must emit audit-log records with the minimum shared audit field set from the primary spec
- `POST /api/v1/admin/knowledge-documents/{doc_id}/reindex` is treated as high-risk and must also require `confirm_token`
- create-knowledge-base is synchronous in the current placeholder baseline
- update-knowledge-base is synchronous in the current placeholder baseline and reuses the shared `AdminKnowledgeBase` read model
- create-document and reindex are asynchronous in the current placeholder baseline and return an `AsyncJob`-style read model or an accepted document status
- `PATCH /api/v1/admin/knowledge-bases/{kb_id}` currently accepts additive fields `name`, `description`, `retrieval_mode`, and `status` (`ready` / `disabled`)
- `GET /api/v1/admin/knowledge-documents/{doc_id}` returns the selected document read model together with `chunk_stats.{chunk_count, token_count, average_tokens_per_chunk, latest_job_id}` plus an optional top-level `error_message`; document-level `error_message` may also be omitted or `null` when no document error exists
- `GET /api/v1/admin/jobs/{job_id}` is the current polling/drill-down route for the knowledge-service async-job baseline and returns the shared `AdminAsyncJob` read model; nullable owner-model fields such as `error_message` remain additive and should be treated as no-error/no-result states

## Temporary gateway allowances still documented here
Until dedicated admin routes are promoted for these flows, the gateway may proxy:
- starter-catalog bootstrap -> `POST /api/knowledge/v1/catalog:bootstrap` with `admin:kb.write`, `X-Operator-Reason`, and audit logging
- answer preview -> `POST /api/rag/v1/answer` with `admin:kb.read`

These temporary allowances are integration notes only. New admin clients should prefer the documented `/api/v1/admin/**` routes whenever a frozen placeholder exists.
