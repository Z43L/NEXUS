"""Signer interface + Ed25519.

Backends: `cryptography` if installed; otherwise a pure-Python RFC 8032 implementation.
NOT AUDITED - replace with vetted library (the pure-Python path is variable-time, for testnet only).
"""
import hashlib
import secrets
from typing import Optional

try:  # vetted backend, optional
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False

# ---- pure Python Ed25519 (RFC 8032 section 6) -- NOT AUDITED - replace with vetted library ----
_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> Optional[int]:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(s: int, p):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _compress(p) -> bytes:
    zi = _inv(p[2])
    x, y = p[0] * zi % _P, p[1] * zi % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _eq(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _expand(seed: bytes):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _h512(m: bytes) -> int:
    return int.from_bytes(hashlib.sha512(m).digest(), "little")


def py_public_key(seed: bytes) -> bytes:
    """Ed25519 public key from a 32-byte seed (pure Python)."""
    return _compress(_mul(_expand(seed)[0], _G))


def py_sign(seed: bytes, msg: bytes) -> bytes:
    """Ed25519 signature (pure Python)."""
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, _G))
    r = _h512(prefix + msg) % _L
    R = _compress(_mul(r, _G))
    k = _h512(R + pub + msg) % _L
    return R + int.to_bytes((r + k * a) % _L, 32, "little")


def py_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    """Ed25519 verification (pure Python)."""
    if len(sig) != 64 or len(pub) != 32:
        return False
    A, R = _decompress(pub), _decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _L:
        return False
    k = _h512(sig[:32] + pub + msg) % _L
    return _eq(_mul(s, _G), _add(R, _mul(k, A)))


# ---- interface ----
class Signer:
    """Signing interface: public_key_hex + sign(msg)."""

    backend = "abstract"

    @property
    def public_key_hex(self) -> str:
        raise NotImplementedError

    def sign(self, msg: bytes) -> bytes:
        raise NotImplementedError


class PurePythonEd25519Signer(Signer):
    """RFC 8032 in pure Python. NOT AUDITED - replace with vetted library."""

    backend = "pure-python-ed25519 (NOT AUDITED)"

    def __init__(self, seed: Optional[bytes] = None) -> None:
        self.seed = seed if seed is not None else secrets.token_bytes(32)
        if len(self.seed) != 32:
            raise ValueError("seed must be 32 bytes")
        self._pub = py_public_key(self.seed)

    @property
    def public_key_hex(self) -> str:
        return self._pub.hex()

    def sign(self, msg: bytes) -> bytes:
        return py_sign(self.seed, msg)


class CryptographyEd25519Signer(Signer):
    """Ed25519 via the `cryptography` package."""

    backend = "cryptography-ed25519"

    def __init__(self, seed: Optional[bytes] = None) -> None:
        if not HAVE_CRYPTOGRAPHY:
            raise RuntimeError("cryptography not installed")
        seed = seed if seed is not None else secrets.token_bytes(32)
        self.seed = seed
        self._sk = Ed25519PrivateKey.from_private_bytes(seed)
        self._pub = self._sk.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    @property
    def public_key_hex(self) -> str:
        return self._pub.hex()

    def sign(self, msg: bytes) -> bytes:
        return self._sk.sign(msg)


def generate_signer(seed: Optional[bytes] = None) -> Signer:
    """Best available Ed25519 signer."""
    return CryptographyEd25519Signer(seed) if HAVE_CRYPTOGRAPHY else PurePythonEd25519Signer(seed)


Ed25519Signer = generate_signer  # convenience alias: Ed25519Signer() -> Signer


def verify_signature(pubkey_hex: str, msg: bytes, sig: bytes) -> bool:
    """Verify an Ed25519 signature; never raises."""
    try:
        pub = bytes.fromhex(pubkey_hex)
        if HAVE_CRYPTOGRAPHY:
            try:
                Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
                return True
            except (InvalidSignature, ValueError):
                return False
        return py_verify(pub, msg, sig)
    except Exception:
        return False
