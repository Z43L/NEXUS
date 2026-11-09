import itertools
import os
import random
import tempfile
import unittest

from nexus_storage import (AesGcmCipher, AttestationError, DecryptionError, DirStore, HmacCtrCipher,
                           IntegrityError, KeyVault, ManifestError, MemoryStore, ModelManifest,
                           PurePythonEd25519Signer, QuorumError, derive_slot_key, erasure,
                           fetch_slot, generate_signer, merkle_proof, merkle_root, publish_model,
                           split_chunks, verify_proof, verify_signature)
from nexus_storage import chunker, crypto, signing

RNG = random.Random(1234)


def rb(n):
    return bytes(RNG.getrandbits(8) for _ in range(n))


def model(sizes):
    return [rb(s) for s in sizes]


class ErasureTests(unittest.TestCase):
    def test_all_subsets(self):
        for k, n in [(1, 1), (1, 3), (2, 2), (2, 4), (3, 5), (4, 4), (4, 7)]:
            data = rb(101)
            frags = erasure.encode(data, k, n)
            self.assertEqual(len(frags), n)
            for subset in itertools.combinations(range(n), k):
                got = erasure.decode({i: frags[i] for i in subset}, k, n, len(data))
                self.assertEqual(got, data, (k, n, subset))

    def test_loss_of_n_minus_k_and_10_of_16(self):
        data = rb(5000)
        frags = erasure.encode(data, 10, 16)
        for _ in range(30):
            keep = RNG.sample(range(16), 10)
            self.assertEqual(erasure.decode({i: frags[i] for i in keep}, 10, 16, len(data)), data)

    def test_edge_lengths_and_too_few(self):
        for ln in (0, 1, 9, 10, 11):
            d = rb(ln)
            f = erasure.encode(d, 3, 5)
            self.assertEqual(erasure.decode({1: f[1], 3: f[3], 4: f[4]}, 3, 5, ln), d)
        with self.assertRaises(ValueError):
            erasure.decode({0: b"a", 1: b"b"}, 3, 5, 3)
        with self.assertRaises(ValueError):
            erasure.encode(b"x", 5, 4)

    def test_corrupt_fragment_gives_wrong_data(self):
        data = rb(300)
        f = erasure.encode(data, 3, 5)
        bad = bytearray(f[4]); bad[0] ^= 1
        self.assertNotEqual(erasure.decode({0: f[0], 1: f[1], 4: bytes(bad)}, 3, 5, 300), data)


class MerkleTests(unittest.TestCase):
    def test_proofs(self):
        for n in (1, 2, 3, 5, 8, 9):
            chunks = [rb(10) for _ in range(n)]
            leaves = [chunker.leaf_hash(c) for c in chunks]
            root = merkle_root(leaves)
            for i in range(n):
                p = merkle_proof(leaves, i)
                self.assertTrue(verify_proof(leaves[i], p, root))
                self.assertFalse(verify_proof(chunker.leaf_hash(b"x"), p, root))
        self.assertEqual(b"".join(split_chunks(b"abcdefg", 3)), b"abcdefg")


class CryptoTests(unittest.TestCase):
    def ciphers(self):
        cs = [HmacCtrCipher()]
        if crypto.HAVE_CRYPTOGRAPHY:
            cs.append(AesGcmCipher())
        return cs

    def test_roundtrip_wrong_key_tamper(self):
        for c in self.ciphers():
            k, n = os.urandom(32), crypto.chunk_nonce(0, 7)
            pt = rb(1000)
            ct = c.encrypt(k, n, pt, b"aad")
            self.assertEqual(c.decrypt(k, n, ct, b"aad"), pt)
            with self.assertRaises(DecryptionError):
                c.decrypt(os.urandom(32), n, ct, b"aad")
            with self.assertRaises(DecryptionError):
                c.decrypt(k, n, ct, b"other")
            with self.assertRaises(DecryptionError):
                c.decrypt(k, n, bytes([ct[0] ^ 1]) + ct[1:], b"aad")
            self.assertNotEqual(ct[:len(pt)], pt)

    def test_nonces_unique_and_slot_keys_differ(self):
        ns = {crypto.chunk_nonce(s, c) for s in range(4) for c in range(100)}
        self.assertEqual(len(ns), 400)
        m = crypto.new_master_key()
        self.assertNotEqual(derive_slot_key(m, 0), derive_slot_key(m, 1))
        self.assertEqual(len(derive_slot_key(m, 0)), 32)

    def test_hkdf_rfc5869_case1(self):
        ikm = bytes([0x0b] * 22)
        salt = bytes.fromhex("000102030405060708090a0b0c")
        info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
        okm = crypto.hkdf(ikm, info, 42, salt)
        self.assertEqual(okm.hex(), "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865")


class SigningTests(unittest.TestCase):
    def test_rfc8032_vector1(self):
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        s = PurePythonEd25519Signer(seed)
        self.assertEqual(s.public_key_hex, "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = s.sign(b"")
        self.assertEqual(sig.hex(), "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertTrue(signing.py_verify(s._pub, b"", sig))
        self.assertFalse(signing.py_verify(s._pub, b"x", sig))

    def test_backends_interoperate(self):
        if not signing.HAVE_CRYPTOGRAPHY:
            self.skipTest("cryptography not installed")
        seed = os.urandom(32)
        a, b = signing.CryptographyEd25519Signer(seed), PurePythonEd25519Signer(seed)
        self.assertEqual(a.public_key_hex, b.public_key_hex)
        self.assertEqual(a.sign(b"m"), b.sign(b"m"))
        self.assertTrue(verify_signature(b.public_key_hex, b"m", a.sign(b"m")))


def publish(sizes, cipher=None, **kw):
    store = kw.pop("store", None) or MemoryStore()
    args = dict(model_id="m", version="1", n_slots=4, ec_k=3, ec_n=5, store=store,
                author_signer=generate_signer(), license="Apache-2.0", chunk_size=700)
    args.update(kw)
    layers = model(sizes)
    man, mk = publish_model(layers, cipher=cipher, **args)
    return layers, man, mk, store


SIZES = [1000, 1, 3500, 0, 2048, 777, 1500, 64]


class PublishTests(unittest.TestCase):
    def ciphers(self):
        return [None, "hmac-sha256-ctr"]

    def test_roundtrip_models(self):
        for cipher in self.ciphers():
            for sizes, S in [(SIZES, 4), ([5000] * 8, 4), ([10, 20, 30], 3), ([4096], 1), ([123] * 9, 4)]:
                layers, man, mk, store = publish(sizes, cipher, n_slots=S)
                self.assertTrue(man.verify())
                got = []
                for s in range(S):
                    got += fetch_slot(man, s, store, derive_slot_key(mk, s))
                self.assertEqual(got, layers)

    def test_slices(self):
        layers, man, mk, store = publish(SIZES, n_slots=2, n_slices=3)
        for s in range(2):
            parts = [fetch_slot(man, s, store, derive_slot_key(mk, s), slice=j) for j in range(3)]
            a, b = man.slots[s * 3]["layer_range"]
            for li, layer in enumerate(layers[a:b]):
                self.assertEqual(b"".join(p[li] for p in parts), layer)

    def test_master_key_accepted_and_dirstore(self):
        with tempfile.TemporaryDirectory() as d:
            layers, man, mk, store = publish(SIZES, store=DirStore(d))
            self.assertEqual(fetch_slot(man, 0, DirStore(d), mk), layers[:2])

    def test_missing_fragments_ok_and_quorum_failure(self):
        layers, man, mk, store = publish(SIZES)
        key = derive_slot_key(mk, 2)
        cids = man.slots[2]["chunk_cids"]
        n = man.ec_n
        for i in range(0, len(cids), n):  # drop n-k = 2 fragments per chunk
            for j in (0, 3):
                del store.blobs[cids[i + j]]
        self.assertEqual(fetch_slot(man, 2, store, key), layers[man.slots[2]["layer_range"][0]:man.slots[2]["layer_range"][1]])
        del store.blobs[cids[1]]
        with self.assertRaises(QuorumError):
            fetch_slot(man, 2, store, key)

    def test_corrupt_fragment_detected_and_skipped(self):
        layers, man, mk, store = publish(SIZES)
        key = derive_slot_key(mk, 1)
        cids = man.slots[1]["chunk_cids"]
        store.blobs[cids[0]] = b"\x00" * len(store.blobs[cids[0]])  # corrupt a data fragment
        r = man.slots[1]["layer_range"]
        self.assertEqual(fetch_slot(man, 1, store, key), layers[r[0]:r[1]])
        for j in (1, 2):  # corrupt more than n-k -> clear failure
            store.blobs[cids[j]] = b"\x01" * len(store.blobs[cids[j]])
        with self.assertRaises(QuorumError) as cm:
            fetch_slot(man, 1, store, key)
        self.assertIn("corrupt", str(cm.exception))

    def test_merkle_catches_swapped_consistent_chunks(self):
        layers, man, mk, store = publish(SIZES, n_slots=1, ec_k=1, ec_n=1)
        e = man.slots[0]
        # replace a chunk by another valid (content-addressed) blob; manifest edited unsigned -> signature fails
        other = store.put(b"z" * len(store.blobs[e["chunk_cids"][0]]))
        e["chunk_cids"][0] = other
        with self.assertRaises(ManifestError):
            fetch_slot(man, 0, store, mk)
        with self.assertRaises(IntegrityError):  # signature skipped: Merkle still catches it
            fetch_slot(man, 0, store, mk, verify=False)

    def test_wrong_key(self):
        layers, man, mk, store = publish(SIZES)
        with self.assertRaises(DecryptionError):
            fetch_slot(man, 0, store, derive_slot_key(mk, 1))
        with self.assertRaises(DecryptionError):
            fetch_slot(man, 0, store, os.urandom(32))

    def test_manifest_tamper_and_signature(self):
        layers, man, mk, store = publish(SIZES)
        self.assertTrue(ModelManifest.from_json(man.to_json()).verify())
        self.assertEqual(ModelManifest.from_json(man.to_json()).to_json(), man.to_json())
        for field, val in [("royalty_bps", 9999), ("license", "MIT"), ("version", "2"), ("ec_k", 2)]:
            m2 = ModelManifest.from_json(man.to_json())
            setattr(m2, field, val)
            self.assertFalse(m2.verify(), field)
        m3 = ModelManifest.from_json(man.to_json())
        m3.slots[0]["merkle_root"] = "00" * 32
        self.assertFalse(m3.verify())
        m4 = ModelManifest.from_json(man.to_json())
        m4.signature = "00" * 64
        self.assertFalse(m4.verify())
        m5 = ModelManifest.from_json(man.to_json())
        m5.author_pubkey = generate_signer().public_key_hex  # attacker re-keys
        self.assertFalse(m5.verify())
        with self.assertRaises(ManifestError):
            ModelManifest.from_json('{"format":"x"}')
        with self.assertRaises(ManifestError):
            fetch_slot(m5, 0, store, mk)

    def test_bad_params(self):
        with self.assertRaises(ValueError):
            publish([1, 2], n_slots=3)
        with self.assertRaises(ValueError):
            publish([1, 2], n_slots=1, ec_k=4, ec_n=3)


class VaultTests(unittest.TestCase):
    def test_grant_revoke_log(self):
        layers, man, mk, store = publish(SIZES)
        v = KeyVault(mk)
        k = v.grant("nodeA", 2, attestation={"x": 1})
        self.assertEqual(fetch_slot(man, 2, store, k), layers[man.slots[2]["layer_range"][0]:man.slots[2]["layer_range"][1]])
        v.revoke("nodeA")
        with self.assertRaises(AttestationError):
            v.grant("nodeA", 3)
        self.assertEqual(v.granted_slots("nodeA"), [2])
        self.assertEqual([g["ok"] for g in v.grants], [True, False])
        self.assertTrue(v.grant("nodeB", 3))

    def test_attestation_callback(self):
        v = KeyVault(os.urandom(32), attestation_verifier=lambda n, s, a: bool(a and a.get("mrenclave") == "ok"))
        with self.assertRaises(AttestationError):
            v.grant("n", 0)
        with self.assertRaises(AttestationError):
            v.grant("n", 0, attestation={"mrenclave": "bad"})
        self.assertEqual(len(v.grant("n", 0, attestation={"mrenclave": "ok"})), 32)


if __name__ == "__main__":
    unittest.main()
