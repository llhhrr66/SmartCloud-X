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

"${QA_PYTHON[@]}" scripts/qa/verify_openapi_contracts.py
scripts/qa/run_full_stack_validation.sh
"${QA_PYTHON[@]}" -m pytest tests -q
