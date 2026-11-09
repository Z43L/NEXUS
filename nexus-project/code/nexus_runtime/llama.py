"""REAL model path: Llama-architecture transformer (SmolLM2-135M-Instruct, Apache-2.0) in numpy.

numpy-only on purpose (no torch at serving time). One transformer block = one `LlamaLayer`; a node serves the
contiguous layers of its slot and keeps a per-request KV cache. The embedding/lm_head/tokenizer ("head") stay on the
gateway side: they are ~21% of this model's parameters and are NOT partitioned across operators (honest limit).

Weights are stored as raw bfloat16 (exact: bf16 -> float32 is a bit shift), activations travel as float64 lists on the
existing wire format (a float32 value round-trips through float64 exactly), so the distributed result is bit-identical to
the single-process reference as long as nodes run the same numpy/BLAS build (cross-hardware equivalence is NOT guaranteed).
"""
from __future__ import annotations

import json
import mmap
import os
import struct
from typing import Dict, List, Optional, Sequence

import sys
import warnings

import numpy as np

if sys.platform == "darwin":  # numpy 2.0.x + Accelerate emits spurious FP warnings from matmul (results are correct)
    warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*encountered in matmul")

MAGIC = b"NXLL"
_F32 = np.float32


def bf16_to_f32(raw) -> np.ndarray:
    u = np.frombuffer(raw, dtype=np.uint16).astype(np.uint32) << 16
    return u.view(np.float32)


def f32_to_bf16_bytes(a: np.ndarray) -> bytes:
    u = np.ascontiguousarray(a, dtype=np.float32).view(np.uint32)
    return (u >> 16).astype(np.uint16).tobytes()  # only used on values that are already bf16-exact


def read_safetensors(path: str) -> Dict[str, dict]:
    """Minimal safetensors reader: name -> {dtype, shape, raw(bytes-like)}. Keeps the mmap alive via `_mm`."""
    f = open(path, "rb")
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    (n,) = struct.unpack("<Q", mm[:8])
    hdr = json.loads(mm[8:8 + n])
    base, out = 8 + n, {}
    for k, v in hdr.items():
        if k == "__metadata__":
            continue
        a, b = v["data_offsets"]
        out[k] = {"dtype": v["dtype"], "shape": v["shape"], "raw": memoryview(mm)[base + a:base + b]}
    out["_mm"] = {"mm": mm, "f": f}
    return out


# ---- layer blob -------------------------------------------------------------------------------------------------
_ORDER = ["input_layernorm.weight", "self_attn.q_proj.weight", "self_attn.k_proj.weight", "self_attn.v_proj.weight",
          "self_attn.o_proj.weight", "post_attention_layernorm.weight", "mlp.gate_proj.weight",
          "mlp.up_proj.weight", "mlp.down_proj.weight"]


def layer_blob(tensors: Dict[str, dict], idx: int, cfg: dict) -> bytes:
    meta = {"d": cfg["hidden_size"], "n_heads": cfg["num_attention_heads"], "n_kv": cfg["num_key_value_heads"],
            "ff": cfg["intermediate_size"], "eps": cfg["rms_norm_eps"], "theta": cfg["rope_theta"], "shapes": []}
    body = b""
    for name in _ORDER:
        t = tensors["model.layers.%d.%s" % (idx, name)]
        if t["dtype"] != "BF16":
            raise ValueError("only BF16 checkpoints are supported")
        meta["shapes"].append(t["shape"])
        body += bytes(t["raw"])
    h = json.dumps(meta, sort_keys=True).encode()
    return MAGIC + struct.pack("<I", len(h)) + h + body


def is_llama_blob(b: bytes) -> bool:
    return b[:4] == MAGIC


class _Cache:
    """Per-request, per-layer KV cache with amortised growth."""

    def __init__(self, n_kv, hd):
        self.n, self.k, self.v = 0, np.zeros((64, n_kv, hd), _F32), np.zeros((64, n_kv, hd), _F32)

    def append(self, k, v):
        if self.n == self.k.shape[0]:
            self.k = np.concatenate([self.k, np.zeros_like(self.k)]); self.v = np.concatenate([self.v, np.zeros_like(self.v)])
        self.k[self.n], self.v[self.n] = k, v
        self.n += 1


class LlamaLayer:
    def __init__(self, meta: dict, tensors: List[np.ndarray]):
        self.d, self.n_heads, self.n_kv = meta["d"], meta["n_heads"], meta["n_kv"]
        self.hd = self.d // self.n_heads
        self.eps, self.theta = _F32(meta["eps"]), meta["theta"]
        (self.ln1, self.wq, self.wk, self.wv, self.wo, self.ln2, self.wg, self.wu, self.wd) = tensors
        half = self.hd // 2
        self.inv_freq = (1.0 / (self.theta ** (np.arange(0, half, dtype=np.float64) * 2.0 / self.hd))).astype(_F32)

    @staticmethod
    def from_bytes(b: bytes) -> "LlamaLayer":
        if not is_llama_blob(b):
            raise ValueError("not a llama layer blob")
        (hl,) = struct.unpack_from("<I", b, 4)
        meta = json.loads(b[8:8 + hl])
        off, ts = 8 + hl, []
        for shp in meta["shapes"]:
            n = int(np.prod(shp)) * 2
            ts.append(bf16_to_f32(b[off:off + n]).reshape(shp)); off += n
        if off != len(b):
            raise ValueError("corrupt llama layer blob")
        return LlamaLayer(meta, ts)

    def new_cache(self) -> _Cache:
        return _Cache(self.n_kv, self.hd)

    def _rms(self, x, w):
        return (x * (1.0 / np.sqrt(np.mean(x * x) + self.eps))).astype(_F32) * w

    def _rope(self, x, pos):  # x: [heads, hd], non-interleaved (rotate_half)
        ang = _F32(pos) * self.inv_freq
        c, s = np.cos(ang).astype(_F32), np.sin(ang).astype(_F32)
        h = self.hd // 2
        x1, x2 = x[:, :h], x[:, h:]
        return np.concatenate([x1 * c - x2 * s, x2 * c + x1 * s], axis=1)

    def forward(self, x: np.ndarray, cache: _Cache) -> np.ndarray:
        pos = cache.n
        h = self._rms(x, self.ln1)
        q = (self.wq @ h).reshape(self.n_heads, self.hd)
        k = (self.wk @ h).reshape(self.n_kv, self.hd)
        v = (self.wv @ h).reshape(self.n_kv, self.hd)
        q, k = self._rope(q, pos), self._rope(k, pos)
        cache.append(k, v)
        K, V = cache.k[:cache.n], cache.v[:cache.n]            # [T, n_kv, hd]
        rep = self.n_heads // self.n_kv
        out = np.empty((self.n_heads, self.hd), _F32)
        scale = _F32(1.0 / np.sqrt(self.hd))
        for hh in range(self.n_heads):
            g = hh // rep
            sc = (K[:, g, :] @ q[hh]) * scale
            sc = np.exp(sc - sc.max()); sc /= sc.sum()
            out[hh] = sc @ V[:, g, :]
        x = x + self.wo @ out.reshape(-1)
        h = self._rms(x, self.ln2)
        gate = self.wg @ h
        act = gate / (1.0 + np.exp(-gate)) * (self.wu @ h)
        return (x + self.wd @ act).astype(_F32)


class StageState:
    """KV caches for one request on one node (all layers of its slot)."""

    def __init__(self, layers: Sequence[LlamaLayer]):
        self.caches = [ly.new_cache() for ly in layers]
        self.n = 0  # tokens processed

    def step(self, layers: Sequence[LlamaLayer], x: np.ndarray) -> np.ndarray:
        for ly, c in zip(layers, self.caches):
            x = ly.forward(x, c)
        self.n += 1
        return x


# ---- head (client/gateway side) ---------------------------------------------------------------------------------
class LlamaHead:
    stateful = True

    def __init__(self, model_id, d, n_layers, embed, norm, eps, tokenizer, eos_ids, chat_template="chatml"):
        self.model_id, self.d, self.n_layers = model_id, d, n_layers
        self.embed_w, self.norm_w, self.eps, self.tok, self.eos_ids = embed, norm, _F32(eps), tokenizer, set(eos_ids)
        self.vocab = embed.shape[0]

    def encode(self, text: str) -> List[int]:
        return self.tok.encode(text, add_special_tokens=False).ids

    def decode(self, ids: Sequence[int]) -> str:
        return self.tok.decode(list(ids), skip_special_tokens=True)

    def chat_prompt(self, messages: List[Dict]) -> str:
        s = "".join("<|im_start|>%s\n%s<|im_end|>\n" % (m.get("role", "user"), m.get("content", "")) for m in messages)
        return s + "<|im_start|>assistant\n"

    def embed_token(self, t: int) -> List[float]:
        return self.embed_w[t].astype(np.float64).tolist()

    def logits(self, h: Sequence[float]) -> np.ndarray:
        x = np.asarray(h, dtype=_F32)
        x = (x * (1.0 / np.sqrt(np.mean(x * x) + self.eps))).astype(_F32) * self.norm_w
        return self.embed_w @ x  # tied lm_head

    @staticmethod
    def sample(logits, temperature: float, rng) -> int:
        if temperature <= 0:
            return int(np.argmax(logits))
        z = (np.asarray(logits, dtype=np.float64) - float(np.max(logits))) / temperature
        p = np.exp(z); p /= p.sum()
        return int(rng.choices(range(len(p)), weights=p.tolist())[0])

    @classmethod
    def load(cls, directory: str) -> "LlamaHead":
        from tokenizers import Tokenizer
        with open(os.path.join(directory, "meta.json")) as f:
            meta = json.load(f)
        with open(os.path.join(directory, "head.bin"), "rb") as f:
            raw = f.read()
        d, v = meta["d"], meta["vocab"]
        norm = np.frombuffer(raw[:d * 4], dtype=_F32).copy()
        embed = bf16_to_f32(raw[d * 4:]).reshape(v, d)
        return cls(meta["model_id"], d, meta["n_layers"], embed, norm, meta["eps"],
                   Tokenizer.from_file(os.path.join(directory, "tokenizer.json")), meta["eos_ids"])


class LlamaReference:
    """Single-process reference (all layers + head) for equivalence tests and benchmarks."""

    def __init__(self, layer_blobs: List[bytes]):
        self.layers = [LlamaLayer.from_bytes(b) for b in layer_blobs]

    def generate(self, head: LlamaHead, prompt_ids, n_new, stop=True):
        st, out = StageState(self.layers), []
        ids = list(prompt_ids)
        for step in range(len(ids) + n_new - 1):
            if step >= len(ids):
                ids.append(out[-1])
            y = st.step(self.layers, np.asarray(head.embed_token(ids[step]), dtype=_F32))
            if step >= len(prompt_ids) - 1:
                t = head.sample(head.logits(y.astype(np.float64).tolist()), 0.0, None)
                out.append(t)
                if stop and t in head.eos_ids:
                    break
        return out


def convert(src_dir: str):
    """Read a HF safetensors checkpoint dir -> (layer blobs, head dict for `write_head`). Returns (blobs, meta, head_bytes)."""
    t = read_safetensors(os.path.join(src_dir, "model.safetensors"))
    with open(os.path.join(src_dir, "config.json")) as f:
        cfg = json.load(f)
    if cfg.get("model_type") != "llama" or cfg.get("hidden_act") != "silu" or cfg.get("rope_scaling"):
        raise ValueError("unsupported architecture (need plain llama + silu + no rope scaling)")
    if not cfg.get("tie_word_embeddings", False):
        raise ValueError("this adapter expects tied embeddings")
    blobs = [layer_blob(t, i, cfg) for i in range(cfg["num_hidden_layers"])]
    emb, norm = t["model.embed_tokens.weight"], t["model.norm.weight"]
    head = bf16_to_f32(norm["raw"]).astype(_F32).tobytes() + bytes(emb["raw"])
    with open(os.path.join(src_dir, "generation_config.json")) as f:
        gen = json.load(f)
    eos = gen.get("eos_token_id", cfg.get("eos_token_id", 2))
    meta = {"kind": "llama", "d": cfg["hidden_size"], "n_layers": cfg["num_hidden_layers"],
            "vocab": cfg["vocab_size"], "eps": cfg["rms_norm_eps"], "eos_ids": eos if isinstance(eos, list) else [eos]}
    return blobs, meta, head
