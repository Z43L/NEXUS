import json
import hashlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "nexus" / "h0"))

import nexus_common as nc
from batch_builder import ZERO_ADDRESS, SettlementContext, settlement_batch_commitment, verify_claim
from receipt_to_batch import _amount_in_base_units, _load_config, _settlement_job_id, read_verified_jobs


NODE_ADDRESS = "0x" + "11" * 20
AUTHOR_ADDRESS = "0x" + "22" * 20
BATCH_ID = "0x" + "ab" * 32
SETTLEMENT_CONTEXT = {
    "chainId": 31337,
    "escrowAddress": "0x" + "33" * 20,
    "tokenAddress": "0x" + "44" * 20,
}


def fingerprint(public_pem):
    public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    public_der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(public_der).hexdigest()


def config(**overrides):
    value = {
        "settlementContext": SETTLEMENT_CONTEXT,
        "batchId": BATCH_ID,
        "depositAmount": 1000,
        "token": {
            "symbol": "USDC",
            "decimals": 6,
            "usdPerTokenNumerator": 1,
            "usdPerTokenDenominator": 1,
        },
        "nodeWallets": {},
        "nodePublicKeyFingerprints": {},
        "authorWallets": {},
    }
    value.update(overrides)
    return _load_config(value)


class ReceiptBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "router.sqlite"
        self.node_dir = Path(self.temp.name) / "node"
        self.private_key, self.public_pem, self.node_id = nc.load_or_create_node_key(self.node_dir)
        self._create_db()
        self.receipt = self._receipt("job_000001", [])
        self._insert(self.receipt)
        self.cfg = config(nodeWallets={self.node_id: NODE_ADDRESS},
                          nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)})

    def _create_db(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE nodes(node_id TEXT PRIMARY KEY, pubkey_pem TEXT);
                CREATE TABLE jobs(job_id TEXT PRIMARY KEY, status TEXT, node_id TEXT, nram TEXT);
                CREATE TABLE receipts(job_id TEXT PRIMARY KEY, node_id TEXT, receipt TEXT,
                    signature TEXT, verified INTEGER, discrepancy_pct REAL);
                CREATE TABLE nram_assets(nram_id TEXT PRIMARY KEY, author_id TEXT NOT NULL);
            """)
            conn.execute("INSERT INTO nodes VALUES(?, ?)", (self.node_id, self.public_pem))

    def _register_nram(self, nram_id, author_id):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO nram_assets VALUES(?, ?)", (nram_id, author_id))

    def _receipt(self, job_id, nram_used, input_tokens=100, output_tokens=20):
        price = nc.price_micro_usd(input_tokens, output_tokens)
        receipt = {
            "job_id": job_id,
            "node_id": self.node_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "engine_prompt_tokens": input_tokens,
            "engine_completion_tokens": output_tokens,
            "scaffolding_tokens": 0,
            "price_micro_usd": price,
            "nram_used": nram_used,
            "shares": nc.split_payment(price, bool(nram_used)),
        }
        return receipt

    def _insert(self, receipt, *, verified=1, discrepancy=0.0, node_id=None,
                status="done", signature=None, public_pem=None):
        signature = signature or nc.sign_receipt(self.private_key, receipt)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            if public_pem is not None:
                conn.execute("UPDATE nodes SET pubkey_pem=? WHERE node_id=?",
                             (public_pem, node_id or self.node_id))
            conn.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?,?)",
                         (receipt["job_id"], status, node_id or self.node_id,
                          json.dumps(receipt.get("nram_used", []))))
            conn.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?)",
                         (receipt["job_id"], node_id or self.node_id,
                          json.dumps(receipt), signature, verified, discrepancy))

    def test_converts_only_verified_router_receipts_and_builds_claims(self):
        unverified = self._receipt("0x" + "02" * 32, [])
        self._insert(unverified, verified=0)
        jobs = read_verified_jobs(self.db_path, self.cfg)
        self.assertEqual(len(jobs), 1)
        expected_job_id = _settlement_job_id(self.receipt, nc.sign_receipt(self.private_key, self.receipt))
        self.assertEqual(jobs[0]["jobId"], expected_job_id)
        self.assertEqual(jobs[0]["routerJobId"], "job_000001")
        self.assertEqual(jobs[0]["amount"], 7)  # 7 micro-USD == 7 USDC base units.
        batch = __import__("batch_builder").build_batch(SETTLEMENT_CONTEXT, BATCH_ID, jobs, 1000)
        self.assertTrue(verify_claim(SETTLEMENT_CONTEXT, BATCH_ID, batch.claims[0], batch.root, batch.root_sum))
        self.assertEqual(batch.as_contract_batch()["settlementContext"], SETTLEMENT_CONTEXT)

    def test_cli_builds_batch_from_local_router_database(self):
        config_path = Path(self.temp.name) / "policy.json"
        config_path.write_text(json.dumps(self.cfg), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(ROOT / "receipt_to_batch.py"),
             "--db", str(self.db_path), "--config", str(config_path)],
            check=True, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        batch = json.loads(completed.stdout)
        self.assertEqual(batch["rootSum"], 7)
        self.assertEqual(batch["depositAmount"], self.cfg["depositAmount"])
        self.assertEqual(batch["tokenDecimals"], self.cfg["token"]["decimals"])
        self.assertEqual(batch["settlementPolicyHash"],
                         "0x" + hashlib.sha256(nc.canonical_json(self.cfg)).hexdigest())
        self.assertEqual(batch["tokenPolicy"]["usdPerTokenDenominator"],
                         self.cfg["token"]["usdPerTokenDenominator"])
        self.assertEqual(batch["settlementContext"], SETTLEMENT_CONTEXT)
        self.assertEqual(
            batch["settlementBatchCommitment"],
            "0x" + settlement_batch_commitment(
                SettlementContext.from_mapping(batch["settlementContext"]),
                batch["batchId"], batch["root"], batch["rootSum"],
            ).hex(),
        )
        claim_id = batch["claims"][0]["jobId"]
        self.assertEqual(batch["sourceReceipts"][claim_id]["routerJobId"], "job_000001")
        self.assertEqual(claim_id, _settlement_job_id(self.receipt, nc.sign_receipt(self.private_key, self.receipt)))

    def test_router_native_ids_are_namespaced_by_signed_receipt(self):
        same_local_id = self._receipt("job_000001", [])
        other_private, _, other_node_id = nc.load_or_create_node_key(Path(self.temp.name) / "other-node")
        same_local_id["node_id"] = other_node_id
        other_signature = nc.sign_receipt(other_private, same_local_id)
        first_signature = nc.sign_receipt(self.private_key, self.receipt)
        first_evm_id = _settlement_job_id(self.receipt, first_signature)
        other_evm_id = _settlement_job_id(same_local_id, other_signature)
        self.assertRegex(first_evm_id, r"^0x[0-9a-f]{64}$")
        self.assertNotEqual(first_evm_id, other_evm_id)
        self.assertEqual(first_evm_id, _settlement_job_id(self.receipt, first_signature))

    def test_maps_registered_nram_publisher_to_wallet_and_no_author_to_zero(self):
        nram_id = "ab" * 32
        self._register_nram(nram_id, "alice")
        receipt = self._receipt("0x" + "03" * 32, [nram_id])
        self._insert(receipt)
        cfg = config(nodeWallets={self.node_id: NODE_ADDRESS},
                     nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)},
                     authorWallets={"alice": AUTHOR_ADDRESS})
        mapped = read_verified_jobs(self.db_path, cfg)
        evm_id = _settlement_job_id(receipt, nc.sign_receipt(self.private_key, receipt))
        job = next(x for x in mapped if x["jobId"] == evm_id)
        self.assertEqual(job["author"], AUTHOR_ADDRESS)
        self.assertEqual(job["authorId"], "alice")
        receipt_evm_id = _settlement_job_id(self.receipt, nc.sign_receipt(self.private_key, self.receipt))
        no_author = next(x for x in mapped if x["jobId"] == receipt_evm_id)
        self.assertEqual(no_author["author"], ZERO_ADDRESS)
        self.assertIsNone(no_author["authorId"])

    def test_job_served_with_nram_pays_ten_percent_to_author_wallet(self):
        nram_id = "cd" * 32
        self._register_nram(nram_id, "alice")
        receipt = self._receipt("0x" + "06" * 32, [nram_id], input_tokens=1_000_000, output_tokens=0)
        self._insert(receipt)
        cfg = config(depositAmount=60_000,
                     nodeWallets={self.node_id: NODE_ADDRESS},
                     nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)},
                     authorWallets={"alice": AUTHOR_ADDRESS})
        config_path = Path(self.temp.name) / "royalty-policy.json"
        config_path.write_text(json.dumps(cfg), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(ROOT / "receipt_to_batch.py"),
             "--db", str(self.db_path), "--config", str(config_path)],
            check=True, capture_output=True, text=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        batch = json.loads(completed.stdout)
        evm_id = _settlement_job_id(receipt, nc.sign_receipt(self.private_key, receipt))
        claim = next(c for c in batch["claims"] if c["jobId"] == evm_id)
        self.assertEqual(claim["author"], AUTHOR_ADDRESS)
        self.assertEqual(claim["amount"], 50_000)
        # Same floor rule as InferenceEscrow._bps(amount, AUTHOR_BPS): 10% of the job.
        royalty = batch["authorRoyalties"]["alice"]
        self.assertEqual(royalty, {"wallet": AUTHOR_ADDRESS, "baseUnits": 5_000, "microUsd": 5_000})
        self.assertEqual(royalty["microUsd"], receipt["shares"]["nram_author"])
        self.assertEqual(royalty["baseUnits"], claim["amount"] * 1_000 // 10_000)
        verified = verify_claim(SETTLEMENT_CONTEXT, BATCH_ID,
                                __import__("batch_builder").JobProof(
                                    job_id=claim["jobId"], node=claim["node"], author=claim["author"],
                                    amount=claim["amount"], proof=tuple(claim["proof"]),
                                    proof_sums=tuple(claim["proofSums"])),
                                batch["root"], batch["rootSum"])
        self.assertTrue(verified)

    def test_fails_closed_for_unregistered_nram_or_unmapped_publisher(self):
        receipt = self._receipt("0x" + "04" * 32, ["ef" * 32])
        self._insert(receipt)
        with self.assertRaisesRegex(ValueError, "not in the Router registry"):
            read_verified_jobs(self.db_path, self.cfg)
        self._register_nram("ef" * 32, "bob")
        cfg = config(nodeWallets={self.node_id: NODE_ADDRESS},
                     nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)},
                     authorWallets={"alice": AUTHOR_ADDRESS})
        with self.assertRaisesRegex(ValueError, "no explicit wallet mapping for author bob"):
            read_verified_jobs(self.db_path, cfg)

    def test_wallet_policy_is_keyed_by_publisher_not_bundle_id(self):
        nram_id = "12" * 32
        self._register_nram(nram_id, "alice")
        self._insert(self._receipt("0x" + "07" * 32, [nram_id]))
        cfg = config(nodeWallets={self.node_id: NODE_ADDRESS},
                     nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)},
                     authorWallets={nram_id: AUTHOR_ADDRESS})
        with self.assertRaisesRegex(ValueError, "no explicit wallet mapping for author alice"):
            read_verified_jobs(self.db_path, cfg)

    def test_unverified_receipts_never_pay_royalties(self):
        receipt = self._receipt("0x" + "08" * 32, ["34" * 32])
        self._insert(receipt, verified=0)
        jobs = read_verified_jobs(self.db_path, self.cfg)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["routerJobId"], "job_000001")

    def test_rejects_ambiguous_multiple_authors(self):
        receipt = self._receipt("0x" + "05" * 32, ["author-a", "author-b"])
        self._insert(receipt)
        cfg = config(nodeWallets={self.node_id: NODE_ADDRESS},
                     nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)},
                     authorWallets={"author-a": AUTHOR_ADDRESS, "author-b": AUTHOR_ADDRESS})
        with self.assertRaisesRegex(ValueError, "author mapping is ambiguous"):
            read_verified_jobs(self.db_path, cfg)

    def test_rejects_signature_tampering(self):
        bad = dict(self.receipt, output_tokens=21)
        self._insert(bad, signature=nc.sign_receipt(self.private_key, self.receipt))
        with self.assertRaisesRegex(ValueError, "signature invalid"):
            read_verified_jobs(self.db_path, self.cfg)

    def test_rejects_receipt_author_not_requested_by_router_job(self):
        author_id = "author_not_requested"
        receipt = self._receipt("job_000099", [author_id])
        self._insert(receipt)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE jobs SET nram='[]' WHERE job_id=?", (receipt["job_id"],))
        self.cfg["authorWallets"] = {author_id: AUTHOR_ADDRESS}
        with self.assertRaisesRegex(ValueError, "do not match the persisted Router job"):
            read_verified_jobs(self.db_path, self.cfg)

    def test_rejects_node_database_key_replacement_against_policy_pin(self):
        other_key, other_pem, other_id = nc.load_or_create_node_key(Path(self.temp.name) / "other")
        del other_key
        with self.assertRaisesRegex(ValueError, "does not match the settlement policy pin"):
            self._insert(self.receipt, public_pem=other_pem)
            read_verified_jobs(self.db_path, self.cfg)

    def test_rejects_registered_key_bound_to_wrong_node_id(self):
        fake_node_id = "node_" + "00" * 8
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE jobs SET node_id=? WHERE job_id=?",
                         (fake_node_id, self.receipt["job_id"]))
            conn.execute("UPDATE receipts SET node_id=? WHERE job_id=?",
                         (fake_node_id, self.receipt["job_id"]))
            conn.execute("INSERT INTO nodes VALUES(?, ?)", (fake_node_id, self.public_pem))
        cfg = config(nodeWallets={fake_node_id: NODE_ADDRESS},
                     nodePublicKeyFingerprints={fake_node_id: fingerprint(self.public_pem)})
        with self.assertRaisesRegex(ValueError, "registered node identity mismatch"):
            read_verified_jobs(self.db_path, cfg)

    def test_rejects_public_key_not_pinned_by_settlement_policy(self):
        altered = config(nodeWallets={self.node_id: NODE_ADDRESS},
                         nodePublicKeyFingerprints={self.node_id: "00" * 32})
        with self.assertRaisesRegex(ValueError, "does not match the settlement policy pin"):
            read_verified_jobs(self.db_path, altered)

    def test_rejects_unverified_state_inconsistent_or_bad_discrepancy(self):
        with self.assertRaisesRegex(ValueError, "job/receipt state is inconsistent"):
            self._insert(self.receipt, status="failed")
            read_verified_jobs(self.db_path, self.cfg)
        with self.assertRaisesRegex(ValueError, "discrepancy"):
            self._insert(self.receipt, discrepancy=1.1)
            read_verified_jobs(self.db_path, self.cfg)

    def test_rejects_invalid_token_policy_or_inexact_amount(self):
        with self.assertRaisesRegex(ValueError, "not exactly representable"):
            _cfg = config(token={"symbol": "TKN", "decimals": 0,
                                 "usdPerTokenNumerator": 3,
                                 "usdPerTokenDenominator": 1},
                          nodeWallets={self.node_id: NODE_ADDRESS},
                          nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)})
            read_verified_jobs(self.db_path, _cfg)
        with self.assertRaisesRegex(ValueError, "decimals"):
            config(token={"symbol": "TKN", "decimals": 37,
                          "usdPerTokenNumerator": 1,
                          "usdPerTokenDenominator": 1})

    def test_sub_micro_usd_evm_precision_is_distinct_from_h0_share_precision(self):
        token_policy = {
            "symbol": "TKN", "decimals": 6,
            "usdPerTokenNumerator": 1, "usdPerTokenDenominator": 10_000,
        }
        self.assertEqual(_amount_in_base_units(1, token_policy), 10_000)
        # The receipt's H0 accounting shares are whole micro-USD; the escrow
        # distributes those converted 10,000 token units at finer precision.
        self.assertEqual(nc.split_payment(1, True), {
            "node": 0, "nram_author": 0, "verification": 0,
            "burn": 0, "treasury": 1,
        })

    def test_settlement_context_is_required_and_strictly_validated(self):
        for invalid in (
            None,
            {"chainId": 0, "escrowAddress": NODE_ADDRESS, "tokenAddress": AUTHOR_ADDRESS},
            {"chainId": True, "escrowAddress": NODE_ADDRESS, "tokenAddress": AUTHOR_ADDRESS},
            {"chainId": 31337, "escrowAddress": ZERO_ADDRESS, "tokenAddress": AUTHOR_ADDRESS},
            {"chainId": 31337, "escrowAddress": NODE_ADDRESS, "tokenAddress": "bad"},
            {"chainId": 31337, "escrowAddress": NODE_ADDRESS,
             "tokenAddress": AUTHOR_ADDRESS, "extra": 1},
        ):
            with self.subTest(context=invalid), self.assertRaises(ValueError):
                config(settlementContext=invalid)
        without_context = config()
        del without_context["settlementContext"]
        with self.assertRaisesRegex(ValueError, "missing fields: settlementContext"):
            _load_config(without_context)

    def test_root_is_bound_to_chain_escrow_and_token(self):
        from batch_builder import build_batch
        jobs = [{"jobId": "0x" + "55" * 32, "node": NODE_ADDRESS,
                 "author": ZERO_ADDRESS, "amount": 7}]
        original = build_batch(SETTLEMENT_CONTEXT, BATCH_ID, jobs, 7)
        for key, value in (("chainId", 31338), ("escrowAddress", "0x" + "66" * 20),
                           ("tokenAddress", "0x" + "77" * 20)):
            changed = dict(SETTLEMENT_CONTEXT, **{key: value})
            other = build_batch(changed, BATCH_ID, jobs, 7)
            self.assertNotEqual(original.root, other.root)
            self.assertFalse(verify_claim(changed, BATCH_ID, original.claims[0],
                                          original.root, original.root_sum))

    def test_rejects_recomputed_price_and_share_mismatches(self):
        bad_price = dict(self.receipt, price_micro_usd=8)
        self._insert(bad_price)
        with self.assertRaisesRegex(ValueError, "price does not match"):
            read_verified_jobs(self.db_path, self.cfg)
        bad_shares = dict(self.receipt, shares={"node": 7})
        self._insert(bad_shares)
        with self.assertRaisesRegex(ValueError, "payment shares are invalid"):
            read_verified_jobs(self.db_path, self.cfg)

    def test_rejects_empty_verified_set_and_deposit_shortfall(self):
        self._insert(self.receipt, verified=0)
        with self.assertRaisesRegex(ValueError, "no explicitly verified"):
            read_verified_jobs(self.db_path, self.cfg)
        too_small = config(depositAmount=6, nodeWallets={self.node_id: NODE_ADDRESS},
                           nodePublicKeyFingerprints={self.node_id: fingerprint(self.public_pem)})
        self._insert(self.receipt, verified=1)
        with self.assertRaisesRegex(ValueError, "exceeds deposit"):
            __import__("batch_builder").build_batch(
                too_small["settlementContext"], BATCH_ID,
                read_verified_jobs(self.db_path, too_small), too_small["depositAmount"])


if __name__ == "__main__":
    unittest.main()
