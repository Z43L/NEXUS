#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
exec ./atenhea serve --backend nram --model models/gemma4-e2b-trainable --bundle models/athenea-e2b.nram --model-name athenea-e2b --ctx-size 131072 --chl-memory models/athenea.memory --no-auto-learn --no-inference-debug "$@"
