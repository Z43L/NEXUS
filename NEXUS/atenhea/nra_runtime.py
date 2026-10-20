"""Small, dependency-free NRA-M transaction prototype.

This module tests the container and safe mutation loop. It is deliberately not
an implementation of a pretrained language model or a GPT-2 runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterable

MAGIC = b"NRAM\x00\x01"
HEADER = struct.Struct(">Q")


class NRAMError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def save_nram(path: str | Path, state: dict[str, Any]) -> None:
    """Atomically save a checksummed JSON payload in a versioned NRAM envelope."""
    path = Path(path)
    payload = _canonical_json(state)
    envelope = {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "state": state,
    }
    body = _canonical_json(envelope)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(MAGIC)
            stream.write(HEADER.pack(len(body)))
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def load_nram(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if len(raw) < len(MAGIC) + HEADER.size or raw[: len(MAGIC)] != MAGIC:
        raise NRAMError("Invalid NRAM magic or truncated header")
    (size,) = HEADER.unpack(raw[len(MAGIC) : len(MAGIC) + HEADER.size])
    body = raw[len(MAGIC) + HEADER.size :]
    if size != len(body):
        raise NRAMError("Payload length mismatch")
    try:
        envelope = json.loads(body)
        state = envelope["state"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise NRAMError("Invalid NRAM payload") from exc
    expected = hashlib.sha256(_canonical_json(state)).hexdigest()
    if envelope.get("sha256") != expected:
        raise NRAMError("Checksum mismatch")
    if state.get("format_version") != 1:
        raise NRAMError("Unsupported NRAM format version")
    return state


def predict(state: dict[str, Any], x: float) -> float:
    """Tiny reference model: y = (base + persistent_delta) * x."""
    weight = float(state["model"]["base_weight"]) + float(state["model"]["delta_weight"])
    return weight * x


def mse(state: dict[str, Any], examples: Iterable[tuple[float, float]]) -> float:
    rows = list(examples)
    if not rows:
        raise ValueError("Evaluation set must not be empty")
    return sum((predict(state, x) - y) ** 2 for x, y in rows) / len(rows)


def propose_delta(state: dict[str, Any], examples: Iterable[tuple[float, float]], rate: float = 0.1) -> float:
    """One gradient-descent step on the scalar delta, over training examples."""
    rows = list(examples)
    if not rows:
        raise ValueError("Training set must not be empty")
    weight = float(state["model"]["base_weight"]) + float(state["model"]["delta_weight"])
    grad = sum(2.0 * (weight * x - y) * x for x, y in rows) / len(rows)
    return float(state["model"]["delta_weight"]) - rate * grad


def try_commit(
    path: str | Path,
    train: Iterable[tuple[float, float]],
    validation: Iterable[tuple[float, float]],
    *,
    rate: float = 0.1,
    min_improvement: float = 1e-12,
    evaluator: Callable[[dict[str, Any], Iterable[tuple[float, float]]], float] = mse,
) -> dict[str, Any]:
    """Propose a weight delta, validate on held-out examples, then commit or reject."""
    state = load_nram(path)
    validation_rows = list(validation)
    before = evaluator(state, validation_rows)
    candidate = json.loads(json.dumps(state))
    candidate["model"]["delta_weight"] = propose_delta(state, train, rate)
    after = evaluator(candidate, validation_rows)
    accepted = after + min_improvement < before
    if accepted:
        candidate["version"] = int(state["version"]) + 1
        candidate["journal"].append(
            {"version": candidate["version"], "validation_before": before, "validation_after": after}
        )
        save_nram(path, candidate)
        return {"accepted": True, "before": before, "after": after, "version": candidate["version"]}
    return {"accepted": False, "before": before, "after": after, "version": state["version"]}


def initial_state() -> dict[str, Any]:
    return {
        "format_version": 1,
        "model": {
            "backend": "toy-linear-reference",
            "base_weight": 0.0,
            "delta_weight": 0.0,
            "target_model": "distilbert/distilgpt2",
            "target_model_params": 82000000,
        },
        "graph": ["ENCODE", "TRANSFORM", "EVALUATE", "COMMIT", "DECODE", "HALT"],
        "version": 0,
        "journal": [],
    }
