"""Serve several local base models from one engine process.

The hub maps catalog names to NRA-M bundles and loads an engine for a name on
first use. At most max_resident engines stay in memory; the least recently
used engine that no request is leasing is released when another model is
needed. Requests name a model with the same rules the worker uses: the exact
catalog name, or the name with or without ':latest'. An empty name selects the
catalog's first entry.

Engines are created through a factory, so this module does not import torch.
"""
from __future__ import annotations

import contextlib
import json
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

LATEST = ":latest"


class ModelBusyError(RuntimeError):
    """Every resident engine is leased, so the requested model cannot be loaded now."""


class ModelHub:
    def __init__(self, catalog: dict[str, str], factory: Callable[[str, str], object],
                 max_resident: int = 1):
        if not catalog:
            raise ValueError("model catalog must list at least one model")
        if max_resident < 1:
            raise ValueError("max_resident must be at least 1")
        self.catalog = dict(catalog)
        self.default = next(iter(self.catalog))
        self.factory = factory
        self.max_resident = max_resident
        self._engines: OrderedDict[str, object] = OrderedDict()
        self._leases: dict[str, int] = {}
        self._lock = threading.RLock()

    def names(self) -> list[str]:
        return list(self.catalog)

    def resolve(self, requested) -> str:
        if not requested:
            return self.default
        if not isinstance(requested, str):
            raise ValueError("model must be a string")
        if requested in self.catalog:
            return requested
        if requested.endswith(LATEST) and requested[:-len(LATEST)] in self.catalog:
            return requested[:-len(LATEST)]
        if requested + LATEST in self.catalog:
            return requested + LATEST
        raise ValueError(f"unknown model {requested!r}; available: {', '.join(self.catalog)}")

    @contextlib.contextmanager
    def lease(self, requested):
        """Hold the engine for one request; it cannot be released while leased."""
        name = self.resolve(requested)
        with self._lock:
            engine = self._load(name)
            self._leases[name] = self._leases.get(name, 0) + 1
        try:
            yield engine
        finally:
            with self._lock:
                self._leases[name] -= 1

    def _load(self, name: str):
        if name in self._engines:
            self._engines.move_to_end(name)
            return self._engines[name]
        while len(self._engines) >= self.max_resident:
            victim = next((key for key in self._engines if not self._leases.get(key)), None)
            if victim is None:
                raise ModelBusyError("all resident models are in use; retry shortly")
            self._engines.pop(victim).close()
        engine = self.factory(name, self.catalog[name])
        self._engines[name] = engine
        return engine

    def preload(self, requested=None) -> None:
        with self.lease(requested):
            pass

    def health(self) -> dict:
        with self._lock:
            resident = list(self._engines)
            newest = self._engines[resident[-1]].health() if resident else {}
        return {**newest, "backend": "nram", "default_model": self.default,
                "models": self.names(), "resident_models": resident,
                "max_resident_models": self.max_resident}

    def close(self) -> None:
        with self._lock:
            for name in list(self._engines):
                self._engines.pop(name).close()


def load_catalog(path: str | Path) -> dict[str, str]:
    """Read {"models": [{"name": ..., "bundle": ...}, ...]}; bundle paths are relative to the file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("models") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("catalog must contain a non-empty 'models' list")
    catalog: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) \
                or not isinstance(entry.get("bundle"), str):
            raise ValueError("each catalog entry needs string 'name' and 'bundle'")
        name = entry["name"]
        if name in catalog:
            raise ValueError(f"duplicate model name {name!r}")
        bundle = Path(entry["bundle"])
        catalog[name] = str(bundle if bundle.is_absolute() else path.parent / bundle)
    return catalog
