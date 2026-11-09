"""Signed work receipts. One receipt = one verified unit of stage work.

A receipt is signed by the node's Ed25519 key (`node_id` IS the public key hex)
over canonical JSON of all other fields. NOT AUDITED crypto if the pure-Python
fallback is active (see crypto.py).
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Dict

from .crypto import Signer, verify
from ._batch_builder import keccak256

RECEIPT_VERSION = 1
REQUIRED = ("v", "unit_id", "req_id", "model_id", "node_id", "slot", "layer_lo", "layer_hi",
            "work_units", "in_hash", "out_hash", "compute_ms", "ts", "sig")


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def unit_id_for(req_id: str, step: int, slot: int) -> str:
    return sha256_hex(("%s:%d:%d" % (req_id, step, slot)).encode())


def evm_address(pub_hex: str) -> str:
    """STAND-IN wallet address: last 20 bytes of keccak256(pubkey).

    Real deployments must register an actual wallet address per operator;
    Ed25519 keys are not secp256k1 keys, so this is only a deterministic mapping
    for testnet batches.
    """
    return "0x" + keccak256(bytes.fromhex(pub_hex))[12:].hex()


def make_receipt(signer: Signer, *, unit_id, req_id, model_id, slot, layer_lo, layer_hi,
                 work_units, in_hash, out_hash, compute_ms) -> Dict:
    body = {"v": RECEIPT_VERSION, "unit_id": unit_id, "req_id": req_id, "model_id": model_id,
            "node_id": signer.public_key_hex, "slot": slot, "layer_lo": layer_lo,
            "layer_hi": layer_hi, "work_units": work_units, "in_hash": in_hash,
            "out_hash": out_hash, "compute_ms": round(compute_ms, 3), "ts": int(time.time())}
    body["sig"] = signer.sign(canonical(body)).hex()
    return body


def verify_receipt(r: Dict) -> bool:
    """True iff all fields are present, well-typed, and the signature matches node_id."""
    try:
        if not isinstance(r, dict) or any(k not in r for k in REQUIRED):
            return False
        if r["v"] != RECEIPT_VERSION or not isinstance(r["work_units"], int) or r["work_units"] <= 0:
            return False
        body = {k: v for k, v in r.items() if k != "sig"}
        return verify(r["node_id"], canonical(body), bytes.fromhex(r["sig"]))
    except (ValueError, TypeError, KeyError):
        return False
