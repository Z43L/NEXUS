#!/usr/bin/env bash
# Local end-to-end demo WITHOUT Docker: coordinator + N node processes + pipeline + gateway + settlement.
# Usage: deploy/run_demo.sh [--nodes 6] [--slots 3] [--tokens 24] [--stub]
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if [ -x .venv/bin/python ] && [ -z "${PYTHON:-}" ] && [ -n "${NEXUS_USE_VENV:-}" ]; then PY=.venv/bin/python; fi
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m nexus_cli demo "$@"
