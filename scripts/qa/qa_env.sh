#!/usr/bin/env bash

SMARTCLOUD_QA_UV_WITH=(
  --with fastapi
  --with uvicorn
  --with pydantic
  --with httpx
  --with cryptography
  --with sqlalchemy
  --with pymysql
  --with redis
  --with minio
  --with prometheus-client
  --with opentelemetry-api
  --with opentelemetry-sdk
  --with opentelemetry-exporter-otlp
  --with opentelemetry-instrumentation-fastapi
  --with pyyaml
  --with jsonschema
  --with pytest
)

smartcloud_qa_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

smartcloud_qa_init() {
  ROOT_DIR="${ROOT_DIR:-$(smartcloud_qa_repo_root)}"
  QA_PYTHON=(python3)
  QA_PYTEST=(python3 -m pytest)
  QA_RUNTIME_LABEL="system-python3"

  if command -v uv >/dev/null 2>&1; then
    QA_PYTHON=(uv run "${SMARTCLOUD_QA_UV_WITH[@]}" python)
    QA_PYTEST=(uv run "${SMARTCLOUD_QA_UV_WITH[@]}" pytest)
    QA_RUNTIME_LABEL="uv"
  elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    QA_PYTHON=("$ROOT_DIR/.venv/bin/python")
    QA_PYTEST=("$ROOT_DIR/.venv/bin/python" -m pytest)
    QA_RUNTIME_LABEL="$ROOT_DIR/.venv/bin/python"
  fi
}

smartcloud_qa_assert_python_runtime() {
  if "${QA_PYTHON[@]}" -c "import cryptography, fastapi, httpx, jsonschema, minio, prometheus_client, pydantic, pymysql, pytest, redis, sqlalchemy, uvicorn, yaml" >/dev/null 2>&1; then
    return 0
  fi

  echo "[qa-env] selected QA runtime is missing required Python dependencies: $QA_RUNTIME_LABEL"
  echo "[qa-env] preferred fix: install uv, or provision $ROOT_DIR/.venv with the QA dependencies"
  echo "[qa-env] fallback: run via 'uv run ${SMARTCLOUD_QA_UV_WITH[*]} <command>'"
  return 1
}

smartcloud_qa_configure_live_infra_env() {
  if [[ "${SMARTCLOUD_QA_USE_LIVE_INFRA:-0}" != "1" ]]; then
    return 0
  fi

  export SMARTCLOUD_QA_SHARED_MYSQL_DSN="${SMARTCLOUD_QA_SHARED_MYSQL_DSN:-mysql+pymysql://smartcloud:smartcloud@127.0.0.1:3306/smartcloud}"
  export SMARTCLOUD_QA_SHARED_REDIS_URL="${SMARTCLOUD_QA_SHARED_REDIS_URL:-redis://127.0.0.1:6379/0}"
  export SMARTCLOUD_QA_SHARED_RAG_REDIS_URL="${SMARTCLOUD_QA_SHARED_RAG_REDIS_URL:-redis://127.0.0.1:6379/1}"
  export SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT="${SMARTCLOUD_QA_SHARED_MINIO_ENDPOINT:-http://127.0.0.1:${SMARTCLOUD_MINIO_HOST_PORT:-19000}}"
  export SMARTCLOUD_QA_SHARED_MINIO_BUCKET="${SMARTCLOUD_QA_SHARED_MINIO_BUCKET:-knowledge-raw}"
  export SMARTCLOUD_QA_SHARED_MINIO_ACCESS_KEY="${SMARTCLOUD_QA_SHARED_MINIO_ACCESS_KEY:-smartcloud}"
  export SMARTCLOUD_QA_SHARED_MINIO_SECRET_KEY="${SMARTCLOUD_QA_SHARED_MINIO_SECRET_KEY:-smartcloud123}"
  export SMARTCLOUD_QA_SHARED_QDRANT_URL="${SMARTCLOUD_QA_SHARED_QDRANT_URL:-http://127.0.0.1:6333}"
  export SMARTCLOUD_QA_SHARED_OPENSEARCH_URL="${SMARTCLOUD_QA_SHARED_OPENSEARCH_URL:-http://127.0.0.1:9200}"

  echo "[qa-env] SMARTCLOUD_QA_USE_LIVE_INFRA=1; using localhost shared-backend defaults unless explicitly overridden"
}

smartcloud_qa_require_playwright() {
  if [[ ! -x "$ROOT_DIR/apps/web-user/node_modules/.bin/playwright" ]]; then
    echo "[qa-env] Playwright is missing under apps/web-user/node_modules"
    echo "[qa-env] run: npm --prefix apps/web-user ci && npm --prefix tests/e2e run install:browsers"
    return 1
  fi
}

smartcloud_qa_port_in_use() {
  local port="$1"
  python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket() as sock:
    sock.settimeout(0.2)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
PY
}

smartcloud_qa_find_free_port() {
  python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

smartcloud_qa_configure_browser_ports() {
  local requested_app_port="${QA_BROWSER_APP_PORT:-3200}"
  local requested_api_port="${QA_BROWSER_API_PORT:-39090}"
  local resolved_app_port="$requested_app_port"
  local resolved_api_port="$requested_api_port"

  if smartcloud_qa_port_in_use "$requested_app_port"; then
    resolved_app_port="$(smartcloud_qa_find_free_port)"
    echo "[qa-env] QA_BROWSER_APP_PORT=$requested_app_port is busy; using $resolved_app_port"
  fi

  if smartcloud_qa_port_in_use "$requested_api_port"; then
    resolved_api_port="$(smartcloud_qa_find_free_port)"
    while [[ "$resolved_api_port" == "$resolved_app_port" ]]; do
      resolved_api_port="$(smartcloud_qa_find_free_port)"
    done
    echo "[qa-env] QA_BROWSER_API_PORT=$requested_api_port is busy; using $resolved_api_port"
  fi

  if [[ "$resolved_api_port" == "$resolved_app_port" ]]; then
    resolved_api_port="$(smartcloud_qa_find_free_port)"
    while [[ "$resolved_api_port" == "$resolved_app_port" ]]; do
      resolved_api_port="$(smartcloud_qa_find_free_port)"
    done
    echo "[qa-env] browser app/api ports collided; using QA_BROWSER_API_PORT=$resolved_api_port"
  fi

  export QA_BROWSER_APP_PORT="$resolved_app_port"
  export QA_BROWSER_API_PORT="$resolved_api_port"
}
