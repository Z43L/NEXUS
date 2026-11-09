"""In-process cluster helper (coordinator + node agents on threads) for tests and quick demos.
The real multi-PROCESS demo lives in nexus_cli/demo.py."""
from __future__ import annotations

import tempfile
from typing import Dict, List, Optional, Sequence

from .coordinator import Coordinator
from .crypto import Ed25519Signer
from .layers import StubLayerSource
from .ledger import Ledger
from .model_demo import DemoModel
from .node import NodeAgent


class LocalCluster:
    """specs: list of dicts {operator, slowdown?, declared_speed?}."""

    def __init__(self, specs: Sequence[Dict], n_slots: int, model: Optional[DemoModel] = None,
                 beacon_seed: str = "test-beacon", hb_timeout: float = 2.0, hb_interval: float = 0.3,
                 use_storage: bool = False):
        self.model = model or DemoModel()
        self.dir = tempfile.mkdtemp(prefix="nexus-model-")
        self.model.save(self.dir)
        kw, source = {}, StubLayerSource(self.dir)
        self.manifest = None
        if use_storage:  # REAL path: encrypted, erasure-coded slots via nexus_storage
            from nexus_storage import MemoryStore, KeyVault, generate_signer, publish_model
            from .layers import StorageLayerSource
            store = MemoryStore()
            self.manifest, master = publish_model(
                self.model.layer_blobs(), model_id=self.model.model_id, version="1", n_slots=n_slots,
                ec_k=4, ec_n=6, store=store, author_signer=generate_signer(), license="demo-only")
            vault = KeyVault(master)
            kw = {"manifest_json": self.manifest.to_json(),
                  "key_provider": lambda nid, slot: vault.grant(nid, slot)}
            source = StorageLayerSource(store)
        self.coord = Coordinator(n_slots, self.model.n_layers, self.model.model_id,
                                 hb_timeout=hb_timeout, **kw)
        self.coord.serve()
        self.nodes: List[NodeAgent] = []
        for sp in specs:
            n = NodeAgent(self.coord.url, Ed25519Signer(), operator=sp["operator"],
                          layer_source=source, slowdown=sp.get("slowdown", 1.0),
                          declared_speed=sp.get("declared_speed"), hb_interval=hb_interval,
                          d=self.model.d, h=self.model.h)
            n.start()
            self.nodes.append(n)
        self.close_info = self.coord.close_registry(beacon_seed)
        for n in self.nodes:
            n.wait_for_slot(10)

    def head(self) -> DemoModel:
        return DemoModel.load_head(self.dir)

    def nodes_of_slot(self, s: int) -> List[NodeAgent]:
        return [n for n in self.nodes if n.assignment["slot"] == s]

    def stop(self):
        for n in self.nodes:
            try:
                n.stop()
            except Exception:
                pass
        self.coord.server.stop()
