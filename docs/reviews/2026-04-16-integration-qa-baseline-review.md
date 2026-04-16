# Integration QA Baseline Review

## Findings
- No new blocking defect is currently known inside the owned QA files after this baseline upgrade.
- Fixed or refreshed during review:
  - expanded the repo asset matrix to include marketing, research, tool-hub, business-tools, web-admin, and admin OpenAPI coverage in addition to the earlier auth/orchestrator/knowledge/rag/web-user/frontend-sdk baseline
  - replaced the placeholder `tests/e2e/test_ui_smoke.py` with a real no-browser root Playwright wiring smoke and added it to `scripts/qa/run_smoke.sh`
  - upgraded `tests/integration/test_orchestrator_smoke.py` with behavior-level coverage for `collect-auth-context` on the marketing flow and SSE replay/resume via `Last-Event-ID`
  - upgraded `scripts/qa/check_release_readiness.py` so it emits itemized project-area readiness checklist items
  - refreshed runbooks, reviews, status, and supervisor logs/state so the reporting layer matches the upgraded QA baseline

## Scope Reviewed
- `tests/`
- `scripts/qa/`
- `docs/runbooks/`
- `docs/reviews/`
- `docs/status/supervisor-integration-qa-status.md`
- `logs/supervisor-integration-qa/*`

## Validation Completed
- `python3 -m py_compile scripts/qa/baseline_expectations.py scripts/qa/check_release_readiness.py scripts/qa/release_readiness.py tests/e2e/test_ui_smoke.py tests/integration/test_contract_presence.py tests/integration/test_service_smoke.py tests/integration/test_orchestrator_smoke.py`
- `bash -n scripts/qa/run_smoke.sh scripts/qa/run_full_stack_validation.sh scripts/qa/run_local_validation.sh`
- targeted `pytest` over `tests/e2e/test_ui_smoke.py`, `tests/integration/test_contract_presence.py`, `tests/integration/test_service_smoke.py`, `tests/integration/test_orchestrator_smoke.py`, and `tests/integration/test_error_path_smoke.py`
- `python3 scripts/qa/check_release_readiness.py`
- `scripts/qa/run_smoke.sh`

## Residual Risk
- Remaining non-blocking gaps are tracked in `docs/reviews/known-issues.md`.
