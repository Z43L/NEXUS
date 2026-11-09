# NEXUS v0.1 runtime (testnet alpha)

Executable core of NEXUS: coordinator, node agent, staged inference spread over separate processes,
signed receipts, SQLite contribution ledger with settlement batches, an OpenAI-compatible gateway and a CLI.
Python 3.9, **stdlib only** (numpy/cryptography are not required; `cryptography` is used automatically if installed).
No token, no real-money settlement. Ningún operador posee el modelo completo en reposo; un nodo sí tiene su slot en claro
en memoria, y una coalición lo bastante grande podría reconstruir el modelo.

## Architecture

```
client -> nexus_api.Gateway (API key, rate limit, OpenAI JSON)
              | EngineAdapter  (NexusPipelineEngine, or AtenheaEngine = single-node forward to :11436)
              v
         nexus_runtime.Pipeline  --embed--> stage 0 -> stage 1 -> ... -> stage S-1 --head--> token
              | Scheduler/SlotRouter: smooth weighted round-robin by node speed, retry + failover
              v
   Node agents (one process each; one slot = a contiguous range of layers) --signed receipt per stage call-->
   Coordinator: registry, stratified slot assignment, plan, heartbeats  +  Ledger (SQLite) -> settlement batch
   nexus_storage (other package): publish (split/encrypt/erasure code/manifest) and fetch_slot / KeyVault
```

| Module | Role |
|---|---|
| `nexus_runtime/model_demo.py` | Tiny deterministic residual-MLP LM (8 layers, d=64), serialisable layers, single-process reference pass |
| `coordinator.py` | Enrol (signed), measured-vs-declared speed (never above measured), close registry, **stratified assignment, one operator = one slot** (adapted from `research/swarm-sim`), plan, heartbeat/down detection, receipt intake |
| `node.py` | Enrol with public key, get slot, load layers (`layers.py`), serve `/stage`, sign one receipt per call |
| `scheduler.py`, `pipeline.py` | Per-stage routing proportional to speed, failover, per-hop latency and tok/s |
| `receipts.py`, `ledger.py` | Ed25519 receipts; SQLite ledger (work units per node, `work_share` per slot); settlement batch with Merkle-sum root |
| `_batch_builder.py` | Unmodified copy of `NEXUS/settlement-evm/batch_builder.py` (keccak, leaf V2, sorted-pair Merkle-sum) |
| `nexus_api/` | `gateway.py` (`/healthz`, `/v1/models`, `/v1/chat/completions`, non-streaming) and `engine.py` (`EngineAdapter`) |
| `nexus_cli/` | `python3 -m nexus_cli {publish,coordinator,node,gateway,demo,verify-receipt,settle}` |
| `deploy/` | `run_demo.sh` (no Docker), `Dockerfile`, `docker-compose.yml`, `docker_smoke.sh` (Docker end-to-end check) |

## Run

```bash
cd nexus-project/code
PYTHONPATH=. python3 -m unittest discover -s tests/runtime -v      # 18 tests
deploy/run_demo.sh                                                 # 1 coordinator + 6 node processes, JSON report
deploy/run_demo.sh --stub                                          # same, without nexus_storage (plain layer files)
NEXUS_USE_VENV=1 deploy/run_demo.sh                                # with .venv (cryptography => faster Ed25519)

# by hand
python3 -m nexus_cli publish --out-model-dir /tmp/m --store /tmp/s --slots 3
python3 -m nexus_cli coordinator --slots 3 --manifest /tmp/m/manifest.json --master-key-file /tmp/m/master.key --expect-nodes 6
python3 -m nexus_cli node --coordinator http://127.0.0.1:8700 --operator opA --store /tmp/s     # x6, distinct operators
python3 -m nexus_cli gateway --create-key me --api-keys keys.json                                # prints key once
python3 -m nexus_cli gateway --coordinator http://127.0.0.1:8700 --model-dir /tmp/m --api-keys keys.json
curl -s localhost:8800/v1/chat/completions -H "Authorization: Bearer <key>" -d '{"model":"nexus-demo-mlp-8L","messages":[{"role":"user","content":"hi"}]}'
```

## Measured (this machine, macOS, Python 3.9.6, loopback, one run each, indicative only)

Demo: 6 node processes, 3 slots, 8 layers, 24 tokens, `nexus_storage` real path; node slowdowns 1x–3x are a *simulation knob*.

| Metric | system Python (pure-Python Ed25519) | `.venv` (`cryptography` Ed25519) |
|---|---|---|
| Distributed tok/s | 74.5 | 170.2 |
| Mean hop latency (client-observed, per stage call) | 4.39 ms | 1.88 ms |
| Mean node compute per hop | 1.48 ms | 1.50 ms |
| Single-process reference tok/s (same machine) | 236.8 | 224.8 |
| Output identical to single-process reference | yes | yes |
| Failover (one node process killed with `kill -9`, same prompt) | 1 failover, identical output, 70.6 tok/s | 1 failover, identical output, 172.2 tok/s |

Reading: on loopback the staged pipeline is slower than the single-process pass, as expected (HTTP+JSON+base64+signing per hop); the
difference between columns is receipt-signing cost. These are **not** WAN numbers and say nothing about real models.
Work share in the demo matched speed-proportional expectation (e.g. 0.708/0.292 actual vs 0.713/0.287 expected).

## Real vs stand-in

Real: staged execution across OS processes with bit-identical results; layer serialisation; slot assignment and routing logic;
failover; signed receipts and tamper rejection; SQLite ledger; settlement batch built with the escrow's own leaf/Merkle-sum code;
`nexus_storage.fetch_slot` path (encrypted, erasure-coded, Merkle-verified) is used by default in the demo and covered by a test.

Stand-in / not production:
- **Model**: random-weight, untrained MLP; output is gibberish. It proves the plumbing, not model quality. Embedding/head live on the client side.
- **Crypto**: pure-Python Ed25519 fallback is **NOT AUDITED – replace with vetted library** (variable-time). `cryptography` used if present.
- **Transport**: plain HTTP, no TLS. `/stage` requires a shared bearer secret when `NEXUS_STAGE_TOKEN` is set (mandatory in the compose file; constant-time compare) — a shared secret, not per-client identity; the coordinator hands slot keys over plain HTTP and acts as key custodian (`KeyVault` attestation is simulated).
- **Beacon**: `sha256(registry commitment || seed)` supplied by the operator, not a public randomness beacon. Registry is closed once; no late joins/epochs.
- **Trust**: single coordinator process, no consensus. Receipts prove a node *claims* to have processed hashes; correctness is only spot-checked (optional `spot_check_rate`), no fraud proofs or stake.
- **Settlement**: wallet addresses are `keccak(pubkey)[12:]` stand-ins; one job per node per batch (not per request), `amount = work_units * price_per_unit`; batches are built but nothing is sent on-chain. `StubLayerSource` (plain files) exists only for `--stub`.
- `docker-compose.yml` was written but **not run** (Docker not exercised); `run_demo.sh` is the tested path.
- Gateway: no streaming, no tokenizer beyond printable ASCII, limits are simple per-key token buckets.
- Ledger differences vs the H0 path: aggregation per node (see `ledger.py` docstring); contract splits author/node/treasury shares itself.

## Docker (validated 2026-11-09, Colima / Docker 29)

```bash
deploy/docker_smoke.sh      # builds image, compose up (publisher -> coordinator -> 4 nodes -> gateway), checks:
                            # 401 on unauthenticated /stage, chat through the gateway, receipts in the ledger,
                            # settlement batch with Merkle-sum root; then tears everything down
# interactive:
export NEXUS_STAGE_TOKEN=$(openssl rand -hex 24)
docker compose -f deploy/docker-compose.yml up --build      # gateway logs print a bootstrap API key once
```
Fixes made during validation: gateway had no API key on first start (now `--bootstrap-key`), coordinator could start before the
publisher finished (now `service_completed_successfully`). Not covered by the smoke: node failure inside Docker (covered by the
local demo/tests), multi-host networking, TLS.
