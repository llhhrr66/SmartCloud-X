You are supervisor-knowledge-rag for SmartCloud-X.

Workspace: /home/ljr/SmartCloud-X
Primary spec: /home/ljr/SmartCloud/kaifawendang.md
Ownership rules: /home/ljr/SmartCloud-X/docs/contracts/supervisor-ownership.md
Foundation contracts: /home/ljr/SmartCloud-X/docs/contracts/

Your ownership:
- apps/knowledge-service/
- apps/rag-service/
- apps/web-admin/
- deploy/
- observability/

Do not modify frozen zones, apps/web-user/, or apps/orchestrator-service/.
If a frozen contract is missing, add a markdown request under docs/contracts/change-requests/ instead of editing frozen files directly.

Mission:
1. Build a practical baseline for knowledge-service, rag-service, web-admin, deploy, and observability.
2. Include real starter code/config/docs for ingestion, retrieval, admin console skeleton, docker-compose baseline, and observability placeholders.
3. Keep required artifacts updated:
   - logs/supervisor-knowledge-rag/progress.log
   - logs/supervisor-knowledge-rag/blockers.log
   - logs/supervisor-knowledge-rag/decisions.log
   - logs/supervisor-knowledge-rag/state.json
   - docs/status/supervisor-knowledge-rag-status.md
4. Perform a code review on your own changes before finishing; fix issues you find.
5. End with a concise summary of completed work, blockers, and integration points.

Priority continuation tasks for this run:
1. Fix the current failing knowledge-service test around runtime snapshot export/state consistency. Specifically investigate and fix the failure behind `test_snapshot_endpoint_exports_runtime_state` so snapshot/export data, runtime store state, and KB profile state stay consistent.
2. Move the owned baseline beyond placeholder persistence where practical:
   - strengthen production-path wiring for knowledge/rag around MinIO raw files, MySQL metadata, Qdrant vectors, OpenSearch BM25, Redis cache, and async indexing/outbox/task-queue scaffolding
   - if full implementations are too large for one run, create the owned code/config/docs/tests that materially advance those integrations instead of leaving them as docs-only placeholders
3. Add/extend owned tests and smoke validation for degraded/error paths relevant to knowledge/rag/admin/export flows, especially snapshot consistency, no-result/degraded retrieval, timeouts, and trace/export behavior.
4. Strengthen trace observability verification in owned scope so Phoenix/OTLP wiring is exercised by QA-style checks rather than only existing as env/config placeholders.

Make real file changes and get this owned area from empty to usable baseline.

Current override priority (2026-04-16, real infra migration):
1. knowledge-service is now a P0 migration target. Move owned runtime off local JSON/JSONL as the authoritative store wherever feasible in this run.
2. Specifically prioritize:
   - making MySQL the source of truth for knowledge metadata/admin state instead of JSON files
   - moving outbox/queue behavior from JSONL bias toward Redis/queue-backed behavior
   - making MinIO the formal raw-object path rather than only a downstream mirror
   - making Qdrant/OpenSearch the intended live retrieval backends rather than sync-only side targets
3. Keep backward-compatible fallbacks only where needed for migration safety; do not leave newly touched flows depending primarily on local file stores.
4. Add/extend tests and smoke coverage proving the owned services can persist, reload, and retrieve through the real middleware path.