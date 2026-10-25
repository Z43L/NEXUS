#!/bin/sh
# Run the FastAPI compatibility facade against an already-running local H0 Router.
set -eu

API_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
NEXUS_DIR=$(CDPATH= cd -- "$API_DIR/../.." && pwd)
PY=${NEXUS_API_PYTHON:-"$API_DIR/.venv/bin/python"}
ROUTER_URL=${NEXUS_H0_ROUTER_URL:-http://127.0.0.1:18080}
PORT=${NEXUS_API_PORT:-8000}

if [ -n "${NEXUS_API_PYTHON:-}" ]; then
  if ! "$PY" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
    echo "NEXUS_API_PYTHON must provide fastapi and uvicorn." >&2
    exit 1
  fi
else
  if [ ! -x "$PY" ]; then
    python3 -m venv "$API_DIR/.venv"
    "$PY" -m pip install --quiet --require-hashes -r "$API_DIR/requirements-h0.lock"
  fi
  if ! "$PY" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
    echo "API environment is missing dependencies; install nexus/api/requirements-h0.txt." >&2
    exit 1
  fi
fi

# H0 is local-only. Reject a non-loopback upstream before starting the facade.
"$PY" - "$ROUTER_URL" <<'PY'
from ipaddress import ip_address
from urllib.parse import urlsplit
import sys

url = urlsplit(sys.argv[1])
host = (url.hostname or "").lower()
try:
    loopback = ip_address(host).is_loopback
except ValueError:
    loopback = host == "localhost"
if url.scheme != "http" or not loopback or url.path not in ("", "/") or url.query or url.fragment:
    raise SystemExit("NEXUS_H0_ROUTER_URL must be an http URL on localhost/loopback")
PY

if ! "$PY" - "$ROUTER_URL/ready" <<'PY'
import json
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        ready = response.status == 200 and json.loads(response.read()).get("ok") is True
except Exception:
    ready = False
raise SystemExit(0 if ready else 1)
PY
then
  echo "H0 Router is not ready at $ROUTER_URL; start the local H0 stack first." >&2
  exit 1
fi

cd "$NEXUS_DIR"
export NEXUS_H0_ROUTER_URL="$ROUTER_URL"
exec "$PY" -m uvicorn nexus.api.core.api_server:app \
  --host 127.0.0.1 --port "$PORT"
