# Web Admin Baseline

Vite + React admin console for SmartCloud-X knowledge and RAG operations.

## Scope
- service health dashboard for knowledge and RAG APIs
- readiness diagnostics for runtime file paths and the RAG -> knowledge upstream dependency
- one-click runtime snapshot export for the current knowledge/admin state so operators can hand off a portable JSON baseline without opening service files
- admin knowledge-base creation, update, and document reindex controls aligned to `/api/v1/admin/**`
- selected-document detail panel with chunk/token stats and latest async create/reindex job lookup via `/api/v1/admin/knowledge-documents/{doc_id}` and `/api/v1/admin/jobs/{job_id}`
- admin file-backed document creation from previewed import files plus recent audit-trail inspection
- audit-trail filtering by resource, action, and operator id for faster local incident review
- catalog overview for source kinds, top tags, document-language coverage, and largest sources
- starter catalog bootstrap plus direct text-ingestion form
- filesystem import preview + batch-ingestion workflow for markdown/text starter docs mounted into `knowledge-service`
- source, document, chunk, and ingestion activity inventory views
- direct knowledge-search preview plus retrieval diagnostics with source/tag filters, rewrite inspection, unmatched-term analysis, and answer playground

## Run
```bash
cd apps/web-admin
npm install
npm run dev -- --host 0.0.0.0 --port 8050
```

## Environment
- `VITE_KNOWLEDGE_SERVICE_BASE_URL` default: `http://localhost:8030/api/knowledge/v1`
- `VITE_RAG_SERVICE_BASE_URL` default: `http://localhost:8040/api/rag/v1`
- `VITE_OPERATOR_REASON_HEADER` default: `X-Operator-Reason`

## Notes
- The console expects `knowledge-service` and `rag-service` to allow the browser origin through `SMARTCLOUD_CORS_ALLOWED_ORIGINS`.
- The KB create form, KB settings panel, and reindex action call the canonical admin routes under `knowledge-service` and require an operator reason plus the baseline confirm-token convention for reindex.
- Selecting a knowledge base now enables a PATCH-backed settings panel so operators can validate status toggles (`ready` / `disabled`), retrieval-mode changes, and description/name updates without editing runtime JSON files directly.
- Previewed filesystem files can be promoted into the selected KB through `POST /api/v1/admin/knowledge-bases/{kb_id}/documents`, which makes document creation visible in the local audit trail.
- Selecting a document now triggers the canonical admin detail route plus admin job lookup so operators can verify version bumps, token counts, and the most recent create/reindex job without leaving the console.
- The "Seed Starter Catalog" action calls `POST /api/knowledge/v1/catalog:bootstrap` to preload a minimal product, finance, and compliance corpus.
- The filesystem import controls call `GET /api/knowledge/v1/imports:preview` and `POST /api/knowledge/v1/files:ingest`; when a KB is selected, imports attach to that KB instead of creating a new source.
- The audit panel reads `GET /api/knowledge/v1/admin/audit-records` so operators can confirm KB/document create, update, and reindex activity without opening the runtime audit file directly.
- Browser requests now attach `X-Request-Id` and `X-Caller-Service: web-admin`, and surfaced fetch errors include the request id when available so operators can correlate console failures with backend logs faster.
- The knowledge health card now surfaces the active import root and batch-file cap so operators can confirm compose/runtime wiring.
- The health cards now also show readiness checks, warning text, audit-log path details, CORS origins, and the live RAG upstream probe so operators can spot configuration drift before ingestion or retrieval testing.
- The "Export Runtime Snapshot" action downloads `GET /api/knowledge/v1/snapshot` so operators can preserve the current local sources, documents, chunks, KB profiles, admin jobs, overview, and recent audit trail in one JSON file.
- The runtime wiring panel now shows connector configuration plus outbox lifecycle counters and recent event status/attempt/error details, which helps operators validate async indexing scaffolding before dedicated workers land.
- The recent-ingestion activity feed now resolves human-readable source and document names by combining `GET /api/knowledge/v1/sources`, `GET /api/knowledge/v1/documents`, and `GET /api/knowledge/v1/ingestions`.
- The "Preview Knowledge Search" action calls `POST /api/knowledge/v1/search` so operators can validate the raw knowledge layer before involving RAG reranking.
- The knowledge-base/document inventory now uses the admin placeholder routes, while the chunk inspector still reads the richer owner-local chunk payload from `GET /api/knowledge/v1/chunks?documentId=...`.
- The diagnostics panel calls `POST /api/rag/v1/diagnose` so operators can inspect rewrite expansion, candidate counts, and applied filters before trusting answer composition.
- The console now also calls the canonical admin placeholder routes `POST /api/v1/admin/retrieval/search-preview` and `POST /api/v1/admin/retrieval/diagnostics` so operators can compare the richer owner-local preview with the contract-facing admin surface in one place.
- Admin write actions honor `VITE_OPERATOR_REASON_HEADER`, which should match `SMARTCLOUD_OPERATOR_REASON_HEADER` when deploy/runtime environments override the shared operator-reason header name.
