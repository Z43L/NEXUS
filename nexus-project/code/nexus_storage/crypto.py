"""Ciphers (AEAD), HKDF and per-slot key derivation.

AesGcmCipher uses `cryptography`. HmacCtrCipher is a stdlib fallback:
NOT AUDITED - replace with vetted library.
"""
import hashlib
import hmac
import secrets
import struct
from typing import Optional

from .errors import DecryptionError, NexusStorageError

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAVE_CRYPTOGRAPHY = True
except Exception:  # pragma: no cover
    HAVE_CRYPTOGRAPHY = False


def hkdf(ikm: bytes, info: bytes, length: int = 32, salt: bytes = b"") -> bytes:
    """HKDF-SHA256 (RFC 5869)."""
    prk = hmac.new(salt or b"\x00" * 32, ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def new_master_key() -> bytes:
    """Fresh 32-byte per-model master key."""
    return secrets.token_bytes(32)


def derive_slot_key(master_key: bytes, slot: int) -> bytes:
    """Per-slot key: HKDF(master, "nexus/v1/slot/<slot>")."""
    return hkdf(master_key, b"nexus/v1/slot/%d" % slot)


def chunk_nonce(slice_idx: int, chunk_idx: int) -> bytes:
    """Unique 12-byte nonce per (slice, chunk); the key is already unique per slot."""
    return struct.pack(">IQ", slice_idx, chunk_idx)


def chunk_aad(model_id: str, version: str, slot: int, slice_idx: int, chunk_idx: int) -> bytes:
    """Associated data binding a chunk to its position."""
    return ("nexus/v1|%s|%s|%d|%d|%d" % (model_id, version, slot, slice_idx, chunk_idx)).encode()


class Cipher:
    """AEAD interface. encrypt returns ct||tag; decrypt raises DecryptionError."""

    name = "abstract"
    tag_len = 16

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
        raise NotImplementedError

    def decrypt(self, key: bytes, nonce: bytes, data: bytes, aad: bytes = b"") -> bytes:
        raise NotImplementedError


class AesGcmCipher(Cipher):
    """AES-256-GCM via `cryptography`."""

    name = "aes-256-gcm"
    tag_len = 16

    def __init__(self) -> None:
        if not HAVE_CRYPTOGRAPHY:
            raise NexusStorageError("cipher aes-256-gcm needs the `cryptography` package")

    def encrypt(self, key, nonce, plaintext, aad=b""):
        return AESGCM(key).encrypt(nonce, plaintext, aad)

    def decrypt(self, key, nonce, data, aad=b""):
        try:
            return AESGCM(key).decrypt(nonce, data, aad)
        except InvalidTag:
            raise DecryptionError("authentication failed (wrong key or corrupted data)")


class HmacCtrCipher(Cipher):
    """Stdlib stream cipher: HMAC-SHA256 in counter mode, encrypt-then-MAC (HMAC-SHA256 tag).

    NOT AUDITED - replace with vetted library.
    """

    name = "hmac-sha256-ctr"
    tag_len = 32

    @staticmethod
    def _keys(key: bytes):
        return hkdf(key, b"nexus/hmacctr/enc"), hkdf(key, b"nexus/hmacctr/mac")

    @staticmethod
    def _keystream(enc_key: bytes, nonce: bytes, n: int) -> bytes:
        base = hmac.new(enc_key, nonce, hashlib.sha256)
        blocks = []
        for ctr in range((n + 31) // 32):
            h = base.copy()
            h.update(struct.pack(">Q", ctr))
            blocks.append(h.digest())
        return b"".join(blocks)[:n]

    @staticmethod
    def _tag(mac_key, nonce, aad, ct) -> bytes:
        m = hmac.new(mac_key, struct.pack(">Q", len(aad)) + aad + nonce, hashlib.sha256)
        m.update(ct)
        return m.digest()

    def encrypt(self, key, nonce, plaintext, aad=b""):
        ek, mk = self._keys(key)
        ks = self._keystream(ek, nonce, len(plaintext))
        n = len(plaintext)
        ct = (int.from_bytes(plaintext, "big") ^ int.from_bytes(ks, "big")).to_bytes(n, "big")
        return ct + self._tag(mk, nonce, aad, ct)

    def decrypt(self, key, nonce, data, aad=b""):
        if len(data) < self.tag_len:
            raise DecryptionError("ciphertext too short")
        ek, mk = self._keys(key)
        ct, tag = data[:-self.tag_len], data[-self.tag_len:]
        if not hmac.compare_digest(tag, self._tag(mk, nonce, aad, ct)):
            raise DecryptionError("authentication failed (wrong key or corrupted data)")
        n = len(ct)
        ks = self._keystream(ek, nonce, n)
        return (int.from_bytes(ct, "big") ^ int.from_bytes(ks, "big")).to_bytes(n, "big")


def get_cipher(name: Optional[str] = None) -> Cipher:
    """Cipher by manifest name; default = best available."""
    if name is None:
        name = AesGcmCipher.name if HAVE_CRYPTOGRAPHY else HmacCtrCipher.name
    if name == AesGcmCipher.name:
        return AesGcmCipher()
    if name == HmacCtrCipher.name:
        return HmacCtrCipher()
    raise NexusStorageError("unknown cipher %r" % name)
