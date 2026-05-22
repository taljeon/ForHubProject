#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"
LOG_FILE="$LOG_DIR/source-scan.log"

log_line "$LOG_FILE" "start: seed job sources"
if run_python app.cli seed-sources >/dev/null 2>&1; then
  log_line "$LOG_FILE" "done: seed job sources"
else
  status=$?
  log_line "$LOG_FILE" "failed: seed job sources exit=${status}. Rerun interactively for details."
  exit "$status"
fi

log_line "$LOG_FILE" "start: scan job sources"
if run_python app.cli scan-sources >/dev/null 2>&1; then
  log_line "$LOG_FILE" "done: scan job sources"
  exit 0
else
  status=$?
fi

log_line "$LOG_FILE" "failed: scan job sources exit=${status}. Rerun interactively for details."
exit "$status"
