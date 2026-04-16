#!/bin/sh
set -eu

OUTPUT_PATH="/usr/share/nginx/html/runtime-config.js"

json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

app_title="${VITE_APP_TITLE:-SmartCloud-X User Console}"
app_version="${VITE_APP_VERSION:-0.1.0}"
api_base_url="${VITE_API_BASE_URL:-http://localhost:8000}"
use_mock_api="${VITE_USE_MOCK_API:-false}"
request_timeout_ms="${VITE_REQUEST_TIMEOUT_MS:-30000}"
sse_heartbeat_seconds="${VITE_SSE_HEARTBEAT_SECONDS:-15}"

cat > "$OUTPUT_PATH" <<EOF
window.__SMARTCLOUD_RUNTIME_CONFIG__ = {
  "VITE_APP_TITLE": "$(json_escape "$app_title")",
  "VITE_APP_VERSION": "$(json_escape "$app_version")",
  "VITE_API_BASE_URL": "$(json_escape "$api_base_url")",
  "VITE_USE_MOCK_API": "$(json_escape "$use_mock_api")",
  "VITE_REQUEST_TIMEOUT_MS": "$(json_escape "$request_timeout_ms")",
  "VITE_SSE_HEARTBEAT_SECONDS": "$(json_escape "$sse_heartbeat_seconds")"
};
EOF
