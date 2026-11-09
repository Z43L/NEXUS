#!/usr/bin/env bash
# Docker smoke test: compose up (coordinator + 4 nodes + gateway), chat through the gateway, check ledger. Testnet only.
# Usage: deploy/docker_smoke.sh   (from anywhere; needs a running Docker daemon)
set -euo pipefail
cd "$(dirname "$0")/.."
export NEXUS_STAGE_TOKEN=$(openssl rand -hex 24)
P=nexus-smoke; C="docker compose -f deploy/docker-compose.yml -p $P"
trap '$C down -v --remove-orphans >/dev/null 2>&1' EXIT
$C down -v --remove-orphans >/dev/null 2>&1 || true
$C up -d --build >/dev/null
for i in $(seq 1 60); do curl -fs localhost:8800/healthz >/dev/null 2>&1 && break; sleep 1; done
KEY=$($C logs gateway 2>&1 | sed -n "s/.*bootstrap API key 'compose' (shown once): //p" | head -1)
[ -n "$KEY" ] || { echo "FAIL: no bootstrap key"; $C logs gateway; exit 1; }
for i in $(seq 1 30); do
  R=$(curl -s localhost:8800/v1/chat/completions -H "Authorization: Bearer $KEY" \
      -d '{"model":"nexus-demo-mlp-8L","messages":[{"role":"user","content":"hi"}],"max_tokens":8}' || true)
  echo "$R" | grep -q '"choices"' && break; sleep 2
done
echo "$R" | grep -q '"choices"' || { echo "FAIL: chat: $R"; $C logs --tail=20; exit 1; }
# nodes must reject /stage without the token (they are not exposed on the host, so probe from the gateway container)
CODE=$($C exec -T gateway python - <<'PY' 2>&1 | tail -1
import urllib.request, urllib.error
try:
    urllib.request.urlopen(urllib.request.Request("http://node1:8701/stage", data=b"{}", headers={"Content-Type": "application/json"}))
except urllib.error.HTTPError as e:
    print(e.code)
PY
)
[ "$CODE" = "401" ] || { echo "FAIL: node accepted unauthenticated /stage (got $CODE)"; exit 1; }
echo "stage auth OK (401 without token)"
echo "chat OK: $R" | cut -c1-300
# receipts must have reached the coordinator ledger (async intake: poll briefly)
N=0
for i in $(seq 1 15); do
  N=$($C exec -T coordinator python -c "
import sqlite3;c=sqlite3.connect('/data/ledger.sqlite')
print(sum(c.execute('select count(*) from '+t[0]).fetchone()[0] for t in c.execute(\"select name from sqlite_master where type='table'\").fetchall()))" 2>/dev/null || echo 0)
  [ "${N:-0}" -gt 0 ] && break; sleep 1
done
[ "${N:-0}" -gt 0 ] || { echo "FAIL: ledger empty"; exit 1; }
echo "ledger rows: $N"
B=0x$(printf '%064d' 1)
$C exec -T coordinator python -m nexus_cli settle --ledger /data/ledger.sqlite --batch-id "$B" --price-per-unit 1 \
  --escrow 0x1111111111111111111111111111111111111111 --token 0x2222222222222222222222222222222222222222 > /tmp/nexus_batch.json \
  || { echo "FAIL: settle"; exit 1; }
grep -q '"root"' /tmp/nexus_batch.json || { echo "FAIL: settlement batch has no root"; exit 1; }
echo "settlement batch built: $(grep -c '"proof"' /tmp/nexus_batch.json) claims"
echo "SMOKE PASSED"
