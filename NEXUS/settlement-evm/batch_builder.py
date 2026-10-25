"""Build EVM-compatible Merkle-sum batches for InferenceEscrow.

Pure Python standard library. The ABI leaf and Merkle-sum parent formats must
stay byte-for-byte aligned with src/InferenceEscrow.sol.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import sys
from typing import Mapping, Sequence

_MASK64 = (1 << 64) - 1
_RATE = 136  # Keccak-256 bitrate (1088 bits)
_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_ROTATION = (
    0, 1, 62, 28, 27,
    36, 44, 6, 55, 20,
    3, 10, 43, 25, 39,
    41, 45, 15, 21, 8,
    18, 2, 61, 56, 14,
)
_MAX_UINT256 = (1 << 256) - 1
ZERO_ADDRESS = "0x" + "00" * 20


def _rotl64(value: int, shift: int) -> int:
    if shift == 0:
        return value & _MASK64
    return ((value << shift) | (value >> (64 - shift))) & _MASK64


def _keccak_f1600(state: list[int]) -> None:
    for rc in _ROUND_CONSTANTS:
        columns = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
                   for x in range(5)]
        delta = [columns[(x - 1) % 5] ^ _rotl64(columns[(x + 1) % 5], 1)
                 for x in range(5)]
        for y in range(5):
            for x in range(5):
                state[x + 5 * y] ^= delta[x]

        moved = [0] * 25
        for y in range(5):
            for x in range(5):
                moved[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(
                    state[x + 5 * y], _ROTATION[x + 5 * y]
                )

        for y in range(5):
            row = moved[5 * y:5 * y + 5]
            for x in range(5):
                state[x + 5 * y] = row[x] ^ ((~row[(x + 1) % 5]) & row[(x + 2) % 5])
                state[x + 5 * y] &= _MASK64
        state[0] ^= rc


def keccak256(data: bytes) -> bytes:
    """Ethereum Keccak-256 (legacy Keccak padding, not FIPS SHA3-256)."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    padding_length = _RATE - (len(data) % _RATE)
    padded = bytearray(data)
    padded.append(0x01)
    padded.extend(b"\x00" * (padding_length - 1))
    padded[-1] ^= 0x80

    state = [0] * 25
    for offset in range(0, len(padded), _RATE):
        block = padded[offset:offset + _RATE]
        for lane in range(_RATE // 8):
            start = lane * 8
            state[lane] ^= int.from_bytes(block[start:start + 8], "little")
        _keccak_f1600(state)
    return b"".join(lane.to_bytes(8, "little") for lane in state)[:32]


LEAF_DOMAIN = keccak256(b"NEXUS_INFERENCE_ESCROW_LEAF_V2")


def _bytes32(value: str, field: str, *, allow_zero: bool = False) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a 32-byte hex string")
    raw = value[2:] if value.startswith(("0x", "0X")) else value
    if len(raw) != 64:
        raise ValueError(f"{field} must contain exactly 32 bytes")
    try:
        result = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    if len(result) != 32:
        raise ValueError(f"{field} must contain exactly 32 bytes")
    if not allow_zero and not any(result):
        raise ValueError(f"{field} cannot be zero")
    return result


def _address(value: str, field: str, *, allow_zero: bool = False) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a 20-byte hex address")
    raw = value[2:] if value.startswith(("0x", "0X")) else value
    if len(raw) != 40:
        raise ValueError(f"{field} must contain exactly 20 bytes")
    try:
        result = bytes.fromhex(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    if len(result) != 20:
        raise ValueError(f"{field} must contain exactly 20 bytes")
    if not allow_zero and not any(result):
        raise ValueError(f"{field} cannot be zero")
    return result


def _uint256(value: object, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer in ERC-20 base units")
    if value < (0 if allow_zero else 1) or value > _MAX_UINT256:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field} must be a {qualifier} uint256")
    return value


def _word_uint(value: int) -> bytes:
    return value.to_bytes(32, "big")


@dataclass(frozen=True)
class JobInput:
    job_id: str
    node: str
    author: str
    amount: int


@dataclass(frozen=True)
class SettlementContext:
    chain_id: int
    escrow_address: str
    token_address: str

    @classmethod
    def from_mapping(cls, value: object) -> "SettlementContext":
        if not isinstance(value, Mapping):
            raise ValueError("settlementContext must be an object")
        required = {"chainId", "escrowAddress", "tokenAddress"}
        missing = required - set(value)
        if missing:
            raise ValueError("settlementContext missing fields: " + ", ".join(sorted(missing)))
        _uint256(value["chainId"], "settlementContext.chainId")
        _address(value["escrowAddress"], "settlementContext.escrowAddress")
        _address(value["tokenAddress"], "settlementContext.tokenAddress")
        if set(value) != required:
            raise ValueError("settlementContext must contain exactly chainId, escrowAddress, tokenAddress")
        return cls(value["chainId"], value["escrowAddress"], value["tokenAddress"])

    def as_json(self) -> dict[str, object]:
        return {"chainId": self.chain_id, "escrowAddress": self.escrow_address,
                "tokenAddress": self.token_address}


@dataclass(frozen=True)
class JobProof:
    job_id: str
    node: str
    author: str
    amount: int
    proof: tuple[str, ...]
    proof_sums: tuple[int, ...]

    def as_contract_claim(self) -> dict[str, object]:
        """Return the field names expected by InferenceEscrow.JobClaim."""
        return {
            "jobId": self.job_id,
            "node": self.node,
            "author": self.author,
            "amount": self.amount,
            "proof": list(self.proof),
            "proofSums": list(self.proof_sums),
        }


@dataclass(frozen=True)
class BatchProof:
    settlement_context: SettlementContext
    batch_id: str
    root: str
    root_sum: int
    claims: tuple[JobProof, ...]

    def as_contract_batch(self) -> dict[str, object]:
        return {
            "settlementContext": self.settlement_context.as_json(),
            "batchId": self.batch_id,
            "root": self.root,
            "rootSum": self.root_sum,
            "claims": [claim.as_contract_claim() for claim in self.claims],
        }


@dataclass(frozen=True)
class _Node:
    digest: bytes
    amount_sum: int
    indexes: tuple[int, ...]


def _leaf_hash(context: SettlementContext, batch_id: bytes, job_id: bytes,
               node: bytes, author: bytes, amount: int) -> bytes:
    # All fields are static ABI values and occupy one 32-byte word each.
    encoded = (LEAF_DOMAIN + _word_uint(context.chain_id)
               + _address(context.escrow_address, "settlementContext.escrowAddress").rjust(32, b"\x00")
               + _address(context.token_address, "settlementContext.tokenAddress").rjust(32, b"\x00")
               + batch_id + job_id + node.rjust(32, b"\x00")
               + author.rjust(32, b"\x00") + _word_uint(amount))
    if len(encoded) != 288:
        raise AssertionError("static ABI encoding must be nine 32-byte words")
    return keccak256(encoded)


def encode_job_leaf(settlement_context: SettlementContext | Mapping[str, object],
                    batch_id: str, job_id: str, node: str, author: str, amount: int) -> bytes:
    """Encode the V2 context-bound leaf as nine static ABI words (288 bytes)."""
    context = (settlement_context if isinstance(settlement_context, SettlementContext)
               else SettlementContext.from_mapping(settlement_context))
    batch_bytes = _bytes32(batch_id, "batchId")
    job_bytes = _bytes32(job_id, "jobId")
    node_bytes = _address(node, "node")
    author_bytes = _address(author, "author", allow_zero=True)
    value = _uint256(amount, "amount")
    return (LEAF_DOMAIN + _word_uint(context.chain_id)
            + _address(context.escrow_address, "settlementContext.escrowAddress").rjust(32, b"\x00")
            + _address(context.token_address, "settlementContext.tokenAddress").rjust(32, b"\x00")
            + batch_bytes + job_bytes + node_bytes.rjust(32, b"\x00")
            + author_bytes.rjust(32, b"\x00") + _word_uint(value))


def _leaf_node(leaf_hash: bytes, amount: int) -> bytes:
    return keccak256(leaf_hash + _word_uint(amount))


def _parent(left_hash: bytes, left_sum: int, right_hash: bytes, right_sum: int) -> bytes:
    if left_hash < right_hash:
        first_hash, first_sum, second_hash, second_sum = left_hash, left_sum, right_hash, right_sum
    else:  # Matches Solidity's `<` branch (equal hashes put the sibling first).
        first_hash, first_sum, second_hash, second_sum = right_hash, right_sum, left_hash, left_sum
    return keccak256(first_hash + _word_uint(first_sum) + second_hash + _word_uint(second_sum))


def build_batch(settlement_context: SettlementContext | Mapping[str, object], batch_id: str,
                jobs: Sequence[JobInput | Mapping[str, object]], deposit_amount: int) -> BatchProof:
    """Build a canonical sorted-pair Merkle-sum batch for the escrow contract.

    `amount` and `deposit_amount` are raw ERC-20 units (wei-like base units),
    never decimal token amounts. Receipts must first be deliberately mapped to
    wallet addresses and converted to that token's base units by the caller.
    """
    context = (settlement_context if isinstance(settlement_context, SettlementContext)
               else SettlementContext.from_mapping(settlement_context))
    batch_bytes = _bytes32(batch_id, "batchId")
    deposit = _uint256(deposit_amount, "deposit_amount")
    if not jobs:
        raise ValueError("jobs cannot be empty")

    normalized: list[JobInput] = []
    seen_job_ids: set[bytes] = set()
    total = 0
    for index, item in enumerate(jobs):
        if isinstance(item, JobInput):
            job = item
        elif isinstance(item, Mapping):
            try:
                job = JobInput(
                    job_id=item["jobId"],
                    node=item["node"],
                    author=item.get("author", ZERO_ADDRESS),
                    amount=item["amount"],
                )
            except KeyError as exc:
                raise ValueError(f"jobs[{index}] missing field {exc.args[0]}") from exc
        else:
            raise ValueError(f"jobs[{index}] must be JobInput or mapping")

        job_id_bytes = _bytes32(job.job_id, f"jobs[{index}].jobId")
        if job_id_bytes in seen_job_ids:
            raise ValueError(f"duplicate jobId: {job.job_id}")
        seen_job_ids.add(job_id_bytes)
        node_bytes = _address(job.node, f"jobs[{index}].node")
        author_bytes = _address(job.author, f"jobs[{index}].author", allow_zero=True)
        amount = _uint256(job.amount, f"jobs[{index}].amount")
        if total > _MAX_UINT256 - amount:
            raise ValueError("sum of job amounts exceeds uint256")
        total += amount
        normalized.append(JobInput(job.job_id, job.node, job.author, amount))

    if total > deposit:
        raise ValueError(f"sum of job amounts ({total}) exceeds deposit ({deposit})")

    proofs: list[list[tuple[bytes, int]]] = [[] for _ in normalized]
    level: list[_Node] = []
    for index, job in enumerate(normalized):
        leaf_id = _bytes32(job.job_id, f"jobs[{index}].jobId")
        node_address = _address(job.node, f"jobs[{index}].node")
        author_address = _address(job.author, f"jobs[{index}].author", allow_zero=True)
        leaf = _leaf_hash(context, batch_bytes, leaf_id, node_address, author_address, job.amount)
        level.append(_Node(_leaf_node(leaf, job.amount), job.amount, (index,)))

    while len(level) > 1:
        next_level: list[_Node] = []
        for offset in range(0, len(level), 2):
            left = level[offset]
            if offset + 1 == len(level):
                # Promote an odd final node unchanged; do not duplicate its value.
                next_level.append(left)
                continue
            right = level[offset + 1]
            if left.amount_sum > _MAX_UINT256 - right.amount_sum:
                raise ValueError("Merkle-sum parent exceeds uint256")
            for leaf_index in left.indexes:
                proofs[leaf_index].append((right.digest, right.amount_sum))
            for leaf_index in right.indexes:
                proofs[leaf_index].append((left.digest, left.amount_sum))
            parent_sum = left.amount_sum + right.amount_sum
            next_level.append(_Node(_parent(left.digest, left.amount_sum, right.digest, right.amount_sum),
                                    parent_sum, left.indexes + right.indexes))
        level = next_level

    claims = tuple(
        JobProof(
            job_id=job.job_id,
            node=job.node,
            author=job.author,
            amount=job.amount,
            proof=tuple("0x" + digest.hex() for digest, _ in proofs[index]),
            proof_sums=tuple(amount_sum for _, amount_sum in proofs[index]),
        )
        for index, job in enumerate(normalized)
    )
    if not any(level[0].digest):
        raise ValueError("computed root is zero and cannot be published")
    return BatchProof(settlement_context=context, batch_id="0x" + batch_bytes.hex(), root="0x" + level[0].digest.hex(),
                      root_sum=level[0].amount_sum, claims=claims)


def verify_claim(settlement_context: SettlementContext | Mapping[str, object],
                 batch_id: str, claim: JobProof, root: str, root_sum: int) -> bool:
    """Local verifier mirroring Solidity's leaf and sorted sum-proof rules."""
    context = (settlement_context if isinstance(settlement_context, SettlementContext)
               else SettlementContext.from_mapping(settlement_context))
    batch_bytes = _bytes32(batch_id, "batchId")
    root_bytes = _bytes32(root, "root")
    expected_sum = _uint256(root_sum, "root_sum")
    if len(claim.proof) != len(claim.proof_sums):
        return False
    leaf = _leaf_hash(
        context,
        batch_bytes,
        _bytes32(claim.job_id, "jobId"),
        _address(claim.node, "node"),
        _address(claim.author, "author", allow_zero=True),
        _uint256(claim.amount, "amount"),
    )
    current_hash = _leaf_node(leaf, claim.amount)
    current_sum = claim.amount
    for proof_hash, proof_sum in zip(claim.proof, claim.proof_sums):
        sibling_hash = _bytes32(proof_hash, "proof")
        sibling_sum = _uint256(proof_sum, "proof sum", allow_zero=True)
        if current_sum > _MAX_UINT256 - sibling_sum:
            return False
        current_hash = _parent(current_hash, current_sum, sibling_hash, sibling_sum)
        current_sum += sibling_sum
    return current_hash == root_bytes and current_sum == expected_sum


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build InferenceEscrow Merkle-sum roots and claim proofs from JSON."
    )
    parser.add_argument("input", help="JSON file path, or '-' to read JSON from stdin")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            document = json.load(sys.stdin)
        else:
            with open(args.input, "r", encoding="utf-8") as source:
                document = json.load(source)
        if not isinstance(document, Mapping):
            raise ValueError("top-level JSON value must be an object")
        for required in ("settlementContext", "batchId", "depositAmount", "jobs"):
            if required not in document:
                raise ValueError(f"input missing field {required}")
        batch = build_batch(document["settlementContext"], document["batchId"],
                            document["jobs"], document["depositAmount"])
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    json.dump(batch.as_contract_batch(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
