# Supervisor Integration QA Status

- Date: 2026-04-24
- Owner: `supervisor-integration-qa`
- Status: **live knowledge/rag connector proof is green; gateway acceptance is green; strict release gate is green; current repository evidence now shows both the runtime acceptance path and the strict release gate passing. SiliconFlow live cutover is not part of the currently passed gate evidence and has not been independently confirmed as active in the running knowledge-service.**

## Reused evidence baseline

The following evidence remains valid and is not restated as new execution output in this document:

- focused baseline remains `tests/integration/test_contract_presence.py`, `tests/integration/test_service_smoke.py`, `tests/integration/test_error_path_smoke.py`, `tests/integration/test_orchestrator_smoke.py`, `tests/integration/test_auth_marketing_research_flow.py`, and `tests/e2e/test_ui_smoke.py`
- repo-root browser smoke remains `tests/e2e/app-smoke.spec.ts`, `tests/e2e/playwright_smoke.spec.ts`, and `tests/e2e/test_browser_entry.spec.ts`
- the default targeted service-process baseline is green in local mode
- `scripts/qa/qa_env.sh` exports loopback `NO_PROXY/no_proxy` and defaults `SMARTCLOUD_QA_REQUEST_TIMEOUT_SECONDS=30`
- the official repo-owned live QA contract remains localhost/compose-backed through `scripts/qa/qa_env.sh`
- prior shell-only override evidence against `45.207.220.216` remains a useful live environment datapoint, but it does not override repo strict gate rules

## Previously validated checks still reusable

- repo-root Playwright passed `10/10`
- `tests/e2e/test_ui_smoke.py` passed `5/5`
- `tests/integration/test_service_smoke.py` passed `8/8`
- `scripts/qa/infra_persistence_matrix.py` passed `26/26`
- local `auth-marketing-research`, `knowledge-rag-admin`, `business-tools-tool-hub`, and `orchestrator-billing` subprocess smoke all passed
- shell-only override live `auth-marketing-research` passed against `45.207.220.216`
- shell-only override live `knowledge-rag-admin` passed against `45.207.220.216`
- shell-only override live `business-tools-tool-hub` passed against `45.207.220.216`
- shell-only override live `orchestrator-billing` passed against `45.207.220.216`
- Round 9 `gateway_acceptance_probe.py` passed `23/23`
- Round 11 `.venv/bin/python scripts/qa/release_readiness.py --strict` passed with `ok=true`, `missingArtifacts=[]`, `focusedReadiness.ok=true`, `focusedReadiness.blockingFailures=[]`, `infraPersistence.summary.failed=0`, and `blockingKnownIssues=[]`

## Current gate mapping

This document must align to the repository gate scripts rather than earlier narrative summaries:

- `scripts/qa/run_full_stack_validation.sh` explicitly runs focused smoke, default targeted service-process baseline, optional compose/trace/browser phases, gateway acceptance, and then `scripts/qa/release_readiness.py --strict`
- `scripts/qa/release_readiness.py --strict` fails when `docs/reviews/known-issues.md` contains any `critical/high` issue in `open` or `accepted-risk`
- therefore a green subset of QA evidence does **not** equal release-ready unless the strict-gate inputs are also green at rerun time
- current recorded repository evidence now includes both a green gateway acceptance run and a green strict-gate rerun

## Current issue posture

- reusable QA evidence exists for focused baseline, root browser smoke, infra persistence, and live shared-backend checks
- `knowledge-rag-admin` remains passed in `logs/supervisor-integration-qa/state.json`, so live knowledge/rag connector proof is green
- Round 9 confirmed `gateway_acceptance_probe.py` passed `23/23`
- Round 11 confirmed `.venv/bin/python scripts/qa/release_readiness.py --strict` passed with `blockingKnownIssues=[]`, `missingArtifacts=[]`, `focusedReadiness.ok=true`, `focusedReadiness.blockingFailures=[]`, and `infraPersistence.summary.failed=0`
- the earlier `qa-reporting-consistent` document-alignment blocker has been cleared by the successful Round 11 strict rerun

## SiliconFlow supplemental validation posture

The embedding-provider follow-up must be tracked separately from the formal repository gate:

- `docs/status/supervisor-siliconflow-embedding-status.md` is the stable repository-owned evidence anchor for the SiliconFlow / embedding-provider follow-up
- that document confirms the codebase has an OpenAI-compatible embedding integration path for `knowledge-service`
- that same document records that the current running `knowledge-service` live instance was **not** independently re-verified as switched to SiliconFlow `BAAI/bge-m3`
- the retained live rerun conclusion found `SMARTCLOUD_EMBEDDING_PROVIDER`, `SMARTCLOUD_EMBEDDING_API_URL`, `SMARTCLOUD_EMBEDDING_API_KEY`, and `SMARTCLOUD_EMBEDDING_MODEL` unset in the running container
- the same retained conclusion found `/api/knowledge/v1/embedding:test` returning `provider=HashEmbeddingProvider`, `configuredProvider=hash-baseline`, and `dimensions=32`

Interpretation:

- the repository currently has passing release-gate evidence
- the repository also currently lacks independently confirmed proof that the running live `knowledge-service` has been cut over to SiliconFlow
- these are not contradictory facts, because SiliconFlow live cutover was not the condition that turned the recorded Round 9 / Round 11 gates green

## Current release blockers

- no active strict blocker is currently evidenced in `docs/reviews/known-issues.md`
- no active `qa-reporting-consistent` blocker remains in the latest strict rerun
- no current repository gate blocker is created solely by the unresolved SiliconFlow live cutover, because the passed gate evidence was recorded without claiming that cutover as complete
- this document should not describe the repository as waiting on a follow-up strict rerun, because that rerun has already passed

## Repository-accurate conclusion

- QA evidence quality: **green and reusable for the validated paths**
- live knowledge/rag connector proof: **green and aligned with `logs/supervisor-integration-qa/state.json`**
- gateway acceptance: **green (`23/23` in Round 9)**
- strict release gate: **green (`ok=true` in Round 11)**
- SiliconFlow code-path readiness: **implemented in code, but current running live cutover remains unverified / not completed**
- SiliconFlow running live status: **not switched according to the independent rerun evidence**
- known-issues strict blocker posture: **aligned / cleared at document level and confirmed by script output**
- source of truth: **script outputs and runtime evidence first; status prose must follow those results**
