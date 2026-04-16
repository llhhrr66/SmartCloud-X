# Known Issues

Last validated: 2026-04-17T00:16:53+08:00 by `supervisor-integration-qa`.

| ID | Severity | Status | Area | Summary |
| --- | --- | --- | --- | --- |
| QA-001 | medium | resolved | orchestrator-timeout-chain | Owned subprocess QA now drives a real orchestrator -> tool-hub -> business-tools timeout chain in both local mode and `SMARTCLOUD_QA_USE_LIVE_INFRA=1`, preserving `status=timeout` plus MySQL-backed timeout audit/state evidence when shared backends are up. |
| QA-002 | low | open | backend-rate-limit | Structured `429` handling is covered in owned smoke, but the repo still lacks one stable live integration-friendly backend `429` route outside the controlled QA harness. |
| QA-003 | low | open | browser-root-entry-scope | The repo-root `tests/e2e` package covers dashboard/session smoke, billing citation happy path, marketing/research reload persistence, billing refresh-plus-reload recovery, route/citation denial, rate limit, SSE reconnect, and research report preview errors, but it still lacks a comparable `web-admin` slice and remains smaller than app-local browser suites. |
| QA-004 | low | open | qa-environment | Fresh runners still need `apps/web-user` node modules plus a Chromium install before repo-root browser smoke can run; Python-side QA should go through `scripts/qa/qa_env.sh` instead of assuming bare `python` or standalone `pytest` on `PATH`. |
| QA-005 | medium | resolved | knowledge-rag-admin | The isolated `knowledge-rag-admin` subprocess path passes in local-runtime mode and revalidates admin document detail, snapshot retention, search, and diagnostics after restarting both services. |
| QA-006 | medium | resolved | business-tools-tool-hub | `business-tools-tool-hub` passes in both local fallback mode and `SMARTCLOUD_QA_USE_LIVE_INFRA=1` shared-backend mode while still surfacing external drift notes. |
| QA-007 | medium | open | persistence-contract-matrix | Shared frozen contracts still do not define one cross-service persistence/backend matrix, so QA continues to rely on `docs/contracts/change-requests/2026-04-16-persistence-backend-contract-baseline.md`. |
| QA-008 | medium | resolved | knowledge-live-connector-proof | Live `knowledge-rag-admin` connector proof is now green against compose-backed MySQL/Redis/MinIO/Qdrant/OpenSearch. QA recorded structured shared-connector evidence after restart in `logs/supervisor-integration-qa/state.json`. |
| QA-009 | low | open | tool-hub-public-call-route | Public `POST /api/v1/tools/call` still returns `405`, so the subprocess QA path falls back to `/internal/v1/tools/call`. |
| QA-010 | medium | open | tool-hub-frozen-response-drift | Existing tool-hub change requests still track live response drift around direct invoke metadata and audit `status=completed` output. |
| QA-011 | medium | open | runtime-health-evidence | `auth-user-service`, `marketing-service`, and `research-service` still lack a canonical runtime backend evidence contract on health/snapshot surfaces; track `docs/contracts/change-requests/2026-04-16-auth-marketing-research-runtime-backend-health-baseline.md`. |
| QA-012 | medium | open | marketing-live-minio-artifact-proof | The stronger live `auth-marketing-research` rerun reaches MySQL/Redis successfully, but `marketingPosterObjectStored` is still false: the MinIO bucket is reachable at `http://127.0.0.1:19000` and already contains knowledge objects, yet the expected `{task_id}.png` poster object does not land. |

## Notes
- The owned QA baseline now explicitly checks the compose-backed live infra surface plus the MinIO `19000/19001` host-port mapping across `deploy/docker-compose/docker-compose.yml`, `scripts/qa/qa_env.sh`, and `docs/runbooks/local-validation.md`.
- `SMARTCLOUD_QA_USE_LIVE_INFRA=1` remains the owned switch for shared-backend subprocess QA against localhost MySQL/Redis/MinIO/Qdrant/OpenSearch defaults.
- `scripts/qa/project_smoke.py --scenario knowledge-rag-admin` now proves shared MySQL/Redis/MinIO/Qdrant/OpenSearch landing plus restart retention from QA-owned paths only.
- `scripts/qa/project_smoke.py --scenario auth-marketing-research --scenario business-tools-tool-hub --scenario orchestrator-billing` still passes for MySQL/Redis-backed persistence when shared MinIO vars are cleared.
- The stronger MinIO-enabled rerun exposed QA-012: the bucket itself is healthy, but marketing poster objects are still missing after task completion.
- `scripts/qa/check_release_readiness.py` now treats live knowledge/rag connector proof as blocking recorded runtime evidence and keeps the marketing MinIO artifact probe visible as a separate non-blocking item.
- repo-root Playwright remains green at `10/10` in the latest rerun already recorded in QA docs; no new browser regression was introduced in this turn.
- the latest fast smoke rerun passed `34` focused tests with readiness `120/120` and infra persistence `26/26`.
- the supported Python runner contract is still `scripts/qa/qa_env.sh`; bare `python` and standalone `pytest` are not assumed on `PATH`.
