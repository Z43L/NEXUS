"""Chunking and SHA-256 Merkle tree with inclusion proofs."""
import hashlib
from typing import List, Tuple

Proof = List[Tuple[str, bytes]]  # [("L"|"R", sibling_hash)]


def split_chunks(data: bytes, chunk_size: int) -> List[bytes]:
    """Split data into chunks of chunk_size bytes (last may be shorter; never empty list)."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not data:
        return [b""]
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]


def join_chunks(chunks: List[bytes]) -> bytes:
    """Inverse of split_chunks."""
    return b"".join(chunks)


def leaf_hash(chunk: bytes) -> bytes:
    """Domain-separated leaf hash."""
    return hashlib.sha256(b"\x00" + chunk).digest()


def _node(l: bytes, r: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + l + r).digest()


def _levels(leaves: List[bytes]) -> List[List[bytes]]:
    if not leaves:
        raise ValueError("no leaves")
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        cur, nxt = levels[-1], []
        for i in range(0, len(cur), 2):
            nxt.append(_node(cur[i], cur[i + 1]) if i + 1 < len(cur) else cur[i])  # odd node promoted
        levels.append(nxt)
    return levels


def merkle_root(leaves: List[bytes]) -> bytes:
    """Merkle root over already-hashed leaves (see leaf_hash)."""
    return _levels(leaves)[-1][0]


def merkle_proof(leaves: List[bytes], index: int) -> Proof:
    """Inclusion proof for leaves[index]."""
    levels = _levels(leaves)
    proof: Proof = []
    for lvl in levels[:-1]:
        sib = index ^ 1
        if sib < len(lvl):
            proof.append(("L" if sib < index else "R", lvl[sib]))
        index //= 2
    return proof


def verify_proof(leaf: bytes, proof: Proof, root: bytes) -> bool:
    """Check an inclusion proof for a hashed leaf against root."""
    h = leaf
    for side, sib in proof:
        h = _node(sib, h) if side == "L" else _node(h, sib)
    return h == root
