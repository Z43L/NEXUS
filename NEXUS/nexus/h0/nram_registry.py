"""Local H2 registry for NRA-M v2 adapter bundles.

Pure-stdlib validation so the Router never imports torch or safetensors. A
bundle is accepted only if its magic, section lengths, JSON manifest and
tensor checksum are consistent. The bundle id is the SHA-256 of the whole
file, so a worker can verify a download against the id it was asked for.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import tempfile
from pathlib import Path

MAGIC = b"NRAM\x00\x02"
HEADER = struct.Struct(">QQ")  # manifest length, tensor section length
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
ID_RE = re.compile(r"[0-9a-f]{64}")
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}")
VERSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")


class NramError(ValueError):
    pass


def inspect_bundle(data: bytes) -> dict:
    """Validate an NRA-M v2 file and return its manifest (with bundle size)."""
    if len(data) > MAX_BUNDLE_BYTES:
        raise NramError("bundle exceeds 64 MiB")
    prefix = len(MAGIC) + HEADER.size
    if len(data) < prefix or data[: len(MAGIC)] != MAGIC:
        raise NramError("invalid NRA-M v2 magic")
    manifest_len, tensors_len = HEADER.unpack(data[len(MAGIC):prefix])
    boundary = prefix + manifest_len
    if boundary + tensors_len != len(data):
        raise NramError("NRA-M section lengths do not match file size")
    try:
        manifest = json.loads(data[prefix:boundary].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NramError("invalid NRA-M JSON manifest") from exc
    if not isinstance(manifest, dict):
        raise NramError("NRA-M manifest must be an object")
    if manifest.get("container") != "NRA-M" or manifest.get("format_version") != 2:
        raise NramError("unsupported NRA-M version")
    if hashlib.sha256(data[boundary:]).hexdigest() != manifest.get("tensor_sha256"):
        raise NramError("NRA-M tensor checksum mismatch")
    name = manifest.get("name")
    version = manifest.get("version")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise NramError("manifest name must be 1-80 characters of [A-Za-z0-9_.-]")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        raise NramError("manifest version must be 1-32 characters of [A-Za-z0-9_.-]")
    return {"name": name, "version": version, "size_bytes": len(data),
            "manifest": manifest}


def bundle_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store_bundle(base: Path, nram_id: str, data: bytes) -> Path:
    """Write the bundle atomically under <base>/nram/<id>.nram (mode 0644)."""
    if not ID_RE.fullmatch(nram_id):
        raise NramError("invalid bundle id")
    folder = base / "nram"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{nram_id}.nram"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{nram_id}.", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return target


def read_bundle(base: Path, nram_id: str) -> bytes:
    if not ID_RE.fullmatch(nram_id):
        raise NramError("invalid bundle id")
    data = (base / "nram" / f"{nram_id}.nram").read_bytes()
    if bundle_id(data) != nram_id:
        raise NramError("stored bundle does not match its id")
    return data
