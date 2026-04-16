#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ljr/SmartCloud-X"
LOG_DIR="$ROOT/logs/supervisor-manager"
mkdir -p "$LOG_DIR"
MANAGER_LOG="$LOG_DIR/manager.log"
STATUS_FILE="$LOG_DIR/state.json"

log() {
  printf '[%s] %s\n' "$(date -Is)" "$1" | tee -a "$MANAGER_LOG"
}

status_doc_for() {
  case "$1" in
    foundation) echo "$ROOT/docs/status/supervisor-foundation-status.md" ;;
    orchestrator) echo "$ROOT/docs/status/supervisor-orchestrator-status.md" ;;
    knowledge-rag) echo "$ROOT/docs/status/supervisor-knowledge-rag-status.md" ;;
    web-user) echo "$ROOT/docs/status/supervisor-web-user-status.md" ;;
    auth-marketing-research) echo "$ROOT/docs/status/supervisor-auth-marketing-research-status.md" ;;
    frontend-sdk) echo "$ROOT/docs/status/supervisor-frontend-sdk-status.md" ;;
    integration-qa) echo "$ROOT/docs/status/supervisor-integration-qa-status.md" ;;
    *) return 1 ;;
  esac
}

is_completed() {
  local name="$1"
  local status_doc
  status_doc="$(status_doc_for "$name")" || return 1
  [[ -f "$status_doc" ]] || return 1

  python3 - "$status_doc" <<'PY'
import pathlib, re, sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding='utf-8').lower()

phase_match = re.search(r'^-\s*phase:\s*(.+)$', text, flags=re.MULTILINE)
if phase_match:
    phase = phase_match.group(1).strip()
    if phase == 'done' or phase.startswith('completed'):
        raise SystemExit(0)

has_completed = '## completed' in text
has_validation = '## validation' in text
pending_signoff = 'pending before final signoff' in text

raise SystemExit(0 if has_completed and has_validation and not pending_signoff else 1)
PY
}

is_running() {
  local script_name="$1"
  pgrep -af "$script_name" | grep -Fv "pgrep -af $script_name" >/dev/null 2>&1
}

start_supervisor() {
  local name="$1"
  local script_path="$2"
  local log_file="$LOG_DIR/${name}-launcher.log"
  log "starting ${name} via ${script_path}"
  nohup bash "$script_path" >> "$log_file" 2>&1 < /dev/null &
  sleep 2
  if is_running "$(basename "$script_path")"; then
    log "${name} launch command accepted"
  else
    log "${name} launch did not remain running"
  fi
}

ensure_one() {
  local name="$1"
  local script_path="$2"
  if is_completed "$name"; then
    log "${name} already completed; skipping launch"
  elif is_running "$(basename "$script_path")"; then
    log "${name} already running"
  else
    start_supervisor "$name" "$script_path"
  fi
}

write_state() {
  python3 - <<'PY'
import json, os, pathlib, re, subprocess
root = "/home/ljr/SmartCloud-X"
items = {
    "foundation": {
        "script": "run_supervisor_foundation.sh",
        "status_doc": "docs/status/supervisor-foundation-status.md",
    },
    "orchestrator": {
        "script": "run_supervisor_orchestrator.sh",
        "status_doc": "docs/status/supervisor-orchestrator-status.md",
    },
    "knowledge_rag": {
        "script": "run_supervisor_knowledge_rag.sh",
        "status_doc": "docs/status/supervisor-knowledge-rag-status.md",
    },
    "web_user": {
        "script": "run_supervisor_web_user.sh",
        "status_doc": "docs/status/supervisor-web-user-status.md",
    },
    "auth_marketing_research": {
        "script": "run_supervisor_auth_marketing_research.sh",
        "status_doc": "docs/status/supervisor-auth-marketing-research-status.md",
    },
    "frontend_sdk": {
        "script": "run_supervisor_frontend_sdk.sh",
        "status_doc": "docs/status/supervisor-frontend-sdk-status.md",
    },
    "integration_qa": {
        "script": "run_supervisor_integration_qa.sh",
        "status_doc": "docs/status/supervisor-integration-qa-status.md",
    },
}

def status_is_completed(path_text: str) -> bool:
    path = pathlib.Path(root, path_text)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8").lower()
    match = re.search(r'^-\s*phase:\s*(.+)$', text, flags=re.MULTILINE)
    if match:
        phase = match.group(1).strip()
        if phase == "done" or phase.startswith("completed"):
            return True
    return "## completed" in text and "## validation" in text and "pending before final signoff" not in text

state = {}
for key, config in items.items():
    script = config["script"]
    cmd = f"pgrep -af {script!s}"
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    lines = [line for line in proc.stdout.splitlines() if script in line and "pgrep -af" not in line]
    state[key] = {
        "running": bool(lines),
        "completed": status_is_completed(config["status_doc"]),
        "status_doc": config["status_doc"],
        "processes": lines,
    }
out = {
    "updated_at": subprocess.run("date -Is", shell=True, capture_output=True, text=True).stdout.strip(),
    "supervisors": state,
}
path = os.path.join(root, "logs", "supervisor-manager", "state.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
PY
}

ensure_one foundation "$ROOT/scripts/run_supervisor_foundation.sh"
ensure_one orchestrator "$ROOT/scripts/run_supervisor_orchestrator.sh"
ensure_one knowledge-rag "$ROOT/scripts/run_supervisor_knowledge_rag.sh"
ensure_one web-user "$ROOT/scripts/run_supervisor_web_user.sh"
ensure_one auth-marketing-research "$ROOT/scripts/run_supervisor_auth_marketing_research.sh"
ensure_one frontend-sdk "$ROOT/scripts/run_supervisor_frontend_sdk.sh"
ensure_one integration-qa "$ROOT/scripts/run_supervisor_integration_qa.sh"
write_state
log "manager pass complete"