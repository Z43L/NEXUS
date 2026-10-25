#!/bin/bash
# NEXUS H1 node runner (Mac).
# Usage (local):
#   ROUTER_URL=http://127.0.0.1:18080 bash run_mac_node.sh
# Usage (remote):
#   ROUTER_URL=https://192.168.x.y:18090 ROUTER_CA_FILE=ca.crt \
#     NODE_ENROLLMENT_TOKEN_FILE=enrollment.token bash run_mac_node.sh
# Defaults target the loopback H0 router on this same machine;
# wallet defaults to the H1 ops wallet (identity only: the worker never
# needs an EVM private key; receipts are signed with its own Ed25519 key).
set -e
cd "$(dirname "$0")"
PY=${NEXUS_PYTHON:-"$PWD/.venv/bin/python"}
if [ -n "${NEXUS_PYTHON:-}" ]; then
  "$PY" -c 'import cryptography; assert cryptography.__version__ == "50.0.2"' 2>/dev/null || {
    echo "NEXUS_PYTHON debe incluir cryptography==50.0.2." >&2
    exit 1
  }
else
  if [ ! -x "$PY" ]; then
    python3 -m venv .venv
  fi
  "$PY" -c 'import cryptography; assert cryptography.__version__ == "50.0.2"' 2>/dev/null || \
    .venv/bin/pip install --quiet -r requirements-h1.txt
fi
ROUTER_URL="${ROUTER_URL:-http://127.0.0.1:18080}"
WALLET="${WALLET:-0x945e579Df27859a9F65BD68FBa5cD37F64e1Ec5B}"
echo "router transport configured"
echo "wallet: $WALLET"
echo "engine: http://127.0.0.1:11436 (tu motor Atenhea local, ya corriendo)"
if [[ "$ROUTER_URL" == https://* ]]; then
  if [[ -z "${ROUTER_CA_FILE:-}" || -z "${NODE_ENROLLMENT_TOKEN_FILE:-}" ]]; then
    echo "Para HTTPS define ROUTER_CA_FILE y NODE_ENROLLMENT_TOKEN_FILE (rutas de fichero, no secretos en texto)." >&2
    exit 1
  fi
  exec "$PY" worker2.py --router "$ROUTER_URL" \
    --router-ca "$ROUTER_CA_FILE" --enrollment-token-file "$NODE_ENROLLMENT_TOKEN_FILE" \
    --atenea http://127.0.0.1:11436 --wallet "$WALLET"
fi
if [[ -n "${ROUTER_CA_FILE:-}" || -n "${NODE_ENROLLMENT_TOKEN_FILE:-}" ]]; then
  echo "ROUTER_CA_FILE y NODE_ENROLLMENT_TOKEN_FILE solo se usan con ROUTER_URL HTTPS." >&2
  exit 1
fi
exec "$PY" worker2.py --router "$ROUTER_URL" \
  --atenea http://127.0.0.1:11436 --wallet "$WALLET"
