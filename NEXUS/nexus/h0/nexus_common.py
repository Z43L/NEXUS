"""NEXUS x Atenhea - H0 shared code.

Canonical receipts, Ed25519 signing, pricing per spec v0.1 section 8.
Stdlib + `cryptography` only.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

# --- Pricing reference (spec 8.4): OpenRouter Gemma-class, USD per 1M tokens.
PRICE_INPUT_MICRO_PER_TOKEN = 0.05     # $0.05 / 1M tokens = 0.05 micro-USD/token
PRICE_OUTPUT_MICRO_PER_TOKEN = 0.10    # $0.10 / 1M tokens

# --- Revenue split (spec 8.1), percentages of each job payment.
SPLIT_NODE = 75
SPLIT_NRAM_AUTHOR = 10                 # if no .nram used, goes to the node (85 total)
SPLIT_VERIFICATION = 5
SPLIT_BURN = 5
SPLIT_TREASURY = 5


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def price_micro_usd(input_tokens: int, output_tokens: int) -> int:
    """Price of a job in micro-USD (integer), per the reference table."""
    return int(round(input_tokens * PRICE_INPUT_MICRO_PER_TOKEN
                     + output_tokens * PRICE_OUTPUT_MICRO_PER_TOKEN))


def split_payment(total_micro: int, nram_used: bool) -> dict:
    node = total_micro * SPLIT_NODE // 100
    author = total_micro * SPLIT_NRAM_AUTHOR // 100 if nram_used else 0
    if not nram_used:
        node += total_micro * SPLIT_NRAM_AUTHOR // 100
    verification = total_micro * SPLIT_VERIFICATION // 100
    burn = total_micro * SPLIT_BURN // 100
    treasury = total_micro - node - author - verification - burn
    return {"node": node, "nram_author": author, "verification": verification,
            "burn": burn, "treasury": treasury}


# --- Node identity -----------------------------------------------------------

def load_or_create_node_key(node_dir: str | Path):
    """Returns (private_key, public_pem_str, node_id). Creates keypair if absent."""
    node_dir = Path(node_dir)
    node_dir.mkdir(parents=True, exist_ok=True)
    priv_path = node_dir / "node_key.pem"
    if priv_path.exists():
        priv = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    else:
        priv = Ed25519PrivateKey.generate()
        priv_path.write_bytes(priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        try:
            priv_path.chmod(0o600)
        except OSError:
            pass
    pub = priv.public_key()
    pub_pem = pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    pub_der = pub.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    node_id = "node_" + sha256_hex(pub_der)[:16]
    (node_dir / "node_pub.pem").write_text(pub_pem)
    return priv, pub_pem, node_id


def sign_receipt(priv: Ed25519PrivateKey, receipt: dict) -> str:
    return priv.sign(canonical_json(receipt)).hex()


def verify_receipt(pub_pem: str, receipt: dict, signature_hex: str) -> bool:
    try:
        pub = serialization.load_pem_public_key(pub_pem.encode("ascii"))
        pub.verify(bytes.fromhex(signature_hex), canonical_json(receipt))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# --- Per-job dispatch token (H0 local stand-in for the spec's JWT) ----------

def job_token(secret: bytes, job_id: str) -> str:
    return hmac.new(secret, job_id.encode("utf-8"), hashlib.sha256).hexdigest()


def check_job_token(secret: bytes, job_id: str, token: str) -> bool:
    return hmac.compare_digest(job_token(secret, job_id), token or "")


def load_router_secret(base_dir: str | Path) -> bytes:
    path = Path(base_dir) / "router_secret.txt"
    if path.exists():
        return path.read_bytes().strip()
    secret = hashlib.sha256(f"nexus-h0-{time.time()}-{id(object())}".encode()).digest()
    path.write_bytes(secret.hex().encode("ascii"))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret.hex().encode("ascii")


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
