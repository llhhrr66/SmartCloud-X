# Known Issues

| ID | Severity | Status | Area | Summary |
| --- | --- | --- | --- | --- |
| QA-001 | medium | open | orchestrator-timeout-chain | Repo QA covers tool-hub timeout behavior and an orchestrator timeout branch, but it still lacks a single full live-chain assertion that proves an orchestrator timeout all the way through tool-hub into downstream business-tools without monkeypatching. |
| QA-002 | medium | open | backend-rate-limit | The shipped backend services still do not expose one stable integration-friendly `429` route for repo smoke, so the highest-value `429` UX remains validated through the root/web-user Playwright mock API harness. |
| QA-003 | low | open | browser-root-entry-scope | The root `tests/e2e/` Playwright entry now runs a real browser subset, but wider browser coverage still lives primarily under `apps/web-user/tests/e2e/specs/` and the repo root does not yet add a comparable `web-admin` browser slice. |
| QA-004 | low | open | qa-environment | Fresh runners still need `apps/web-user` node modules plus a matching Chromium install before `SMARTCLOUD_QA_RUN_BROWSER=1 scripts/qa/run_smoke.sh` can pass. |
