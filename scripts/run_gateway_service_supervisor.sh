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
  hermes chat -Q --source tool --yolo --max-turns 220 -q "You are a bounded SmartCloud-X supervisor worker. Work only inside /home/ljr/SmartCloud-X. First fully read and strictly follow $TASK_FILE. Do not ask the user questions. Required flow: (1) read assigned docs/code, (2) execute tasks in priority order, (3) fix compile/test/dependency issues per task-file stop rules, (4) keep working through blocked subtasks instead of stopping overall, (5) run required verification commands, (6) final output must include: modified files, completed items, remaining items, blocked items, validation commands/results, completion table, known limitations." >"$ITER_LOG" 2>&1
  ec=$?
  cat "$ITER_LOG" >> "$SUP_LOG"
  if grep -qiE '全部完成|所有可完成的任务均已完成|completion table|完成度表格|known limitations|已知限制' "$ITER_LOG"; then
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
  if grep -qiE '硬性条件|冻结合约|immediate stop|hard stop|BLOCKER' "$ITER_LOG"; then
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
