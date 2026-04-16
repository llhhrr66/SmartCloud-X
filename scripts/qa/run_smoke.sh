#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$REPO_ROOT/scripts/qa/qa_env.sh"
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
smartcloud_qa_configure_live_infra_env
smartcloud_qa_configure_browser_ports

cd "$REPO_ROOT"

echo "[smoke] validating owned QA shell entrypoints with bash -n"
bash -n scripts/qa/qa_env.sh
bash -n scripts/qa/run_smoke.sh
bash -n scripts/qa/run_full_stack_validation.sh
bash -n scripts/qa/run_local_validation.sh

echo "[smoke] running focused pytest baseline"
"${QA_PYTEST[@]}" -q \
  tests/integration/test_contract_presence.py \
  tests/integration/test_service_smoke.py \
  tests/integration/test_error_path_smoke.py \
  tests/integration/test_orchestrator_smoke.py \
  tests/integration/test_auth_marketing_research_flow.py \
  tests/e2e/test_ui_smoke.py

echo "[smoke] focused readiness snapshot"
"${QA_PYTHON[@]}" scripts/qa/check_release_readiness.py

echo "[smoke] infra persistence snapshot"
"${QA_PYTHON[@]}" scripts/qa/infra_persistence_matrix.py

if [[ "${SMARTCLOUD_QA_RUN_SERVICE_PROCESS_BASELINE:-1}" == "1" ]]; then
  echo "[smoke] running default targeted service-process baseline: auth-marketing-research + orchestrator-billing"
  "${QA_PYTHON[@]}" scripts/qa/project_smoke.py \
    --scenario auth-marketing-research \
    --scenario orchestrator-billing
else
  echo "[smoke] skipping default targeted service-process baseline (set SMARTCLOUD_QA_RUN_SERVICE_PROCESS_BASELINE=1 to enable)"
fi

if [[ "${SMARTCLOUD_QA_RUN_STACK:-0}" == "1" ]]; then
  echo "[smoke] running broader service-process stack: knowledge-rag-admin + business-tools-tool-hub + orchestrator-billing + auth-marketing-research"
  "${QA_PYTHON[@]}" scripts/qa/project_smoke.py \
    --scenario auth-marketing-research \
    --scenario knowledge-rag-admin \
    --scenario business-tools-tool-hub \
    --scenario orchestrator-billing
else
  echo "[smoke] skipping broader stack acceptance (set SMARTCLOUD_QA_RUN_STACK=1 or use scripts/qa/run_full_stack_validation.sh)"
fi

if [[ "${SMARTCLOUD_QA_RUN_BROWSER:-0}" == "1" ]]; then
  smartcloud_qa_require_playwright
  echo "[smoke] running root browser smoke with QA_BROWSER_APP_PORT=${QA_BROWSER_APP_PORT} QA_BROWSER_API_PORT=${QA_BROWSER_API_PORT}"
  npm --prefix tests/e2e run test:browser
else
  echo "[smoke] skipping root browser smoke (set SMARTCLOUD_QA_RUN_BROWSER=1; full wrapper: scripts/qa/run_full_stack_validation.sh)"
fi

echo "[smoke] local wrapper remains available for full developer loops: scripts/qa/run_local_validation.sh"
