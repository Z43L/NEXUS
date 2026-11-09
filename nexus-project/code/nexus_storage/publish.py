"""publish_model / fetch_slot: split -> chunk -> encrypt -> erasure code -> signed manifest."""
import struct
from typing import List, Optional, Tuple

from . import erasure
from .chunker import join_chunks, leaf_hash, merkle_root, split_chunks
from .crypto import (chunk_aad, chunk_nonce, derive_slot_key, get_cipher,
                     new_master_key)
from .errors import (DecryptionError, IntegrityError, ManifestError,
                     NexusStorageError, QuorumError)
from .manifest import ModelManifest
from .signing import Signer
from .store import FragmentStore, cid_of


def _slot_ranges(n_layers: int, n_slots: int) -> List[Tuple[int, int]]:
    base, extra = divmod(n_layers, n_slots)
    out, a = [], 0
    for s in range(n_slots):
        b = a + base + (1 if s < extra else 0)
        out.append((a, b))
        a = b
    return out


def _slice_part(layer: bytes, slice_idx: int, n_slices: int) -> bytes:
    size = -(-len(layer) // n_slices)
    return layer[slice_idx * size:(slice_idx + 1) * size]


def _pack(parts: List[bytes]) -> bytes:
    return b"".join(struct.pack(">Q", len(p)) + p for p in parts)


def _unpack(blob: bytes) -> List[bytes]:
    out, i = [], 0
    while i < len(blob):
        if i + 8 > len(blob):
            raise IntegrityError("truncated slot payload")
        (n,) = struct.unpack(">Q", blob[i:i + 8])
        i += 8
        if i + n > len(blob):
            raise IntegrityError("truncated slot payload")
        out.append(blob[i:i + n])
        i += n
    return out


def publish_model(layers: List[bytes], *, model_id: str, version: str, n_slots: int, ec_k: int,
                  ec_n: int, store: FragmentStore, author_signer: Signer, license: str,
                  royalty_bps: int = 0, n_slices: int = 1, chunk_size: int = 1 << 20,
                  cipher: Optional[str] = None, master_key: Optional[bytes] = None
                  ) -> Tuple[ModelManifest, bytes]:
    """Publish a model; returns (signed manifest, master_key).

    Layers are cut into n_slots contiguous ranges; each layer is further cut into n_slices byte
    parts (slice j of every layer of a slot forms one stored object). Each object is chunked,
    encrypted with the slot key, and every encrypted chunk is erasure-coded into ec_n fragments.
    """
    if not (1 <= n_slots <= len(layers)):
        raise ValueError("need 1 <= n_slots <= n_layers")
    if n_slices < 1 or not (1 <= ec_k <= ec_n <= 255) or not (0 <= royalty_bps <= 10000):
        raise ValueError("invalid n_slices / erasure / royalty parameters")
    ci = get_cipher(cipher)
    master = master_key or new_master_key()
    entries = []
    for slot, (a, b) in enumerate(_slot_ranges(len(layers), n_slots)):
        skey = derive_slot_key(master, slot)
        for sl in range(n_slices):
            payload = _pack([_slice_part(layers[i], sl, n_slices) for i in range(a, b)])
            cids, leaves = [], []
            for ci_idx, chunk in enumerate(split_chunks(payload, chunk_size)):
                ct = ci.encrypt(skey, chunk_nonce(sl, ci_idx), chunk,
                                chunk_aad(model_id, version, slot, sl, ci_idx))
                leaves.append(leaf_hash(ct))
                cids.extend(store.put(f) for f in erasure.encode(ct, ec_k, ec_n))
            entries.append({"slot": slot, "slice": sl, "chunk_cids": cids,
                            "merkle_root": merkle_root(leaves).hex(), "size": len(payload),
                            "layer_range": [a, b]})
    m = ModelManifest(model_id=model_id, version=version, n_layers=len(layers), n_slots=n_slots,
                      n_slices=n_slices, ec_k=ec_k, ec_n=ec_n, cipher=ci.name, license=license,
                      author_pubkey="", royalty_bps=royalty_bps, slots=entries, chunk_size=chunk_size)
    m.sign(author_signer)
    return m, master


def fetch_slot(manifest: ModelManifest, slot: int, store: FragmentStore, key: bytes,
               slice: int = 0, verify: bool = True) -> List[bytes]:
    """Rebuild, verify (CIDs, Merkle root, AEAD) and decrypt one slot slice; returns its layers.

    `key` is the slot key (KeyVault.grant). A model master key is also accepted.
    Raises ManifestError / QuorumError / IntegrityError / DecryptionError.
    """
    if verify and not manifest.verify():
        raise ManifestError("manifest signature/structure invalid")
    entry = next((e for e in manifest.slots if e["slot"] == slot and e["slice"] == slice), None)
    if entry is None:
        raise ManifestError("no entry for slot %d slice %d" % (slot, slice))
    k, n, ci = manifest.ec_k, manifest.ec_n, get_cipher(manifest.cipher)
    cids, size, cs = entry["chunk_cids"], entry["size"], manifest.chunk_size
    n_chunks = max(1, -(-size // cs))
    if len(cids) != n_chunks * n:
        raise ManifestError("chunk_cids length inconsistent with size/ec params")
    cts, leaves = [], []
    for i in range(n_chunks):
        plain_len = min(cs, size - i * cs)
        ct_len = plain_len + ci.tag_len
        good, bad, missing = {}, [], []
        for j in range(n):  # data fragments first: fast path needs no matrix inversion
            if len(good) >= k:
                break
            cid = cids[i * n + j]
            frag = store.get(cid)
            if frag is None:
                missing.append(j)
            elif cid_of(frag) != cid:
                bad.append(j)
            else:
                good[j] = frag
        if len(good) < k:
            raise QuorumError("slot %d slice %d chunk %d: %d valid fragments, need %d "
                              "(missing=%s corrupt=%s)" % (slot, slice, i, len(good), k, missing, bad))
        ct = erasure.decode(good, k, n, ct_len)
        cts.append(ct)
        leaves.append(leaf_hash(ct))
    if merkle_root(leaves).hex() != entry["merkle_root"]:
        raise IntegrityError("Merkle root mismatch for slot %d slice %d" % (slot, slice))
    def dec(skey):
        return [ci.decrypt(skey, chunk_nonce(slice, i), ct,
                           chunk_aad(manifest.model_id, manifest.version, slot, slice, i))
                for i, ct in enumerate(cts)]
    try:
        plain = dec(key)
    except DecryptionError:
        try:
            plain = dec(derive_slot_key(key, slot))
        except DecryptionError:
            raise DecryptionError("wrong key for slot %d (or tampered ciphertext)" % slot)
    blob = join_chunks(plain)
    if len(blob) != size:
        raise IntegrityError("payload size mismatch")
    layers = _unpack(blob)
    a, b = entry["layer_range"]
    if len(layers) != b - a:
        raise IntegrityError("layer count mismatch")
    return layers
