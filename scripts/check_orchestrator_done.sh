#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/ljr/SmartCloud-X"
[[ -d "$ROOT/apps/orchestrator-service" ]]
[[ -d "$ROOT/apps/tool-hub-service" ]]
[[ -d "$ROOT/apps/business-tools" ]]
echo "orchestrator-ready-check: directories exist"
