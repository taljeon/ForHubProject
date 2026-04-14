#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FAILURES=0
LOCAL_USER="${USER}"
LOCAL_PATH_PATTERN="/Users/${LOCAL_USER}|/home/${LOCAL_USER}"

fail_check() {
  FAILURES=$((FAILURES + 1))
}

echo "[1/5] gitignore protected paths"
cat "$ROOT_DIR/.gitignore"

echo
echo "[2/5] tracked protected paths"
TRACKED_PROTECTED="$(git -C "$ROOT_DIR" ls-files auth data playwright/.auth .env || true)"
if [[ -n "$TRACKED_PROTECTED" ]]; then
  echo "$TRACKED_PROTECTED"
  fail_check
else
  echo "ok"
fi

echo
echo "[3/5] blocked pattern scan in tracked files"
if [[ -d "$ROOT_DIR/.git" ]]; then
  BLOCKED_MATCHES="$(
    git -C "$ROOT_DIR" ls-files \
      | grep -v '^scripts/preflight-github-check\.sh$' \
      | sed "s#^#$ROOT_DIR/#" \
      | xargs rg -n --hidden -S \
          "BEGIN PRIVATE KEY|AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|${LOCAL_PATH_PATTERN}" \
          2>/dev/null || true
  )"
else
  BLOCKED_MATCHES=""
fi

if [[ -n "$BLOCKED_MATCHES" ]]; then
  echo "$BLOCKED_MATCHES"
  fail_check
else
  echo "ok"
fi

echo
echo "[4/5] loose top-level files to review"
if [[ -d "$ROOT_DIR/.git" ]]; then
  LOOSE_TOP_LEVEL="$(
    git -C "$ROOT_DIR" ls-files --others --exclude-standard --directory \
      | awk -F/ 'NF == 1 { print }' \
      | rg '^(tmp_.*|.*\.cpp|.*\.bak|.*\.orig|\.env\.backup.*)$' || true
  )"
else
  LOOSE_TOP_LEVEL="$(
    find "$ROOT_DIR" -maxdepth 1 -type f \
      | rg '/(tmp_.*|.*\.cpp|.*\.bak|.*\.orig|\.env\.backup.*)$' \
      | sort || true
  )"
fi

if [[ -n "$LOOSE_TOP_LEVEL" ]]; then
  echo "$LOOSE_TOP_LEVEL"
  fail_check
else
  echo "ok"
fi

echo
echo "[5/5] summary"
if (( FAILURES > 0 )); then
  echo "preflight failed: resolve the items above before public push."
  exit 1
fi

echo "preflight passed."
