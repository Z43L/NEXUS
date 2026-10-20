#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
exec ./atenhea serve --backend llama.cpp --model models/gemma4-e2b/gemma-4-E2B-it-Q4_K_M.gguf --llama-server build/llama-current/bin/llama-server --model-name gemma4-e2b --ctx-size 8192 --no-auto-learn --no-inference-debug --backend-arg=--flash-attn --backend-arg=on --backend-arg=--cache-type-k --backend-arg=q4_0 --backend-arg=--cache-type-v --backend-arg=q4_0 --backend-arg=--batch-size --backend-arg=256 --backend-arg=--ubatch-size --backend-arg=64 --backend-arg=--load-mode --backend-arg=mmap --backend-arg=--fit --backend-arg=on --backend-arg=--fit-ctx --backend-arg=8192 "$@"
