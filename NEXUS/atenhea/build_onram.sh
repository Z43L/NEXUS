#!/usr/bin/env sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$SCRIPT_DIR/build"
${CC:-cc} -std=c11 -O2 -Wall -Wextra -Werror \
  "$SCRIPT_DIR/onram_launcher.c" -o "$SCRIPT_DIR/build/atenhea"
ln -sf atenhea "$SCRIPT_DIR/build/onram-cli"
ln -sf atenhea "$SCRIPT_DIR/build/onram"
echo "Built $SCRIPT_DIR/build/atenhea"
