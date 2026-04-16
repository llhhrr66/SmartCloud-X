#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/qa_env.sh"
smartcloud_qa_init
smartcloud_qa_assert_python_runtime
smartcloud_qa_configure_live_infra_env
cd "$ROOT_DIR"

"${QA_PYTHON[@]}" scripts/qa/verify_openapi_contracts.py
scripts/qa/run_full_stack_validation.sh
"${QA_PYTHON[@]}" -m pytest tests -q
