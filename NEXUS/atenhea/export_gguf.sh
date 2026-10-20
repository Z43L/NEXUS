#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
if [[ -n "${ONRAM_PYTHON:-}" ]]; then
  PYTHON=$ONRAM_PYTHON
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  PYTHON=$SCRIPT_DIR/.venv/bin/python
elif [[ -x "$SCRIPT_DIR/../../.venv-gemma4/bin/python" ]]; then
  PYTHON=$SCRIPT_DIR/../../.venv-gemma4/bin/python
else
  PYTHON=$(command -v python3)
fi
PYTHON=$(command -v "$PYTHON")

LLAMA_DIR=${ONRAM_LLAMA_CPP_DIR:-"$SCRIPT_DIR/third_party/llama.cpp"}
if [[ ! -f "$LLAMA_DIR/convert_hf_to_gguf.py" || ! -x "$SCRIPT_DIR/build/bin/llama-quantize" ]]; then
  "$SCRIPT_DIR/setup_onram.sh"
fi

"$PYTHON" "$LLAMA_DIR/convert_hf_to_gguf.py" \
  "$SCRIPT_DIR/models/distilgpt2" \
  --outfile "$SCRIPT_DIR/models/distilgpt2-f16.gguf" --outtype f16
"$SCRIPT_DIR/build/bin/llama-quantize" \
  "$SCRIPT_DIR/models/distilgpt2-f16.gguf" \
  "$SCRIPT_DIR/models/distilgpt2-Q4_K_M.gguf" Q4_K_M
