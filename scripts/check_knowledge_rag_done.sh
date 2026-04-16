#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/ljr/SmartCloud-X"
[[ -d "$ROOT/apps/knowledge-service" ]]
[[ -d "$ROOT/apps/rag-service" ]]
[[ -d "$ROOT/apps/web-admin" ]]
[[ -d "$ROOT/deploy" ]]
echo "knowledge-rag-ready-check: directories exist"
