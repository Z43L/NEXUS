"""Systematic Reed-Solomon k-of-n over GF(256), pure Python (Cauchy parity matrix).

Fragments 0..k-1 are the data shards; k..n-1 are parity. Any k fragments rebuild the data.
Speed trick: multiplication by a constant is bytes.translate with a 256-byte table; XOR via big ints.
"""
from functools import lru_cache
from typing import Dict, List, Tuple

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def gf_mul(a: int, b: int) -> int:
    """Multiply in GF(256) (poly 0x11d)."""
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def gf_inv(a: int) -> int:
    """Multiplicative inverse in GF(256)."""
    if a == 0:
        raise ZeroDivisionError("0 has no inverse")
    return _EXP[255 - _LOG[a]]


@lru_cache(maxsize=None)
def _mul_table(c: int) -> bytes:
    return bytes(gf_mul(c, x) for x in range(256))


def _scale(shard: bytes, c: int) -> int:
    if c == 1:
        return int.from_bytes(shard, "big")
    return int.from_bytes(shard.translate(_mul_table(c)), "big")


def _check(k: int, n: int) -> None:
    if not (1 <= k <= n <= 255):
        raise ValueError("need 1 <= k <= n <= 255, got k=%d n=%d" % (k, n))


def _row(idx: int, k: int) -> Tuple[int, ...]:
    """Generator-matrix row for fragment idx: identity for data, Cauchy for parity."""
    if idx < k:
        return tuple(1 if j == idx else 0 for j in range(k))
    return tuple(gf_inv(idx ^ j) for j in range(k))  # x=idx in [k,n), y=j in [0,k): disjoint -> idx^j != 0


@lru_cache(maxsize=256)
def _inverse(idxs: Tuple[int, ...], k: int) -> Tuple[Tuple[int, ...], ...]:
    m = [list(_row(i, k)) + [1 if r == c else 0 for c in range(k)] for r, i in enumerate(idxs)]
    for col in range(k):
        piv = next(r for r in range(col, k) if m[r][col])
        m[col], m[piv] = m[piv], m[col]
        inv = gf_inv(m[col][col])
        m[col] = [gf_mul(inv, v) for v in m[col]]
        for r in range(k):
            if r != col and m[r][col]:
                f = m[r][col]
                m[r] = [v ^ gf_mul(f, w) for v, w in zip(m[r], m[col])]
    return tuple(tuple(r[k:]) for r in m)


def encode(data: bytes, k: int, n: int) -> List[bytes]:
    """Return n equal-size fragments; zero padding is added to a multiple of k."""
    _check(k, n)
    size = -(-len(data) // k)
    padded = data + bytes(size * k - len(data))
    shards = [padded[i * size:(i + 1) * size] for i in range(k)]
    out = list(shards)
    for idx in range(k, n):
        row = _row(idx, k)
        acc = 0
        for c, s in zip(row, shards):
            acc ^= _scale(s, c)
        out.append(acc.to_bytes(size, "big"))
    return out


def decode(frags: Dict[int, bytes], k: int, n: int, length: int) -> bytes:
    """Rebuild the original `length` bytes from any >= k fragments {index: bytes}."""
    _check(k, n)
    idxs = sorted(i for i in frags if 0 <= i < n)
    if len(idxs) < k:
        raise ValueError("need %d fragments, have %d" % (k, len(idxs)))
    idxs = tuple(idxs[:k])
    size = len(frags[idxs[0]])
    if any(len(frags[i]) != size for i in idxs) or size * k < length:
        raise ValueError("fragment sizes inconsistent with length")
    if idxs == tuple(range(k)):
        shards = [frags[i] for i in idxs]
    else:
        inv = _inverse(idxs, k)
        shards = []
        for j in range(k):
            acc = 0
            for c, i in zip(inv[j], idxs):
                if c:
                    acc ^= _scale(frags[i], c)
            shards.append(acc.to_bytes(size, "big"))
    return b"".join(shards)[:length]
