#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ljr/SmartCloud-X"
TASK_FILE="$ROOT/AGENT_ORCHESTRATION_TASK.md"
LOG_DIR="$ROOT/logs/hermes-supervisor-orchestrator"
SUPERVISOR_LOG="$LOG_DIR/supervisor.log"
PROGRESS_LOG="$LOG_DIR/progress.log"
BLOCKERS_LOG="$LOG_DIR/blockers.log"
DECISIONS_LOG="$LOG_DIR/decisions.log"
STATE_FILE="$LOG_DIR/state.json"
LATEST_LINK="$LOG_DIR/latest.out"
MAX_ITER="${MAX_ITER:-80}"
SLEEP_SECS="${SLEEP_SECS:-20}"
RETRY_SLEEP_SECS="${RETRY_SLEEP_SECS:-120}"
PASS_TIMEOUT_SECS="${PASS_TIMEOUT_SECS:-2700}"
MAX_TURNS="${MAX_TURNS:-120}"

mkdir -p "$LOG_DIR"
cd "$ROOT"

touch "$SUPERVISOR_LOG" "$PROGRESS_LOG" "$BLOCKERS_LOG" "$DECISIONS_LOG"

log() {
  local msg="$1"
  printf '[%s] %s\n' "$(date -Is)" "$msg" | tee -a "$SUPERVISOR_LOG"
}

read_iter() {
  if [[ -f "$STATE_FILE" ]]; then
    python3 - "$STATE_FILE" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text(encoding='utf-8'))
    print(int(data.get('iter', 0)))
except Exception:
    print(0)
PY
  else
    echo 0
  fi
}

write_state() {
  local iter="$1"
  local phase="$2"
  local note="$3"
  python3 - "$STATE_FILE" "$iter" "$phase" "$note" <<'PY'
import json, pathlib, sys, datetime
path = pathlib.Path(sys.argv[1])
iter_no = int(sys.argv[2])
phase = sys.argv[3]
note = sys.argv[4]
data = {
    'updated_at': datetime.datetime.now().astimezone().isoformat(),
    'iter': iter_no,
    'phase': phase,
    'note': note,
    'task_file': '/home/ljr/SmartCloud-X/AGENT_ORCHESTRATION_TASK.md',
    'log_dir': '/home/ljr/SmartCloud-X/logs/hermes-supervisor-orchestrator'
}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY
}

ITER="$(read_iter)"
log "hermes supervisor orchestrator booted at iter=$ITER"
write_state "$ITER" "booted" "supervisor started"

while (( ITER < MAX_ITER )); do
  ITER=$((ITER + 1))
  OUT_FILE="$LOG_DIR/iter-${ITER}-$(date +%Y%m%d-%H%M%S).out"
  PROMPT="$(cat "$TASK_FILE")"

  write_state "$ITER" "running" "starting bounded Hermes pass"
  printf '[%s] starting iteration %s\n' "$(date -Is)" "$ITER" | tee -a "$SUPERVISOR_LOG" "$PROGRESS_LOG"

  set +e
  timeout "$PASS_TIMEOUT_SECS" hermes chat -Q --source tool --yolo --max-turns "$MAX_TURNS" -q "$PROMPT" > "$OUT_FILE" 2>&1
  EC=$?
  set -e

  ln -sfn "$OUT_FILE" "$LATEST_LINK"
  {
    echo "----- iteration $ITER exit=$EC start -----"
    cat "$OUT_FILE"
    echo "----- iteration $ITER exit=$EC end -----"
  } >> "$SUPERVISOR_LOG"

  if grep -Eqi 'BLOCKER:|hard blocker:' "$OUT_FILE"; then
    grep -Ei 'BLOCKER:|hard blocker:' "$OUT_FILE" | tail -n 3 | tee -a "$BLOCKERS_LOG" >/dev/null
    log "hard blocker detected in iteration $ITER"
    write_state "$ITER" "blocked" "hard blocker detected"
    exit 2
  fi

  if grep -Eqi 'completed remaining useful work' "$OUT_FILE"; then
    printf '[%s] completed remaining useful work at iteration %s\n' "$(date -Is)" "$ITER" | tee -a "$PROGRESS_LOG" "$SUPERVISOR_LOG"
    write_state "$ITER" "completed" "completed remaining useful work"
    exit 0
  fi

  if [[ "$EC" -eq 124 ]]; then
    log "iteration $ITER timed out after ${PASS_TIMEOUT_SECS}s; retrying after backoff"
    write_state "$ITER" "retry_wait" "pass timeout"
    sleep "$RETRY_SLEEP_SECS"
    continue
  fi

  if [[ "$EC" -ne 0 ]] && grep -Eqi 'Connection error|API call failed after 3 retries|timed out|timeout|502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout|token_invalidated|authentication token has been invalidated|401' "$OUT_FILE"; then
    log "transient/auth provider failure detected in iteration $ITER; retrying after backoff"
    write_state "$ITER" "retry_wait" "transient/auth provider failure"
    sleep "$RETRY_SLEEP_SECS"
    continue
  fi

  if [[ "$EC" -ne 0 ]] && [[ ! -s "$OUT_FILE" || $(wc -c < "$OUT_FILE") -lt 200 ]]; then
    log "iteration $ITER produced too little output for a non-zero exit; treating as transient startup failure and retrying"
    write_state "$ITER" "retry_wait" "thin-output startup failure"
    sleep "$RETRY_SLEEP_SECS"
    continue
  fi

  if grep -Eqi 'needs another bounded pass' "$OUT_FILE"; then
    log "iteration $ITER requested another bounded pass"
    write_state "$ITER" "looping" "agent requested another bounded pass"
    sleep "$SLEEP_SECS"
    continue
  fi

  if [[ "$EC" -eq 0 ]]; then
    log "iteration $ITER finished cleanly without explicit stop condition; continuing after short pause"
    write_state "$ITER" "looping" "clean pass completed"
    sleep "$SLEEP_SECS"
    continue
  fi

  log "iteration $ITER exited with code $EC without known retry marker; stopping for manual inspection"
  write_state "$ITER" "stopped" "unexpected non-zero exit"
  exit "$EC"
done

log "reached MAX_ITER=$MAX_ITER; exiting"
write_state "$ITER" "max_iter_reached" "reached max iterations"
