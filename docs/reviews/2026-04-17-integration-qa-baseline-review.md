# Integration QA Baseline Review

## Findings

- Repo-root browser and subprocess QA evidence is still useful for smoke validation, but it is not enough to prove that chat retrieval events are grounded in real RAG citations.
- No current review document may treat `baseline://router-retrieval` as successful retrieval evidence. Citation trust now depends on structured retrieval output and stream payload integrity.
- Readiness review improved because `auth-user-service`, `knowledge-service`, and `rag-service` now expose `/readyz` in code, but release review still must distinguish code-backed readiness from placeholder or lagging contracts.
- `knowledge-service` index routing now goes through `KnowledgeIndexTargetResolver`, yet review must still allow for `mixed` mode and must not claim a completed full per-domain migration without runtime evidence.
- `gateway-service` remains a BFF/proxy boundary. It is not the owner of orchestrator stream event semantics and must not become a semantic repair layer for broken `retrieval`, `citation`, or `message.error` events.
- High-risk stream/debug work should start from `apps/orchestrator-service/app/services/streaming.py`. Route-level changes in `apps/orchestrator-service/app/api/routes/orchestration.py` should stay minimal and only follow direct source inspection.
- If a route appears to set a field that disappears in the final JSON, inspect the Pydantic response model and serialization path before adding more route-layer dict mutations.

## Scope Reviewed

- `apps/gateway-service/app/api/routes/chat.py`
- `apps/orchestrator-service/app/api/routes/orchestration.py`
- `apps/orchestrator-service/app/services/agent_runtime.py`
- `apps/orchestrator-service/app/services/router.py`
- `apps/orchestrator-service/app/services/streaming.py`
- `apps/auth-user-service/app/routes.py`
- `apps/knowledge-service/app/api/routes/health.py`
- `apps/knowledge-service/app/services/indexing_worker.py`
- `apps/rag-service/app/api/routes/health.py`
- `docs/reviews/known-issues.md`
- `project_document/architecture-review-2026-04-18.md`

## Validation Completed

- direct code review of orchestrator stream event construction in `apps/orchestrator-service/app/services/streaming.py`
- direct code review of gateway citation capture and canonical error handling in `apps/gateway-service/app/api/routes/chat.py`
- direct code review of readiness route presence in `apps/auth-user-service/app/routes.py`, `apps/knowledge-service/app/api/routes/health.py`, and `apps/rag-service/app/api/routes/health.py`
- direct code review of knowledge indexing target selection entry point in `apps/knowledge-service/app/services/indexing_worker.py`
- architecture cross-check against `project_document/architecture-review-2026-04-18.md`

## Residual Risk

- QA smoke can pass while stream event meaning is still wrong or overstated.
- Readiness route presence can be mistaken for uniform contract maturity or release readiness.
- Knowledge retrieval behavior can remain partially baseline-backed while docs overstate per-domain migration.
- Route-level hotfixes can hide model-filtering problems and create further drift if response models are not checked first.
