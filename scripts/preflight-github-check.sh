#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

FAILURES=0
LOCAL_USER="${USER}"
LOCAL_PATH_PATTERN="/Users/${LOCAL_USER}|/home/${LOCAL_USER}"

fail_check() {
  FAILURES=$((FAILURES + 1))
}

echo "[1/6] required .gitignore entries"
typeset -a REQUIRED_GITIGNORE_PATTERNS=(
  ".env"
  ".env.*"
  "!.env.example"
  "auth/"
  "playwright/.auth/"
  "data/*.db"
  "data/*.db-shm"
  "data/*.db-wal"
  "data/*.sqlite3"
  "data/digests/"
  "data/logs/"
  "data/blobs/"
)
MISSING_GITIGNORE=""
for pattern in "${REQUIRED_GITIGNORE_PATTERNS[@]}"; do
  if ! grep -Fqx "$pattern" .gitignore; then
    MISSING_GITIGNORE+="${pattern}"$'\n'
  fi
done

if [[ -n "$MISSING_GITIGNORE" ]]; then
  echo "$MISSING_GITIGNORE"
  fail_check
else
  echo "ok"
fi

echo
echo "[2/6] tracked protected or generated paths"
TRACKED_PROTECTED="$(git ls-files | rg '^(auth/|data/|playwright/\.auth/|\.env$|\.env\..+|.*\.plist$)' | rg -v '^\.env\.example$' || true)"
if [[ -n "$TRACKED_PROTECTED" ]]; then
  echo "$TRACKED_PROTECTED"
  fail_check
else
  echo "ok"
fi

echo
echo "[3/6] blocked pattern scan in tracked files"
BLOCKED_PATTERN="BEGIN PRIVATE KEY|AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{20,}|ya29\\.[0-9A-Za-z._-]+|\\b[A-Za-z0-9._%+-]+@(?!example\\.(?:com|org|net)\\b)[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b|${LOCAL_PATH_PATTERN}"
if [[ -d .git ]]; then
  BLOCKED_MATCHES="$(
    git ls-files \
      | rg -v '^(scripts/preflight-github-check\.sh|docs/public-release-checklist\.md)$' \
      | tr '\n' '\0' \
      | xargs -0 rg -n -I -P "$BLOCKED_PATTERN" 2>/dev/null || true
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
echo "[4/6] launchd template script targets"
TEMPLATE_TARGET_FAILURES=""
for template_path in ops/launchd/templates/*.plist.in; do
  if ! rg -q "__FORME_ROOT__/scripts/" "$template_path"; then
    continue
  fi
  target_path="$(sed -n 's#.*<string>__FORME_ROOT__/\(scripts/[^<]*\)</string>#\1#p' "$template_path" | head -n 1)"
  if [[ -z "$target_path" ]]; then
    TEMPLATE_TARGET_FAILURES+="${template_path}: missing script target"$'\n'
    continue
  fi
  if [[ ! -f "$ROOT_DIR/$target_path" ]]; then
    TEMPLATE_TARGET_FAILURES+="${template_path}: missing ${target_path}"$'\n'
  fi
done

if [[ -n "$TEMPLATE_TARGET_FAILURES" ]]; then
  echo "$TEMPLATE_TARGET_FAILURES"
  fail_check
else
  echo "ok"
fi

echo
echo "[5/6] untracked artifacts to review"
if [[ -d .git ]]; then
  UNTRACKED_REVIEW="$(
    git ls-files --others --exclude-standard --directory \
      | rg '(^|/)(tmp_.*|.*\.cpp|.*\.bak|.*\.orig|\.env\.backup.*|.*\.(db|db-wal|db-shm|sqlite3|log|png|jpg|jpeg|pdf|csv|zip))$' || true
  )"
else
  UNTRACKED_REVIEW="$(
    find "$ROOT_DIR" -type f \
      | rg '/(tmp_.*|.*\.cpp|.*\.bak|.*\.orig|\.env\.backup.*|.*\.(db|db-wal|db-shm|sqlite3|log|png|jpg|jpeg|pdf|csv|zip))$' \
      | sort || true
  )"
fi

if [[ -n "$UNTRACKED_REVIEW" ]]; then
  echo "$UNTRACKED_REVIEW"
  fail_check
else
  echo "ok"
fi

echo
echo "[6/6] summary"
if (( FAILURES > 0 )); then
  echo "preflight failed: resolve the items above before public push."
  exit 1
fi

echo "preflight passed."
