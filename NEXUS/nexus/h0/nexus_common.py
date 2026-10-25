"""NEXUS x Atenhea - H0 shared code.

Canonical receipts, Ed25519 signing, pricing per spec v0.1 section 8.
Stdlib + `cryptography` only.
"""
from __future__ import annotations

import hashlib
import base64
import json
import secrets
import time
import urllib.error
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
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


def node_id_from_public_pem(public_pem: str) -> str:
    public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    return "node_" + sha256_hex(public_der)[:16]


def resolve_model(requested: str, available: list[str]) -> str:
    """Resolve a requested model to an advertised engine model or fail closed."""
    if not available:
        raise ValueError("worker has no available models")
    if not requested:
        return available[0]
    if requested in available:
        return requested
    latest = ":latest"
    if requested.endswith(latest) and requested[:-len(latest)] in available:
        return requested[:-len(latest)]
    if requested + latest in available:
        return requested + latest
    raise ValueError(f"requested model is not available on this worker: {requested}")


def is_transient_transport_error(exc: BaseException) -> bool:
    """Retry HTTP 429/5xx and transport failures, but not application errors."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code <= 599
    return isinstance(exc, (urllib.error.URLError, TimeoutError))


def node_request_message(method: str, path: str, timestamp: str, nonce: str, body: dict) -> bytes:
    body_hash = sha256_hex(canonical_json(body))
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{body_hash}".encode("utf-8")


def sign_node_request(private_key, method: str, path: str, body: dict | None = None) -> dict:
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    message = node_request_message(method, path, timestamp, nonce, body or {})
    return {"X-Nexus-Timestamp": timestamp, "X-Nexus-Nonce": nonce,
            "X-Nexus-Signature": private_key.sign(message).hex()}


def verify_node_request(public_pem: str, method: str, path: str, body: dict,
                        timestamp: str, nonce: str, signature_hex: str) -> bool:
    try:
        timestamp_int = int(timestamp)
        if abs(int(time.time()) - timestamp_int) > 60:
            return False
        if not nonce or len(nonce) > 128:
            return False
        public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
        public_key.verify(bytes.fromhex(signature_hex),
                          node_request_message(method, path, timestamp, nonce, body))
        return True
    except (InvalidSignature, ValueError, TypeError, UnicodeError):
        return False


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_dec(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def load_or_create_router_key(base_dir: str | Path):
    """Load or create the router's Ed25519 signing key and public PEM."""
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / "router_key.pem"
    if path.exists():
        private_key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        private_key = Ed25519PrivateKey.generate()
        path.write_bytes(private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    return private_key, public_pem


def issue_job_jwt(private_key, node_id: str, job_id: str, ttl_s: int = 900) -> str:
    now = int(time.time())
    header = {"alg": "EdDSA", "typ": "JWT"}
    claims = {"iss": "nexus-router", "aud": "nexus-node", "sub": node_id,
              "job_id": job_id, "iat": now, "exp": now + ttl_s,
              "jti": f"{job_id}-{now}"}
    signing_input = (_b64u(json.dumps(header, separators=(",", ":")).encode()) + "." +
                     _b64u(json.dumps(claims, separators=(",", ":")).encode()))
    signature = private_key.sign(signing_input.encode("ascii"))
    return signing_input + "." + _b64u(signature)


def verify_job_jwt(public_pem: str, token: str, node_id: str, job_id: str) -> dict:
    """Verify router signature, issuer, audience, node/job binding and expiry."""
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ValueError("malformed dispatch JWT")
    try:
        header = json.loads(_b64u_dec(parts[0]))
        claims = json.loads(_b64u_dec(parts[1]))
        signature = _b64u_dec(parts[2])
        public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
        if header != {"alg": "EdDSA", "typ": "JWT"}:
            raise ValueError("unsupported JWT header")
        public_key.verify(signature, (parts[0] + "." + parts[1]).encode("ascii"))
    except InvalidSignature as exc:
        raise ValueError("invalid dispatch JWT signature") from exc
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid dispatch JWT") from exc
    now = int(time.time())
    issued = int(claims.get("iat", 0))
    expires = int(claims.get("exp", 0))
    if claims.get("iss") != "nexus-router" or claims.get("aud") != "nexus-node":
        raise ValueError("invalid dispatch JWT issuer or audience")
    if claims.get("sub") != node_id or claims.get("job_id") != job_id:
        raise ValueError("dispatch JWT is bound to another node or job")
    if issued > now + 30 or expires <= now or expires <= issued or expires - issued > 1800:
        raise ValueError("dispatch JWT is expired or has invalid lifetime")
    return claims


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
