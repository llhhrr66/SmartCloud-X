# Supervisor Integration QA Status

## Status
- phase: baseline validated
- updated at: 2026-04-16T16:00:00+08:00
- owned scope: `tests/`, `scripts/qa/`, `docs/runbooks/`, `docs/reviews/`

## Completed
- restored `tests/integration/test_service_smoke.py` as a real SmartCloud-X smoke suite covering auth, orchestrator, knowledge, rag, web-user, and frontend-sdk reality
- restored `tests/integration/test_contract_presence.py` as a real repo/readiness check over current service assets, frozen contracts, status docs, and shared observations
- replaced the placeholder root browser entry with a real Playwright subset at `tests/e2e/test_browser_entry.spec.ts`
- restored `scripts/qa/run_smoke.sh` and `scripts/qa/check_release_readiness.py` so the QA surface is executable again
- refreshed local validation, review, status, and logging artifacts to match the current repo QA baseline

## Validation
- compile review via `python -m py_compile` on the refreshed QA Python files
- shell syntax review via `bash -n` on `scripts/qa/run_smoke.sh`, `scripts/qa/run_full_stack_validation.sh`, and `scripts/qa/run_local_validation.sh`
- focused pytest over contract presence, service smoke, orchestrator smoke, error-path smoke, auth/marketing/research flow, and root browser wiring
- readiness JSON via `scripts/qa/check_release_readiness.py`
- focused baseline via `scripts/qa/run_smoke.sh`

## Blockers / Risks
- no active blocker remains inside owned QA paths
- repo-wide `429` coverage is still mock-harness backed because the live backend stack does not yet expose one stable integration-friendly rate-limit route
- a fully live orchestrator timeout chain assertion is still a medium-gap follow-up; current coverage mixes live tool-hub timeout validation with orchestrator-level timeout simulation
- real root Playwright smoke still depends on preinstalled `apps/web-user` node modules and Chromium on the runner

## Next Steps
- extend repo-owned behavior checks toward a live full-chain orchestrator timeout assertion
- keep the root browser subset small but runnable while broader browser coverage remains in `apps/web-user/tests/e2e/specs/`
- continue using `scripts/qa/run_full_stack_validation.sh` for heavier subprocess/browser/trace/compose acceptance when the environment supports it
