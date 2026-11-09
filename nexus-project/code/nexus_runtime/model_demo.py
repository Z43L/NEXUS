"""Tiny REAL deterministic model for the v0.1 demo (pure Python, stdlib only).

What it is: a residual-MLP "language model" over a 95-symbol printable-ASCII
vocabulary. N identical-shaped residual blocks  x <- x + W2 tanh(W1 x + b1) + b2
with seeded random weights; context mixing happens in `embed` (last token +
decayed mean of previous tokens + positional signal), so every block is
stateless and can be served by any node of its slot.

What it is NOT: it is not trained. Output text is deterministic gibberish. Its
purpose is to exercise the real distributed machinery (layer serialisation,
staged execution across processes, numerical equivalence, receipts).

Embedding table / output head are small and held by the client side (gateway /
pipeline); only the transformer-like layers are partitioned across operators.
"""
from __future__ import annotations

import base64
import json
import math
import os
import random
import struct
from typing import List, Sequence

VOCAB = 95  # printable ASCII 32..126


def tok_encode(text: str) -> List[int]:
    out = []
    for ch in text:
        o = ord(ch)
        out.append(o - 32 if 32 <= o <= 126 else (o * 31) % VOCAB)
    return out or [0]


def tok_decode(ids: Sequence[int]) -> str:
    return "".join(chr(32 + (i % VOCAB)) for i in ids)


def pack_vec(v: Sequence[float]) -> bytes:
    return struct.pack("<%dd" % len(v), *v)


def unpack_vec(b: bytes) -> List[float]:
    return list(struct.unpack("<%dd" % (len(b) // 8), b))


def vec_to_b64(v: Sequence[float]) -> str:
    return base64.b64encode(pack_vec(v)).decode()


def vec_from_b64(s: str) -> List[float]:
    return unpack_vec(base64.b64decode(s))


class Layer:
    """One residual MLP block. Serialised as header(d,h) + doubles."""

    def __init__(self, d, h, w1, b1, w2, b2):
        self.d, self.h, self.w1, self.b1, self.w2, self.b2 = d, h, w1, b1, w2, b2

    @staticmethod
    def random(d, h, rng: random.Random) -> "Layer":
        s1, s2 = 1.0 / math.sqrt(d), 1.0 / math.sqrt(h)
        w1 = [[rng.gauss(0, s1) for _ in range(d)] for _ in range(h)]
        w2 = [[rng.gauss(0, s2) for _ in range(h)] for _ in range(d)]
        b1 = [rng.gauss(0, 0.1) for _ in range(h)]
        b2 = [rng.gauss(0, 0.1) for _ in range(d)]
        return Layer(d, h, w1, b1, w2, b2)

    def to_bytes(self) -> bytes:
        flat = [x for row in self.w1 for x in row] + self.b1 + \
               [x for row in self.w2 for x in row] + self.b2
        return struct.pack("<II", self.d, self.h) + pack_vec(flat)

    @staticmethod
    def from_bytes(b: bytes) -> "Layer":
        d, h = struct.unpack_from("<II", b, 0)
        flat = unpack_vec(b[8:])
        if len(flat) != 2 * d * h + h + d:
            raise ValueError("corrupt layer blob")
        o = 0
        w1 = [flat[o + i * d:o + (i + 1) * d] for i in range(h)]; o += h * d
        b1 = flat[o:o + h]; o += h
        w2 = [flat[o + i * h:o + (i + 1) * h] for i in range(d)]; o += d * h
        b2 = flat[o:o + d]
        return Layer(d, h, w1, b1, w2, b2)

    def forward(self, x: List[float]) -> List[float]:
        tanh = math.tanh
        hid = [tanh(sum(w * xi for w, xi in zip(row, x)) + b)
               for row, b in zip(self.w1, self.b1)]
        return [xi + sum(w * hi for w, hi in zip(row, hid)) + b
                for xi, row, b in zip(x, self.w2, self.b2)]


def apply_layers(layers: Sequence[Layer], x: List[float]) -> List[float]:
    for ly in layers:
        x = ly.forward(x)
    return x


class DemoModel:
    def __init__(self, n_layers=8, d=64, h=128, seed=1234, model_id="nexus-demo-mlp-8L"):
        self.n_layers, self.d, self.h, self.seed, self.model_id = n_layers, d, h, seed, model_id
        rng = random.Random(seed)
        self.emb = [[rng.gauss(0, 1.0) for _ in range(d)] for _ in range(VOCAB)]
        self.layers = [Layer.random(d, h, rng) for _ in range(n_layers)]

    # --- client-side parts -------------------------------------------------
    def embed(self, ctx: Sequence[int]) -> List[float]:
        last = self.emb[ctx[-1]]
        prev = ctx[-17:-1]
        pos = len(ctx)
        v = list(last)
        if prev:
            w = 0.5 / len(prev)
            for t in prev:
                e = self.emb[t]
                v = [a + w * b for a, b in zip(v, e)]
        return [a + 0.1 * math.sin(pos * (i + 1) * 0.37) for i, a in enumerate(v)]

    def logits(self, h: Sequence[float]) -> List[float]:
        n = math.sqrt(sum(x * x for x in h)) or 1.0
        return [sum(a * b for a, b in zip(e, h)) / n for e in self.emb]

    @staticmethod
    def sample(logits, temperature: float, rng: random.Random) -> int:
        if temperature <= 0:
            return max(range(len(logits)), key=lambda i: (logits[i], -i))
        m = max(logits)
        ws = [math.exp((l - m) / temperature) for l in logits]
        return rng.choices(range(len(ws)), weights=ws)[0]

    # --- single-process reference pass --------------------------------------
    def reference_forward(self, x: List[float]) -> List[float]:
        return apply_layers(self.layers, x)

    def reference_generate(self, prompt_ids, n_new, temperature=0.0, seed=0):
        ctx, rng, out = list(prompt_ids), random.Random(seed), []
        for _ in range(n_new):
            t = self.sample(self.logits(self.reference_forward(self.embed(ctx))), temperature, rng)
            ctx.append(t); out.append(t)
        return out

    # --- serialisation ------------------------------------------------------
    def layer_blobs(self) -> List[bytes]:
        return [ly.to_bytes() for ly in self.layers]

    def head_blob(self) -> bytes:
        return pack_vec([x for row in self.emb for x in row])

    @staticmethod
    def head_from_blob(b: bytes, d: int) -> List[List[float]]:
        flat = unpack_vec(b)
        return [flat[i * d:(i + 1) * d] for i in range(len(flat) // d)]

    def save(self, directory: str) -> None:
        """Plain (unencrypted) model dir; this is the STUB layer source."""
        os.makedirs(directory, exist_ok=True)
        meta = {"model_id": self.model_id, "n_layers": self.n_layers, "d": self.d,
                "h": self.h, "seed": self.seed}
        with open(os.path.join(directory, "meta.json"), "w") as f:
            json.dump(meta, f)
        with open(os.path.join(directory, "head.bin"), "wb") as f:
            f.write(self.head_blob())
        for i, b in enumerate(self.layer_blobs()):
            with open(os.path.join(directory, "layer_%03d.bin" % i), "wb") as f:
                f.write(b)

    @classmethod
    def load_head(cls, directory: str) -> "DemoModel":
        """Client-side view: embedding/head only (layers are NOT loaded)."""
        with open(os.path.join(directory, "meta.json")) as f:
            meta = json.load(f)
        m = cls.__new__(cls)
        m.n_layers, m.d, m.h, m.seed, m.model_id = (meta["n_layers"], meta["d"], meta["h"],
                                                    meta["seed"], meta["model_id"])
        with open(os.path.join(directory, "head.bin"), "rb") as f:
            m.emb = cls.head_from_blob(f.read(), m.d)
        m.layers = []
        return m


def slot_ranges(n_layers: int, n_slots: int):
    """Contiguous layer ranges [lo, hi) per slot, as even as possible."""
    base, extra = divmod(n_layers, n_slots)
    out, lo = [], 0
    for s in range(n_slots):
        hi = lo + base + (1 if s < extra else 0)
        out.append((lo, hi)); lo = hi
    return out
