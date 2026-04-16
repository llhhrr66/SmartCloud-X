# Local Validation

`supervisor-integration-qa` owns the repo-level validation entrypoints under `tests/`, `scripts/qa/`, `docs/runbooks/`, and `docs/reviews/`.

## What This Baseline Validates

- key service assets for `auth-user-service`, `orchestrator-service`, `knowledge-service`, `rag-service`, `web-user`, and `packages/frontend-sdk`
- required status docs and QA-owned reporting artifacts
- restart-oriented database-backed persistence smoke for auth refresh sessions, marketing copy/link/poster records, and research tasks
- structured error-path smoke for `401`, `403`, `409`, `429`, tool timeout, plus `rag-service` `retrieve`/`diagnose`/`answer` empty-result and degraded-upstream behavior
- knowledge snapshot/outbox persistence across restart while keeping configured MySQL, Redis, MinIO, Qdrant, and OpenSearch targets visible in snapshot payloads
- degraded-backend truth for orchestrator, tool-hub, and business-tools when MySQL or Redis is configured but unreachable
- namespace-aware degraded-backend truth for orchestrator, tool-hub, and business-tools, including Redis namespace intent, transport mode, and fallback-write posture from current health payloads
- runtime backend helper presence for current MySQL/Redis-backed orchestrator, tool-hub, business-tools, and knowledge metadata surfaces via `scripts/qa/infra_persistence_matrix.py`
- `scripts/qa/project_smoke.py` backend evidence showing whether data landed in SQLite fallback storage or in live shared backends when `SMARTCLOUD_QA_USE_LIVE_INFRA=1`
- compose-backed live infra defaults for MySQL, Redis, MinIO, Qdrant, and OpenSearch plus the MinIO `19000/19001` host-port mapping that `scripts/qa/qa_env.sh` injects into the shared-backend QA path
- isolated `scripts/qa/project_smoke.py --scenario knowledge-rag-admin` coverage that restarts `knowledge-service` and `rag-service`, then revalidates admin document detail, snapshot retention, search, and diagnostics after restart
- `scripts/qa/project_smoke.py --scenario orchestrator-billing` driving a QA-owned hanging business-tools endpoint so the real `orchestrator-service -> tool-hub-service -> business-tools-service` timeout chain is exercised without modifying service code
- repo-root Playwright wiring through `tests/e2e/` plus runnable browser coverage for dashboard/session smoke, billing citation happy path, reload persistence in marketing/research, reload-safe billing `401` refresh recovery, route `403`, citation `403`, SSE reconnect, `429`, and research report gaps
- `scripts/qa/check_release_readiness.py` checking committed QA assets plus recorded runtime proof in `logs/supervisor-integration-qa/state.json`, including local smoke, repo browser, knowledge/rag restart proof, live knowledge/rag connector proof, and live MySQL/Redis auth/tooling/orchestrator evidence

## Fast Local Path

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
scripts/qa/run_smoke.sh
```

That path runs:

- `bash -n` over the QA shell entrypoints
- focused pytest over `tests/integration/test_contract_presence.py`, `tests/integration/test_service_smoke.py`, `tests/integration/test_error_path_smoke.py`, `tests/integration/test_orchestrator_smoke.py`, `tests/integration/test_auth_marketing_research_flow.py`, and `tests/e2e/test_ui_smoke.py`
- `scripts/qa/check_release_readiness.py`
- `scripts/qa/infra_persistence_matrix.py`
- the default targeted service-process baseline in `scripts/qa/project_smoke.py` for `auth-marketing-research` and `orchestrator-billing`

Do not assume bare `python` or `pytest` exist on the host shell. Initialize `scripts/qa/qa_env.sh` first, then use `${QA_PYTHON[@]}` and `${QA_PYTEST[@]}` for direct QA invocations.

## Full Local Loop

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
"${QA_PYTHON[@]}" scripts/qa/verify_openapi_contracts.py
scripts/qa/run_full_stack_validation.sh
"${QA_PYTEST[@]}" tests -q
```

The wrapper `scripts/qa/run_local_validation.sh` runs the same sequence.

## Live Shared-Backend Path

When Docker-backed infra is available on the local host, enable the stronger runtime proof path:

```bash
docker compose -f deploy/docker-compose/docker-compose.yml up -d mysql redis minio qdrant opensearch
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
export SMARTCLOUD_QA_USE_LIVE_INFRA=1
smartcloud_qa_configure_live_infra_env
"${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario knowledge-rag-admin
```

`smartcloud_qa_configure_live_infra_env` injects localhost defaults for:

- `SMARTCLOUD_QA_SHARED_MYSQL_DSN`
- `SMARTCLOUD_QA_SHARED_REDIS_URL`
- `SMARTCLOUD_QA_SHARED_RAG_REDIS_URL`
- `SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT`
- `SMARTCLOUD_QA_SHARED_MINIO_BUCKET`
- `SMARTCLOUD_QA_SHARED_QDRANT_URL`
- `SMARTCLOUD_QA_SHARED_OPENSEARCH_URL`

The current QA baseline now proves the `knowledge-rag-admin` live connector path with those defaults. The SmartCloud MinIO container is intentionally mapped to host ports `19000/19001`, so the owned QA path should use `http://127.0.0.1:19000` unless you explicitly override `SMARTCLOUD_MINIO_HOST_PORT`.

For the broader live shared-backend path:

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
export SMARTCLOUD_QA_USE_LIVE_INFRA=1
smartcloud_qa_configure_live_infra_env
"${QA_PYTHON[@]}" scripts/qa/project_smoke.py \
  --scenario auth-marketing-research \
  --scenario business-tools-tool-hub \
  --scenario orchestrator-billing
```

Current reality from this run:

- The owned baseline now explicitly checks `deploy/docker-compose/docker-compose.yml`, `scripts/qa/qa_env.sh`, and this runbook for shared-backend default alignment, including the MinIO `19000/19001` host-port mapping.
- MySQL/Redis-backed auth, research, `business-tools-tool-hub`, and `orchestrator-billing` proof is green.
- Live knowledge/rag shared-connector proof is green.
- The stronger MinIO-enabled marketing artifact proof is still open because `marketingPosterObjectStored` remains false even though the bucket itself is reachable.

If you need the older MySQL/Redis-only path while QA-012 remains open, clear the shared MinIO variables before invoking the broader live rerun.

## Optional Acceptance Layers

- `SMARTCLOUD_QA_RUN_STACK=1 scripts/qa/run_smoke.sh`
  Runs the broader subprocess stack for `knowledge-rag-admin` and `business-tools-tool-hub` in addition to the default targeted baseline.
- `SMARTCLOUD_QA_USE_LIVE_INFRA=1 scripts/qa/run_smoke.sh`
  Keeps the same smoke entrypoint but switches `project_smoke.py` to shared-backend evidence mode for services that can use MySQL, Redis, and MinIO from the local host.
- `"${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario orchestrator-billing`
  Runs the orchestrator happy path plus the QA-owned timeout-chain probe against local fallback storage.
- `SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario orchestrator-billing`
  Revalidates the same orchestrator timeout chain while requiring MySQL/Redis landing for conversation/state/audit evidence.
- `SMARTCLOUD_QA_RUN_BROWSER=1 scripts/qa/run_smoke.sh`
  Runs the repo-root Playwright entry after `smartcloud_qa_configure_browser_ports` assigns `QA_BROWSER_APP_PORT` and `QA_BROWSER_API_PORT`.
- `SMARTCLOUD_QA_RUN_BROWSER=1 scripts/qa/run_full_stack_validation.sh`
  Uses the same root browser entry from `tests/e2e/`.
- `SMARTCLOUD_QA_RUN_TRACE=1 scripts/qa/run_full_stack_validation.sh`
  Runs `deploy/docker-compose/trace-smoke.py`.
- `SMARTCLOUD_QA_RUN_COMPOSE=1 scripts/qa/run_full_stack_validation.sh`
  Runs `deploy/docker-compose/smoke-test.py` for the strongest compose-backed knowledge/rag/web-admin connector proof.

## Browser Prerequisites

```bash
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_require_playwright
npm --prefix tests/e2e run install:browsers
```

If the repo is on a fresh runner, install the app dependencies first:

```bash
npm --prefix apps/web-user ci
npm --prefix tests/e2e run install:browsers
```

## Release Gate

Use these commands before promoting the current QA baseline:

```bash
"${QA_PYTHON[@]}" scripts/qa/check_release_readiness.py
"${QA_PYTHON[@]}" scripts/qa/release_readiness.py --strict
```

`check_release_readiness.py` is the focused gate for current repo reality. It emits concrete pass/fail items for:

- key-service-assets-present
- owned-artifacts-present
- contracts-and-status-docs-present
- repo-browser-entry-present
- qa-runners-present
- shared-backend-acceptance-path-present
- runtime-backend-capability-matrix-green
- local-smoke-recorded
- repo-browser-validation-recorded
- knowledge-rag-local-restart-proof-recorded
- orchestrator-timeout-chain-local-proof-recorded
- live-auth-tooling-backend-proof-recorded
- live-orchestrator-timeout-chain-proof-recorded
- live-knowledge-rag-connector-rerun-recorded
- qa-reporting-consistent
- infra-persistence-live-proof
- live-marketing-minio-artifact-proof-recorded
- live-auth-and-orchestrator-backend-rerun-recorded

Its recorded-runtime checks now fail if `state.json` only contains a coarse pass flag without the expected structured backend evidence for the recorded restart and live-backend scenarios.
It now also fails if `docs/reviews/known-issues.md`, `docs/reviews/integration-qa-baseline.md`, or `docs/status/supervisor-integration-qa-status.md` drift from the live knowledge/rag scenario state recorded in `state.json`.
The current baseline keeps the blocking gate green while leaving the marketing MinIO artifact probe explicitly visible as a non-blocking failure until that service gap is closed.
