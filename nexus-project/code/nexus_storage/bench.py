"""Simple throughput benchmark: PYTHONPATH=. python3 -m nexus_storage.bench [MB]"""
import os
import sys
import time

from . import crypto, erasure, signing
from .publish import fetch_slot, publish_model
from .store import MemoryStore


def _rate(label, mb, fn):
    t = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t
    print("%-44s %8.2f MB/s  (%.3fs)" % (label, mb / dt, dt))
    return r


def main(mb: float = 4.0) -> None:
    data = os.urandom(int(mb * 1024 * 1024))
    print("python %s | cryptography=%s | payload %.1f MB" % (sys.version.split()[0], crypto.HAVE_CRYPTOGRAPHY, mb))
    for k, n in [(10, 16), (4, 6)]:
        frags = _rate("erasure encode %d-of-%d" % (k, n), mb, lambda: erasure.encode(data, k, n))
        _rate("erasure decode %d-of-%d (data frags, fast)" % (k, n), mb,
              lambda: erasure.decode({i: frags[i] for i in range(k)}, k, n, len(data)))
        keep = {i: frags[i] for i in range(n - k, n)}  # worst case: lose first n-k data shards
        _rate("erasure decode %d-of-%d (n-k lost, matrix)" % (k, n), mb,
              lambda: erasure.decode(keep, k, n, len(data)))
    names = [crypto.HmacCtrCipher.name] + ([crypto.AesGcmCipher.name] if crypto.HAVE_CRYPTOGRAPHY else [])
    for name in names:
        c, key, nonce = crypto.get_cipher(name), os.urandom(32), crypto.chunk_nonce(0, 0)
        ct = _rate("encrypt %s" % name, mb, lambda: c.encrypt(key, nonce, data))
        _rate("decrypt %s" % name, mb, lambda: c.decrypt(key, nonce, ct))
    for name in names:
        layers = [data[i::8] for i in range(8)]
        store, signer = MemoryStore(), signing.generate_signer()
        man, mk = _rate("publish_model 8 layers S=4 10-of-16 %s" % name, mb, lambda: publish_model(
            layers, model_id="b", version="1", n_slots=4, ec_k=10, ec_n=16, store=store,
            author_signer=signer, license="n/a", cipher=name))
        _rate("fetch_slot x4 (all slots) %s" % name, mb, lambda: [
            fetch_slot(man, s, store, crypto.derive_slot_key(mk, s)) for s in range(4)])
    s = signing.PurePythonEd25519Signer()
    t = time.perf_counter(); sig = s.sign(b"m"); t1 = time.perf_counter(); signing.py_verify(s._pub, b"m", sig); t2 = time.perf_counter()
    print("pure-python ed25519: sign %.1f ms, verify %.1f ms" % ((t1 - t) * 1e3, (t2 - t1) * 1e3))


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 4.0)
