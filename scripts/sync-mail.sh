#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"
LOG_FILE="$LOG_DIR/mail-sync.log"
GMAIL_CREDENTIALS_PATH="${FORME_GMAIL_CREDENTIALS:-$ROOT_DIR/auth/google-oauth/credentials.json}"

if [[ ! -f "$GMAIL_CREDENTIALS_PATH" ]]; then
  log_line "$LOG_FILE" "skip: Gmail credentials not found"
  exit 0
fi

log_line "$LOG_FILE" "start: incremental Gmail sync"
if run_python app.cli sync-gmail-incremental >/dev/null 2>&1; then
  log_line "$LOG_FILE" "done: incremental Gmail sync"
  exit 0
else
  incremental_status=$?
fi

log_line "$LOG_FILE" "fallback: incremental sync failed (exit=$incremental_status), trying full sync"
if run_python app.cli sync-gmail-full >/dev/null 2>&1; then
  log_line "$LOG_FILE" "done: full Gmail sync"
  exit 0
else
  full_status=$?
fi

log_line "$LOG_FILE" "failed: full Gmail sync (exit=$full_status). Rerun interactively for details."
exit "$full_status"
