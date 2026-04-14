#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"
LOG_FILE="$LOG_DIR/mail-sync.log"

log() {
  local message="$1"
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$message" | tee -a "$LOG_FILE"
}

if [[ ! -f "$ROOT_DIR/auth/google-oauth/credentials.json" ]]; then
  log "skip: Gmail credentials.json not found"
  exit 0
fi

log "start: incremental Gmail sync"
if run_python app.cli sync-gmail-incremental 2>&1 | tee -a "$LOG_FILE"; then
  log "done: incremental Gmail sync"
  run_python app.cli list-mail --limit 1 2>&1 | tee -a "$LOG_FILE"
  exit 0
fi

log "fallback: incremental sync failed, trying full sync"
run_python app.cli sync-gmail-full 2>&1 | tee -a "$LOG_FILE"
log "done: full Gmail sync"
run_python app.cli list-mail --limit 1 2>&1 | tee -a "$LOG_FILE"
