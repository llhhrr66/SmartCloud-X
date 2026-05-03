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
  hermes chat -Q --source tool --yolo --max-turns 260 -q "You are a bounded SmartCloud-X supervisor worker. Work only inside /home/ljr/SmartCloud-X. First fully read and strictly follow $TASK_FILE. Do not ask the user questions. You must obey this strict loop: (1) read docs/code, (2) inspect every required item one by one, (3) verify whether code is truly complete, (4) run real tests/compile/verification, (5) if not complete then classify risks into P0/P1/P2/P3, (6) continue development + testing + self-review + fixes, (7) update status, (8) continue to the next item, (9) do not stop just because you wrote a review or because some items are review_required. Only stop when all actionable in-scope tasks are truly complete, or only real blocked items remain after repeated repair attempts required by the task file. Final output must include: modified files, completed items, remaining items, blocked items, validation commands/results, completion table, known limitations, P0 risks, P1 risks, P2 risks, P3 risks, and whether anything still needs another development/testing/review loop." >"$ITER_LOG" 2>&1
  ec=$?
  cat "$ITER_LOG" >> "$SUP_LOG"
  if grep -qiE 'all actionable tasks are truly complete|所有可完成的任务均已真正完成|only real blocked items remain|仅剩真实 blocked 项|completion table|完成度表格' "$ITER_LOG"; then
    if grep -qiE 'remaining items\s*-\s*none|remaining items\s*-\s*无|仅剩真实 blocked|only real blocked items remain' "$ITER_LOG"; then
      phase="completed"
      reason="strict completion marker detected"
      python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
      log "iteration $iter strict completion marker detected; supervisor stopping"
      exit 0
    fi
  fi
  if grep -qiE '## BLOCKER REPORT|^BLOCKER REPORT|唯一应该立即停止的硬性条件|冻结合约|hard stop' "$ITER_LOG"; then
    phase="blocked"
    reason="strict blocker marker detected"
    python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
    log "iteration $iter strict blocker marker detected; supervisor stopping"
    exit 0
  fi
  phase="retrying"
  reason="needs another development/testing/review loop"
  python3 - <<'PY' "$STATE_JSON" "$iter" "$ec" "$phase" "$reason" "$TASK_FILE"
import json,sys,datetime
path,it,ec,phase,reason,task = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
json.dump({"iter":it,"updated_at":datetime.datetime.now().astimezone().isoformat(),"phase":phase,"last_exit":ec,"stop_reason":reason,"task_file":task}, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
PY
  log "iteration $iter requires another strict loop; retrying after backoff"
  sleep 20
done
