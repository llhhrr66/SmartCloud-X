# Integration QA Baseline

## Scope

This baseline stays inside QA-owned paths and validates current SmartCloud-X reality from those paths:

- integration smoke in `tests/integration/test_service_smoke.py`
- contract/presence checks in `tests/integration/test_contract_presence.py`
- focused runner in `scripts/qa/run_smoke.sh`
- subprocess acceptance in `scripts/qa/project_smoke.py`
- persistence/reporting analysis in `scripts/qa/infra_persistence_matrix.py`
- repo browser entries in `tests/e2e/app-smoke.spec.ts`, `tests/e2e/playwright_smoke.spec.ts`, and `tests/e2e/test_browser_entry.spec.ts`
- review and risk tracking in `docs/reviews/known-issues.md`

## Current Coverage

- key service file and directory presence across auth, orchestrator, knowledge, rag, web-user, web-admin, business-tools, tool-hub, and frontend-sdk surfaces
- status-doc and QA-owned artifact presence checks
- database-backed restart persistence smoke for auth refresh sessions, marketing copy/link/poster records, and research tasks
- isolated `knowledge-rag-admin` subprocess smoke that restarts `knowledge-service` and `rag-service`, then revalidates admin document detail, snapshot retention, search, and diagnostics after restart
- live shared-backend evidence through `SMARTCLOUD_QA_USE_LIVE_INFRA` for auth/marketing/research, `business-tools-tool-hub`, `orchestrator-billing`, and now `knowledge-rag-admin`
- structured recorded runtime proof in `logs/supervisor-integration-qa/state.json` for local smoke, repo browser, knowledge/rag restart, live knowledge/rag shared connectors, live auth/tooling/orchestrator MySQL/Redis landing, and the local/live orchestrator timeout chain
- release readiness blocking on the runtime-backend capability matrix from `scripts/qa/infra_persistence_matrix.py`, QA reporting consistency, and the new live knowledge/rag shared-connector evidence
- compose-backed shared-backend defaults plus the MinIO `19000/19001` host-port override are now explicitly guarded from owned QA paths by checks on `deploy/docker-compose/docker-compose.yml`, `scripts/qa/qa_env.sh`, and `docs/runbooks/local-validation.md`
- repo browser smoke covering dashboard bootstrap, billing citation happy path, reload persistence in marketing/research, reload-safe billing `401` refresh recovery, route/citation `403`, SSE reconnect, `429`, and research report gaps
- a separate non-blocking live probe now records the stronger MinIO-enabled marketing artifact gap instead of hiding it behind the older knowledge/rag blocker narrative

## Latest Validation

- `2026-04-17T00:16:53+08:00`: final self-review for the owned QA diff passed `14` targeted tests across `tests/integration/test_contract_presence.py` and `tests/e2e/test_ui_smoke.py`; `scripts/qa/check_release_readiness.py` stayed green at `120/120`, the status-report wording fix did not change the blocker set, and `git diff --check` stayed clean.
- `2026-04-17T00:13:15+08:00`: `scripts/qa/run_smoke.sh` passed with `34` focused pytest tests, readiness `120/120`, infra persistence `26/26`, and a green default targeted `auth-marketing-research` plus `orchestrator-billing` service-process baseline.
- `2026-04-16T23:49:25+08:00`: targeted self-review rerun passed `13` tests across `tests/integration/test_contract_presence.py` and `tests/e2e/test_ui_smoke.py`; `scripts/qa/check_release_readiness.py` stayed green at `118/118` blocking path/content/package checks, and `git diff --check` stayed clean for the owned QA diff.
- `2026-04-16T23:37:38+08:00`: `scripts/qa/run_smoke.sh` passed with `33` focused pytest tests, readiness `118/118`, infra persistence `26/26`, and a green default targeted service-process baseline.
- `2026-04-16T23:39:19+08:00`: `SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario knowledge-rag-admin` passed and recorded shared-connector evidence for MinIO raw storage, MySQL metadata, Qdrant vectors, OpenSearch BM25, Redis cache/task queue, and restart retention.
- `2026-04-16T23:40:00+08:00`: the stronger MinIO-enabled `SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario auth-marketing-research --scenario business-tools-tool-hub --scenario orchestrator-billing` rerun failed on `marketingPosterObjectStored`; the bucket stayed reachable at `http://127.0.0.1:19000`, but the expected poster object still did not land.

## Current Gaps

- live knowledge/rag connector proof through MySQL/Redis/MinIO/Qdrant/OpenSearch is now green, but the stronger marketing MinIO artifact landing proof is still open
- `auth-user-service`, `marketing-service`, and `research-service` still do not expose a frozen runtime backend evidence surface on health or snapshot endpoints
- tool-hub still relies on `/internal/v1/tools/call` for the subprocess smoke because the frozen public `POST /api/v1/tools/call` route returns `405`
- the repo-root browser package still depends on `apps/web-user` dependencies and Playwright browsers being provisioned on the runner
- the new compose/runbook/qa_env alignment guard reduces drift around localhost live-backend defaults, but it does not replace the need for the live reruns already recorded in `state.json`
- `docs/reviews/known-issues.md` remains the source of truth for unresolved QA scope and release risks

## Intended Use

- use `scripts/qa/run_smoke.sh` for the fast baseline
- use `SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario knowledge-rag-admin` when MySQL/Redis/MinIO/Qdrant/OpenSearch-backed knowledge/rag proof is the priority
- use `SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario auth-marketing-research --scenario business-tools-tool-hub --scenario orchestrator-billing` when MySQL/Redis landing is the priority and to recheck whether the MinIO-backed marketing poster artifact gap has been fixed
- use `scripts/qa/project_smoke.py --scenario orchestrator-billing` when a change touches orchestrator/tool-hub/business-tools happy-path or timeout-chain behavior
- use `scripts/qa/infra_persistence_matrix.py` and `scripts/qa/check_release_readiness.py` when deciding whether a build is ready to move beyond QA
