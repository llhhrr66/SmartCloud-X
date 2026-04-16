# Integration QA Baseline

## Goal
Keep a practical, runnable integration/QA baseline for the whole SmartCloud-X workspace while staying inside QA-owned paths.

## Current SmartCloud-X Reality Covered
### Service and asset presence
- auth: `apps/auth-user-service/`, OpenAPI, local demo auth routes
- orchestrator: `apps/orchestrator-service/`, route/runtime/state services, published OpenAPI
- knowledge: `apps/knowledge-service/`, starter catalog, public/admin routes, published OpenAPI
- rag: `apps/rag-service/`, retrieval/answer services, published OpenAPI
- web-user: package manifest, chat/runtime-config assets, browser mock API harness
- frontend-sdk: package manifest, core/web-user/web-admin exports, web-user shared-sdk bridge
- status docs: all supervisor status files under `docs/status/`
- frozen contracts: shared contract baseline still present under `docs/contracts/`

## QA Assets Added Or Refreshed In This Run
- `tests/integration/test_service_smoke.py`
- `tests/integration/test_contract_presence.py`
- `tests/e2e/test_browser_entry.spec.ts`
- `scripts/qa/run_smoke.sh`
- `scripts/qa/check_release_readiness.py`
- `docs/runbooks/local-validation.md`
- `docs/reviews/integration-qa-baseline.md`
- `docs/reviews/known-issues.md`
- `docs/status/supervisor-integration-qa-status.md`
- `logs/supervisor-integration-qa/progress.log`
- `logs/supervisor-integration-qa/blockers.log`
- `logs/supervisor-integration-qa/decisions.log`
- `logs/supervisor-integration-qa/state.json`

## Focused Coverage Now In Place
### Integration pytest smoke
- auth demo login still returns tokens and `user:chat.use`
- auth invalid password still returns canonical `4010002`
- orchestrator agent registry still exposes product / finance / ICP / marketing / research agents and starter tool bindings
- orchestrator billing flow still pauses with `collect-auth-context` when account context or permission is missing
- knowledge starter catalog can bootstrap into a temp runtime store and answer a GPU search
- rag capabilities still advertise keyword rewrite + knowledge-service retrieval, and `/healthz` still reports degraded upstream state when knowledge is unavailable
- web-user/frontend-sdk package and shared-sdk bridge assets remain aligned to the current repo layout
- cross-service auth/marketing/research flow remains covered in `tests/integration/test_auth_marketing_research_flow.py`
- higher-value behavior/error coverage remains in `tests/integration/test_error_path_smoke.py` and `tests/integration/test_orchestrator_smoke.py`

### Root browser E2E entry
The repo-level Playwright entry under `tests/e2e/test_browser_entry.spec.ts` now provides a real runnable browser subset for:
- one-time `401` refresh recovery on billing bootstrap
- route-level permission denial for `limited_marketing`
- SSE interruption plus reconnect on chat
- citation-detail `403` UX
- structured marketing `429` UX

### Release readiness
- `scripts/qa/check_release_readiness.py` emits an itemized pass/fail checklist from the shared baseline expectation matrix
- `scripts/qa/run_smoke.sh` compiles QA files, runs focused pytest coverage, prints readiness JSON, and can optionally run browser / service-stack / trace / compose acceptance phases
- the existing `scripts/qa/run_full_stack_validation.sh` remains the heavier stack wrapper for subprocess/browser/trace/compose validation

## Self-review
- changes stayed inside `tests/`, `scripts/qa/`, `docs/runbooks/`, `docs/reviews/`, `docs/status/`, and `logs/`
- no business implementation directory was modified
- reused the existing `tests.qa_helpers.service_loader` harness instead of introducing new non-repo test plumbing
- aligned the smoke and readiness checks to actual current paths and browser wiring already present in the workspace

## Validation Performed In This Run
- `uv run --with fastapi --with uvicorn --with pydantic --with httpx --with prometheus-client --with opentelemetry-api --with opentelemetry-sdk --with opentelemetry-exporter-otlp --with opentelemetry-instrumentation-fastapi --with pyyaml --with jsonschema --with pytest python -m py_compile scripts/qa/baseline_expectations.py scripts/qa/check_release_readiness.py scripts/qa/release_readiness.py tests/e2e/test_ui_smoke.py tests/integration/test_contract_presence.py tests/integration/test_service_smoke.py tests/integration/test_orchestrator_smoke.py tests/integration/test_error_path_smoke.py tests/integration/test_auth_marketing_research_flow.py`
- `bash -n scripts/qa/run_smoke.sh scripts/qa/run_full_stack_validation.sh scripts/qa/run_local_validation.sh`
- focused pytest over `tests/integration/test_contract_presence.py`, `tests/integration/test_service_smoke.py`, `tests/integration/test_orchestrator_smoke.py`, `tests/integration/test_error_path_smoke.py`, `tests/integration/test_auth_marketing_research_flow.py`, and `tests/e2e/test_ui_smoke.py`
- `python3 scripts/qa/check_release_readiness.py`
- `scripts/qa/run_smoke.sh`
- optional root Playwright smoke can be executed with `SMARTCLOUD_QA_RUN_BROWSER=1 scripts/qa/run_smoke.sh`

## Blockers And Follow-ups
- no new frozen-contract blocker was discovered in this QA pass, so no additional change request was required
- remaining non-blocking QA gaps are tracked in `docs/reviews/known-issues.md`
