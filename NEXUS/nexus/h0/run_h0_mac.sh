#!/bin/sh
# NEXUS x Atenhea - H0 runner for David's Mac.
# Everything runs on this machine: Atenhea (real engine) + Router + worker + client.
# Usage:  cd ~/Desktop/nexus-h0 && ./run_h0_mac.sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

ATENHEA_DIR=${ATENHEA_DIR:-"$SCRIPT_DIR/../../atenhea"}
PY=.venv/bin/python

# 1) Python env (H0-pinned cryptography for Ed25519 receipts)
if [ ! -x "$PY" ]; then
  echo ">> creating .venv"
  python3 -m venv .venv
fi
if ! "$PY" -c 'import cryptography; assert cryptography.__version__ == "50.0.2"' 2>/dev/null; then
  .venv/bin/pip install --quiet -r "$SCRIPT_DIR/requirements-h0.txt"
fi

# 2) Atenhea engine: the worker talks to the ENGINE at :11436 (not the :11434
#    agent proxy), so H0 jobs never touch CHL memory or local tools.
engine_up() { curl -s -m 3 http://127.0.0.1:11436/v1/models >/dev/null 2>&1; }
proxy_up()  { curl -s -m 3 http://127.0.0.1:11434/v1/models >/dev/null 2>&1; }

if engine_up; then
  echo ">> Atenhea engine already running at :11436"
elif proxy_up; then
  echo "!! Atenhea proxy at :11434 is up but the engine port :11436 does not answer."
  echo "   Stop the current Atenhea and re-run this script; it will start the nram backend."
  exit 1
else
  echo ">> starting Atenhea (nram backend) from $ATENHEA_DIR"
  if [ -x "$ATENHEA_DIR/start-athenea.sh" ]; then
    (cd "$ATENHEA_DIR" && nohup ./start-athenea.sh >"$SCRIPT_DIR/atenea-h0.log" 2>&1 &)
  else
    echo "!! Atenhea launcher not found at $ATENHEA_DIR/start-athenea.sh."
    echo "   Set ATENHEA_DIR to the integrated NEXUS/atenhea directory."
    exit 1
  fi
  i=0
  while [ $i -lt 90 ]; do
    if engine_up; then break; fi
    i=$((i+1)); sleep 2
  done
  engine_up || { echo "!! engine did not come up in 180s - see atenea-h0.log"; exit 1; }
  echo ">> Atenhea engine up"
fi

# 3) Jobs batch; archive any previous run's ledger/report for a clean gate
if [ -f nexus_h0.db ]; then
  mv nexus_h0.db "nexus_h0.db.bak-$(date +%s)"
fi
[ -f h0_report.json ] && mv h0_report.json "h0_report.json.bak-$(date +%s)"
[ -f jobs.jsonl ] || $PY gen_jobs.py

# 4) Router + worker (killed at the end; Atenhea is left running)
$PY router.py --port 18080 --dir . >router-h0.log 2>&1 &
ROUTER_PID=$!
$PY worker_agent.py --router http://127.0.0.1:18080 \
  --atenea http://127.0.0.1:11436 --node-dir ./node >worker-h0.log 2>&1 &
WORKER_PID=$!
cleanup() { kill $ROUTER_PID $WORKER_PID 2>/dev/null || true; }
trap cleanup EXIT INT TERM
sleep 3

# 5) Dogfood run: 100 jobs + tools probe -> h0_report.json
$PY dogfood_client.py --router http://127.0.0.1:18080 --timeout-s 7200
echo ""
echo ">> H0 run finished. Report: $(pwd)/h0_report.json"
echo ">> Send David's assistant the h0_report.json (or just say 'H0 ejecutado')."
