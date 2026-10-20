"""Versioned single-file NRA-M container with safe tensor sections."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
from pathlib import Path
from typing import Any

from safetensors.torch import load as load_tensors
from safetensors.torch import save as save_tensors
import torch

MAGIC = b"NRAM\x00\x02"
HEADER = struct.Struct(">QQ")  # JSON manifest length, safetensors section length


class NRAMContainerError(ValueError):
    pass


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def save_bundle(path: str | Path, manifest: dict[str, Any], tensors: dict[str, torch.Tensor]) -> None:
    """Write manifest + adapter tensors atomically; tensor data uses Safetensors."""
    path = Path(path)
    tensor_bytes = save_tensors({k: v.detach().cpu().contiguous() for k, v in tensors.items()})
    header = dict(manifest)
    header["container"] = "NRA-M"
    header["format_version"] = 2
    header["tensor_sha256"] = hashlib.sha256(tensor_bytes).hexdigest()
    header_bytes = _json_bytes(header)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(MAGIC)
            stream.write(HEADER.pack(len(header_bytes), len(tensor_bytes)))
            stream.write(header_bytes)
            stream.write(tensor_bytes)
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


def load_bundle(path: str | Path) -> tuple[dict[str, Any], dict[str, torch.Tensor]]:
    raw = Path(path).read_bytes()
    prefix_len = len(MAGIC) + HEADER.size
    if len(raw) < prefix_len or raw[: len(MAGIC)] != MAGIC:
        raise NRAMContainerError("Invalid NRA-M v2 magic/header")
    header_len, tensors_len = HEADER.unpack(raw[len(MAGIC) : prefix_len])
    boundary = prefix_len + header_len
    if boundary + tensors_len != len(raw):
        raise NRAMContainerError("NRA-M section lengths do not match file size")
    try:
        manifest = json.loads(raw[prefix_len:boundary])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise NRAMContainerError("Invalid NRA-M JSON manifest") from exc
    tensor_bytes = raw[boundary:]
    if hashlib.sha256(tensor_bytes).hexdigest() != manifest.get("tensor_sha256"):
        raise NRAMContainerError("NRA-M tensor checksum mismatch")
    if manifest.get("container") != "NRA-M" or manifest.get("format_version") != 2:
        raise NRAMContainerError("Unsupported NRA-M version")
    try:
        tensors = load_tensors(tensor_bytes)
    except Exception as exc:
        raise NRAMContainerError("Invalid Safetensors section") from exc
    return manifest, tensors
