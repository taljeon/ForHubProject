#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"

if [[ ! -f "$ROOT_DIR/auth/google-oauth/credentials.json" ]]; then
  echo "Missing: $ROOT_DIR/auth/google-oauth/credentials.json"
  echo "Place your Desktop OAuth client credentials there first."
  exit 1
fi

run_python app.cli init-db
run_python app.cli seed-sources
run_python app.cli sync-gmail-full
run_python app.cli list-mail --limit 10
