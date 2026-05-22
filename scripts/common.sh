#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT_DIR/.venv/bin:$PATH"
typeset -ga FORME_LOADED_ENV_KEYS=()

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

env_key_loaded_from_file() {
  local key="$1"
  local loaded_key
  for loaded_key in "${FORME_LOADED_ENV_KEYS[@]}"; do
    if [[ "$loaded_key" == "$key" ]]; then
      return 0
    fi
  done
  return 1
}

remember_loaded_env_key() {
  local key="$1"
  if env_key_loaded_from_file "$key"; then
    return 0
  fi
  FORME_LOADED_ENV_KEYS+=("$key")
}

strip_matching_quotes() {
  local value="$1"
  if [[ ${#value} -ge 2 && ${value[1]} == '"' && ${value[-1]} == '"' ]]; then
    printf '%s' "${value[2,-2]}"
    return 0
  fi
  if [[ ${#value} -ge 2 && ${value[1]} == "'" && ${value[-1]} == "'" ]]; then
    printf '%s' "${value[2,-2]}"
    return 0
  fi
  printf '%s' "$value"
}

load_env_file() {
  local env_file="$1"
  local raw_line line key value
  if [[ ! -f "$env_file" ]]; then
    return 0
  fi

  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="$(trim_whitespace "$raw_line")"
    if [[ -z "$line" || "$line" == \#* || "$line" != *=* ]]; then
      continue
    fi

    key="$(trim_whitespace "${line%%=*}")"
    value="$(trim_whitespace "${line#*=}")"
    if [[ -z "$key" ]]; then
      continue
    fi

    value="$(strip_matching_quotes "$value")"
    if (( ${+parameters[$key]} )) && ! env_key_loaded_from_file "$key"; then
      continue
    fi

    export "$key=$value"
    remember_loaded_env_key "$key"
  done < "$env_file"
}

load_env_file "$ROOT_DIR/.env"
load_env_file "$ROOT_DIR/.env.local"

LOG_DIR="${FORME_LOG_DIR:-$ROOT_DIR/data/logs}"
mkdir -p "$LOG_DIR"

timestamp() {
  date '+%Y-%m-%d %H:%M:%S'
}

log_line() {
  local log_file="$1"
  local message="$2"
  printf '%s %s\n' "$(timestamp)" "$message" | tee -a "$log_file"
}

run_python() {
  "$ROOT_DIR/.venv/bin/python" -m "$@"
}
