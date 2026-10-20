#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
LLAMA_CPP_COMMIT=1b70350c92563449576bcbbf552994b1d1ed847d

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
if [[ -n "${CMAKE:-}" ]]; then
  CMAKE_BIN=$(command -v "$CMAKE")
elif [[ -x "$(dirname "$PYTHON")/cmake" ]]; then
  CMAKE_BIN="$(dirname "$PYTHON")/cmake"
else
  CMAKE_BIN=$(command -v cmake)
fi

MANAGED_LLAMA_DIR=0
if [[ -n "${ONRAM_LLAMA_CPP_DIR:-}" ]]; then
  LLAMA_DIR=$ONRAM_LLAMA_CPP_DIR
  if [[ ! -d "$LLAMA_DIR/.git" ]]; then
    echo "ONRAM_LLAMA_CPP_DIR must point to an existing llama.cpp Git checkout: $LLAMA_DIR" >&2
    exit 2
  fi
else
  LLAMA_DIR="$SCRIPT_DIR/third_party/llama.cpp"
  MANAGED_LLAMA_DIR=1
fi
if [[ ! -d "$LLAMA_DIR/.git" && "$MANAGED_LLAMA_DIR" == 1 ]]; then
  mkdir -p "$(dirname "$LLAMA_DIR")"
  git clone https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
fi
if [[ "$MANAGED_LLAMA_DIR" == 1 ]]; then
  git -C "$LLAMA_DIR" checkout --detach "$LLAMA_CPP_COMMIT"
fi

PATCH="$SCRIPT_DIR/patches/gpt2-skip-causal-mask.patch"
if [[ "$MANAGED_LLAMA_DIR" == 1 ]] && rg -q 'yield from super\(\).modify_tensors\(data_torch, name, bid\)' \
  "$LLAMA_DIR/conversion/gpt2.py"; then
  git -C "$LLAMA_DIR" apply --check "$PATCH"
  git -C "$LLAMA_DIR" apply "$PATCH"
fi

TRACE_PATCH="$SCRIPT_DIR/patches/llama-cpp-inference-trace.patch"
if ! rg -q 'ONRAM_INFERENCE_TRACE_FILE' "$LLAMA_DIR/tools/server/server-context.cpp"; then
  git -C "$LLAMA_DIR" apply --check "$TRACE_PATCH"
  git -C "$LLAMA_DIR" apply "$TRACE_PATCH"
fi

"$CMAKE_BIN" -S "$LLAMA_DIR" -B "$SCRIPT_DIR/build" \
  -DGGML_CUDA=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_SERVER=ON
"$CMAKE_BIN" --build "$SCRIPT_DIR/build" \
  --target llama-server llama-completion llama-quantize \
  --parallel "${ONRAM_BUILD_JOBS:-4}"
