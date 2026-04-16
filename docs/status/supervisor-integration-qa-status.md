# Supervisor Integration QA Status

- Date: 2026-04-17
- Owner: `supervisor-integration-qa`
- Status: baseline revalidated; release readiness now blocks on the runtime-backend capability matrix, structured recorded runtime proof, QA reporting consistency, and shared-backend acceptance alignment, and live knowledge/rag connector proof is green; the current remaining live-backend gap is still the stronger marketing MinIO artifact check, where `marketingPosterObjectStored` fails even though the bucket is reachable

## Current Baseline

- focused baseline: `tests/integration/test_contract_presence.py`, `tests/integration/test_service_smoke.py`, `tests/integration/test_error_path_smoke.py`, `tests/integration/test_orchestrator_smoke.py`, `tests/integration/test_auth_marketing_research_flow.py`, and `tests/e2e/test_ui_smoke.py`
- root browser smoke: `tests/e2e/app-smoke.spec.ts`, `tests/e2e/playwright_smoke.spec.ts`, and `tests/e2e/test_browser_entry.spec.ts`
- default targeted service-process baseline: `scripts/qa/run_smoke.sh` runs `scripts/qa/project_smoke.py` for `auth-marketing-research` and `orchestrator-billing` by default
- broader service-process acceptance remains available for `knowledge-rag-admin` and `business-tools-tool-hub`
- live shared-backend acceptance is available through `SMARTCLOUD_QA_USE_LIVE_INFRA=1`
- shared-backend acceptance now also guards the compose-backed MySQL/Redis/MinIO/Qdrant/OpenSearch defaults and the MinIO `19000/19001` host-port mapping from owned QA paths
- infra persistence reporting is centralized in `scripts/qa/infra_persistence_matrix.py`
- readiness now reads structured runtime evidence from `logs/supervisor-integration-qa/state.json` for knowledge/rag restart, live shared-backend MySQL/Redis proof, live knowledge/rag connectors, and the local/live orchestrator timeout chain

## Latest Validation

- validated in this run: targeted self-review rerun passed `14` tests across `tests/integration/test_contract_presence.py` and `tests/e2e/test_ui_smoke.py`, `scripts/qa/check_release_readiness.py` stayed green at `120/120`, `scripts/qa/infra_persistence_matrix.py` stayed green at `26/26`, and `git diff --check` stayed clean for the owned QA diff
- validated in this run: `scripts/qa/run_smoke.sh` passed with `34` focused tests, readiness `120/120`, infra persistence `26/26`, and a green default targeted service-process baseline
- validated in this run: targeted self-review rerun passed `13` tests across `tests/integration/test_contract_presence.py` and `tests/e2e/test_ui_smoke.py`, `scripts/qa/check_release_readiness.py` stayed green at `118/118`, and `git diff --check` stayed clean for the owned QA diff
- validated in this run: `scripts/qa/run_smoke.sh` passed with `33` focused tests, readiness `118/118`, infra persistence `26/26`, and a green default targeted service-process baseline
- validated in this run: `SMARTCLOUD_QA_USE_LIVE_INFRA=1 "${QA_PYTHON[@]}" scripts/qa/project_smoke.py --scenario knowledge-rag-admin` passed and proved shared MySQL/Redis/MinIO/Qdrant/OpenSearch connector landing after restart
- validated in this run: the stronger live shared-backend rerun for `auth-marketing-research`, `business-tools-tool-hub`, and `orchestrator-billing` still fails on `marketingPosterObjectStored`; MySQL/Redis proof remains green, but the MinIO-backed marketing poster artifact is still missing
- validated previously in the latest browser rerun: repo-root Playwright stayed green at `10/10`

## Known Blocking Themes

- the strongest live shared-backend gap is now marketing poster artifact landing to MinIO, not `knowledge-rag-admin`
- frozen/shared contract support is still missing for the cross-service persistence matrix and for auth/marketing/research runtime backend evidence
