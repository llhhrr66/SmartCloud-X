# Integration QA Baseline Review

## Findings
- No blocking defects were found after expanding the owned RAG fallback matrix across `retrieve`/`diagnose`/`answer` and adding the repo-root billing citation happy-path browser check.
- No blocking defects were found in the QA-owned baseline after rerunning the focused expectations checks plus the local and live orchestrator subprocess path in this turn.
- Medium external: live shared-backend proof remains pending only for the compose-backed `knowledge-rag-admin` path in this turn. The new orchestrator timeout-chain acceptance is green; the remaining blocker is the knowledge/rag connector stack.
- Medium: release-readiness and QA reporting docs had stale language around the orchestrator timeout-chain gap. The owned docs now reflect the newly recorded green state for the local and live timeout-chain path, plus the updated knowledge/rag blocker.
- Medium: `auth-user-service`, `marketing-service`, and `research-service` still lack a frozen runtime backend evidence contract; see `docs/contracts/change-requests/2026-04-16-auth-marketing-research-runtime-backend-health-baseline.md`.
- Medium external: `business-tools-tool-hub` still surfaces the existing tool-hub public-route `405` gap and frozen response drift tracked by change requests under `docs/contracts/change-requests/`.

## Scope Reviewed
- `tests/`
- `scripts/qa/`
- `docs/runbooks/`
- `docs/reviews/`
- `docs/status/supervisor-integration-qa-status.md`
- `logs/supervisor-integration-qa/*`

## Validation Completed
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTEST[@]}" -q tests/integration/test_error_path_smoke.py tests/integration/test_contract_presence.py tests/e2e/test_ui_smoke.py`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && smartcloud_qa_require_playwright && smartcloud_qa_configure_browser_ports && npm --prefix tests/e2e run test:browser`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTEST[@]}" -q tests/integration/test_contract_presence.py tests/e2e/test_ui_smoke.py`
- `git diff --check`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario orchestrator-billing`
- `docker compose -f deploy/docker-compose/docker-compose.yml up -d mysql redis`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario orchestrator-billing`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTEST[@]}" -q tests/integration/test_contract_presence.py tests/e2e/test_ui_smoke.py`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTHON[@]}" scripts/qa/check_release_readiness.py`
- `source scripts/qa/qa_env.sh && smartcloud_qa_init && smartcloud_qa_assert_python_runtime && "${QA_PYTHON[@]}" scripts/qa/infra_persistence_matrix.py`

## Residual Risk
- Remaining repo-level gaps are tracked in `docs/reviews/known-issues.md`.
- `business-tools-tool-hub` and the new orchestrator timeout-chain path are recorded green in live shared-backend mode, but `knowledge-rag-admin` still needs one completed compose-backed rerun on a warmed connector stack.
- Release promotion still depends on live shared-backend landing proof, not only config-aware or degraded-fallback health evidence.
