#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"
CONFIG="$SCRIPT_DIR/models/strata/strata-ssd-fast.json"
if [ ! -f "$CONFIG" ]; then
  echo "Prepare Strata first: ./atenhea strata-setup --io-backend metal --arena-gb 1 --no-start" >&2
  exit 1
fi
exec ./atenhea serve --backend strata --strata-dir "$SCRIPT_DIR/third_party/strata" --strata-config "$CONFIG" "$@"
