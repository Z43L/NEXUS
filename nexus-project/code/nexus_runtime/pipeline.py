"""Distributed inference: embed -> stage 0 -> ... -> stage S-1 -> head, across processes.

Measures wall-clock latency per hop (client-observed, includes JSON/base64,
HTTP, node compute and receipt signing) and node-reported compute time, and
real tokens/second. Receipts are collected and submitted to the coordinator.
"""
from __future__ import annotations

import random
import time
import uuid
from typing import Callable, Dict, List, Optional

from . import httpx
from .model_demo import DemoModel, tok_decode, tok_encode
from .scheduler import Scheduler, SlotRouter


class Pipeline:
    def __init__(self, coordinator_url: str, head_model: DemoModel, spot_check_rate: float = 0.0,
                 timeout: float = 5.0, seed: int = 0):
        self.coord = coordinator_url.rstrip("/")
        self.model = head_model
        self.router = SlotRouter(self.coord)
        self.sched = Scheduler(self.router, timeout=timeout)
        self.spot_rate, self._rng = spot_check_rate, random.Random(seed)
        self.spot_mismatch = 0

    def forward(self, x: List[float], req_id: str, step: int, hops: Optional[List[Dict]] = None,
                receipts: Optional[List[Dict]] = None) -> List[float]:
        for s in range(self.router.slots()):
            r = self.sched.run_stage(s, req_id, step, x)
            if hops is not None:
                hops.append({"slot": s, "node": r["node_id"], "hop_ms": r["hop_ms"],
                             "compute_ms": r["compute_ms"]})
            if receipts is not None:
                receipts.append(r["receipt"])
            if self.spot_rate and self._rng.random() < self.spot_rate:
                ok = self.sched.spot_check(s, r["node_id"], req_id, step, x, r["y"])
                if ok is False:
                    self.spot_mismatch += 1
            x = r["y"]
        return x

    def _generate_stateful(self, prompt_ids, n_new, temperature, seed, req_id, on_token, submit_receipts):
        """Token-by-token through all slots; nodes keep KV caches (see Scheduler/NodeAgent replay on failover)."""
        m = self.model
        ids, out, hops, receipts = list(prompt_ids), [], [], []
        rng, fo0, finish = random.Random(seed), self.sched.failovers, "length"
        t0 = time.perf_counter()
        try:
            for step in range(len(prompt_ids) + n_new - 1):
                if step >= len(prompt_ids):
                    ids.append(out[-1])
                h = self.forward(m.embed_token(ids[step]), req_id, step, hops, receipts)
                if step >= len(prompt_ids) - 1:
                    t = m.sample(m.logits(h), temperature, rng)
                    out.append(t)
                    if on_token:
                        on_token(step, t)
                    if t in m.eos_ids:
                        finish = "stop"
                        break
        finally:
            self.sched.end(req_id)
        wall = time.perf_counter() - t0
        sub = httpx.call(self.coord, "/receipts", {"receipts": receipts}, timeout=60.0) if (submit_receipts and receipts) else None
        hop = [x["hop_ms"] for x in hops]
        comp = [x["compute_ms"] for x in hops]
        return {"req_id": req_id, "tokens": out, "text": m.decode([t for t in out if t not in m.eos_ids]),
                "finish_reason": finish, "wall_s": wall, "tok_s": len(out) / wall if wall else 0.0,
                "prompt_tokens": len(prompt_ids), "hops": len(hops),
                "mean_hop_ms": sum(hop) / len(hop) if hop else 0.0,
                "mean_compute_ms": sum(comp) / len(comp) if comp else 0.0,
                "max_hop_ms": max(hop) if hop else 0.0, "failovers": self.sched.failovers - fo0,
                "receipts": receipts, "submitted": sub}

    def generate(self, prompt_ids: List[int], n_new: int, temperature: float = 0.0, seed: int = 0,
                 req_id: Optional[str] = None, on_token: Optional[Callable[[int, int], None]] = None,
                 submit_receipts: bool = True) -> Dict:
        req_id = req_id or uuid.uuid4().hex
        if getattr(self.model, "stateful", False):
            return self._generate_stateful(prompt_ids, n_new, temperature, seed, req_id, on_token, submit_receipts)
        ctx, out, hops, receipts = list(prompt_ids), [], [], []
        rng = random.Random(seed)
        fo0 = self.sched.failovers
        t0 = time.perf_counter()
        for step in range(n_new):
            h = self.forward(self.model.embed(ctx), req_id, step, hops, receipts)
            t = self.model.sample(self.model.logits(h), temperature, rng)
            ctx.append(t); out.append(t)
            if on_token:
                on_token(step, t)
        wall = time.perf_counter() - t0
        sub = None
        if submit_receipts and receipts:
            sub = httpx.call(self.coord, "/receipts", {"receipts": receipts}, timeout=30.0)
        hop = [x["hop_ms"] for x in hops]
        comp = [x["compute_ms"] for x in hops]
        return {"req_id": req_id, "tokens": out, "text": tok_decode(out), "wall_s": wall,
                "tok_s": n_new / wall if wall else 0.0,
                "hops": len(hops),
                "mean_hop_ms": sum(hop) / len(hop) if hop else 0.0,
                "mean_compute_ms": sum(comp) / len(comp) if comp else 0.0,
                "max_hop_ms": max(hop) if hop else 0.0,
                "failovers": self.sched.failovers - fo0,
                "receipts": receipts, "submitted": sub}
