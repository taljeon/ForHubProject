#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/data/logs"
mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"

URL="http://127.0.0.1:8000"
PORT=8000

healthcheck() {
  "$ROOT_DIR/.venv/bin/python" - <<'PY' >/dev/null 2>&1
from urllib.request import urlopen
response = urlopen("http://127.0.0.1:8000", timeout=1)
raise SystemExit(0 if response.status == 200 else 1)
PY
}

find_server_pids() {
  lsof -t -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

if healthcheck; then
  open "$URL"
  echo "Dashboard already running: $URL"
  exit 0
fi

pids="$(find_server_pids)"
if [[ -n "$pids" ]]; then
  echo "Stopping stale dashboard server on port $PORT: $pids"
  kill $pids
  sleep 1
fi

"$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 --reload >> "$LOG_DIR/dashboard.log" 2>&1 &
SERVER_PID=$!
sleep 2
open "$URL"
echo "Dashboard started at $URL (pid=$SERVER_PID)"
echo "Stop with: kill $SERVER_PID"
wait "$SERVER_PID"
