"""Node agent: enrol, receive a slot, load its layers, serve its stage, sign receipts.

The node holds its slot's layers in clear in memory (unavoidable without TEE/MPC;
see BRIEF section 2). Layer retrieval goes through a LayerSource: the real one is
nexus_storage.fetch_slot; StubLayerSource is a stand-in (see layers.py).
"""
from __future__ import annotations

import hmac
import os
import random
import threading
import time
from collections import OrderedDict
from typing import Optional

from . import httpx
from .crypto import Ed25519Signer, Signer
from .model_demo import Layer, apply_layers, vec_from_b64, vec_to_b64, pack_vec
from .receipts import make_receipt, sha256_hex, canonical
from .coordinator import enroll_message


def bench_layer_speed(layer: Layer, slowdown: float = 1.0, iters: int = 30) -> float:
    """Layer-passes per second on this machine (includes the simulated slowdown)."""
    rng = random.Random(7)
    x = [rng.gauss(0, 1) for _ in range(layer.d)]
    t0 = time.perf_counter()
    for _ in range(iters):
        layer.forward(x)
    dt = (time.perf_counter() - t0) * slowdown
    return iters / dt


class _CacheMiss(Exception):
    def __init__(self, have):
        self.have = have


class NodeAgent:
    def __init__(self, coordinator_url: str, signer: Optional[Signer] = None, operator: str = None,
                 host: str = "127.0.0.1", port: int = 0, advertise_url: str = None,
                 layer_source=None, slowdown: float = 1.0, declared_speed: float = None,
                 hb_interval: float = 1.0, d: int = 64, h: int = 128, stage_token: Optional[str] = None):
        self.coord = coordinator_url.rstrip("/")
        self.signer = signer or Ed25519Signer()
        self.node_id = self.signer.public_key_hex
        self.operator = operator or self.node_id
        self.layer_source, self.slowdown = layer_source, max(1.0, slowdown)
        self.declared_speed, self.hb_interval = declared_speed, hb_interval
        self.host, self.port, self.advertise_url = host, port, advertise_url
        self.d, self.h = d, h
        # shared secret the scheduler must present on /stage (bearer). Empty = open (testnet/loopback only).
        self.stage_token = stage_token if stage_token is not None else os.environ.get("NEXUS_STAGE_TOKEN", "")
        self.layers = []
        self.kind = "mlp"
        self.states = OrderedDict()  # req_id -> StageState (llama KV caches), LRU-bounded
        self.max_states = 32
        self.assignment = None
        self.served = 0
        self._stop = threading.Event()
        self._srv = None
        self._lock = threading.Lock()

    # ---- lifecycle ----------------------------------------------------------
    def start(self):
        self._srv = httpx.JsonServer(self.host, self.port, self._handle).start()
        self.port = self._srv.port
        self.url = self.advertise_url or "http://%s:%d" % (self.host, self.port)
        probe = Layer.random(self.d, self.h, random.Random(1))
        self.measured = bench_layer_speed(probe, self.slowdown)
        declared = self.declared_speed if self.declared_speed is not None else self.measured
        req = {"node_id": self.node_id, "operator": self.operator, "url": self.url,
               "declared_speed": declared, "measured_speed": self.measured, "ts": int(time.time())}
        req["sig"] = self.signer.sign(enroll_message(req)).hex()
        httpx.call(self.coord, "/enroll", req)
        threading.Thread(target=self._hb_loop, daemon=True).start()
        return self

    def _hb_loop(self):
        while not self._stop.wait(self.hb_interval):
            try:
                httpx.call(self.coord, "/heartbeat", {"node_id": self.node_id, "load": self.served},
                           timeout=2.0)
            except Exception:
                pass

    def wait_for_slot(self, timeout: float = 30.0) -> dict:
        """Poll until the registry closes, then fetch this node's layers."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            a = httpx.call(self.coord, "/assignment?node_id=" + self.node_id)
            if a.get("ready"):
                layers = self.layer_source.get_layers(a)
                with self._lock:
                    if layers and layers[0][:4] == b"NXLL":
                        from . import llama  # numpy only needed for real-model slots
                        self.kind, self.layers = "llama", [llama.LlamaLayer.from_bytes(b) for b in layers]
                        self.d = self.layers[0].d
                    else:
                        self.kind, self.layers = "mlp", [Layer.from_bytes(b) for b in layers]
                    self.states.clear()
                    self.assignment = a
                return a
            time.sleep(0.1)
        raise TimeoutError("registry did not close in time")

    def stop(self):
        self._stop.set()
        if self._srv:
            self._srv.stop()

    # ---- serving ------------------------------------------------------------
    def _handle(self, method, path, q, body, headers):
        if method == "GET" and path == "/healthz":
            return 200, {"ok": True, "node_id": self.node_id, "slot": (self.assignment or {}).get("slot")}
        if method == "POST" and path == "/stage" and body is not None:
            if self.stage_token:
                got = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
                if not hmac.compare_digest(got.encode(), ("Bearer " + self.stage_token).encode()):
                    return 401, {"error": "unauthorized"}
            return self._stage(body)
        return 404, {"error": "not found"}

    def _stage(self, b):
        a = self.assignment
        if a is None or not self.layers:
            return 503, {"error": "no slot loaded"}
        if b.get("slot") != a["slot"]:
            return 409, {"error": "wrong slot"}
        try:
            x = vec_from_b64(b["x"])
            unit_id, req_id = b["unit_id"], b["req_id"]
        except (KeyError, ValueError):
            return 400, {"error": "bad request"}
        if len(x) != self.d:
            return 400, {"error": "bad dimension"}
        t0 = time.perf_counter()
        if self.kind == "llama":
            try:
                y = self._llama_step(req_id, x, b.get("step"), b.get("replay"))
            except _CacheMiss as e:
                return 409, {"error": "cache-miss", "have": e.have}
        else:
            y = apply_layers(self.layers, x)
        el = time.perf_counter() - t0
        if self.slowdown > 1.0:  # SIMULATION KNOB: emulate a weaker machine
            time.sleep(el * (self.slowdown - 1.0))
            el *= self.slowdown
        self.served += 1
        r = make_receipt(self.signer, unit_id=unit_id, req_id=req_id, model_id=a["model_id"],
                         slot=a["slot"], layer_lo=a["layer_lo"], layer_hi=a["layer_hi"],
                         work_units=len(self.layers), in_hash=sha256_hex(pack_vec(x)),
                         out_hash=sha256_hex(pack_vec(y)), compute_ms=el * 1000)
        return 200, {"y": vec_to_b64(y), "receipt": r, "compute_ms": el * 1000, "stateful": self.kind == "llama"}

    def _llama_step(self, req_id, x, step, replay):
        """One token through this slot's layers with the request's KV cache.

        `step` is the token position. If our cache is not exactly at `step` (new node after failover, lost reply, evicted),
        the caller must send `replay` = the inputs of steps 0..step-1 so we can rebuild it; otherwise 409 cache-miss.
        Replayed steps are recomputed but not receipted (overhead of failover is unpaid, by design in v0.1).
        """
        import numpy as np
        from . import llama
        if not isinstance(step, int) or step < 0:
            raise _CacheMiss(0)
        with self._lock:
            st = self.states.get(req_id)
            if st is not None:
                self.states.move_to_end(req_id)
        if st is None or st.n != step:
            if step == 0:
                st = llama.StageState(self.layers)
            elif isinstance(replay, list) and len(replay) == step:
                st = llama.StageState(self.layers)
                for rb in replay:
                    st.step(self.layers, np.asarray(vec_from_b64(rb), dtype=np.float32))
            else:
                raise _CacheMiss(st.n if st else 0)
            with self._lock:
                self.states[req_id] = st
                while len(self.states) > self.max_states:
                    self.states.popitem(last=False)
        y = st.step(self.layers, np.asarray(x, dtype=np.float32))
        return y.astype(np.float64).tolist()
