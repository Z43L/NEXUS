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

bundle=${1:-models/distilgpt2-nra-qa.nram}
name=${2:-distilgpt2-nra-export}
hf_dir="models/${name}-hf"
f16_file="models/${name}-f16.gguf"
q4_file="models/${name}-Q4_K_M.gguf"
LLAMA_DIR=${ONRAM_LLAMA_CPP_DIR:-"$SCRIPT_DIR/third_party/llama.cpp"}
if [[ ! -f "$LLAMA_DIR/convert_hf_to_gguf.py" || ! -x "$SCRIPT_DIR/build/bin/llama-quantize" ]]; then
  "$SCRIPT_DIR/setup_onram.sh"
fi

"$PYTHON" nram_merge.py --bundle "$bundle" --output "$hf_dir"
"$PYTHON" "$LLAMA_DIR/convert_hf_to_gguf.py" \
  "$hf_dir" --outfile "$f16_file" --outtype f16
"$SCRIPT_DIR/build/bin/llama-quantize" "$f16_file" "$q4_file" Q4_K_M
printf 'Wrote %s and %s\n' "$f16_file" "$q4_file"
