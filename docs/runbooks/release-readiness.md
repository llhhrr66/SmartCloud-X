# Release Readiness Runbook

## Release Gate
A SmartCloud-X baseline is release-ready only when all of the following are true:

1. `scripts/qa/verify_openapi_contracts.py` passes.
2. `scripts/qa/run_full_stack_validation.sh` passes, with optional browser/trace/compose phases enabled when the release environment supports them.
3. `pytest tests -q` passes under the QA dependency set.
4. `scripts/qa/release_readiness.py --strict` passes.
5. `docs/reviews/known-issues.md` has no open `critical` or `high` issue.
6. `docs/status/supervisor-integration-qa-status.md` and `logs/supervisor-integration-qa/*` reflect the current run.

## Minimum Evidence
- OpenAPI summary output saved from `scripts/qa/verify_openapi_contracts.py`
- smoke/readiness output from `scripts/qa/run_full_stack_validation.sh`
- pytest result for `tests/`
- itemized readiness JSON from `scripts/qa/check_release_readiness.py`
- strict release JSON summary from `scripts/qa/release_readiness.py --strict`
- updated status and review docs

## Recommended Sequence
```bash
scripts/qa/run_local_validation.sh
```

If the full wrapper is not used, run:

```bash
python scripts/qa/verify_openapi_contracts.py
scripts/qa/run_full_stack_validation.sh
pytest tests -q
python scripts/qa/release_readiness.py --strict
```

Use the `uv run --with ...` form from the local validation runbook when the host Python environment does not already contain the required packages.

## Decision Rules
- contract failures: stop release work and align the implementation or frozen contracts before proceeding
- integration test failures: stop release work and fix the failing QA or service behavior before proceeding
- smoke failures: treat as blocking because they indicate live startup or cross-service drift
- medium/low known issues: document explicitly and decide whether to ship with accepted risk

## Current QA Scope
- API contract verification from the published OpenAPI files
- project-level pytest coverage for cross-service token compatibility, orchestrator stateful billing flow, orchestrator auth follow-up, orchestrator SSE replay/resume, tool-hub permission denial/timeout, and RAG degraded/no-result behavior
- no-browser repo Playwright wiring smoke plus optional runnable root browser smoke for `401` refresh, route/citation `403`, SSE reconnect, and marketing `429`
- live subprocess smoke for the service stack owned across the repository

## Out of Scope
- UI regression for `web-admin`
- load/performance testing
- security scanning beyond the current starter auth/integration coverage
