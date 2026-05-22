#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"
GMAIL_CREDENTIALS_PATH="${FORME_GMAIL_CREDENTIALS:-$ROOT_DIR/auth/google-oauth/credentials.json}"

if [[ ! -f "$GMAIL_CREDENTIALS_PATH" ]]; then
  echo "Missing: $GMAIL_CREDENTIALS_PATH"
  echo "Place your Desktop OAuth client credentials there first."
  exit 1
fi

run_python app.cli init-db
run_python app.cli seed-sources
run_python app.cli sync-gmail-full
echo
echo "Initial Gmail sync completed."
echo "Open the dashboard or run 'python -m app.cli list-mail --limit 10' if you want to inspect cached mail."
