#!/bin/zsh

set -euo pipefail

. "$(cd "$(dirname "$0")" && pwd)/common.sh"
cd "$ROOT_DIR"

HOST="${FORME_DASHBOARD_HOST:-127.0.0.1}"
PORT="${FORME_DASHBOARD_PORT:-8000}"
ACCESS_TOKEN_PATH="${FORME_DASHBOARD_ACCESS_TOKEN_PATH:-$ROOT_DIR/data/dashboard-access.token}"
OPEN_HOST="$HOST"
if [[ "$OPEN_HOST" == "0.0.0.0" ]]; then
  OPEN_HOST="127.0.0.1"
fi
URL="http://${OPEN_HOST}:${PORT}"
HEALTHCHECK_URL="${URL}/healthz"

read_access_token() {
  [[ -f "$ACCESS_TOKEN_PATH" ]] || return 1
  tr -d '\n' < "$ACCESS_TOKEN_PATH"
}

build_dashboard_url() {
  local access_token="$1"
  printf '%s/?access_token=%s\n' "$URL" "$access_token"
}

healthcheck() {
  "$ROOT_DIR/.venv/bin/python" - "$1" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

response = urlopen(sys.argv[1], timeout=1)
raise SystemExit(0 if response.status == 200 else 1)
PY
}

find_server_pids() {
  lsof -t -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

is_forme_dashboard_pid() {
  local pid="$1"
  local command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ -n "$command" ]] || return 1
  [[ "$command" == *"$ROOT_DIR/.venv/bin/uvicorn"* ]] || return 1
  [[ "$command" == *"app.main:app"* ]]
}

if healthcheck "$HEALTHCHECK_URL"; then
  if ! access_token="$(read_access_token)"; then
    echo "Dashboard is running, but access token file is missing: $ACCESS_TOKEN_PATH" >&2
    exit 1
  fi
  dashboard_url="$(build_dashboard_url "$access_token")"
  open "$dashboard_url"
  echo "Dashboard already running: $dashboard_url"
  exit 0
fi

pids="$(find_server_pids)"
if [[ -n "$pids" ]]; then
  typeset -a owned_pids=()
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    if is_forme_dashboard_pid "$pid"; then
      owned_pids+=("$pid")
      continue
    fi
    echo "Port $PORT is already in use by another process. Refusing to kill it." >&2
    ps -p "$pid" -o pid=,command=
    exit 1
  done <<< "$pids"

  if (( ${#owned_pids[@]} > 0 )); then
    echo "Stopping stale Forme dashboard server on port $PORT: ${owned_pids[*]}"
    kill "${owned_pids[@]}"
  fi
  sleep 1
fi

"$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT" --reload >> "$LOG_DIR/dashboard.log" 2>&1 &
SERVER_PID=$!
sleep 2

if healthcheck "$HEALTHCHECK_URL"; then
  if ! access_token="$(read_access_token)"; then
    echo "Dashboard started but access token file is missing: $ACCESS_TOKEN_PATH" >&2
    exit 1
  fi
  dashboard_url="$(build_dashboard_url "$access_token")"
  open "$dashboard_url"
  echo "Dashboard started at $dashboard_url (pid=$SERVER_PID)"
else
  echo "Dashboard did not become healthy. Check $LOG_DIR/dashboard.log." >&2
fi

echo "Stop with: kill $SERVER_PID"
wait "$SERVER_PID"
