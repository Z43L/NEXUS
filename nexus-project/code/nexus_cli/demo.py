"""End-to-end local demo: coordinator + N node PROCESSES + pipeline + gateway + settlement."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from nexus_runtime import httpx
from nexus_runtime.layers import storage_available
from nexus_runtime.ledger import Ledger
from nexus_runtime.model_demo import DemoModel, tok_decode, tok_encode
from nexus_runtime.pipeline import Pipeline


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def run_demo(a) -> int:
    tmp = tempfile.mkdtemp(prefix="nexus-demo-")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [os.getcwd(), env.get("PYTHONPATH", "")]))
    procs = []
    use_storage = storage_available() and not a.stub
    cli = [sys.executable, "-m", "nexus_cli"]
    mdir, store = os.path.join(tmp, "model"), os.path.join(tmp, "store")
    out = {"python": sys.version.split()[0], "storage": "nexus_storage" if use_storage else "stub (plain files)"}
    try:
        base = {"stdout": open(os.path.join(tmp, "procs.log"), "ab"), "stderr": subprocess.STDOUT, "env": env}
        if use_storage:
            subprocess.run(cli + ["publish", "--out-model-dir", mdir, "--store", store, "--slots", str(a.slots)],
                           check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ckw = ["--manifest", os.path.join(mdir, "manifest.json"),
                   "--master-key-file", os.path.join(mdir, "master.key")]
            nsrc = ["--store", store]
        else:
            DemoModel().save(mdir)
            ckw, nsrc = [], ["--model-dir", mdir]
        model = DemoModel()  # reference copy (same seed)
        cport = _free_port()
        curl = "http://127.0.0.1:%d" % cport
        procs.append(subprocess.Popen(cli + ["coordinator", "--port", str(cport), "--slots", str(a.slots),
                                             "--ledger", os.path.join(tmp, "ledger.sqlite"),
                                             "--expect-nodes", str(a.nodes), "--close-seed", "demo-beacon",
                                             "--hb-timeout", "3"] + ckw, **base))
        _wait(lambda: httpx.call(curl, "/healthz", timeout=1))
        slow = [1.0, 1.0, 1.0, 2.0, 1.0, 3.0, 1.0, 1.5]
        node_procs = []
        for i in range(a.nodes):
            np_ = subprocess.Popen(cli + ["node", "--coordinator", curl, "--operator", "op%d" % i,
                                          "--slowdown", str(slow[i % len(slow)])] + nsrc, **base)
            node_procs.append(np_); procs.append(np_)
        _wait(lambda: httpx.call(curl, "/plan", timeout=1)["closed"] and _all_loaded(curl), 60)
        plan = httpx.call(curl, "/plan")
        out["slots"] = [{"slot": s["slot"], "layers": [s["layer_lo"], s["layer_hi"]],
                         "nodes": [{"node": n["node_id"][:8], "operator": n["operator"],
                                    "speed_layer_passes_s": round(n["weight"], 1)} for n in s["nodes"]]}
                        for s in plan["slots"]]
        out["processes"] = {"coordinator": 1, "nodes": a.nodes}

        head = DemoModel.load_head(mdir)
        pipe = Pipeline(curl, head)
        ids = tok_encode("hello nexus")
        pipe.generate(ids, 3, req_id="warmup", submit_receipts=False)
        t0 = time.perf_counter()
        ref = model.reference_generate(ids, a.tokens)
        ref_s = time.perf_counter() - t0
        r = pipe.generate(ids, a.tokens, req_id="demo-1")
        out["equivalent_to_reference"] = r["tokens"] == ref
        out["distributed"] = {"tokens": a.tokens, "tok_s": round(r["tok_s"], 2),
                              "mean_hop_ms": round(r["mean_hop_ms"], 2),
                              "mean_node_compute_ms": round(r["mean_compute_ms"], 2),
                              "max_hop_ms": round(r["max_hop_ms"], 2), "hops": r["hops"],
                              "receipts": len(r["receipts"]), "accepted_by_ledger": r["submitted"]["accepted"]}
        out["single_process_reference"] = {"tok_s": round(a.tokens / ref_s, 2)}

        # work share vs expected (measured over the first generation only, before any node dies)
        out["work_share"] = {}
        for s in plan["slots"]:
            ws = httpx.call(curl, "/work_share?slot=%d" % s["slot"])
            out["work_share"]["slot%d" % s["slot"]] = {
                k[:8]: {"actual": round(ws["share"].get(k, 0), 3), "expected_by_speed": round(v, 3)}
                for k, v in ws["expected"].items()}
        # failover: kill one node of a slot that has a peer, generate again
        victim = None
        for s in plan["slots"]:
            if len(s["nodes"]) >= 2:
                victim = s["nodes"][0]; break
        if victim:
            pid_url = victim["url"]
            port = int(pid_url.rsplit(":", 1)[1])
            _kill_node_on_port(node_procs, port, tmp)
            r2 = pipe.generate(ids, a.tokens, req_id="demo-2")
            out["failover"] = {"killed": victim["node_id"][:8], "equivalent_to_reference": r2["tokens"] == ref,
                               "failovers": r2["failovers"], "tok_s": round(r2["tok_s"], 2)}
        # gateway round trip (in-process gateway, remote pipeline)
        from nexus_api.engine import NexusPipelineEngine
        from nexus_api.gateway import ApiKeyStore, Gateway
        keys = ApiKeyStore()
        key = keys.create("demo")
        gsrv = Gateway(NexusPipelineEngine(curl, mdir), keys).serve()
        gurl = "http://127.0.0.1:%d" % gsrv.port
        t0 = time.perf_counter()
        resp = httpx.call(gurl, "/v1/chat/completions",
                          {"model": model.model_id, "max_tokens": 8,
                           "messages": [{"role": "user", "content": "hello"}]},
                          headers={"Authorization": "Bearer " + key}, timeout=60)
        out["gateway"] = {"status": "ok", "usage": resp["usage"], "latency_s": round(time.perf_counter() - t0, 3),
                          "content_is_untrained_gibberish": resp["choices"][0]["message"]["content"]}
        gsrv.stop()
        # settlement from the coordinator's SQLite ledger (read the file directly)
        time.sleep(0.3)
        led = Ledger(os.path.join(tmp, "ledger.sqlite"))
        ctx = {"chainId": 31337, "escrowAddress": "0x" + "ab" * 20, "tokenAddress": "0x" + "cd" * 20}
        doc = led.build_settlement("0x" + "01" * 32, ctx, 1000)
        out["settlement"] = {"receipts_in_ledger": led.count(), "jobs": len(doc["claims"]),
                             "root": doc["root"], "rootSum": doc["rootSum"],
                             "all_claims_verify": Ledger.verify_batch_doc(doc)}
        print(json.dumps(out, indent=2))
        return 0 if out["equivalent_to_reference"] else 1
    finally:
        for p_ in procs:
            if p_.poll() is None:
                p_.terminate()
        for p_ in procs:
            try:
                p_.wait(5)
            except Exception:
                p_.kill()
        if not a.keep:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            print("kept", tmp, file=sys.stderr)


def _all_loaded(curl):
    plan = httpx.call(curl, "/plan", timeout=1)
    ns = [n for s in plan["slots"] for n in s["nodes"]]
    if not ns or not all(s["nodes"] for s in plan["slots"]):
        return False
    for n in ns:
        try:
            if httpx.call(n["url"], "/healthz", timeout=1).get("slot") is None:
                return False
        except Exception:
            return False
    return True


def _kill_node_on_port(node_procs, port, tmp):
    import re
    out = subprocess.run(["lsof", "-ti", "tcp:%d" % port, "-sTCP:LISTEN"], capture_output=True, text=True).stdout
    for pid in out.split():
        os.kill(int(pid), 9)


def _wait(fn, timeout=30):
    t0 = time.time()
    while True:
        try:
            if fn():
                return
        except Exception:
            pass
        if time.time() - t0 > timeout:
            raise TimeoutError("demo step timed out")
        time.sleep(0.2)
