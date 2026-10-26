"""Provision and revoke NEXUS API client credentials in a private registry."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

CLIENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SCOPES = {"inference", "models:read", "jobs:read", "auth:session", "admin"}


def _read_registry(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("registry must not be a symlink")
    if not path.exists():
        return {"version": 1, "clients": []}
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError("registry permissions must be 0600")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("clients"), list):
        raise ValueError("registry format is invalid")
    if len(data["clients"]) > 1000:
        raise ValueError("registry exceeds the supported client limit")
    ids, token_hashes = set(), set()
    for client in data["clients"]:
        if not isinstance(client, dict):
            raise ValueError("registry entry is invalid")
        client_id = client.get("client_id")
        token_hash = client.get("token_sha256")
        scopes = client.get("scopes")
        quota = client.get("rate_limit_per_minute")
        if (not isinstance(client_id, str) or not CLIENT_ID.fullmatch(client_id)
                or client_id.startswith("user-")
                or not isinstance(token_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", token_hash)
                or not isinstance(scopes, list) or not scopes
                or any(not isinstance(scope, str) or scope not in SCOPES for scope in scopes)
                or len(set(scopes)) != len(scopes)
                or isinstance(quota, bool) or not isinstance(quota, int)
                or not 1 <= quota <= 10000
                or client_id in ids or token_hash in token_hashes):
            raise ValueError("registry entry is invalid")
        ids.add(client_id)
        token_hashes.add(token_hash)
    return data


def _write_registry(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PermissionError("registry directory must be private (mode 0700)")
    fd, temporary = tempfile.mkstemp(prefix=".api-clients-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _scope_list(value: str) -> list[str]:
    scopes = [scope.strip() for scope in value.split(",") if scope.strip()]
    if not scopes or any(scope not in SCOPES for scope in scopes) or len(set(scopes)) != len(scopes):
        raise ValueError("scopes must be unique values from: " + ", ".join(sorted(SCOPES)))
    return sorted(scopes)


def manage(path: Path, action: str, client_id: str | None = None,
           scopes: str = "inference,models:read,jobs:read", quota: int = 60) -> str | None:
    if client_id is not None and (not CLIENT_ID.fullmatch(client_id) or client_id.startswith("user-")):
        raise ValueError("client id must be 1–64 letters, digits, dot, underscore or hyphen")
    if not 1 <= quota <= 10000:
        raise ValueError("quota must be between 1 and 10000 requests per minute")
    parsed_scopes = _scope_list(scopes) if action == "add" else []
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PermissionError("registry directory must be private (mode 0700)")
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(lock_fd, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        registry = _read_registry(path)
        clients = registry["clients"]
        if action == "list":
            return json.dumps([
                {"client_id": item["client_id"], "scopes": item["scopes"],
                 "rate_limit_per_minute": item["rate_limit_per_minute"]}
                for item in clients
            ], indent=2)
        if action == "revoke":
            remaining = [item for item in clients if item.get("client_id") != client_id]
            if len(remaining) == len(clients):
                raise ValueError(f"unknown API client: {client_id}")
            registry["clients"] = remaining
            _write_registry(path, registry)
            return None
        if action == "add":
            if any(item.get("client_id") == client_id for item in clients):
                raise ValueError(f"API client already exists: {client_id}")
            token = "nxs_" + secrets.token_urlsafe(32)
            clients.append({
                "client_id": client_id,
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                "scopes": parsed_scopes,
                "rate_limit_per_minute": quota,
            })
            registry["clients"] = clients
            _write_registry(path, registry)
            return token
    raise ValueError(f"unsupported action: {action}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True,
                        help="private api_clients.json file")
    subparsers = parser.add_subparsers(dest="action", required=True)
    add = subparsers.add_parser("add", help="create a one-time client token")
    add.add_argument("--id", dest="client_id", required=True)
    add.add_argument("--scopes", default="inference,models:read,jobs:read")
    add.add_argument("--rate-limit-per-minute", type=int, default=60)
    revoke = subparsers.add_parser("revoke", help="revoke a client by id")
    revoke.add_argument("--id", dest="client_id", required=True)
    subparsers.add_parser("list", help="list client ids, scopes and quotas")
    args = parser.parse_args()
    token = manage(args.registry, args.action, getattr(args, "client_id", None),
                   getattr(args, "scopes", ""),
                   getattr(args, "rate_limit_per_minute", 60))
    if token:
        print("Store this token securely; it is shown only once:")
        print(token)


if __name__ == "__main__":
    main()
