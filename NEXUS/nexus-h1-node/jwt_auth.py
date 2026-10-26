"""Minimal EdDSA (Ed25519) JWT for NEXUS H1 job dispatch (spec 6.1).

The Router signs a short-lived (15 min) JWT per dispatched job; the worker
verifies it against the Router's public key before executing anything.
Stdlib + cryptography only, same stack as H0 receipts.
"""
from __future__ import annotations

import base64
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_dec(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_or_create_router_key(base_dir):
    from pathlib import Path
    import hashlib
    base = Path(base_dir)
    path = base / "router_key.pem"
    if path.exists():
        priv = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        priv = Ed25519PrivateKey.generate()
        path.write_bytes(priv.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    return priv, pub_pem


def issue_job_jwt(priv, node_id: str, job_id: str, ttl_s: int = 900) -> str:
    now = int(time.time())
    header = {"alg": "EdDSA", "typ": "JWT"}
    claims = {"iss": "nexus-router", "aud": "nexus-node", "sub": node_id,
              "job_id": job_id, "iat": now, "exp": now + ttl_s,
              "jti": f"{job_id}-{now}"}
    signing_input = (_b64u(json.dumps(header, separators=(",", ":")).encode())
                     + "." + _b64u(json.dumps(claims, separators=(",", ":")).encode()))
    sig = priv.sign(signing_input.encode("ascii"))
    return signing_input + "." + _b64u(sig)


def verify_job_jwt(pub_pem: str, token: str, node_id: str, job_id: str) -> dict:
    """Raises ValueError on any problem; returns claims when valid."""
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ValueError("malformed jwt")
    signing_input = (parts[0] + "." + parts[1]).encode("ascii")
    pub = serialization.load_pem_public_key(pub_pem.encode("ascii"))
    try:
        pub.verify(_b64u_dec(parts[2]), signing_input)
    except InvalidSignature:
        raise ValueError("bad jwt signature")
    claims = json.loads(_b64u_dec(parts[1]))
    if claims.get("iss") != "nexus-router" or claims.get("aud") != "nexus-node":
        raise ValueError("bad jwt iss/aud")
    if claims.get("sub") != node_id or claims.get("job_id") != job_id:
        raise ValueError("jwt not bound to this node/job")
    if int(claims.get("exp", 0)) < int(time.time()):
        raise ValueError("jwt expired")
    return claims
