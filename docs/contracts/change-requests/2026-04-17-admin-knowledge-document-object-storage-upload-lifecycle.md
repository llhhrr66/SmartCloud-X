# Change Request: admin knowledge document object-storage upload lifecycle

- **Date**: 2026-04-17
- **Requester**: supervisor-knowledge-rag
- **Owned services impacted**: `apps/knowledge-service`, `apps/rag-service`, `deploy`, `observability`
- **Frozen areas requiring foundation follow-up**: `docs/contracts/shared/*`, `openapi/*`

## Background
Window 2 has now advanced the current owned backend so that admin document creation can ingest directly from shared MinIO-backed object storage without changing the existing request shape:

- `POST /api/v1/admin/knowledge-bases/{kb_id}/documents`
- existing fields reused:
  - `file_id`
  - `source_type`
  - `source_uri`
- current live-proof path:
  - `source_type=minio`
  - `file_id=<object-key>`
  - `source_uri=minio://<bucket>/<object-key>` (or omitted and derived from config)

Window 2 now also has an owner-local backend lifecycle:
- `POST /api/v1/admin/files/uploads`
- `PUT /api/v1/admin/files/uploads/{upload_id}/content`
- `POST /api/v1/admin/files/uploads/{upload_id}:complete`

This closes the feature gap inside owned scope, but it is **not yet a frozen shared upload lifecycle contract**. The system still lacks one canonical cross-service definition for how admin or frontend clients should interact with this lifecycle once shared/admin/gateway contracts are promoted.

## What exists now
- shared-backend live QA already proves MinIO/MySQL/Qdrant/OpenSearch/Redis as the active knowledge/rag path.
- admin document creation no longer has to be file-backed when object storage is available.
- the current implementation no longer requires the object to pre-exist manually; owner-local QA now proves upload init/content/complete plus subsequent admin document creation against shared MinIO.
- the remaining gap is no longer “feature missing”, but “frozen canonical contract still absent”.

## Gap requiring frozen follow-up
Foundation still needs to define the canonical lifecycle for **new** knowledge document uploads into shared object storage. At minimum, downstream teams need stable answers for:

1. upload initiation
- which route issues the upload target or policy
- whether the route belongs to admin API, gateway, or a dedicated file service
- which auth/RBAC permission governs it

2. upload completion/reference
- how the caller turns a freshly uploaded object into a `file_id` / `source_uri` reference
- whether the canonical reference is:
  - raw object key
  - bucket + object key
  - `minio://bucket/key`
  - opaque uploaded file id

3. validation and audit
- whether `X-Operator-Reason` is mandatory for upload-finalization
- what audit records must exist for:
  - upload initiated
  - upload completed
  - knowledge document create accepted

4. async behavior
- whether upload completion is synchronous
- whether virus scan / parsing / checksum / metadata extraction are baseline requirements or future-phase requirements

## Requested additions

### 1) Canonical upload lifecycle contract
Please freeze one additive admin/file-upload contract for knowledge documents, for example:
- `POST /api/v1/admin/files/uploads`
- `POST /api/v1/admin/files/uploads/{upload_id}:complete`

The exact route names can differ, but the lifecycle must define:
- request auth
- response envelope
- returned object reference fields
- completion/error semantics

### 2) Canonical knowledge-document object reference shape
Please freeze the canonical admin-facing reference shape used by:
- knowledge document create
- admin document detail
- downstream frontend/admin SDK consumers

Today the owned implementation can consume `minio://bucket/key`, but this should not remain owner-local convention forever.

### 3) Shared validation rules
Please freeze:
- allowed source types for shared object storage
- UTF-8 / content-type expectations
- maximum object size expectations or where they are declared
- whether bucket selection is caller-controlled or platform-controlled

## Why this needs foundation
Window 2 has already extended the owned implementation as far as it safely can inside owned scope. The remaining work now crosses frozen contracts, admin surfaces, and likely frontend SDK consumers. Without a frozen contract, downstream callers could hardcode different object reference formats or route semantics and reintroduce drift.

## Compatibility notes
- this request is additive
- the current owner-local MinIO path can remain as the working baseline until the frozen lifecycle exists
- no existing live route needs to be removed immediately
