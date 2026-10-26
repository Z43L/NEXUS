"""Provision local NEXUS browser accounts in a private user registry."""
from __future__ import annotations

import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import stat
import tempfile

from nexus.api.auth.user_sessions import hash_password, validate_registry

SCOPES = {"inference", "models:read", "jobs:read", "admin"}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PermissionError("user registry directory must be private (mode 0700)")
    fd, temporary = tempfile.mkstemp(prefix=".api-users-", dir=path.parent)
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


def _read(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError("user registry must not be a symlink")
    if not path.exists():
        return {"version": 1, "users": []}
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError("user registry permissions must be 0600")
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_registry(value)
    return value


def manage(path: Path, action: str, user_id: str | None = None,
           scopes: str = "inference,models:read,jobs:read", quota: int = 60,
           password: str | None = None) -> str:
    """Apply one account change; return redacted output suitable for CLI."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise PermissionError("user registry directory must be private (mode 0700)")
    lock_fd = os.open(path.with_name(path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
    os.fchmod(lock_fd, 0o600)
    with os.fdopen(lock_fd, "r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        data = _read(path)
        users = data["users"]
        by_id = {item["user_id"]: item for item in users}
        if action == "list":
            return json.dumps([
                {"user_id": item["user_id"], "scopes": item["scopes"],
                 "rate_limit_per_minute": item["rate_limit_per_minute"]}
                for item in users
            ], indent=2)
        if user_id is None:
            raise ValueError("user id is required")
        if action == "remove":
            if user_id not in by_id:
                raise ValueError(f"unknown user: {user_id}")
            data["users"] = [item for item in users if item["user_id"] != user_id]
        elif action in {"add", "set-password"}:
            if password is None:
                raise ValueError("password must be provided by the interactive CLI")
            if action == "add":
                if user_id in by_id:
                    raise ValueError(f"user already exists: {user_id}")
                scope_list = sorted({part.strip() for part in scopes.split(",") if part.strip()})
                if not scope_list or any(scope not in SCOPES for scope in scope_list):
                    raise ValueError("invalid user scope")
                if isinstance(quota, bool) or not 1 <= quota <= 10000:
                    raise ValueError("quota must be 1–10000 per minute")
                users.append({
                    "user_id": user_id,
                    "password_scrypt": hash_password(password),
                    "client_id": f"user-{user_id}",
                    "scopes": scope_list,
                    "rate_limit_per_minute": quota,
                })
            else:
                if user_id not in by_id:
                    raise ValueError(f"unknown user: {user_id}")
                by_id[user_id]["password_scrypt"] = hash_password(password)
        else:
            raise ValueError("unsupported action")
        validate_registry(data)
        _write(path, data)
        return "User registry updated. Restart/recreate the API to refresh file-backed secrets."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    commands = parser.add_subparsers(dest="action", required=True)
    add = commands.add_parser("add")
    add.add_argument("--id", dest="user_id", required=True)
    add.add_argument("--scopes", default="inference,models:read,jobs:read")
    add.add_argument("--rate-limit-per-minute", type=int, default=60)
    for name in ("set-password", "remove"):
        command = commands.add_parser(name)
        command.add_argument("--id", dest="user_id", required=True)
    commands.add_parser("list")
    args = parser.parse_args()
    password = None
    if args.action in {"add", "set-password"}:
        password = getpass.getpass("Password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if not password or password != confirmation:
            parser.error("passwords must be non-empty and match")
    result = manage(args.registry, args.action, getattr(args, "user_id", None),
                    getattr(args, "scopes", ""), getattr(args, "rate_limit_per_minute", 60), password)
    print(result)


if __name__ == "__main__":
    main()
