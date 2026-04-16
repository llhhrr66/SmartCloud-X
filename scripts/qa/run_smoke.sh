#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

UV_WITH=(
  --with fastapi
  --with uvicorn
  --with pydantic
  --with httpx
  --with prometheus-client
  --with opentelemetry-api
  --with opentelemetry-sdk
  --with opentelemetry-exporter-otlp
  --with opentelemetry-instrumentation-fastapi
  --with pyyaml
  --with jsonschema
  --with pytest
)

QA_PYTHON=(python3)
QA_PYTEST=(python3 -m pytest)
if command -v uv >/dev/null 2>&1; then
  QA_PYTHON=(uv run "${UV_WITH[@]}" python)
  QA_PYTEST=(uv run "${UV_WITH[@]}" pytest)
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  QA_PYTHON=("$ROOT_DIR/.venv/bin/python")
  QA_PYTEST=("$ROOT_DIR/.venv/bin/python" -m pytest)
fi

printf '==> Compiling QA-owned baseline artifacts\n'
"${QA_PYTHON[@]}" -m py_compile \
  scripts/qa/baseline_expectations.py \
  scripts/qa/check_release_readiness.py \
  scripts/qa/release_readiness.py \
  tests/e2e/test_ui_smoke.py \
  tests/integration/test_contract_presence.py \
  tests/integration/test_service_smoke.py \
  tests/integration/test_orchestrator_smoke.py \
  tests/integration/test_error_path_smoke.py \
  tests/integration/test_auth_marketing_research_flow.py

printf '==> Running focused integration/browser-wiring baseline\n'
"${QA_PYTEST[@]}" \
  tests/integration/test_contract_presence.py \
  tests/integration/test_service_smoke.py \
  tests/integration/test_orchestrator_smoke.py \
  tests/integration/test_error_path_smoke.py \
  tests/integration/test_auth_marketing_research_flow.py \
  tests/e2e/test_ui_smoke.py \
  -q

printf '==> Running release-readiness checklist\n'
"${QA_PYTHON[@]}" scripts/qa/check_release_readiness.py

if [[ "${SMARTCLOUD_QA_RUN_BROWSER:-0}" == "1" ]]; then
  if [[ ! -x "$ROOT_DIR/apps/web-user/node_modules/.bin/playwright" ]]; then
    echo '[qa-smoke] browser smoke requested but Playwright is missing under apps/web-user/node_modules'
    echo '[qa-smoke] run: npm --prefix apps/web-user ci && npm --prefix tests/e2e run install:browsers'
    exit 1
  fi
  printf '==> Running root Playwright browser smoke\n'
  npm --prefix tests/e2e run test:browser
else
  echo '[qa-smoke] skipping root Playwright browser smoke (set SMARTCLOUD_QA_RUN_BROWSER=1 to enable)'
fi

if [[ "${SMARTCLOUD_QA_RUN_STACK:-0}" == "1" ]]; then
  printf '==> Running subprocess service-stack smoke via project_smoke.py\n'
  "${QA_PYTHON[@]}" scripts/qa/project_smoke.py
else
  echo '[qa-smoke] skipping subprocess service-stack smoke (set SMARTCLOUD_QA_RUN_STACK=1 to enable)'
fi

if [[ "${SMARTCLOUD_QA_RUN_TRACE:-0}" == "1" ]]; then
  printf '==> Running trace acceptance smoke\n'
  "${QA_PYTHON[@]}" deploy/docker-compose/trace-smoke.py
else
  echo '[qa-smoke] skipping trace smoke (set SMARTCLOUD_QA_RUN_TRACE=1 to enable)'
fi

if [[ "${SMARTCLOUD_QA_RUN_COMPOSE:-0}" == "1" ]]; then
  printf '==> Running compose acceptance smoke\n'
  "${QA_PYTHON[@]}" deploy/docker-compose/smoke-test.py
else
  echo '[qa-smoke] skipping compose smoke (set SMARTCLOUD_QA_RUN_COMPOSE=1 to enable)'
fi

echo '[qa-smoke] baseline complete'
