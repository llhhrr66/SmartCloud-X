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
if command -v uv >/dev/null 2>&1; then
  QA_PYTHON=(uv run "${UV_WITH[@]}" python)
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  QA_PYTHON=("$ROOT_DIR/.venv/bin/python")
fi

echo "[full-stack] running focused smoke baseline"
./scripts/qa/run_smoke.sh

echo "[full-stack] running service-process acceptance smoke"
"${QA_PYTHON[@]}" scripts/qa/project_smoke.py

if [[ "${SMARTCLOUD_QA_RUN_BROWSER:-0}" == "1" ]]; then
  if [[ ! -x "$ROOT_DIR/apps/web-user/node_modules/.bin/playwright" ]]; then
    echo "[full-stack] browser smoke requested but Playwright is missing under apps/web-user/node_modules"
    echo "[full-stack] run: npm --prefix apps/web-user ci && npm --prefix tests/e2e run install:browsers"
    exit 1
  fi
  echo "[full-stack] running repo browser smoke"
  npm --prefix tests/e2e run test:browser
else
  echo "[full-stack] skipping repo browser smoke (set SMARTCLOUD_QA_RUN_BROWSER=1 to enable)"
fi

if [[ "${SMARTCLOUD_QA_RUN_TRACE:-0}" == "1" ]]; then
  echo "[full-stack] running trace acceptance smoke"
  "${QA_PYTHON[@]}" deploy/docker-compose/trace-smoke.py
else
  echo "[full-stack] skipping trace acceptance smoke (set SMARTCLOUD_QA_RUN_TRACE=1 to enable)"
fi

if [[ "${SMARTCLOUD_QA_RUN_COMPOSE:-0}" == "1" ]]; then
  echo "[full-stack] running compose acceptance smoke"
  "${QA_PYTHON[@]}" deploy/docker-compose/smoke-test.py
else
  echo "[full-stack] skipping compose acceptance smoke (set SMARTCLOUD_QA_RUN_COMPOSE=1 to enable)"
fi

echo "[full-stack] running strict release readiness"
"${QA_PYTHON[@]}" scripts/qa/release_readiness.py --strict
