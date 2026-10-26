"""Create an EVM settlement batch from Router-verified H0 SQLite receipts.

This is an offline, read-only bridge. It trusts the local Router database's
verified flag as the authorization record, then independently rechecks the
worker signature and all H0 receipt invariants that can be checked without
job content. No network calls or transactions are made.
"""
from __future__ import annotations

import argparse
from decimal import InvalidOperation
import hashlib
import hmac
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Mapping

from cryptography.hazmat.primitives import serialization

from batch_builder import SettlementContext, build_batch, keccak256

H0_DIR = Path(__file__).resolve().parents[1] / "nexus" / "h0"
if str(H0_DIR) not in sys.path:
    sys.path.insert(0, str(H0_DIR))
import nexus_common as nc  # noqa: E402


def _integer(value, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _load_config(document: object) -> dict:
    if not isinstance(document, Mapping):
        raise ValueError("config must be a JSON object")
    required = {
        "settlementContext", "batchId", "depositAmount", "token", "nodeWallets",
        "nodePublicKeyFingerprints", "authorWallets",
    }
    missing = required - set(document)
    if missing:
        raise ValueError("config missing fields: " + ", ".join(sorted(missing)))
    context = SettlementContext.from_mapping(document["settlementContext"])
    token = document["token"]
    if not isinstance(token, Mapping):
        raise ValueError("token must be an object")
    for key in ("symbol", "decimals", "usdPerTokenNumerator", "usdPerTokenDenominator"):
        if key not in token:
            raise ValueError(f"token missing field {key}")
    if not isinstance(token["symbol"], str) or not token["symbol"].strip():
        raise ValueError("token.symbol must be a non-empty string")
    decimals = _integer(token["decimals"], "token.decimals")
    if decimals > 36:
        raise ValueError("token.decimals must be <= 36")
    numerator = _integer(token["usdPerTokenNumerator"], "token.usdPerTokenNumerator", minimum=1)
    denominator = _integer(token["usdPerTokenDenominator"], "token.usdPerTokenDenominator", minimum=1)
    for key in ("nodeWallets", "nodePublicKeyFingerprints", "authorWallets"):
        if not isinstance(document[key], Mapping):
            raise ValueError(f"{key} must be an object keyed by exact H0 identity")
    missing_pins = set(document["nodeWallets"]) - set(document["nodePublicKeyFingerprints"])
    if missing_pins:
        raise ValueError("nodePublicKeyFingerprints missing node IDs: " + ", ".join(sorted(missing_pins)))
    # Centralized builder validates batch id, deposit and EVM addresses. Validate
    # mappings up front too, including unused entries, so typos cannot hide.
    from batch_builder import _address
    for identity, wallet in document["nodeWallets"].items():
        if not isinstance(identity, str) or not identity.startswith("node_"):
            raise ValueError("nodeWallets keys must be exact node_id values")
        _address(wallet, f"nodeWallets[{identity}]")
    for identity, fingerprint in document["nodePublicKeyFingerprints"].items():
        if not isinstance(identity, str) or not identity.startswith("node_"):
            raise ValueError("nodePublicKeyFingerprints keys must be exact node_id values")
        if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                or any(char not in "0123456789abcdefABCDEF" for char in fingerprint)):
            raise ValueError(f"nodePublicKeyFingerprints[{identity}] must be a 32-byte SHA-256 hex digest")
    for identity, wallet in document["authorWallets"].items():
        if not isinstance(identity, str) or not identity:
            raise ValueError("authorWallets keys must be non-empty exact NRAM identifiers")
        _address(wallet, f"authorWallets[{identity}]")
    _integer(document["depositAmount"], "depositAmount")
    normalized = dict(document)
    normalized["settlementContext"] = context.as_json()
    return normalized


def _amount_in_base_units(price_micro_usd: int, token: Mapping) -> int:
    """Convert micro-USD to base units using exact USD/token rational pricing."""
    numerator = token["usdPerTokenNumerator"]
    denominator = token["usdPerTokenDenominator"]
    decimals = token["decimals"]
    scaled = price_micro_usd * (10 ** decimals) * denominator
    divisor = 1_000_000 * numerator
    amount, remainder = divmod(scaled, divisor)
    if remainder:
        raise ValueError(
            f"price {price_micro_usd} micro-USD is not exactly representable in "
            f"{token['symbol']} base units under the configured price policy"
        )
    if amount <= 0:
        raise ValueError("converted job amount must be positive")
    return amount


def _settlement_job_id(receipt: Mapping, signature_hex: str) -> str:
    """Namespace a Router-native counter into a stable bytes32 settlement key.

    H0 currently emits IDs such as ``job_000001``. Hashing the canonical signed
    receipt avoids counter collisions across routers and gives an exact replay
    the same settlement key even if copied into another Router ledger.
    """
    try:
        signature = bytes.fromhex(signature_hex)
    except (ValueError, TypeError) as exc:
        raise ValueError("receipt signature is not hexadecimal") from exc
    if len(signature) != 64:
        raise ValueError("receipt signature must be a 64-byte Ed25519 signature")
    preimage = b"NEXUS_H0_RECEIPT_V1\x00" + nc.canonical_json(dict(receipt)) + signature
    return "0x" + keccak256(preimage).hex()


def _public_key_fingerprint(public_pem: object) -> str:
    if not isinstance(public_pem, str) or not public_pem:
        raise ValueError("missing registered node public key")
    try:
        public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
        public_der = public_key.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError("invalid registered node public key") from exc
    return hashlib.sha256(public_der).hexdigest()


def _verify_receipt(receipt: object, signature: object, public_pem: object,
                    expected_job_id: str, expected_node_id: str,
                    discrepancy_pct: object) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError(f"{expected_job_id}: receipt is not an object")
    if not isinstance(signature, str) or not signature:
        raise ValueError(f"{expected_job_id}: missing worker signature")
    if not isinstance(public_pem, str) or not public_pem:
        raise ValueError(f"{expected_job_id}: missing registered node public key")
    try:
        derived_node_id = nc.node_id_from_public_pem(public_pem)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{expected_job_id}: invalid registered public key") from exc
    if derived_node_id != expected_node_id or receipt.get("node_id") != expected_node_id:
        raise ValueError(f"{expected_job_id}: registered node identity mismatch")
    if receipt.get("job_id") != expected_job_id:
        raise ValueError(f"{expected_job_id}: receipt job_id mismatch")
    if not nc.verify_receipt(public_pem, receipt, signature):
        raise ValueError(f"{expected_job_id}: worker receipt signature invalid")
    if isinstance(discrepancy_pct, bool) or not isinstance(discrepancy_pct, (int, float)):
        raise ValueError(f"{expected_job_id}: missing Router metering discrepancy")
    if not math.isfinite(discrepancy_pct) or discrepancy_pct < 0 or discrepancy_pct > 1.0:
        raise ValueError(f"{expected_job_id}: Router metering discrepancy exceeds 1% or is invalid")

    for field in ("input_tokens", "output_tokens", "price_micro_usd"):
        _integer(receipt.get(field), f"{expected_job_id}.{field}")
    scaffolding = _integer(receipt.get("scaffolding_tokens", 0),
                           f"{expected_job_id}.scaffolding_tokens")
    if nc.price_micro_usd(receipt["input_tokens"], receipt["output_tokens"]) != receipt["price_micro_usd"]:
        raise ValueError(f"{expected_job_id}: receipt price does not match H0 token pricing")
    engine_in = _integer(receipt.get("engine_prompt_tokens", receipt["input_tokens"]),
                         f"{expected_job_id}.engine_prompt_tokens")
    engine_out = _integer(receipt.get("engine_completion_tokens", receipt["output_tokens"]),
                          f"{expected_job_id}.engine_completion_tokens")
    adjusted_in = max(0, engine_in - scaffolding)
    base = max(adjusted_in + engine_out, 1)
    computed_discrepancy = abs((receipt["input_tokens"] + receipt["output_tokens"])
                               - (adjusted_in + engine_out)) / base * 100.0
    if computed_discrepancy > 1.0 or abs(computed_discrepancy - discrepancy_pct) > 1e-9:
        raise ValueError(f"{expected_job_id}: receipt and Router discrepancy disagree")
    nram_used = receipt.get("nram_used")
    if not isinstance(nram_used, list) or any(not isinstance(x, str) or not x for x in nram_used):
        raise ValueError(f"{expected_job_id}: nram_used must be a list of non-empty identifiers")
    if len(set(nram_used)) != len(nram_used):
        raise ValueError(f"{expected_job_id}: duplicate NRAM author identifiers are ambiguous")
    expected_shares = nc.split_payment(receipt["price_micro_usd"], bool(nram_used))
    if receipt.get("shares") != expected_shares:
        raise ValueError(f"{expected_job_id}: receipt payment shares are invalid")
    return receipt


def read_verified_jobs(db_path: str | Path, config: Mapping) -> list[dict]:
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Router database does not exist: {path}")
    uri = path.as_uri() + "?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        rows = conn.execute(
            "SELECT r.job_id, r.node_id, r.receipt, r.signature, r.verified, "
            "r.discrepancy_pct, n.pubkey_pem, j.status, j.node_id AS job_node_id, j.nram AS job_nram "
            "FROM receipts r LEFT JOIN nodes n ON n.node_id=r.node_id "
            "LEFT JOIN jobs j ON j.job_id=r.job_id ORDER BY r.job_id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"cannot read H0 Router database: {exc}") from exc
    finally:
        if "conn" in locals():
            conn.close()
    jobs = []
    node_wallets = config["nodeWallets"]
    node_key_fingerprints = config["nodePublicKeyFingerprints"]
    author_wallets = config["authorWallets"]
    for row in rows:
        # Filter by the authoritative Router DB flag, not receipt fields supplied
        # by the worker. Any inconsistency in a verified row is fatal.
        if row["verified"] != 1:
            continue
        job_id = row["job_id"]
        node_id = row["node_id"]
        if row["status"] != "done" or row["job_node_id"] != node_id:
            raise ValueError(f"{job_id}: Router job/receipt state is inconsistent")
        expected_fingerprint = node_key_fingerprints.get(node_id)
        if expected_fingerprint is None:
            raise ValueError(f"{job_id}: no externally pinned public-key fingerprint for node_id {node_id}")
        if not hmac.compare_digest(_public_key_fingerprint(row["pubkey_pem"]), expected_fingerprint.lower()):
            raise ValueError(f"{job_id}: registered node public key does not match the settlement policy pin")
        receipt = _verify_receipt(json.loads(row["receipt"]), row["signature"],
                                  row["pubkey_pem"], job_id, node_id,
                                  row["discrepancy_pct"])
        try:
            requested_nram = json.loads(row["job_nram"] or "[]")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{job_id}: persisted Router job NRAM metadata is invalid") from exc
        if not isinstance(requested_nram, list) or receipt["nram_used"] != requested_nram:
            raise ValueError(f"{job_id}: receipt NRAM authors do not match the persisted Router job")
        if node_id not in node_wallets:
            raise ValueError(f"{job_id}: no explicit wallet mapping for node_id {node_id}")
        nram_used = receipt["nram_used"]
        if len(nram_used) > 1:
            raise ValueError(f"{job_id}: multiple NRAM identifiers; author mapping is ambiguous")
        if nram_used:
            author_id = nram_used[0]
            if author_id not in author_wallets:
                raise ValueError(f"{job_id}: no explicit wallet mapping for author {author_id}")
            author = author_wallets[author_id]
        else:
            author = "0x" + "00" * 20
        jobs.append({
            "jobId": _settlement_job_id(receipt, row["signature"]),
            "routerJobId": job_id,
            "nodeId": node_id,
            "node": node_wallets[node_id],
            "author": author,
            "amount": _amount_in_base_units(receipt["price_micro_usd"], config["token"]),
        })
    if not jobs:
        raise ValueError("Router database contains no explicitly verified H0 receipts")
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="path to the local H0 Router SQLite database")
    parser.add_argument("--config", required=True, help="explicit mapping and price policy JSON")
    args = parser.parse_args(argv)
    try:
        with open(args.config, encoding="utf-8") as source:
            config = _load_config(json.load(source))
        jobs = read_verified_jobs(args.db, config)
        source_receipts = {
            job["jobId"]: {"routerJobId": job["routerJobId"], "nodeId": job["nodeId"]}
            for job in jobs
        }
        batch = build_batch(config["settlementContext"], config["batchId"], jobs,
                            config["depositAmount"])
    except (OSError, json.JSONDecodeError, TypeError, ValueError, InvalidOperation) as exc:
        parser.error(str(exc))
    output = batch.as_contract_batch()
    # The Merkle leaf binds addresses and chain ID, while decimals are contract
    # configuration. Carry the policy value so the on-chain publisher can
    # reject a batch generated under a different unit scale.
    output["tokenDecimals"] = config["token"]["decimals"]
    output["depositAmount"] = config["depositAmount"]
    output["settlementPolicyHash"] = "0x" + hashlib.sha256(nc.canonical_json(config)).hexdigest()
    output["tokenPolicy"] = {
        "symbol": config["token"]["symbol"],
        "usdPerTokenNumerator": config["token"]["usdPerTokenNumerator"],
        "usdPerTokenDenominator": config["token"]["usdPerTokenDenominator"],
    }
    output["sourceReceipts"] = source_receipts
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
