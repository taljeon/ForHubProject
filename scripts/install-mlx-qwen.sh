#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

MODEL_NAME="${FORME_LOCAL_LLM_MODEL:-NexVeridian/Qwen3-14B-4bit}"

"$ROOT_DIR/.venv/bin/python" -m pip install "mlx>=0.28" "mlx-lm>=0.28"
"$ROOT_DIR/.venv/bin/python" -m mlx_lm.generate \
  --model "$MODEL_NAME" \
  --prompt "간단히 자기소개를 해주세요." \
  --max-tokens 32 \
  --temp 0.1

echo "MLX local LLM ready: $MODEL_NAME"
