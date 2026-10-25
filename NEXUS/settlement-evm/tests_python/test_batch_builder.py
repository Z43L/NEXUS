import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from batch_builder import (
    JobInput,
    ZERO_ADDRESS,
    build_batch,
    encode_job_leaf,
    keccak256,
    verify_claim,
)

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "vectors" / "merkle_sum_vectors.json").read_text())
CONTEXT = VECTORS["batch"]["settlementContext"]


class KeccakTests(unittest.TestCase):
    def test_known_ethereum_keccak_vectors(self):
        for vector in VECTORS["keccak256"]:
            with self.subTest(input=vector["inputHex"]):
                actual = "0x" + keccak256(bytes.fromhex(vector["inputHex"])).hex()
                self.assertEqual(actual, vector["digest"])

    def test_static_abi_leaf_encoding_and_hash(self):
        batch = VECTORS["batch"]
        job = batch["jobs"][0]
        encoded = encode_job_leaf(CONTEXT, batch["batchId"], job["jobId"], job["node"], job["author"], job["amount"])
        self.assertEqual(len(encoded), 288)
        self.assertEqual(encoded[:32].hex(), batch["leafDomain"][2:])
        self.assertEqual(encoded[32:64].hex(), CONTEXT["chainId"].to_bytes(32, "big").hex())
        self.assertEqual(encoded[64:96].hex(), "00" * 12 + CONTEXT["escrowAddress"][2:])
        self.assertEqual(encoded[96:128].hex(), "00" * 12 + CONTEXT["tokenAddress"][2:])
        self.assertEqual(encoded[128:160].hex(), batch["batchId"][2:])
        self.assertEqual(encoded[160:192].hex(), job["jobId"][2:])
        self.assertEqual(encoded[192:224].hex(), "00" * 12 + job["node"][2:])
        self.assertEqual(encoded[224:256].hex(), "00" * 12 + job["author"][2:])
        self.assertEqual(encoded[256:].hex(), job["amount"].to_bytes(32, "big").hex())
        self.assertEqual("0x" + keccak256(encoded).hex(), job["leafHash"])


class BatchBuilderTests(unittest.TestCase):
    def test_cli_reads_json_and_emits_contract_batch(self):
        vector = VECTORS["batch"]
        completed = subprocess.run(
            [sys.executable, str(ROOT / "batch_builder.py"), "-"],
            input=json.dumps({
                "batchId": vector["batchId"],
                "settlementContext": CONTEXT,
                "depositAmount": vector["depositAmount"],
                "jobs": vector["jobs"],
            }),
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        output = json.loads(completed.stdout)
        self.assertEqual(output["root"], vector["root"])
        self.assertEqual(output["rootSum"], vector["rootSum"])
        self.assertEqual(output["claims"][1]["proofSums"], vector["jobs"][1]["proofSums"])

    def test_two_leaf_merkle_sum_vector_matches_solidity_layout(self):
        vector = VECTORS["batch"]
        batch = build_batch(CONTEXT, vector["batchId"], vector["jobs"], vector["depositAmount"])
        self.assertEqual(batch.root, vector["root"])
        self.assertEqual(batch.root_sum, vector["rootSum"])
        self.assertEqual(len(batch.claims), len(vector["jobs"]))
        for claim, expected in zip(batch.claims, vector["jobs"]):
            with self.subTest(job=claim.job_id):
                self.assertEqual(claim.proof, tuple(expected["proof"]))
                self.assertEqual(claim.proof_sums, tuple(expected["proofSums"]))
                self.assertTrue(verify_claim(CONTEXT, batch.batch_id, claim, batch.root, batch.root_sum))
        self.assertEqual(batch.as_contract_batch()["claims"][0]["jobId"], vector["jobs"][0]["jobId"])

    def test_odd_tree_promotes_last_node_without_double_counting(self):
        batch_id = "0x" + "11" * 32
        jobs = [
            JobInput("0x" + f"{i:02x}" * 32, "0x" + f"{i + 10:02x}" * 20, ZERO_ADDRESS, i)
            for i in (1, 2, 3)
        ]
        batch = build_batch(CONTEXT, batch_id, jobs, 10)
        self.assertEqual(batch.root_sum, 6)
        self.assertEqual([len(item.proof) for item in batch.claims], [2, 2, 1])
        self.assertEqual([len(item.proof_sums) for item in batch.claims], [2, 2, 1])
        self.assertTrue(all(verify_claim(CONTEXT, batch.batch_id, item, batch.root, batch.root_sum) for item in batch.claims))

    def test_proof_mutation_fails(self):
        vector = VECTORS["batch"]
        batch = build_batch(CONTEXT, vector["batchId"], vector["jobs"], vector["depositAmount"])
        claim = batch.claims[0]
        altered = type(claim)(claim.job_id, claim.node, claim.author, claim.amount,
                              ("0x" + "ff" * 32,), claim.proof_sums)
        self.assertFalse(verify_claim(CONTEXT, batch.batch_id, altered, batch.root, batch.root_sum))

    def test_rejects_duplicate_job_ids_case_insensitively(self):
        job = VECTORS["batch"]["jobs"][0]
        duplicate = dict(job, jobId=job["jobId"].upper().replace("0X", "0x"))
        with self.assertRaisesRegex(ValueError, "duplicate jobId"):
            build_batch(CONTEXT, VECTORS["batch"]["batchId"], [job, duplicate], 1000)

    def test_rejects_job_sum_above_deposit(self):
        jobs = VECTORS["batch"]["jobs"]
        with self.assertRaisesRegex(ValueError, "exceeds deposit"):
            build_batch(CONTEXT, VECTORS["batch"]["batchId"], jobs, 299)

    def test_rejects_invalid_amounts_ids_and_addresses(self):
        job = VECTORS["batch"]["jobs"][0]
        for value in (0, -1, True, "100", 1 << 256):
            with self.subTest(amount=value), self.assertRaises(ValueError):
                build_batch(CONTEXT, VECTORS["batch"]["batchId"], [dict(job, amount=value)], 1000)
        with self.assertRaisesRegex(ValueError, "batchId"):
            build_batch(CONTEXT, "0x1234", [job], 1000)
        with self.assertRaisesRegex(ValueError, "node"):
            build_batch(CONTEXT, VECTORS["batch"]["batchId"], [dict(job, node=ZERO_ADDRESS)], 1000)
        with self.assertRaisesRegex(ValueError, "exactly 20 bytes"):
            build_batch(CONTEXT, VECTORS["batch"]["batchId"], [dict(job, node="0x" + "00" * 19 + "  ")], 1000)

    def test_mapping_author_defaults_to_zero_address(self):
        job = VECTORS["batch"]["jobs"][0]
        job_without_author = {key: value for key, value in job.items() if key not in {
            "author", "leafHash", "proof", "proofSums"
        }}
        batch = build_batch(CONTEXT, VECTORS["batch"]["batchId"], [job_without_author], 100)
        self.assertEqual(batch.claims[0].author, ZERO_ADDRESS)
        self.assertTrue(verify_claim(CONTEXT, batch.batch_id, batch.claims[0], batch.root, batch.root_sum))


if __name__ == "__main__":
    unittest.main()
