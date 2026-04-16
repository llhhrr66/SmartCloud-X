#!/usr/bin/env bash
set -euo pipefail
ROOT="/home/ljr/SmartCloud-X"
LOG_DIR="$ROOT/logs/supervisor-web-user"
PROMPT_FILE="$ROOT/scripts/prompts/supervisor-web-user.md"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/run-$TS.log"
LATEST_LINK="$LOG_DIR/latest.log"
cd "$ROOT"
echo "[$(date -Is)] starting supervisor-web-user" | tee -a "$LOG_DIR/progress.log"
cat "$PROMPT_FILE" | codex exec \
  --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  -C "$ROOT" \
  - > "$LOG_FILE" 2>&1
ln -sfn "$LOG_FILE" "$LATEST_LINK"
echo "[$(date -Is)] finished supervisor-web-user" | tee -a "$LOG_DIR/progress.log"
echo "$LOG_FILE"