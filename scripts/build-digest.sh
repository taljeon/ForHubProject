#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"

run_python app.cli build-digest >> "$LOG_DIR/digest.log" 2>&1

