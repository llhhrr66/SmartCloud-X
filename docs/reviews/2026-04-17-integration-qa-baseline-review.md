# Integration QA Baseline Review

## Findings
- No blocking defects were found in the owned QA diff after adding explicit checks for the compose-backed live infra surface and MinIO `19000/19001` host-port alignment.
- No blocking defects were found in the owned QA baseline after rerunning the focused expectations path, the release-readiness report, the infra persistence matrix, and the broader `scripts/qa/run_smoke.sh` baseline in this turn.
- Medium external: the strongest remaining live-backend gap is still QA-012. `marketingPosterObjectStored` remains false in the recorded MinIO-enabled live rerun even though the shared bucket itself is reachable.
- Medium: `auth-user-service`, `marketing-service`, and `research-service` still lack a frozen runtime backend evidence contract; see `docs/contracts/change-requests/2026-04-16-auth-marketing-research-runtime-backend-health-baseline.md`.
- Low: the repo-root browser package still depends on `apps/web-user` node modules and Playwright browsers being provisioned on the runner.

## Scope Reviewed
- `tests/`
- `scripts/qa/`
- `docs/runbooks/`
- `docs/reviews/`
- `docs/status/supervisor-integration-qa-status.md`
- `logs/supervisor-integration-qa/*`

## Validation Completed
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTEST[@]}" -q tests/integration/test_contract_presence.py tests/e2e/test_ui_smoke.py`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTHON[@]}" scripts/qa/check_release_readiness.py`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTHON[@]}" scripts/qa/infra_persistence_matrix.py`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && scripts/qa/run_smoke.sh`
- `git diff --check`

## Residual Risk
- Remaining repo-level gaps are tracked in `docs/reviews/known-issues.md`.
- The new compose/runbook/qa_env alignment guard proves the owned QA path matches current localhost defaults, but live release confidence still depends on the existing shared-backend reruns recorded in `logs/supervisor-integration-qa/state.json`.
- Release promotion still depends on live shared-backend landing proof, not only config-aware or degraded-fallback health evidence.
