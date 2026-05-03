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
- status-doc and QA-owned artifact presence checks, including `logs/supervisor-integration-qa/*`
- local restart persistence smoke for auth, marketing, research, knowledge, rag, tool-hub/business-tools, and orchestrator timeout-chain behavior
- repo-root browser smoke covering dashboard bootstrap, billing citation happy path, reload persistence in marketing/research, reload-safe billing `401` refresh recovery, route/citation `403`, SSE reconnect, `429`, and research report gaps
- cross-platform repo-root browser startup on Windows via QA-owned Node wrappers plus loopback `NO_PROXY/no_proxy` handling
- shell-only live override evidence refresh against `45.207.220.216` without changing repo defaults; `SMARTCLOUD_QA_USE_LIVE_INFRA=1` remains the contract switch
- runtime backend helper and matrix coverage through `scripts/qa/infra_persistence_matrix.py`

## Latest Validation

- `2026-04-17T16:28:28+08:00`: `scripts/qa/infra_persistence_matrix.py` passed `26/26`
- `2026-04-17T16:27:53+08:00`: repo-root Playwright passed `10/10`
- `2026-04-17T16:27:05+08:00`: local `orchestrator-billing` subprocess smoke passed
- `2026-04-17T16:25:30+08:00`: local `business-tools-tool-hub` subprocess smoke passed
- `2026-04-17T16:24:02+08:00`: local `knowledge-rag-admin` subprocess smoke passed
- `2026-04-17T16:23:47+08:00`: local `auth-marketing-research` subprocess smoke passed
- `2026-04-17T16:28:28+08:00` to `2026-04-17T16:31:44+08:00`: shell-only live override `auth-marketing-research`, `knowledge-rag-admin`, `business-tools-tool-hub`, and `orchestrator-billing` all passed against `45.207.220.216`

## Current Gaps

- no active repo-root browser gap remains in the current baseline; both `web-user` and `web-admin` now have repo-level Playwright entry coverage

## Intended Use

- use `scripts/qa/run_smoke.sh` for the fast baseline
- use `scripts/qa/project_smoke.py --scenario auth-marketing-research`, `--scenario knowledge-rag-admin`, `--scenario business-tools-tool-hub`, and `--scenario orchestrator-billing` for current local subprocess proof
- use shell-only live overrides when localhost compose-backed infra is unavailable but you need to refresh current live evidence without changing repo defaults
- use `scripts/qa/infra_persistence_matrix.py` and `scripts/qa/check_release_readiness.py` when deciding whether the current build is ready to move beyond QA
