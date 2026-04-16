# Local Validation Runbook

## Purpose
Run the SmartCloud-X repo QA baseline from the `supervisor-integration-qa` ownership boundary without touching business implementation directories.

## Prerequisites
- working directory: `/home/ljr/SmartCloud-X`
- either `uv` is installed or `.venv/bin/python` already has the required QA dependencies
- for real browser smoke: `apps/web-user/node_modules` plus a Chromium install for the matching Playwright version

## Recommended Fast Path
```bash
scripts/qa/run_smoke.sh
```

That focused runner now performs four concrete steps against current repo reality:
1. compiles the QA-owned Python artifacts
2. runs focused pytest coverage for contract presence, service smoke, orchestrator behavior, error paths, cross-service auth/marketing/research, and root browser wiring
3. prints the itemized readiness JSON from `scripts/qa/check_release_readiness.py`
4. optionally runs browser/service-stack/trace/compose acceptance phases when the matching env flags are enabled

## Browser Entry
Run the real root Playwright smoke when the runner already has Playwright + Chromium available:

```bash
SMARTCLOUD_QA_RUN_BROWSER=1 scripts/qa/run_smoke.sh
```

If the browser runtime is missing, bootstrap it with:

```bash
npm --prefix apps/web-user ci
npm --prefix tests/e2e run install:browsers
```

## Optional Acceptance Layers
Subprocess service-stack smoke:

```bash
SMARTCLOUD_QA_RUN_STACK=1 scripts/qa/run_smoke.sh
```

Trace acceptance smoke:

```bash
SMARTCLOUD_QA_RUN_TRACE=1 scripts/qa/run_smoke.sh
```

Compose acceptance smoke:

```bash
SMARTCLOUD_QA_RUN_COMPOSE=1 scripts/qa/run_smoke.sh
```

All optional layers are already wired more comprehensively in the existing wrapper:

```bash
scripts/qa/run_full_stack_validation.sh
```

## Full Validation Wrapper
For the full repo-owned validation chain, use:

```bash
scripts/qa/run_local_validation.sh
```

That wrapper still covers:
- OpenAPI verification via `scripts/qa/verify_openapi_contracts.py`
- focused smoke via `scripts/qa/run_smoke.sh`
- subprocess/browser/trace/compose acceptance via `scripts/qa/run_full_stack_validation.sh`
- repo pytest via `pytest tests -q`
- strict release gating via `scripts/qa/release_readiness.py --strict`

## Manual Focused Commands
Compile the current QA baseline files:

```bash
uv run \
  --with fastapi \
  --with uvicorn \
  --with pydantic \
  --with httpx \
  --with prometheus-client \
  --with opentelemetry-api \
  --with opentelemetry-sdk \
  --with opentelemetry-exporter-otlp \
  --with opentelemetry-instrumentation-fastapi \
  --with pyyaml \
  --with jsonschema \
  --with pytest \
  python -m py_compile \
  scripts/qa/baseline_expectations.py \
  scripts/qa/check_release_readiness.py \
  scripts/qa/release_readiness.py \
  tests/e2e/test_ui_smoke.py \
  tests/integration/test_contract_presence.py \
  tests/integration/test_service_smoke.py
```

Run the focused pytest baseline:

```bash
uv run \
  --with fastapi \
  --with uvicorn \
  --with pydantic \
  --with httpx \
  --with prometheus-client \
  --with opentelemetry-api \
  --with opentelemetry-sdk \
  --with opentelemetry-exporter-otlp \
  --with opentelemetry-instrumentation-fastapi \
  --with pyyaml \
  --with jsonschema \
  --with pytest \
  pytest \
  tests/integration/test_contract_presence.py \
  tests/integration/test_service_smoke.py \
  tests/integration/test_orchestrator_smoke.py \
  tests/integration/test_error_path_smoke.py \
  tests/integration/test_auth_marketing_research_flow.py \
  tests/e2e/test_ui_smoke.py \
  -q
```

Print the focused readiness report:

```bash
uv run \
  --with fastapi \
  --with uvicorn \
  --with pydantic \
  --with httpx \
  --with prometheus-client \
  --with opentelemetry-api \
  --with opentelemetry-sdk \
  --with opentelemetry-exporter-otlp \
  --with opentelemetry-instrumentation-fastapi \
  --with pyyaml \
  --with jsonschema \
  --with pytest \
  python scripts/qa/check_release_readiness.py
```

## What The Baseline Verifies
### Current service and asset reality
- key auth/orchestrator/knowledge/rag service files remain present
- key web-user/frontend-sdk/browser assets remain present
- frozen contracts and supervisor status docs still exist
- QA-owned logs, runbooks, reviews, and status/state files remain in place

### Behavior-level smoke
- auth demo login and canonical invalid-password `401`
- orchestrator agent registry and billing auth-context follow-up path
- knowledge starter-catalog bootstrap plus GPU search hit
- RAG capabilities plus degraded upstream-health reporting
- cross-service auth token compatibility for marketing + research
- structured error-path coverage for `401`, `403`, `409`, tool timeout, permission denial, SSE replay/resume, and degraded/no-result RAG behavior
- root browser wiring plus optional real Playwright coverage for `401` refresh, route/citation `403`, SSE reconnect, and marketing `429`

## Failure Handling
- readiness/report failures: inspect the `failures` list from `scripts/qa/check_release_readiness.py`
- pytest failures: fix the specific QA artifact or surface drift before running wider acceptance again
- browser bootstrap failures: run the documented Playwright install commands and rerun with `SMARTCLOUD_QA_RUN_BROWSER=1`
- service-stack failures: inspect `scripts/qa/project_smoke.py` output and emitted per-service logs
