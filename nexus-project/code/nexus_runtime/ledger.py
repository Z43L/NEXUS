"""SQLite contribution ledger + settlement batch builder.

Settlement format (compatible with NEXUS/settlement-evm InferenceEscrow V2):
  * leaf    = keccak256(abi.encode(LEAF_DOMAIN, chainid, escrow, token, batchId,
                                   jobId, node, author, amount))
  * parent  = sorted-pair Merkle-sum, odd node promoted
  * built by the unmodified `_batch_builder.build_batch` (copy of batch_builder.py)

Differences vs the H0 receipt-to-batch path (documented, not hidden):
  1. Granularity: the contract's "job" is one leaf. We aggregate ALL unsettled
     receipts of one node into ONE job per batch (jobId = keccak256(
     "NEXUS_NODE_BATCH" || batchId || nodeAddress)), instead of one leaf per
     inference request. Fewer leaves; individual receipts remain in the ledger
     and can be audited against the aggregate.
  2. amount = work_units * price_per_unit (integer ERC-20 base units). The
     contract itself splits amount into node/author/verification/burn/treasury.
  3. node/author addresses: `evm_address(pubkey)` is a STAND-IN mapping. Pass a
     `wallets` dict {node_pubkey_hex: 0x...} for real wallets.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import defaultdict
from typing import Callable, Dict, Optional

from . import _batch_builder as bb
from .receipts import evm_address, verify_receipt, canonical


class Ledger:
    def __init__(self, path: str = ":memory:"):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.executescript("""
        CREATE TABLE IF NOT EXISTS receipts(
            unit_id TEXT PRIMARY KEY, req_id TEXT, model_id TEXT, node_id TEXT NOT NULL,
            slot INTEGER NOT NULL, work_units INTEGER NOT NULL, compute_ms REAL, ts INTEGER,
            receipt TEXT NOT NULL, batch_id TEXT);
        CREATE INDEX IF NOT EXISTS idx_node ON receipts(node_id);
        CREATE INDEX IF NOT EXISTS idx_slot ON receipts(slot);
        CREATE TABLE IF NOT EXISTS batches(
            batch_id TEXT PRIMARY KEY, created INTEGER, root TEXT, root_sum INTEGER, doc TEXT);
        """)

    def submit(self, receipt: Dict, is_enrolled: Optional[Callable[[str], bool]] = None):
        """Return (accepted, reason). Rejects bad signatures, unknown nodes, duplicates."""
        if not verify_receipt(receipt):
            return False, "bad-signature-or-format"
        if is_enrolled is not None and not is_enrolled(receipt["node_id"]):
            return False, "unknown-node"
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO receipts(unit_id,req_id,model_id,node_id,slot,work_units,compute_ms,ts,receipt)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (receipt["unit_id"], receipt["req_id"], receipt["model_id"], receipt["node_id"],
                     receipt["slot"], receipt["work_units"], receipt["compute_ms"], receipt["ts"],
                     canonical(receipt).decode()))
                self._db.commit()
            except sqlite3.IntegrityError:
                return False, "duplicate-unit"
        return True, "ok"

    def work_by_node(self, slot: Optional[int] = None, unsettled_only=False) -> Dict[str, int]:
        q, a = "SELECT node_id, SUM(work_units) FROM receipts WHERE 1=1", []
        if slot is not None:
            q += " AND slot=?"; a.append(slot)
        if unsettled_only:
            q += " AND batch_id IS NULL"
        with self._lock:
            return {n: int(u) for n, u in self._db.execute(q + " GROUP BY node_id", a)}

    def work_share(self, slot: int) -> Dict[str, float]:
        w = self.work_by_node(slot)
        tot = sum(w.values())
        return {n: u / tot for n, u in w.items()} if tot else {}

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]

    def build_settlement(self, batch_id: str, context: Dict, price_per_unit: int, *,
                         author_address: str = bb.ZERO_ADDRESS,
                         wallets: Optional[Dict[str, str]] = None,
                         deposit: Optional[int] = None, mark: bool = True) -> Dict:
        """Aggregate unsettled work per node into a Merkle-sum batch (see module doc)."""
        wallets = wallets or {}
        work = self.work_by_node(unsettled_only=True)
        if not work:
            raise ValueError("no unsettled receipts")
        batch_bytes = bb._bytes32(batch_id, "batchId")
        jobs, meta = [], {}
        for node_id in sorted(work):
            addr = wallets.get(node_id) or evm_address(node_id)
            job_id = "0x" + bb.keccak256(b"NEXUS_NODE_BATCH" + batch_bytes
                                         + bytes.fromhex(addr[2:])).hex()
            jobs.append({"jobId": job_id, "node": addr, "author": author_address,
                         "amount": work[node_id] * price_per_unit})
            meta[addr] = {"node_id": node_id, "work_units": work[node_id]}
        total = sum(j["amount"] for j in jobs)
        batch = bb.build_batch(context, batch_id, jobs, deposit if deposit is not None else total)
        doc = batch.as_contract_batch()
        doc["depositAmount"] = deposit if deposit is not None else total
        doc["pricePerUnit"] = price_per_unit
        doc["nodes"] = meta
        if mark:
            with self._lock:
                self._db.execute("UPDATE receipts SET batch_id=? WHERE batch_id IS NULL", (batch_id,))
                self._db.execute("INSERT INTO batches VALUES(?,?,?,?,?)",
                                 (batch_id, int(time.time()), batch.root, batch.root_sum, json.dumps(doc)))
                self._db.commit()
        return doc

    @staticmethod
    def verify_batch_doc(doc: Dict) -> bool:
        """Re-verify every claim of a batch document against its root."""
        ctx = bb.SettlementContext.from_mapping(doc["settlementContext"])
        for c in doc["claims"]:
            jp = bb.JobProof(c["jobId"], c["node"], c["author"], c["amount"],
                             tuple(c["proof"]), tuple(c["proofSums"]))
            if not bb.verify_claim(ctx, doc["batchId"], jp, doc["root"], doc["rootSum"]):
                return False
        return True
