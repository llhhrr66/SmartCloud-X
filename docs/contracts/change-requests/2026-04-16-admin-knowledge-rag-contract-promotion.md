# Change Request: Admin knowledge/RAG contract promotion baseline

- **Date**: 2026-04-16
- **Requester**: supervisor-knowledge-rag
- **Owned services impacted**: `apps/knowledge-service`, `apps/rag-service`, `apps/web-admin`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/`

## Background
The owned baseline now provides a practical operator console in `apps/web-admin` for:
- starter-catalog bootstrap
- text ingestion
- catalog overview
- direct knowledge search preview
- RAG diagnostics
- answer preview

Today that console talks directly to the current internal owner routes:
- `GET /api/knowledge/v1/overview`
- `POST /api/knowledge/v1/catalog:bootstrap`
- `POST /api/knowledge/v1/documents:ingest`
- `POST /api/knowledge/v1/search`
- `POST /api/rag/v1/diagnose`
- `POST /api/rag/v1/answer`

This is acceptable as an owned baseline, but it does not yet align with the primary spec sections `20.14` and `20.15`, which expect admin-facing external surfaces under `/api/v1/admin/**` with RBAC, audit, and explicit ownership.

## Requested additions

### 1) Admin knowledge-management OpenAPI placeholders
Please add frozen admin placeholders for the minimum operator flows now exercised by the baseline:
- `GET /api/v1/admin/dashboard/summary`
- `GET /api/v1/admin/knowledge-bases`
- `POST /api/v1/admin/knowledge-bases`
- `GET /api/v1/admin/knowledge-bases/{kb_id}/documents`
- `POST /api/v1/admin/knowledge-bases/{kb_id}/documents`
- `GET /api/v1/admin/knowledge-documents/{doc_id}/chunks`
- `POST /api/v1/admin/knowledge-documents/{doc_id}/reindex`

### 2) Admin retrieval-diagnostics contract
Please define where the baseline admin retrieval-validation flow should live contractually. The current operator console needs a stable admin-facing path for:
- direct knowledge search preview
- retrieval diagnostics with rewrite details
- citation/coverage inspection

This may be a dedicated admin aggregation route or a documented allowance for admin surfaces to consume internal owner routes through a gateway.

### 3) Audit/RBAC minimums for the baseline flows
Please freeze the minimum expectations for the owned admin write actions already represented in the baseline:
- catalog bootstrap
- document ingestion/upload
- document reindex trigger

At minimum the contract needs to state:
- required permission codes
- whether `X-Operator-Reason` is mandatory
- whether the operation must emit audit-log records
- whether the operation is synchronous or async in the baseline phase

## Why foundation help is needed
The current baseline is usable for local integration and operator validation, but keeping these flows only as downstream implementation details risks drift when gateway, RBAC, and admin frontend work formalize around the spec-required `/api/v1/admin/**` surface.

## Compatibility notes
- this request is additive
- it does not require removing the current internal owner routes immediately
- current downstream payloads can remain owner-defined initially as long as the admin route ownership and lifecycle rules are frozen

## Foundation Processing Result
- processed at: 2026-04-16
- decision: accepted and implemented in frozen space
- implemented:
  - added `openapi/admin-api.openapi.yaml` with frozen admin placeholders for dashboard summary, knowledge-base/document management, search preview, and retrieval diagnostics
  - promoted shared admin DTO schemas for dashboard summaries, knowledge bases/documents/chunks, async jobs, and retrieval preview/diagnostic payloads into `packages/common-schemas`
  - added `docs/contracts/shared/admin-api-baseline.md` to freeze current admin ownership, RBAC, audit, operator-reason, and temporary gateway-proxy rules
  - expanded shared auth/runtime/header baselines with canonical `admin:kb.*` permissions plus `X-Operator-Reason` and related shared header-name config
