"""Signing primitives behind a replaceable `Signer` interface.

If the `cryptography` package is importable it is used (vetted library).
Otherwise a pure-Python Ed25519 (RFC 8032 reference algorithm) is used.

NOT AUDITED - replace with vetted library. The pure-Python fallback is not
constant-time and is meant only for the stdlib-only MVP / tests.
"""
from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod

try:  # optional fast path
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.hazmat.primitives import serialization as _ser
    from cryptography.exceptions import InvalidSignature as _InvalidSignature
    HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False

# ---------------------------------------------------------------------------
# Pure-Python Ed25519 (RFC 8032 section 6 reference). NOT AUDITED.
# ---------------------------------------------------------------------------
_p = 2 ** 255 - 19
_q = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _p - 2, _p) % _p
_sqrt_m1 = pow(2, (_p - 1) // 4, _p)


def _inv(x):
    return pow(x, _p - 2, _p)


def _add(P, Q):
    A = (P[1] - P[0]) * (Q[1] - Q[0]) % _p
    B = (P[1] + P[0]) * (Q[1] + Q[0]) % _p
    C = 2 * P[3] * Q[3] * _d % _p
    D = 2 * P[2] * Q[2] % _p
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _p, G * H % _p, F * G % _p, E * H % _p)


def _mul(s, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _eq(P, Q):
    return ((P[0] * Q[2] - Q[0] * P[2]) % _p == 0
            and (P[1] * Q[2] - Q[1] * P[2]) % _p == 0)


def _recover_x(y, sign):
    if y >= _p:
        return None
    x2 = (y * y - 1) * _inv(_d * y * y + 1) % _p
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_p + 3) // 8, _p)
    if (x * x - x2) % _p != 0:
        x = x * _sqrt_m1 % _p
    if (x * x - x2) % _p != 0:
        return None
    if (x & 1) != sign:
        x = _p - x
    return x


_gy = 4 * _inv(5) % _p
_gx = _recover_x(_gy, 0)
_G = (_gx, _gy, 1, _gx * _gy % _p)


def _compress(P):
    zi = _inv(P[2])
    x, y = P[0] * zi % _p, P[1] * zi % _p
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _p)


def _expand(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _h(b):
    return int.from_bytes(hashlib.sha512(b).digest(), "little") % _q


def pure_public_key(seed: bytes) -> bytes:
    a, _ = _expand(seed)
    return _compress(_mul(a, _G))


def pure_sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    A = _compress(_mul(a, _G))
    r = _h(prefix + msg)
    Rs = _compress(_mul(r, _G))
    s = (r + _h(Rs + A + msg) * a) % _q
    return Rs + int.to_bytes(s, 32, "little")


def pure_verify(pub: bytes, msg: bytes, sig: bytes) -> bool:
    if len(pub) != 32 or len(sig) != 64:
        return False
    A = _decompress(pub)
    R = _decompress(sig[:32])
    if A is None or R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= _q:
        return False
    k = _h(sig[:32] + pub + msg)
    return _eq(_mul(s, _G), _add(R, _mul(k, A)))


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
class Signer(ABC):
    """Anything that can sign bytes and expose a public key (hex)."""

    @property
    @abstractmethod
    def public_key_hex(self) -> str: ...

    @abstractmethod
    def sign(self, msg: bytes) -> bytes: ...


class Ed25519Signer(Signer):
    def __init__(self, seed: bytes = None):
        self.seed = seed if seed is not None else os.urandom(32)
        if len(self.seed) != 32:
            raise ValueError("seed must be 32 bytes")
        if HAVE_CRYPTOGRAPHY:
            self._k = Ed25519PrivateKey.from_private_bytes(self.seed)
            self._pub = self._k.public_key().public_bytes(
                _ser.Encoding.Raw, _ser.PublicFormat.Raw)
        else:
            self._k = None
            self._pub = pure_public_key(self.seed)

    @property
    def public_key_hex(self) -> str:
        return self._pub.hex()

    @property
    def public_key(self) -> bytes:
        return self._pub

    def sign(self, msg: bytes) -> bytes:
        if self._k is not None:
            return self._k.sign(msg)
        return pure_sign(self.seed, msg)


def verify(pub_hex: str, msg: bytes, sig: bytes) -> bool:
    try:
        pub = bytes.fromhex(pub_hex)
    except (ValueError, TypeError):
        return False
    if HAVE_CRYPTOGRAPHY:
        try:
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
            return True
        except (_InvalidSignature, ValueError):
            return False
    return pure_verify(pub, msg, sig)


def load_or_create_signer(path: str) -> Ed25519Signer:
    """Persist a 32-byte seed in `path` (hex, mode 0600). Testnet key storage."""
    if os.path.exists(path):
        with open(path) as f:
            return Ed25519Signer(bytes.fromhex(f.read().strip()))
    s = Ed25519Signer()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(s.seed.hex())
    return s
