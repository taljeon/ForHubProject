#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"
RUN_LABEL="${1:-manual}"
DIGEST_COMMAND="build-digest"
LOG_FILE="$LOG_DIR/digest.log"

if [[ "$RUN_LABEL" != "manual" ]]; then
  LOG_FILE="$LOG_DIR/digest-${RUN_LABEL}.log"
fi

if [[ "${FORME_AUTO_DIGEST_WITH_LOCAL_LLM:-0}" == "1" ]]; then
  DIGEST_COMMAND="build-digest-local"
fi

log_line "$LOG_FILE" "start: ${DIGEST_COMMAND} (${RUN_LABEL})"
if run_python app.cli "$DIGEST_COMMAND" >/dev/null 2>&1; then
  log_line "$LOG_FILE" "done: ${DIGEST_COMMAND} (${RUN_LABEL})"
  exit 0
else
  status=$?
fi

log_line "$LOG_FILE" "failed: ${DIGEST_COMMAND} (${RUN_LABEL}) exit=${status}. Rerun interactively for details."
exit "$status"
