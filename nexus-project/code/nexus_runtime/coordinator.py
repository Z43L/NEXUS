"""Coordinator: node registry, slot assignment, plan, heartbeats, receipt intake.

Slot assignment is adapted from research/swarm-sim/swarmsim.py `assign_slots`
(strategy "stratified"): ONE OPERATOR = ONE SLOT. Operators are sorted by total
measured capacity, cut into blocks of S, and each block gets a random permutation
of slots drawn from a beacon seeded AFTER registry close, so an attacker cannot
choose its slot. Within a slot, routing weight is proportional to node speed.

STAND-INS: the beacon is sha256(registry commitment || caller-supplied seed) - a
real deployment needs a public randomness beacon (drand/VRF). The coordinator is a
single trusted process (no consensus), and also the key custodian in this MVP.
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
import time
from typing import Callable, Dict, List, Optional

from .crypto import verify
from .httpx import JsonServer
from .ledger import Ledger
from .model_demo import slot_ranges
from .receipts import canonical


def enroll_message(req: Dict) -> bytes:
    keys = ("node_id", "operator", "url", "declared_speed", "measured_speed", "ts")
    return b"NEXUS_ENROLL_V1" + canonical({k: req.get(k) for k in keys})


def effective_speed(declared: float, measured: Optional[float]) -> float:
    """Never trust a declaration above what was measured."""
    if measured is None or measured <= 0:
        return max(0.0, declared)
    return max(0.0, min(declared, measured))


def stratified_assign(operators: Dict[str, float], n_slots: int, seed_hex: str) -> Dict[str, int]:
    """operators: {operator_id: capacity}. Returns {operator_id: slot}. Each operator gets one slot."""
    if len(operators) < n_slots:
        raise ValueError("need at least %d operators for %d slots (have %d)"
                         % (n_slots, n_slots, len(operators)))
    rng = random.Random(int(seed_hex, 16))
    ops = sorted(operators.items(), key=lambda kv: (-kv[1], kv[0]))
    out: Dict[str, int] = {}
    for i in range(0, len(ops), n_slots):
        perm = list(range(n_slots))
        rng.shuffle(perm)
        for (op, _), s in zip(ops[i:i + n_slots], perm):
            out[op] = s
    return out


class Coordinator:
    def __init__(self, n_slots: int, n_layers: int, model_id: str, ledger: Optional[Ledger] = None,
                 hb_timeout: float = 6.0, manifest_json: Optional[str] = None,
                 key_provider: Optional[Callable[[str, int], bytes]] = None,
                 clock: Callable[[], float] = time.time):
        self.n_slots, self.n_layers, self.model_id = n_slots, n_layers, model_id
        self.ranges = slot_ranges(n_layers, n_slots)
        self.ledger = ledger or Ledger()
        self.hb_timeout, self.clock = hb_timeout, clock
        self.manifest_json, self.key_provider = manifest_json, key_provider
        self.nodes: Dict[str, Dict] = {}
        self.closed = False
        self.op_slot: Dict[str, int] = {}
        self.beacon: Optional[str] = None
        self._lock = threading.RLock()
        self.server: Optional[JsonServer] = None

    # ---- registry -----------------------------------------------------------
    def enroll(self, req: Dict):
        with self._lock:
            if self.closed:
                return False, "registry-closed"
            try:
                nid, op = req["node_id"], req["operator"]
                if not (isinstance(op, str) and op and isinstance(req["url"], str)):
                    return False, "bad-request"
                if not verify(nid, enroll_message(req), bytes.fromhex(req["sig"])):
                    return False, "bad-signature"
                declared = float(req["declared_speed"])
                measured = None if req.get("measured_speed") is None else float(req["measured_speed"])
            except (KeyError, ValueError, TypeError):
                return False, "bad-request"
            if nid in self.nodes and self.nodes[nid]["operator"] != op:
                return False, "node-key-bound-to-other-operator"
            self.nodes[nid] = {"node_id": nid, "operator": op, "url": req["url"],
                               "declared": declared, "measured": measured,
                               "speed": effective_speed(declared, measured),
                               "last_hb": self.clock(), "failed": False, "slot": None,
                               "load": 0}
            return True, "ok"

    def operator_capacity(self) -> Dict[str, float]:
        cap: Dict[str, float] = {}
        for n in self.nodes.values():
            cap[n["operator"]] = cap.get(n["operator"], 0.0) + n["speed"]
        return cap

    def close_registry(self, seed: str = "") -> Dict:
        with self._lock:
            if self.closed:
                return {"beacon": self.beacon}
            commit = hashlib.sha256(canonical(sorted(
                [n["node_id"], n["operator"], n["speed"]] for n in self.nodes.values()))).hexdigest()
            beacon = hashlib.sha256((commit + "|" + seed).encode()).hexdigest()
            self.op_slot = stratified_assign(self.operator_capacity(), self.n_slots, beacon)
            for n in self.nodes.values():
                n["slot"] = self.op_slot[n["operator"]]
            self.closed, self.beacon = True, beacon
            return {"beacon": beacon, "commitment": commit, "operators": len(self.op_slot)}

    def assignment(self, node_id: str) -> Optional[Dict]:
        with self._lock:
            n = self.nodes.get(node_id)
            if n is None:
                return None
            if not self.closed:
                return {"ready": False}
            s = n["slot"]
            lo, hi = self.ranges[s]
            a = {"ready": True, "slot": s, "layer_lo": lo, "layer_hi": hi, "model_id": self.model_id,
                 "n_slots": self.n_slots}
            if self.manifest_json:
                a["manifest"] = self.manifest_json
            if self.key_provider:
                a["key"] = self.key_provider(node_id, s).hex()
            return a

    # ---- liveness -----------------------------------------------------------
    def heartbeat(self, node_id: str, load: int = 0) -> bool:
        with self._lock:
            n = self.nodes.get(node_id)
            if not n:
                return False
            n["last_hb"], n["failed"], n["load"] = self.clock(), False, load
            return True

    def report_failure(self, node_id: str) -> None:
        with self._lock:
            if node_id in self.nodes:
                self.nodes[node_id]["failed"] = True

    def alive(self, n: Dict) -> bool:
        return (not n["failed"]) and self.clock() - n["last_hb"] <= self.hb_timeout

    def update_speed(self, node_id: str, observed: float, alpha: float = 0.3) -> None:
        """Blend observed service speed into routing weight (never above declaration)."""
        with self._lock:
            n = self.nodes.get(node_id)
            if n and observed > 0:
                n["speed"] = min(n["declared"], (1 - alpha) * n["speed"] + alpha * observed)

    # ---- plan ---------------------------------------------------------------
    def plan(self) -> Dict:
        with self._lock:
            slots: List[Dict] = []
            for s in range(self.n_slots):
                lo, hi = self.ranges[s]
                nodes = [{"node_id": n["node_id"], "operator": n["operator"], "url": n["url"],
                          "weight": n["speed"], "alive": self.alive(n)}
                         for n in self.nodes.values() if n["slot"] == s]
                slots.append({"slot": s, "layer_lo": lo, "layer_hi": hi, "nodes": nodes})
            return {"closed": self.closed, "model_id": self.model_id, "n_slots": self.n_slots,
                    "n_layers": self.n_layers, "beacon": self.beacon, "slots": slots}

    def expected_share(self, slot: int) -> Dict[str, float]:
        """Speed-proportional routing share per node (compare with ledger.work_share)."""
        with self._lock:
            ns = [n for n in self.nodes.values() if n["slot"] == slot]
            tot = sum(n["speed"] for n in ns)
            return {n["node_id"]: n["speed"] / tot for n in ns} if tot else {}

    def submit_receipts(self, receipts: List[Dict]) -> Dict:
        acc, rej = 0, {}
        for r in receipts:
            ok, why = self.ledger.submit(r, is_enrolled=lambda nid: nid in self.nodes)
            if ok:
                acc += 1
            else:
                rej[why] = rej.get(why, 0) + 1
        return {"accepted": acc, "rejected": rej}

    def status(self) -> Dict:
        with self._lock:
            return {"closed": self.closed, "nodes": len(self.nodes),
                    "alive": sum(1 for n in self.nodes.values() if self.alive(n)),
                    "receipts": self.ledger.count()}

    # ---- HTTP ---------------------------------------------------------------
    def handle(self, method, path, q, body, headers):
        if method == "GET":
            if path == "/status":
                return 200, self.status()
            if path == "/plan":
                return 200, self.plan()
            if path == "/assignment":
                a = self.assignment(q.get("node_id", ""))
                return (200, a) if a is not None else (404, {"error": "unknown node"})
            if path == "/work_share":
                return 200, {"share": self.ledger.work_share(int(q.get("slot", 0))),
                             "expected": self.expected_share(int(q.get("slot", 0)))}
            if path == "/healthz":
                return 200, {"ok": True}
        elif method == "POST" and body is not None:
            if path == "/enroll":
                ok, why = self.enroll(body)
                return (200, {"ok": True}) if ok else (400, {"error": why})
            if path == "/heartbeat":
                ok = self.heartbeat(body.get("node_id", ""), int(body.get("load", 0)))
                return (200, {"ok": True}) if ok else (404, {"error": "unknown node"})
            if path == "/close":
                return 200, self.close_registry(str(body.get("seed", "")))
            if path == "/report_failure":
                self.report_failure(body.get("node_id", ""))
                return 200, {"ok": True}
            if path == "/receipts":
                return 200, self.submit_receipts(body.get("receipts", []))
            if path == "/speed":
                self.update_speed(body.get("node_id", ""), float(body.get("observed", 0)))
                return 200, {"ok": True}
        return 404, {"error": "not found"}

    def serve(self, host="127.0.0.1", port=0) -> JsonServer:
        self.server = JsonServer(host, port, self.handle).start()
        return self.server

    @property
    def url(self) -> str:
        return "http://%s:%d" % (self.server.host, self.server.port)
