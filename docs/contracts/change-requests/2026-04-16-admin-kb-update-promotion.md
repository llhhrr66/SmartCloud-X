# Change Request: promote admin knowledge-base update placeholder

- Date: 2026-04-16
- Requested by: `supervisor-knowledge-rag`
- Affected frozen area: `docs/contracts/shared/admin-api-baseline.md` and downstream admin OpenAPI publication

## Why
The primary spec (`20.14.3` and `20.15.2`) already expects administrators to update knowledge-base metadata through:

1. `PATCH /api/v1/admin/knowledge-bases/{kb_id}`

`knowledge-service` and `web-admin` now implement a practical owner-local baseline for that flow so operators can rename a KB, tune `retrieval_mode`, and toggle `status` between `ready` and `disabled` without editing runtime files. The frozen admin baseline still documents only KB list/create, so downstream consumers cannot treat this PATCH surface as a stable shared contract yet.

## Requested promotion

### 1. Knowledge-base update placeholder
- Method: `PATCH`
- Path: `/api/v1/admin/knowledge-bases/{kb_id}`
- Owner: `knowledge-service`
- Minimum request fields for the current baseline:
  - `name?`
  - `description?`
  - `retrieval_mode?`
  - `status?` (`ready` / `disabled`)
- Minimum response shape:
  - current `KnowledgeBaseDTO` / `AdminKnowledgeBase` read model

## Current implementation notes
- `knowledge-service` writes KB updates into the same local JSON-backed source/profile store used by the create/list baseline.
- update writes emit audit records with before/after payloads through the existing local admin audit log.
- `web-admin` now exposes a selected-KB settings panel backed by this route and the compose smoke test validates the create -> update -> list flow end to end.

## Requested foundation follow-up
- add `PATCH /api/v1/admin/knowledge-bases/{kb_id}` to the frozen admin baseline contract and admin OpenAPI publication
- promote the additive update request schema into shared admin DTO coverage so frontend/admin clients can stop keeping this request shape app-local
- keep the owner as `knowledge-service` for the current baseline; gateway aggregation is not required for this write surface

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - published `PATCH /api/v1/admin/knowledge-bases/{kb_id}` in the frozen admin OpenAPI baseline with the existing admin audit/operator-reason conventions
  - promoted the additive `AdminKnowledgeBaseUpdateRequest` shared schema/type so admin clients can reuse the request shape without app-local duplication
  - refreshed shared admin/foundation docs and validator coverage so the knowledge-base update baseline stays frozen for downstream integration
