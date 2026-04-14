#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE_DIR="$ROOT_DIR/ops/launchd/templates"
OUTPUT_DIR="${1:-$HOME/Library/LaunchAgents}"

if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "launchd template directory not found: $TEMPLATE_DIR" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

for template_path in "$TEMPLATE_DIR"/*.plist.in; do
  template_name="$(basename "$template_path")"
  output_name="${template_name%.in}"
  output_path="$OUTPUT_DIR/$output_name"

  sed "s#__FORME_ROOT__#$ROOT_DIR#g" "$template_path" > "$output_path"
  echo "rendered: $output_path"
done

echo
echo "Next steps:"
echo "  launchctl bootstrap gui/$(id -u) \"$OUTPUT_DIR/com.forme.jobhub.mail-sync.plist\""
echo "  launchctl bootstrap gui/$(id -u) \"$OUTPUT_DIR/com.forme.jobhub.source-scan.plist\""
echo "  launchctl bootstrap gui/$(id -u) \"$OUTPUT_DIR/com.forme.jobhub.digest-morning.plist\""
echo "  launchctl bootstrap gui/$(id -u) \"$OUTPUT_DIR/com.forme.jobhub.digest-evening.plist\""
