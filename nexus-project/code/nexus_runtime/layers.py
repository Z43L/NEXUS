"""Layer sources for node agents.

`StorageLayerSource`  - REAL path: nexus_storage.fetch_slot against the signed manifest
                        (erasure-coded, encrypted, Merkle-verified).
`StubLayerSource`     - STAND-IN: reads plain layer files written by DemoModel.save().
                        Used by tests/demo when nexus_storage is unavailable or no
                        manifest has been published.
"""
from __future__ import annotations

import os
from typing import Dict, List

from .model_demo import slot_ranges


class StubLayerSource:
    """STAND-IN for nexus_storage: unencrypted local files. Not part of the real trust model."""

    kind = "stub"

    def __init__(self, model_dir: str):
        self.model_dir = model_dir

    def get_layers(self, assignment: Dict) -> List[bytes]:
        out = []
        for i in range(assignment["layer_lo"], assignment["layer_hi"]):
            with open(os.path.join(self.model_dir, "layer_%03d.bin" % i), "rb") as f:
                out.append(f.read())
        return out


class StorageLayerSource:
    kind = "nexus_storage"

    def __init__(self, store):
        """`store` is a FragmentStore object or a directory path (DirStore)."""
        if isinstance(store, str):
            from nexus_storage.store import DirStore  # raises ImportError if absent
            store = DirStore(store)
        self.store = store

    def get_layers(self, assignment: Dict) -> List[bytes]:
        from nexus_storage.manifest import ModelManifest
        from nexus_storage.publish import fetch_slot
        mj, key = assignment.get("manifest"), assignment.get("key")
        if not mj or not key:
            raise RuntimeError("assignment has no manifest/key; cannot use nexus_storage")
        m = ModelManifest.from_json(mj)
        if not m.verify():
            raise RuntimeError("manifest signature invalid")
        layers = fetch_slot(m, assignment["slot"], self.store, bytes.fromhex(key))
        want = assignment["layer_hi"] - assignment["layer_lo"]
        if len(layers) != want:
            raise RuntimeError("slot layer count %d != expected %d" % (len(layers), want))
        return layers


def storage_available() -> bool:
    try:
        import nexus_storage.publish, nexus_storage.manifest, nexus_storage.store  # noqa
        return True
    except Exception:
        return False


def split_for_slots(n_layers: int, n_slots: int):
    return slot_ranges(n_layers, n_slots)
