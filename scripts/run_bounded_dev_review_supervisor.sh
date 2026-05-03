#!/usr/bin/env bash
set -u
PROJECT_DIR="/home/ljr/SmartCloud-X"
TASK_FILE="$1"
NAME="$2"
LOG_DIR="$PROJECT_DIR/logs/${NAME}"
SUP_LOG="$LOG_DIR/supervisor.log"
STATE_JSON="$LOG_DIR/state.json"
mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR" || exit 1
iter=0
if [[ -f "$STATE_JSON" ]]; then
  prev=$(python3 - <<'PY' "$STATE_JSON"
import json,sys
try:
    print(json.load(open(sys.argv[1],'r',encoding='utf-8')).get('iter',0))
except Exception:
    print(0)
PY
)
  [[ "$prev" =~ ^[0-9]+$ ]] && iter="$prev"
fi
log(){ printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S%z')" "$1" | tee -a "$SUP_LOG"; }
log "$NAME supervisor started iter=$iter"
while true; do
  iter=$((iter+1))
  ITER_LOG="$LOG_DIR/iter-${iter}.log"
  : > "$ITER_LOG"
  python3 - <<'PY' "$STATE_JSON" "$iter" "$TASK_FILE"
import json,sys,datetime
path,it,task = sys.argv[1], int(sys.argv[2]), sys.argv[3]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":"running","task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
  log "starting iteration $iter"
  hermes chat -Q --source tool --yolo --max-turns 160 -q "You are a bounded SmartCloud-X supervisor worker. Work only inside /home/ljr/SmartCloud-X. First fully read and strictly follow $TASK_FILE. Do not ask the user questions. Required flow: (1) read all assigned split development docs and owned code, (2) create/update your dev-review tracking markdown first, (3) maintain the table continuously, (4) then iterate through one tracked item at a time doing development, tests, self-review, fixes, and table updates. You must obey the boundary rules in the task file and never modify out-of-scope directories. Cross-boundary issues must be recorded as cross_boundary, not edited directly. Every completed item must have implementation, validation, review, and doc alignment recorded. Keep working until all in-scope actionable items are completed or only blocked/cross_boundary items remain. If you hit a blocker condition defined in the task file, output a clear BLOCKER section and stop. Final output must include: modified files, completed items, remaining items, blocked items, cross-boundary items, validation commands/results, and whether ready for morning review." >"$ITER_LOG" 2>&1
  ec=$?
  cat "$ITER_LOG" >> "$SUP_LOG"
  if grep -qiE 'ready for morning review|ready to hand back for review|本边界内可落地事项全部完成|仅剩.*cross_boundary|仅剩.*blocked|completed remaining useful work' "$ITER_LOG"; then
    phase="completed"
    reason="completion marker detected"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter completion marker detected; supervisor stopping"
    exit 0
  fi
  if grep -qiE '## BLOCKER|^BLOCKER:|blocker section|cross_boundary only with blockers|blocked items' "$ITER_LOG"; then
    phase="blocked"
    reason="blocker marker detected"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter blocker marker detected; supervisor stopping"
    exit 0
  fi
  if [[ $ec -eq 0 ]]; then
    phase="completed"
    reason="exit 0 without explicit marker"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter exited 0; supervisor stopping"
    exit 0
  fi
  phase="retrying"
  reason="non-zero exit without completion/blocker marker"
  python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
  log "iteration $iter exited $ec; retrying after backoff"
  sleep 20
done
