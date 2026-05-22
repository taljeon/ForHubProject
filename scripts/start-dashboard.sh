#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
HOST="${FORME_DASHBOARD_HOST:-127.0.0.1}"
PORT="${FORME_DASHBOARD_PORT:-8000}"

cd "$ROOT_DIR"
echo "Starting Forme dashboard on http://${HOST}:${PORT}"
echo "Use ./scripts/open-dashboard.sh to open an authenticated browser session."
exec "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload
