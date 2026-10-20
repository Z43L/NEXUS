#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT"

if [[ -z "${ONRAM_PYTHON:-}" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    ONRAM_PYTHON="$ROOT/.venv/bin/python"
  elif [[ -x "$ROOT/../gemma4_pentesting_edge/.venv/bin/python" ]]; then
    ONRAM_PYTHON="$ROOT/../gemma4_pentesting_edge/.venv/bin/python"
  fi
fi
export ONRAM_PYTHON

exec ./atenhea serve \
  --model models/llama3.2-1b-instruct-current.gguf \
  --bundle models/llama3.2-1b-instruct.nram \
  --model-name llama3.2-1b-instruct \
  --port 11534 \
  --backend-port 11538 \
  --auto-learn \
  --inference-debug \
  --learn-batch-size 24
