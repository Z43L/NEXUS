"""Per-stage routing with speed-proportional shares, retries and failover.

Routing is smooth weighted round-robin (deterministic, exact long-run proportions
to weight = node speed) over nodes the coordinator reports alive. On error the
node is excluded for this call, reported to the coordinator, and the next
candidate is tried; the plan is refreshed once before giving up.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional

from . import httpx
from .model_demo import pack_vec, vec_from_b64, vec_to_b64
from .receipts import sha256_hex, unit_id_for


class StageUnavailable(Exception):
    pass


class SlotRouter:
    def __init__(self, coordinator_url: str, cooldown: float = 5.0):
        self.coord = coordinator_url.rstrip("/")
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self._cur: Dict[str, float] = {}
        self._bad: Dict[str, float] = {}
        self.plan: Dict = {}
        self.refresh()

    def refresh(self) -> None:
        plan = httpx.call(self.coord, "/plan", timeout=3.0)
        with self._lock:
            self.plan = plan

    def slots(self) -> int:
        return self.plan["n_slots"]

    def mark_bad(self, node_id: str) -> None:
        with self._lock:
            self._bad[node_id] = time.time() + self.cooldown
        try:
            httpx.call(self.coord, "/report_failure", {"node_id": node_id}, timeout=2.0)
        except Exception:
            pass

    def pick(self, slot: int, exclude=()) -> Optional[Dict]:
        with self._lock:
            now = time.time()
            cands = [n for n in self.plan["slots"][slot]["nodes"]
                     if n["alive"] and n["node_id"] not in exclude
                     and self._bad.get(n["node_id"], 0) <= now and n["weight"] > 0]
            if not cands:
                return None
            tot = sum(n["weight"] for n in cands)
            for n in cands:
                self._cur[n["node_id"]] = self._cur.get(n["node_id"], 0.0) + n["weight"]
            best = max(cands, key=lambda n: (self._cur[n["node_id"]], n["node_id"]))
            self._cur[best["node_id"]] -= tot
            return best


class Scheduler:
    def __init__(self, router: SlotRouter, timeout: float = 5.0, stage_token: Optional[str] = None):
        self.router, self.timeout = router, timeout
        tok = stage_token if stage_token is not None else os.environ.get("NEXUS_STAGE_TOKEN", "")
        self.headers = {"Authorization": "Bearer " + tok} if tok else None
        self.failovers = 0
        self.hist = {}  # (req_id, slot) -> [xb64 per step]; only for stateful (KV-cache) models

    def run_stage(self, slot: int, req_id: str, step: int, x: List[float]) -> Dict:
        """Execute one stage with failover. Returns {y, receipt, hop_ms, compute_ms, node_id}."""
        unit_id = unit_id_for(req_id, step, slot)
        xb64, in_hash = vec_to_b64(x), sha256_hex(pack_vec(x))
        tried = set()
        refreshed = False
        while True:
            node = self.router.pick(slot, exclude=tried)
            if node is None:
                if not refreshed:
                    refreshed = True
                    try:
                        self.router.refresh()
                    except Exception:
                        pass
                    tried = set()
                    continue
                raise StageUnavailable("no live node for slot %d" % slot)
            t0 = time.perf_counter()
            try:
                body = {"slot": slot, "unit_id": unit_id, "req_id": req_id, "x": xb64, "step": step}
                try:
                    resp = httpx.call(node["url"], "/stage", body, timeout=self.timeout, headers=self.headers)
                except httpx.HttpError as e:
                    if e.status != 409 or not isinstance(e.body, dict) or e.body.get("error") != "cache-miss":
                        raise
                    # node has no usable KV cache for this request (failover / eviction): replay prior inputs
                    body["replay"] = self.hist.get((req_id, slot), [])[:step]
                    resp = httpx.call(node["url"], "/stage", body, timeout=max(self.timeout, 30.0), headers=self.headers)
                y = vec_from_b64(resp["y"])
                r = resp["receipt"]
                if (r["out_hash"] != sha256_hex(pack_vec(y)) or r["in_hash"] != in_hash
                        or r["node_id"] != node["node_id"] or r["unit_id"] != unit_id):
                    raise ValueError("receipt does not match payload")
                if resp.get("stateful"):
                    h = self.hist.setdefault((req_id, slot), [])
                    del h[step:]
                    h.append(xb64)
            except Exception:
                tried.add(node["node_id"])
                self.failovers += 1
                self.router.mark_bad(node["node_id"])
                continue
            return {"y": y, "receipt": r, "hop_ms": (time.perf_counter() - t0) * 1000,
                    "compute_ms": resp["compute_ms"], "node_id": node["node_id"]}

    def end(self, req_id: str):
        for k in [k for k in self.hist if k[0] == req_id]:
            del self.hist[k]

    def spot_check(self, slot: int, node_id: str, req_id: str, step: int, x, expected_y) -> Optional[bool]:
        """Re-execute on another node of the slot; True=match, False=mismatch, None=no peer."""
        other = self.router.pick(slot, exclude={node_id})
        if other is None:
            return None
        try:
            resp = httpx.call(other["url"], "/stage",
                              {"slot": slot, "unit_id": unit_id_for(req_id + "#chk", step, slot),
                               "req_id": req_id + "#chk", "x": vec_to_b64(x), "step": step,
                               "replay": self.hist.get((req_id, slot), [])[:step]},
                              timeout=max(self.timeout, 30.0), headers=self.headers)
        except Exception:
            return None
        return resp["y"] == vec_to_b64(expected_y)
