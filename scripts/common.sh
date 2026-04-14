#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export FORME_ROOT_DIR="$ROOT_DIR"
export PATH="$ROOT_DIR/.venv/bin:$PATH"
LOG_DIR="$ROOT_DIR/data/logs"
mkdir -p "$LOG_DIR"

run_python() {
  "$ROOT_DIR/.venv/bin/python" -m "$@"
}

