import json
import os
import sys
import time
import unittest
import urllib.request
import urllib.error

from nexus_runtime import _batch_builder as bb
from nexus_runtime import crypto
from nexus_runtime.coordinator import Coordinator, stratified_assign, effective_speed
from nexus_runtime.crypto import Ed25519Signer
from nexus_runtime.ledger import Ledger
from nexus_runtime.localcluster import LocalCluster
from nexus_runtime.model_demo import DemoModel, tok_encode, slot_ranges, Layer
from nexus_runtime.pipeline import Pipeline
from nexus_runtime.receipts import make_receipt, verify_receipt, evm_address, sha256_hex
from nexus_api.gateway import Gateway, ApiKeyStore, RateLimiter
from nexus_api.engine import NexusPipelineEngine

CTX = {"chainId": 31337, "escrowAddress": "0x" + "ab" * 20, "tokenAddress": "0x" + "cd" * 20}


def mk_receipt(signer, unit="u1", slot=0, units=4):
    return make_receipt(signer, unit_id=sha256_hex(unit.encode()), req_id="r", model_id="m", slot=slot,
                        layer_lo=0, layer_hi=units, work_units=units, in_hash="a" * 64,
                        out_hash="b" * 64, compute_ms=1.0)


class TestCrypto(unittest.TestCase):
    def test_rfc8032_vector1_pure(self):
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        pub = crypto.pure_public_key(seed)
        self.assertEqual(pub.hex(), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        sig = crypto.pure_sign(seed, b"")
        self.assertEqual(sig.hex(), "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        self.assertTrue(crypto.pure_verify(pub, b"", sig))
        self.assertFalse(crypto.pure_verify(pub, b"x", sig))


class TestAtenheaEngine(unittest.TestCase):
    def test_forwards_to_openai_compatible_server(self):
        from nexus_runtime import httpx
        from nexus_api.engine import AtenheaEngine

        def h(method, path, q, body, headers):
            if path == "/v1/models":
                return 200, {"data": [{"id": "athenea-e2b"}]}
            return 200, {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
        srv = httpx.JsonServer("127.0.0.1", 0, h).start()
        try:
            e = AtenheaEngine("http://127.0.0.1:%d" % srv.port)
            self.assertEqual(e.list_models()[0]["id"], "athenea-e2b")
            r = e.chat("athenea-e2b", [{"role": "user", "content": "x"}], 4, 0.0, 1)
            self.assertEqual((r["text"], r["completion_tokens"]), ("ok", 1))
            with self.assertRaises(KeyError):
                e.chat("nope", [], 4, 0.0, 1)
        finally:
            srv.stop()


class TestStageAuth(unittest.TestCase):
    def test_stage_requires_token_when_configured(self):
        from nexus_runtime import httpx
        from nexus_runtime.node import NodeAgent
        n = NodeAgent("http://127.0.0.1:1", stage_token="s3cret")
        self.assertEqual(n._handle("POST", "/stage", {}, {"slot": 0}, {})[0], 401)
        self.assertEqual(n._handle("POST", "/stage", {}, {"slot": 0}, {"Authorization": "Bearer nope"})[0], 401)
        # right token passes auth (then fails later because no slot is loaded)
        self.assertEqual(n._handle("POST", "/stage", {}, {"slot": 0}, {"authorization": "Bearer s3cret"})[0], 503)

    def test_open_when_no_token(self):
        from nexus_runtime.node import NodeAgent
        n = NodeAgent("http://127.0.0.1:1", stage_token="")
        self.assertEqual(n._handle("POST", "/stage", {}, {"slot": 0}, {})[0], 503)


class TestEquivalence(unittest.TestCase):
    def test_distributed_equals_reference(self):
        c = LocalCluster([{"operator": "A"}, {"operator": "B"}, {"operator": "C"}, {"operator": "D"}],
                         n_slots=4)
        try:
            m = c.model
            pipe = Pipeline(c.coord.url, c.head())
            ids = tok_encode("hello nexus")
            # raw activations are bit-identical
            x = m.embed(ids)
            self.assertEqual(pipe.forward(x, "eq-1", 0), m.reference_forward(x))
            # and so is the generated sequence
            r = pipe.generate(ids, 6, req_id="eq-2")
            self.assertEqual(r["tokens"], m.reference_generate(ids, 6))
            self.assertEqual(len(r["receipts"]), 6 * 4)
            self.assertEqual(r["submitted"]["accepted"], 24)
        finally:
            c.stop()

    def test_layer_serialisation_roundtrip(self):
        m = DemoModel(n_layers=2)
        for b in m.layer_blobs():
            self.assertEqual(Layer.from_bytes(b).to_bytes(), b)


class TestStorageIntegration(unittest.TestCase):
    def test_real_nexus_storage_slots_equal_reference(self):
        from nexus_runtime.layers import storage_available
        if not storage_available():
            self.skipTest("nexus_storage not importable")
        c = LocalCluster([{"operator": "A"}, {"operator": "B"}, {"operator": "C"}], n_slots=3,
                         use_storage=True)
        try:
            self.assertTrue(c.manifest.verify())
            self.assertTrue(all(n.layer_source.kind == "nexus_storage" for n in c.nodes))
            ids = tok_encode("via storage")
            r = Pipeline(c.coord.url, c.head()).generate(ids, 4)
            self.assertEqual(r["tokens"], c.model.reference_generate(ids, 4))
        finally:
            c.stop()


class TestFailover(unittest.TestCase):
    def test_node_dies_mid_request(self):
        c = LocalCluster([{"operator": "A"}, {"operator": "B"}, {"operator": "C"}, {"operator": "C2"},
                          {"operator": "D"}, {"operator": "E"}], n_slots=2, hb_timeout=1.5)
        try:
            pipe = Pipeline(c.coord.url, c.head(), timeout=2.0)
            ids = tok_encode("failover")
            ref = c.model.reference_generate(ids, 8)
            killed = []

            def on_token(step, tok):
                if step == 2 and not killed:
                    victim = c.nodes_of_slot(0)[0]
                    victim.stop()
                    killed.append(victim.node_id)

            r = pipe.generate(ids, 8, on_token=on_token)
            self.assertEqual(r["tokens"], ref)
            self.assertEqual(len(killed), 1)
            self.assertGreaterEqual(r["failovers"], 1)
            # every receipt after the kill comes from the survivor(s)
            after = [x for x in r["receipts"] if x["slot"] == 0][3:]
            self.assertTrue(all(x["node_id"] != killed[0] for x in after))
            # coordinator eventually marks it down by heartbeat timeout
            time.sleep(2.0)
            plan = c.coord.plan()
            dead = [n for s in plan["slots"] for n in s["nodes"] if n["node_id"] == killed[0]][0]
            self.assertFalse(dead["alive"])
        finally:
            c.stop()


class TestReceipts(unittest.TestCase):
    def test_valid_and_tampered(self):
        s = Ed25519Signer()
        r = mk_receipt(s)
        self.assertTrue(verify_receipt(r))
        for field, val in (("work_units", 999), ("out_hash", "c" * 64), ("slot", 3), ("node_id", Ed25519Signer().public_key_hex)):
            t = dict(r); t[field] = val
            self.assertFalse(verify_receipt(t), field)
        t = dict(r); del t["sig"]
        self.assertFalse(verify_receipt(t))

    def test_ledger_rejects_tampered_unknown_duplicate(self):
        s = Ed25519Signer()
        led = Ledger()
        r = mk_receipt(s)
        self.assertEqual(led.submit(r, lambda n: n == s.public_key_hex), (True, "ok"))
        self.assertEqual(led.submit(r, lambda n: True), (False, "duplicate-unit"))
        t = mk_receipt(s, "u2"); t["work_units"] = 10 ** 6
        self.assertEqual(led.submit(t)[0], False)
        self.assertEqual(led.submit(mk_receipt(s, "u3"), lambda n: False), (False, "unknown-node"))
        self.assertEqual(led.work_by_node(), {s.public_key_hex: 4})


class TestAssignment(unittest.TestCase):
    def test_operator_never_gets_two_slots(self):
        caps = {"op%d" % i: 1.0 + (i % 5) for i in range(40)}
        for seed in range(20):
            a = stratified_assign(caps, 8, "%064x" % seed)
            self.assertEqual(set(a), set(caps))
            self.assertTrue(all(0 <= s < 8 for s in a.values()))
            self.assertEqual(len(set(a.values())), 8)  # every slot covered
        with self.assertRaises(ValueError):
            stratified_assign({"a": 1, "b": 1}, 3, "00")

    def test_multi_node_operator_stays_in_one_slot(self):
        c = Coordinator(2, 4, "m")
        for i, op in enumerate(["A", "A", "A", "B", "C", "C"]):
            s = Ed25519Signer()
            from nexus_runtime.coordinator import enroll_message
            req = {"node_id": s.public_key_hex, "operator": op, "url": "http://x:%d" % i,
                   "declared_speed": 10.0, "measured_speed": 10.0, "ts": 1}
            req["sig"] = s.sign(enroll_message(req)).hex()
            self.assertTrue(c.enroll(req)[0])
        c.close_registry("seed")
        by_op = {}
        for n in c.nodes.values():
            by_op.setdefault(n["operator"], set()).add(n["slot"])
        self.assertTrue(all(len(v) == 1 for v in by_op.values()))
        self.assertFalse(c.enroll({"node_id": "00", "operator": "Z"})[0])  # registry closed

    def test_enroll_requires_signature_and_caps_declared_speed(self):
        c = Coordinator(1, 2, "m")
        s = Ed25519Signer()
        req = {"node_id": s.public_key_hex, "operator": "A", "url": "http://x", "declared_speed": 10.0,
               "measured_speed": 5.0, "ts": 1, "sig": "00" * 64}
        self.assertEqual(c.enroll(req), (False, "bad-signature"))
        from nexus_runtime.coordinator import enroll_message
        req["sig"] = s.sign(enroll_message(req)).hex()
        self.assertTrue(c.enroll(req)[0])
        self.assertEqual(c.nodes[s.public_key_hex]["speed"], 5.0)
        self.assertEqual(effective_speed(3.0, 9.0), 3.0)


class TestProportionalRouting(unittest.TestCase):
    def test_work_split_follows_speed(self):
        # one slot, two nodes of one operator pair: slowdown 1 vs 3 => ~3:1 speed
        c = LocalCluster([{"operator": "A", "slowdown": 1.0}, {"operator": "A", "slowdown": 4.0}],
                         n_slots=1, model=DemoModel(n_layers=2, d=32, h=64))
        try:
            speeds = {n.node_id: n.measured for n in c.nodes}
            pipe = Pipeline(c.coord.url, c.head())
            r = pipe.generate(tok_encode("route"), 60, req_id="prop")
            share = c.coord.ledger.work_share(0)
            total = sum(speeds.values())
            for nid, sp in speeds.items():
                self.assertAlmostEqual(share[nid], sp / total, delta=0.05)
            fast = max(speeds, key=speeds.get)
            slow = min(speeds, key=speeds.get)
            self.assertGreater(share[fast], 1.5 * share[slow])
        finally:
            c.stop()


class TestSettlement(unittest.TestCase):
    def test_batch_root_matches_independent_computation(self):
        led = Ledger()
        signers = [Ed25519Signer() for _ in range(3)]
        units = [5, 7, 11]
        for i, (s, u) in enumerate(zip(signers, units)):
            self.assertTrue(led.submit(mk_receipt(s, "x%d" % i, slot=i, units=u))[0])
        bid = "0x" + "11" * 32
        author = "0x" + "bb" * 20
        doc = led.build_settlement(bid, CTX, price_per_unit=1000, author_address=author)
        self.assertEqual(doc["rootSum"], sum(units) * 1000)
        self.assertTrue(Ledger.verify_batch_doc(doc))
        # independent recomputation straight from the escrow's leaf/parent definition
        ctx = bb.SettlementContext.from_mapping(CTX)
        bidb = bytes.fromhex(bid[2:])
        leaves = []
        for s, u in sorted(zip(signers, units), key=lambda t: t[0].public_key_hex):
            addr = evm_address(s.public_key_hex)
            jid = bb.keccak256(b"NEXUS_NODE_BATCH" + bidb + bytes.fromhex(addr[2:]))
            leaf = bb.keccak256(bb.encode_job_leaf(ctx, bid, "0x" + jid.hex(), addr, author, u * 1000))
            leaves.append((bb.keccak256(leaf + (u * 1000).to_bytes(32, "big")), u * 1000))
        def parent(a, b):
            (ha, sa), (hb, sb) = (a, b) if a[0] < b[0] else (b, a)
            return (bb.keccak256(ha + sa.to_bytes(32, "big") + hb + sb.to_bytes(32, "big")), sa + sb)
        # 3 leaves: pair (0,1), promote 2, then pair
        root = parent(parent(leaves[0], leaves[1]), leaves[2])
        self.assertEqual(doc["root"], "0x" + root[0].hex())
        # settled receipts are not re-batched
        with self.assertRaises(ValueError):
            led.build_settlement("0x" + "22" * 32, CTX, 1000)
        # tampering with an amount breaks verification
        doc["claims"][0]["amount"] += 1
        self.assertFalse(Ledger.verify_batch_doc(doc))

    def test_escrow_published_vector_root(self):
        p = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "NEXUS", "settlement-evm",
                         "vectors", "merkle_sum_vectors.json")
        if not os.path.exists(p):
            self.skipTest("vectors file not found")
        with open(p) as f:
            doc = json.load(f)
        v = doc["batch"]
        ctx = doc.get("settlementContext") or v.get("settlementContext")
        if not ctx:
            self.skipTest("vector has no settlementContext")
        b = bb.build_batch(ctx, v["batchId"], v["jobs"], v["depositAmount"])
        self.assertEqual(b.root, v["root"])


def http(method, url, body=None, key=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    if key:
        req.add_header("Authorization", "Bearer " + key)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = LocalCluster([{"operator": "A"}, {"operator": "B"}], n_slots=2,
                             model=DemoModel(n_layers=4, d=32, h=64))
        cls.keys = ApiKeyStore()
        cls.key = cls.keys.create("t", rate_per_min=1000)
        cls.low = cls.keys.create("low", rate_per_min=2)
        eng = NexusPipelineEngine(cls.c.coord.url, cls.c.dir)
        cls.gw = Gateway(eng, cls.keys)
        cls.srv = cls.gw.serve()
        cls.base = "http://127.0.0.1:%d" % cls.srv.port

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop(); cls.c.stop()

    def test_rejects_without_or_bad_key(self):
        body = {"model": self.c.model.model_id, "messages": [{"role": "user", "content": "hi"}]}
        self.assertEqual(http("POST", self.base + "/v1/chat/completions", body)[0], 401)
        self.assertEqual(http("POST", self.base + "/v1/chat/completions", body, key="nxs-wrong")[0], 401)
        self.assertEqual(http("GET", self.base + "/v1/models")[0], 401)
        self.assertEqual(http("GET", self.base + "/healthz")[0], 200)

    def test_keys_stored_hashed(self):
        self.assertNotIn(self.key, json.dumps(self.keys.keys))

    def test_chat_openai_shape_and_matches_reference(self):
        st, models = http("GET", self.base + "/v1/models", key=self.key)
        self.assertEqual((st, models["data"][0]["id"]), (200, self.c.model.model_id))
        body = {"model": self.c.model.model_id, "max_tokens": 5,
                "messages": [{"role": "user", "content": "hi"}]}
        st, r = http("POST", self.base + "/v1/chat/completions", body, key=self.key)
        self.assertEqual(st, 200)
        self.assertEqual(r["object"], "chat.completion")
        self.assertEqual(r["usage"]["completion_tokens"], 5)
        ids = tok_encode("user: hi")
        from nexus_runtime.model_demo import tok_decode
        self.assertEqual(r["choices"][0]["message"]["content"],
                         tok_decode(self.c.model.reference_generate(ids, 5)))
        self.assertEqual(http("POST", self.base + "/v1/chat/completions", dict(body, model="nope"), key=self.key)[0], 404)
        self.assertEqual(http("POST", self.base + "/v1/chat/completions", dict(body, stream=True), key=self.key)[0], 400)

    def test_rate_limit(self):
        codes = [http("GET", self.base + "/v1/models", key=self.low)[0] for _ in range(4)]
        self.assertEqual(codes[:2], [200, 200])
        self.assertIn(429, codes)


class TestCli(unittest.TestCase):
    def test_verify_receipt_cli(self):
        import tempfile, io, contextlib
        from nexus_cli.main import main
        s = Ed25519Signer()
        good, bad = mk_receipt(s, "c1"), mk_receipt(s, "c2")
        bad["work_units"] += 1
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.json")
            for docs, code in (([good], 0), ([good, bad], 1)):
                with open(p, "w") as f:
                    json.dump(docs, f)
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["verify-receipt", p]), code)


if __name__ == "__main__":
    unittest.main()
