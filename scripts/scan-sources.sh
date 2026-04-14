#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"

run_python app.cli seed-sources >> "$LOG_DIR/source-scan.log" 2>&1
run_python app.cli scan-sources >> "$LOG_DIR/source-scan.log" 2>&1

