# Release Readiness Runbook

## Release Gate
A SmartCloud-X baseline is release-ready only when all of the following are true:

1. `scripts/qa/verify_openapi_contracts.py` passes.
2. `scripts/qa/run_full_stack_validation.sh` passes, with optional browser/trace/compose phases enabled when the release environment supports them.
3. `pytest tests -q` passes under the QA dependency set.
4. `scripts/qa/release_readiness.py --strict` passes.
5. `docs/reviews/known-issues.md` has no open `critical` or `high` issue.
6. `docs/status/supervisor-integration-qa-status.md` and `logs/supervisor-integration-qa/*` reflect the current run.

## Focused Readiness Interpretation
`scripts/qa/check_release_readiness.py` now emits a concrete `releaseChecklist` section:
- `key-service-assets-present`
- `owned-artifacts-present`
- `contracts-and-status-docs-present`
- `repo-browser-entry-present`
- `qa-runners-present`
- `shared-backend-acceptance-path-present`
- `infra-persistence-live-proof`
- `live-auth-and-orchestrator-backend-rerun-recorded`
- `live-knowledge-rag-connector-rerun-recorded`

Current reality in this run:
- all blocking checklist items pass
- `infra-persistence-live-proof` passes because the owned repo has coverage or proof paths for all tracked services
- `live-auth-and-orchestrator-backend-rerun-recorded` passes because recorded live shared-backend subprocess proof exists for `auth-marketing-research`, `business-tools-tool-hub`, and `orchestrator-billing`
- `live-knowledge-rag-connector-rerun-recorded` remains non-blocking and pending because the compose-backed connector stack was cold in this turn and did not finish bootstrapping

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
source scripts/qa/qa_env.sh
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
"${QA_PYTHON[@]}" scripts/qa/verify_openapi_contracts.py
scripts/qa/run_full_stack_validation.sh
"${QA_PYTEST[@]}" tests -q
"${QA_PYTHON[@]}" scripts/qa/release_readiness.py --strict
```

## Decision Rules
- contract failures: stop release work and align the implementation or frozen contracts before proceeding
- integration test failures: stop release work and fix the failing QA or service behavior before proceeding
- smoke failures: treat as blocking because they indicate live startup or cross-service drift
- medium/low known issues: document explicitly and decide whether to ship with accepted risk

## Current QA Scope
- API contract verification from the published OpenAPI files
- project-level pytest coverage for cross-service token compatibility, orchestrator stateful billing flow, orchestrator auth follow-up, orchestrator SSE replay/resume, tool-hub permission denial/timeout, and RAG degraded/no-result behavior
- restart-oriented persistence smoke for auth, marketing, and research
- degraded-backend-truth health assertions for orchestrator, tool-hub, and business-tools when local QA points at unreachable MySQL/Redis targets
- no-browser repo Playwright wiring smoke plus runnable root browser smoke for `401` refresh, route/citation `403`, SSE reconnect, and marketing `429`
- live subprocess smoke for the service stack owned across the repository, with compose-backed knowledge/rag connector proof remaining the current warm-up-sensitive acceptance layer

## Out of Scope
- UI regression for `web-admin`
- load/performance testing
- security scanning beyond the current starter auth/integration coverage
