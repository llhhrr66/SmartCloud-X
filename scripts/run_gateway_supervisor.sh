#!/usr/bin/env bash
set -u
PROJECT_DIR="/home/ljr/SmartCloud-X"
TASK_FILE="/home/ljr/SmartCloud-X/project_document/gateway-service-development-prompt-2026-04-20.md"
LOG_DIR="$PROJECT_DIR/logs/gateway-supervisor"
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
log "gateway supervisor started iter=$iter"
while true; do
  iter=$((iter+1))
  ITER_LOG="$LOG_DIR/iter-${iter}.log"
  : > "$ITER_LOG"
  python3 - <<'PY' "$STATE_JSON" "$iter"
import json,sys,datetime
path,it = sys.argv[1], int(sys.argv[2])
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":"running","task_file":"/home/ljr/SmartCloud-X/project_document/gateway-service-development-prompt-2026-04-20.md"}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
  log "starting iteration $iter"
  hermes chat -Q --source tool --yolo --max-turns 120 -q "You are the SmartCloud-X gateway-service supervisor worker. Work only inside /home/ljr/SmartCloud-X. First fully read and strictly follow $TASK_FILE. Required behavior: first do gap analysis, then code; complete code, tests, and docs updates requested by the task file; run the required validation commands and do not skip them; if blocked by external/non-code factors, stop guessing and report a clear blocker with needed conditions. Before finishing, provide: modified files list, completion table, validation commands and results, known limitations, and whether ready for main reviewer handoff. Keep changes reviewable and continue autonomously without asking the user questions." >"$ITER_LOG" 2>&1
  ec=$?
  cat "$ITER_LOG" >> "$SUP_LOG"
  if grep -qiE 'completed remaining useful work|ready for handoff back to the main reviewer|可交回主审查人检查[：: ]*(是|yes|true)' "$ITER_LOG"; then
    phase="completed"
    reason="completion marker detected"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason"
import json,sys,datetime
path,it,ec,phase,reason = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":"/home/ljr/SmartCloud-X/project_document/gateway-service-development-prompt-2026-04-20.md"}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter completion marker detected; supervisor stopping"
    exit 0
  fi
  if grep -qiE 'hard blocker:|^BLOCKER:|blocker and required conditions|所需条件' "$ITER_LOG"; then
    phase="blocked"
    reason="blocker marker detected"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason"
import json,sys,datetime
path,it,ec,phase,reason = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":"/home/ljr/SmartCloud-X/project_document/gateway-service-development-prompt-2026-04-20.md"}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter blocker marker detected; supervisor stopping"
    exit 0
  fi
  if [[ $ec -eq 0 ]]; then
    phase="completed"
    reason="exit 0 without explicit marker"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason"
import json,sys,datetime
path,it,ec,phase,reason = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":"/home/ljr/SmartCloud-X/project_document/gateway-service-development-prompt-2026-04-20.md"}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter exited 0; supervisor stopping"
    exit 0
  fi
  phase="retrying"
  reason="non-zero exit without completion/blocker marker"
  python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason"
import json,sys,datetime
path,it,ec,phase,reason = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":"/home/ljr/SmartCloud-X/project_document/gateway-service-development-prompt-2026-04-20.md"}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
  log "iteration $iter exited $ec; retrying after backoff"
  sleep 20
done
