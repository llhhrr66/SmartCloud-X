#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/qa_env.sh"
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
smartcloud_qa_configure_live_infra_env

cd "$ROOT_DIR"

run_step() {
  local label="$1"
  shift
  echo "[full-stack] running ${label}"
  "$@"
}

run_step "focused smoke baseline without duplicate targeted service-process scenarios" \
  env SMARTCLOUD_QA_RUN_SERVICE_PROCESS_BASELINE=0 bash scripts/qa/run_smoke.sh

run_step "service-process acceptance smoke" \
  "${QA_PYTHON[@]}" scripts/qa/project_smoke.py

if [[ "${SMARTCLOUD_QA_RUN_COMPOSE:-0}" == "1" ]]; then
  run_step "compose acceptance smoke" \
    "${QA_PYTHON[@]}" deploy/docker-compose/smoke-test.py
else
  echo "[full-stack] skipping compose acceptance smoke (set SMARTCLOUD_QA_RUN_COMPOSE=1 to enable)"
fi

if [[ "${SMARTCLOUD_QA_RUN_TRACE:-0}" == "1" ]]; then
  run_step "trace acceptance smoke" \
    "${QA_PYTHON[@]}" deploy/docker-compose/trace-smoke.py
else
  echo "[full-stack] skipping trace acceptance smoke (set SMARTCLOUD_QA_RUN_TRACE=1 to enable)"
fi

if [[ "${SMARTCLOUD_QA_RUN_GATEWAY_ACCEPTANCE:-1}" == "1" ]]; then
  smartcloud_qa_require_gateway_acceptance_credentials
  run_step "gateway acceptance probe" \
    "${QA_PYTHON[@]}" scripts/qa/gateway_acceptance_probe.py \
      --base-url "${SMARTCLOUD_QA_GATEWAY_BASE_URL:-http://127.0.0.1:8000}" \
      --timeout "${SMARTCLOUD_QA_GATEWAY_TIMEOUT_SECONDS:-10}"
else
  echo "[full-stack] skipping gateway acceptance probe (set SMARTCLOUD_QA_RUN_GATEWAY_ACCEPTANCE=0 to disable)"
fi

if [[ "${SMARTCLOUD_QA_RUN_BROWSER:-0}" == "1" ]]; then
  smartcloud_qa_require_playwright
  smartcloud_qa_configure_browser_ports
  echo "[full-stack] running repo browser smoke"
  echo "[full-stack] root browser ports: app=${QA_BROWSER_APP_PORT} api=${QA_BROWSER_API_PORT} admin=${QA_BROWSER_ADMIN_PORT}"
  npm --prefix tests/e2e run test:browser
else
  echo "[full-stack] skipping repo browser smoke (set SMARTCLOUD_QA_RUN_BROWSER=1 to enable)"
fi

run_step "strict release readiness" \
  "${QA_PYTHON[@]}" scripts/qa/release_readiness.py --strict
