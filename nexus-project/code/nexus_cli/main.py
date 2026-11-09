"""`nexus` command line (run as `python3 -m nexus_cli <command>`)."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time


def _wait_forever():
    ev = threading.Event()
    for s in (signal.SIGINT, signal.SIGTERM):
        signal.signal(s, lambda *a: ev.set())
    ev.wait()


def cmd_publish(a):
    from nexus_runtime.layers import storage_available
    if not storage_available():
        print("error: nexus_storage not importable (set PYTHONPATH to the code/ directory)", file=sys.stderr)
        return 2
    from nexus_storage import DirStore, generate_signer, publish_model
    from nexus_runtime.model_demo import DemoModel
    if a.model_src:  # REAL model (HF safetensors checkpoint, Llama architecture)
        import shutil
        from nexus_runtime import llama
        blobs, meta, head = llama.convert(a.model_src)
        model_id = a.model_id or os.path.basename(os.path.normpath(a.model_src))
        os.makedirs(a.out_model_dir, exist_ok=True)
        with open(os.path.join(a.out_model_dir, "meta.json"), "w") as f:
            json.dump({**meta, "model_id": model_id}, f)
        with open(os.path.join(a.out_model_dir, "head.bin"), "wb") as f:
            f.write(head)
        shutil.copy(os.path.join(a.model_src, "tokenizer.json"), a.out_model_dir)
    else:
        m = DemoModel(n_layers=a.layers, seed=a.seed)
        m.save(a.out_model_dir)  # plain copy: client-side head + stub source
        blobs, model_id = m.layer_blobs(), m.model_id
    os.makedirs(a.store, exist_ok=True)
    signer = generate_signer()
    manifest, master = publish_model(blobs, model_id=model_id, version=a.version,
                                     n_slots=a.slots, ec_k=a.ec_k, ec_n=a.ec_n, store=DirStore(a.store),
                                     author_signer=signer, license=a.license, royalty_bps=a.royalty_bps)
    with open(os.path.join(a.out_model_dir, "manifest.json"), "w") as f:
        f.write(manifest.to_json())
    fd = os.open(os.path.join(a.out_model_dir, "master.key"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(master.hex())
    print(json.dumps({"model_id": manifest.model_id, "manifest_id": manifest.manifest_id(),
                      "slots": a.slots, "verified": manifest.verify(),
                      "manifest": os.path.join(a.out_model_dir, "manifest.json"),
                      "master_key_file": os.path.join(a.out_model_dir, "master.key")}, indent=2))
    print("note: master.key is a TESTNET secret held by the coordinator-side vault; keep it out of git.",
          file=sys.stderr)
    return 0


def cmd_coordinator(a):
    from nexus_runtime.coordinator import Coordinator
    from nexus_runtime.ledger import Ledger
    kw = {}
    if a.manifest:
        from nexus_storage import KeyVault
        with open(a.manifest) as f:
            kw["manifest_json"] = f.read()
        with open(a.master_key_file) as f:
            vault = KeyVault(bytes.fromhex(f.read().strip()))
        kw["key_provider"] = lambda nid, slot: vault.grant(nid, slot)
    c = Coordinator(a.slots, a.layers, a.model_id, ledger=Ledger(a.ledger), hb_timeout=a.hb_timeout, **kw)
    c.serve(a.host, a.port)
    print("coordinator listening on %s" % c.url, flush=True)
    if a.expect_nodes:
        def auto():
            while len(c.nodes) < a.expect_nodes:
                time.sleep(0.2)
            time.sleep(a.close_delay)
            print("registry closed:", json.dumps(c.close_registry(a.close_seed)), flush=True)
        threading.Thread(target=auto, daemon=True).start()
    _wait_forever()
    return 0


def cmd_node(a):
    from nexus_runtime.crypto import Ed25519Signer, load_or_create_signer
    from nexus_runtime.layers import StorageLayerSource, StubLayerSource
    from nexus_runtime.node import NodeAgent
    src = StorageLayerSource(a.store) if a.store else StubLayerSource(a.model_dir)
    signer = load_or_create_signer(a.key_file) if a.key_file else Ed25519Signer()
    n = NodeAgent(a.coordinator, signer, operator=a.operator, host=a.host, port=a.port,
                  advertise_url=a.advertise, layer_source=src, slowdown=a.slowdown)
    n.start()
    print("node %s... enrolled, serving at %s (measured %.1f layer-passes/s, source=%s)"
          % (n.node_id[:12], n.url, n.measured, src.kind), flush=True)
    a_ = n.wait_for_slot(a.wait)
    print("slot %d layers [%d,%d)" % (a_["slot"], a_["layer_lo"], a_["layer_hi"]), flush=True)
    _wait_forever()
    n.stop()
    return 0


def cmd_gateway(a):
    from nexus_api.engine import NexusPipelineEngine
    from nexus_api.gateway import ApiKeyStore, Gateway
    keys = ApiKeyStore(a.api_keys)
    if a.create_key:
        print("new API key (shown once):", keys.create(a.create_key))
        if not a.coordinator and a.engine == "pipeline":
            return 0
    if not keys.keys and a.bootstrap_key:
        print("bootstrap API key '%s' (shown once):" % a.bootstrap_key, keys.create(a.bootstrap_key), flush=True)
    if not keys.keys:
        print("error: no API keys; run with --create-key NAME first", file=sys.stderr)
        return 2
    if a.engine == "atenhea":
        from nexus_api.engine import AtenheaEngine
        eng = AtenheaEngine(a.atenhea_url)
    else:
        if not (a.coordinator and a.model_dir):
            print("error: --coordinator and --model-dir are required for the pipeline engine", file=sys.stderr)
            return 2
        eng = NexusPipelineEngine(a.coordinator, a.model_dir)
    g = Gateway(eng, keys)
    srv = g.serve(a.host, a.port)
    print("gateway listening on http://%s:%d" % (a.host, srv.port), flush=True)
    _wait_forever()
    return 0


def cmd_verify(a):
    from nexus_runtime.receipts import verify_receipt
    doc = json.load(sys.stdin if a.file == "-" else open(a.file))
    rs = doc if isinstance(doc, list) else [doc]
    bad = [i for i, r in enumerate(rs) if not verify_receipt(r)]
    print(json.dumps({"checked": len(rs), "valid": len(rs) - len(bad), "invalid_indexes": bad}))
    return 0 if not bad else 1


def cmd_settle(a):
    from nexus_runtime.ledger import Ledger
    led = Ledger(a.ledger)
    ctx = {"chainId": a.chain_id, "escrowAddress": a.escrow, "tokenAddress": a.token}
    doc = led.build_settlement(a.batch_id, ctx, a.price_per_unit, author_address=a.author)
    print(json.dumps(doc, indent=2))
    return 0


def cmd_demo(a):
    from .demo import run_demo
    return run_demo(a)


def main(argv=None):
    p = argparse.ArgumentParser(prog="nexus", description="NEXUS v0.1 testnet CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("publish", help="split+encrypt+erasure-code a demo model via nexus_storage")
    s.add_argument("--out-model-dir", required=True); s.add_argument("--store", required=True)
    s.add_argument("--slots", type=int, default=4); s.add_argument("--layers", type=int, default=8)
    s.add_argument("--ec-k", type=int, default=4); s.add_argument("--ec-n", type=int, default=6)
    s.add_argument("--model-src", help="HF safetensors dir of a Llama-architecture model (real model path)"); s.add_argument("--model-id")
    s.add_argument("--version", default="1"); s.add_argument("--license", default="demo-only")
    s.add_argument("--royalty-bps", type=int, default=0); s.add_argument("--seed", type=int, default=1234)
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("coordinator", help="run the coordinator")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8700)
    s.add_argument("--slots", type=int, default=4); s.add_argument("--layers", type=int, default=8)
    s.add_argument("--model-id", default="nexus-demo-mlp-8L"); s.add_argument("--ledger", default="ledger.sqlite")
    s.add_argument("--hb-timeout", type=float, default=6.0)
    s.add_argument("--manifest"); s.add_argument("--master-key-file")
    s.add_argument("--expect-nodes", type=int, default=0, help="auto-close registry after N nodes enrol")
    s.add_argument("--close-delay", type=float, default=1.0); s.add_argument("--close-seed", default="")
    s.set_defaults(fn=cmd_coordinator)

    s = sub.add_parser("node", help="run a node agent")
    s.add_argument("--coordinator", required=True); s.add_argument("--operator")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=0)
    s.add_argument("--advertise"); s.add_argument("--key-file")
    s.add_argument("--slowdown", type=float, default=1.0, help="SIMULATION: emulate a slower machine")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--store", help="DirStore with published fragments (real nexus_storage path)")
    g.add_argument("--model-dir", help="STAND-IN: plain layer files")
    s.add_argument("--wait", type=float, default=300.0)
    s.set_defaults(fn=cmd_node)

    s = sub.add_parser("gateway", help="OpenAI-compatible gateway")
    s.add_argument("--coordinator"); s.add_argument("--model-dir")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8800)
    s.add_argument("--api-keys", default="api_keys.json"); s.add_argument("--create-key"); s.add_argument("--engine", choices=["pipeline", "atenhea"], default="pipeline"); s.add_argument("--atenhea-url", default="http://127.0.0.1:11436"); s.add_argument("--bootstrap-key", help="create this key only if the store is empty")
    s.set_defaults(fn=cmd_gateway)

    s = sub.add_parser("verify-receipt", help="verify signed receipt(s) from a JSON file or '-'")
    s.add_argument("file"); s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("settle", help="build a settlement batch from the ledger")
    s.add_argument("--ledger", required=True); s.add_argument("--batch-id", required=True)
    s.add_argument("--price-per-unit", type=int, required=True)
    s.add_argument("--chain-id", type=int, default=31337)
    s.add_argument("--escrow", required=True); s.add_argument("--token", required=True)
    s.add_argument("--author", default="0x" + "00" * 20)
    s.set_defaults(fn=cmd_settle)

    s = sub.add_parser("demo", help="end-to-end local demo with separate node processes")
    s.add_argument("--nodes", type=int, default=6); s.add_argument("--slots", type=int, default=3)
    s.add_argument("--tokens", type=int, default=24)
    s.add_argument("--stub", action="store_true", help="skip nexus_storage, use plain layer files")
    s.add_argument("--keep", action="store_true", help="keep the working directory")
    s.set_defaults(fn=cmd_demo)

    a = p.parse_args(argv)
    return a.fn(a)
