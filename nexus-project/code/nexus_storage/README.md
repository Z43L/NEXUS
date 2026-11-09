# nexus_storage

Publish a model as **S slots** of encrypted, erasure-coded chunks with a signed Merkle manifest, and fetch one verified slot.
Python 3.9, stdlib only; uses `cryptography` (AES-256-GCM, Ed25519) automatically if installed.

## Example (runnable)

```bash
cd nexus-project/code && PYTHONPATH=. python3 - <<'PY'
from nexus_storage import *
layers = [bytes([i]) * 5000 for i in range(8)]
store, signer = MemoryStore(), generate_signer()
manifest, master = publish_model(layers, model_id="demo", version="1", n_slots=4, ec_k=10, ec_n=16,
                                 store=store, author_signer=signer, license="Apache-2.0", chunk_size=4096)
assert manifest.verify()
key = KeyVault(master).grant("node-1", 2)             # slot key for slot 2
for cid in manifest.slots[2]["chunk_cids"][:6]:       # lose 6 of 16 fragments of the first chunk
    store.blobs.pop(cid, None)
assert fetch_slot(manifest, 2, store, key) == layers[4:6]
print("ok", manifest.manifest_id()[:16], manifest.cipher)
PY
```

## Layout

`chunker` (chunks, SHA-256 Merkle, proofs) · `erasure` (systematic RS over GF(256), Cauchy parity) · `crypto` (`Cipher`, HKDF, per-slot keys, nonces) · `signing` (`Signer`, Ed25519) · `store` (`FragmentStore`, `MemoryStore`, `DirStore`) · `manifest` · `vault` · `publish` · `bench`.

Format: layers are split into contiguous slot ranges; each layer into `n_slices` byte parts; each (slot, slice) payload is chunked (`chunk_size`), each chunk encrypted (AEAD, key = HKDF(master, slot), nonce = slice||chunk index, AAD binds model/version/slot/slice/chunk), each ciphertext chunk erasure-coded into `ec_n` fragments stored by SHA-256 CID. `chunk_cids` is chunk-major (`n` entries per chunk). Merkle root covers the ciphertext chunks. The manifest is canonical JSON (`nexus-manifest/1`), signed by the author; `manifest_id()` is the hash to anchor on-chain. `fetch_slot` skips missing/corrupt fragments (CID check), raises `QuorumError` if fewer than k valid, `IntegrityError` on Merkle mismatch, `DecryptionError` on wrong key. `key` may be the slot key or the master key.
Extras beyond the brief contract (all optional): `chunk_size`, `cipher`, `master_key` in `publish_model`; `verify` in `fetch_slot`; manifest fields `chunk_size`, `format`, slot entry `layer_range`; `MemoryStore`; `generate_signer()`.

## Real vs stand-in

| Piece | Status |
|---|---|
| Reed-Solomon k-of-n, Merkle tree/proofs, content-addressed stores, canonical manifest | Real, tested (pure Python) |
| AES-256-GCM, Ed25519 via `cryptography` | Real library, used when installed (venv) |
| `HmacCtrCipher` (HMAC-SHA256 CTR + HMAC tag) | Stand-in. **NOT AUDITED - replace with vetted library** |
| Pure-Python Ed25519 (RFC 8032 vector 1 passes) | Stand-in. **NOT AUDITED - replace with vetted library**; variable-time |
| `KeyVault` attestation | Simulated callback, not TEE. `revoke` only blocks future grants; a released key cannot be recalled (republish to rotate) |
| Storage network, on-chain anchoring | Not here: stores are local/in-memory; `manifest_id()` is the value to anchor |
| Secrecy | Storage nodes see ciphertext only; a compute node holding a slot key sees that slot in the clear. A coalition holding all slot keys reconstructs the model |

## Tests and benchmark

```bash
cd nexus-project/code && PYTHONPATH=. python3 -m unittest discover -s tests/storage -v   # 21 tests (20 + 1 skipped without cryptography)
PYTHONPATH=. python3 -m nexus_storage.bench 4         # or .venv/bin/python for AES-GCM numbers
```

Measured on this machine (macOS, Python 3.9.6, 4 MB payload, single thread, MemoryStore; one run, indicative only):

| Operation | MB/s |
|---|---|
| RS encode 10-of-16 / 4-of-6 | 255 / 659 |
| RS decode 10-of-16, 6 data shards lost (matrix path) | 231 |
| RS decode when all data shards present (concat) | >10 000 (no work) |
| HmacCtrCipher encrypt / decrypt (stdlib) | 33 / 35 |
| AES-256-GCM encrypt / decrypt (`cryptography`) | 4 518 / 9 063 |
| publish_model, 10-of-16, S=4: stdlib / AES-GCM | 29 / 201 |
| fetch_slot (all 4 slots): stdlib / AES-GCM | 30 / 1 011 |
| Pure-Python Ed25519 sign / verify | 2.6 ms / 2.8 ms |

The stdlib cipher is the bottleneck without `cryptography`; erasure is not.
