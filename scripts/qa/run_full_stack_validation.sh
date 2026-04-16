#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/qa_env.sh"
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
smartcloud_qa_configure_live_infra_env

cd "$ROOT_DIR"

echo "[full-stack] running focused smoke baseline without duplicate targeted service-process scenarios"
SMARTCLOUD_QA_RUN_SERVICE_PROCESS_BASELINE=0 ./scripts/qa/run_smoke.sh

echo "[full-stack] running service-process acceptance smoke"
"${QA_PYTHON[@]}" scripts/qa/project_smoke.py

if [[ "${SMARTCLOUD_QA_RUN_BROWSER:-0}" == "1" ]]; then
  smartcloud_qa_require_playwright
  smartcloud_qa_configure_browser_ports
  echo "[full-stack] running repo browser smoke"
  echo "[full-stack] root browser ports: app=${QA_BROWSER_APP_PORT} api=${QA_BROWSER_API_PORT}"
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
