"""Per-request .nram adapter selection for the native engine.

An adapter is a micro-extension bundle (model_family onram-external-micro-mlp-v1)
kept in a directory owned by the engine. A request names it by SHA-256 id and
the engine never opens a path supplied by the request. Before use the id must
match the file bytes, the bundle must verify, and it must target the same base
checkpoint, module and shape as the extension slot attached at load time.

Selection swaps the slot's tensors for the duration of one generation and
restores them afterwards. The caller must hold the engine lock, which already
serialises generation and training.
"""
from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path

import torch

from micro_extensions import MicroExtensions
from nram_container import parse_bundle

ADAPTER_ID_RE = re.compile(r"[0-9a-f]{64}")
MODEL_FAMILY = "onram-external-micro-mlp-v1"
MAX_CACHED_ADAPTERS = 8


class AdapterError(ValueError):
    pass


class AdapterSlot:
    def __init__(self, bank, extension_manifest, adapter_dir):
        spec = extension_manifest["micro_extensions"]
        self.bank = bank
        self.base_weights_sha256 = extension_manifest["base_weights_sha256"]
        self.module = spec["module"]
        self.shape = (spec["hidden_size"], spec["rank"], spec["experts"])
        self.adapter_dir = Path(adapter_dir)
        self._cache: dict[str, dict[str, torch.Tensor]] = {}

    def installed(self) -> list[str]:
        return sorted(path.stem for path in self.adapter_dir.glob("*.nram")
                      if ADAPTER_ID_RE.fullmatch(path.stem))

    def _state_for(self, adapter_id: str) -> dict[str, torch.Tensor]:
        if not isinstance(adapter_id, str) or not ADAPTER_ID_RE.fullmatch(adapter_id):
            raise AdapterError("nram_adapter must be a 64-character lowercase SHA-256 id")
        cached = self._cache.get(adapter_id)
        if cached is not None:
            return cached
        try:
            raw = (self.adapter_dir / f"{adapter_id}.nram").read_bytes()
        except OSError:
            raise AdapterError("adapter is not installed on this engine") from None
        if hashlib.sha256(raw).hexdigest() != adapter_id:
            raise AdapterError("adapter bytes do not match its id")
        try:
            manifest, tensors = parse_bundle(raw)
        except ValueError as exc:
            raise AdapterError(f"invalid adapter bundle: {exc}") from exc
        if manifest.get("model_family") != MODEL_FAMILY:
            raise AdapterError("bundle is not a micro-extension adapter")
        if manifest.get("base_weights_sha256") != self.base_weights_sha256:
            raise AdapterError("adapter targets a different base checkpoint")
        spec = manifest.get("micro_extensions") or {}
        if spec.get("module") != self.module:
            raise AdapterError("adapter targets a different module")
        if (spec.get("hidden_size"), spec.get("rank"), spec.get("experts")) != self.shape:
            raise AdapterError("adapter shape does not match the engine slot")
        candidate = MicroExtensions(*self.shape)
        tensors.setdefault("active_mask", torch.ones(self.shape[2], dtype=torch.bool))
        try:
            candidate.load_state_dict(tensors, strict=True)
        except RuntimeError as exc:
            raise AdapterError("adapter tensors do not match the slot") from exc
        state = {key: value.detach().clone() for key, value in candidate.state_dict().items()}
        if len(self._cache) >= MAX_CACHED_ADAPTERS:
            self._cache.pop(next(iter(self._cache)))
        self._cache[adapter_id] = state
        return state

    @contextlib.contextmanager
    def applied(self, adapter_id: str):
        """Run one generation with the adapter's tensors in the slot."""
        state = self._state_for(adapter_id)
        saved = {key: value.detach().clone() for key, value in self.bank.state_dict().items()}
        self.bank.load_state_dict(state, strict=True)
        try:
            yield
        finally:
            self.bank.load_state_dict(saved, strict=True)
