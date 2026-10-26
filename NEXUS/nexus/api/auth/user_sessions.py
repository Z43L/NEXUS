"""Private user registry and opaque Redis-backed sessions.

This module is intentionally storage-agnostic: the Redis client is injected and
must provide ``set/get/delete`` methods. Storage errors fail closed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping

USER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,58}\Z")
CLIENT_ID = USER_ID
SCOPE = re.compile(r"[a-z][a-z0-9:_-]{0,63}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_SCRYPT = {"n", "r", "p", "salt", "hash"}
DEFAULT_SCRYPT = {"n": 16384, "r": 8, "p": 1}
MAX_USERS = 10000


class RegistryError(ValueError):
    """The user registry is absent, unsafe, or malformed."""


class SessionStoreError(RuntimeError):
    """Session storage is unavailable or returned invalid data."""


def _valid_scrypt(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != _ALLOWED_SCRYPT:
        return False
    n, r, p = value["n"], value["r"], value["p"]
    return (
        isinstance(n, int) and not isinstance(n, bool) and 2 <= n <= 2**16 and n & (n - 1) == 0
        and isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= 8
        and isinstance(p, int) and not isinstance(p, bool) and 1 <= p <= 4
        and isinstance(value["salt"], str) and bool(re.fullmatch(r"[0-9a-f]{32,128}", value["salt"]))
        and isinstance(value["hash"], str) and bool(_HEX_64.fullmatch(value["hash"]))
    )


def validate_registry(data: Any) -> dict[str, dict[str, Any]]:
    """Validate version-1 JSON data and return users keyed by user_id."""
    if not isinstance(data, dict) or set(data) != {"version", "users"} or data.get("version") != 1:
        raise RegistryError("user registry format is invalid")
    entries = data["users"]
    if not isinstance(entries, list) or len(entries) > MAX_USERS:
        raise RegistryError("user registry format is invalid")
    result: dict[str, dict[str, Any]] = {}
    client_ids: set[str] = set()
    for user in entries:
        if not isinstance(user, dict) or set(user) != {
            "user_id", "password_scrypt", "client_id", "scopes", "rate_limit_per_minute"
        }:
            raise RegistryError("user registry entry is invalid")
        uid, cid, scopes, quota = (user["user_id"], user["client_id"], user["scopes"], user["rate_limit_per_minute"])
        if (not isinstance(uid, str) or not USER_ID.fullmatch(uid) or uid in result
            or not isinstance(cid, str) or not CLIENT_ID.fullmatch(cid) or not cid.startswith("user-") or cid in client_ids
            or not _valid_scrypt(user["password_scrypt"])
            or not isinstance(scopes, list) or not scopes or len(scopes) > 64
            or any(not isinstance(s, str) or not SCOPE.fullmatch(s) for s in scopes)
            or len(set(scopes)) != len(scopes)
            or isinstance(quota, bool) or not isinstance(quota, int) or not 1 <= quota <= 10000):
            raise RegistryError("user registry entry is invalid")
        result[uid] = {
            "user_id": uid,
            "principal": f"user:{uid}",
            "client_id": cid,
            "scopes": list(scopes),
            "rate_limit_per_minute": quota,
            "password_scrypt": dict(user["password_scrypt"]),
        }
        client_ids.add(cid)
    return result


def load_user_registry(path: str | os.PathLike[str]) -> dict[str, dict[str, Any]]:
    """Read and validate a protected JSON registry (file 0600).

    Provisioning tools protect the containing directory too. Container secret
    mounts can use a runtime-owned parent directory, so the API enforces the
    file mode and symlink checks here.
    """
    target = Path(path)
    try:
        if target.is_symlink() or not target.is_file():
            raise RegistryError("user registry is unavailable or unsafe")
        if stat.S_IMODE(target.stat().st_mode) & 0o077:
            raise RegistryError("user registry permissions must be 0600")
        data = json.loads(target.read_text(encoding="utf-8"))
    except RegistryError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryError("user registry is unavailable or invalid") from exc
    return validate_registry(data)


def hash_password(password: str, *, salt: bytes | None = None,
                  n: int = DEFAULT_SCRYPT["n"], r: int = DEFAULT_SCRYPT["r"],
                  p: int = DEFAULT_SCRYPT["p"]) -> dict[str, Any]:
    """Create a serializable scrypt record for operator provisioning tools."""
    if not isinstance(password, str) or not password or len(password.encode("utf-8")) > 1024:
        raise ValueError("password must be a non-empty string of at most 1024 bytes")
    salt = salt if salt is not None else secrets.token_bytes(16)
    if len(salt) < 16 or len(salt) > 64:
        raise ValueError("salt must be between 16 and 64 bytes")
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return {"n": n, "r": r, "p": p, "salt": salt.hex(), "hash": digest.hex()}


def verify_password(password: str, user: Mapping[str, Any] | None) -> bool:
    """Verify scrypt credentials with constant-time digest comparison."""
    record = user.get("password_scrypt") if isinstance(user, Mapping) else None
    valid_password = isinstance(password, str) and bool(password) and len(password.encode("utf-8")) <= 1024
    if not valid_password:
        password = "\0"  # still perform the derivation for malformed inputs
    if not _valid_scrypt(record):
        # Equalize unknown-user/malformed-record work without accepting a result.
        record = {**DEFAULT_SCRYPT, "salt": "00" * 16, "hash": "00" * 32}
        should_accept = False
    else:
        should_accept = valid_password
    try:
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(record["salt"]),
                                n=record["n"], r=record["r"], p=record["p"], dklen=32).hex()
    except (ValueError, MemoryError):
        return False
    return bool(should_accept and hmac.compare_digest(actual, record["hash"]))


def _token_digest(token: str) -> str:
    if not isinstance(token, str) or not token or len(token) > 256:
        raise ValueError("invalid session token")
    return hashlib.sha256(token.encode("ascii", errors="strict")).hexdigest()


def _session_key(token: str, prefix: str) -> str:
    return f"{prefix}:{_token_digest(token)}"


def _store_call(call: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(*args, **kwargs)
    except Exception as exc:
        raise SessionStoreError("session storage unavailable") from None


def create_session(redis: Any, user: Mapping[str, Any], *, ttl_seconds: int = 3600,
                   key_prefix: str = "nexus:session:v1") -> str:
    """Store an opaque 32-byte bearer token hash with expiry; return raw token once."""
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 31_536_000:
        raise ValueError("ttl_seconds must be between 1 and 31536000")
    uid, cid, scopes, quota = user.get("user_id"), user.get("client_id"), user.get("scopes"), user.get("rate_limit_per_minute")
    if not isinstance(uid, str) or not USER_ID.fullmatch(uid) or not isinstance(cid, str) or not CLIENT_ID.fullmatch(cid):
        raise ValueError("invalid user")
    if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or not SCOPE.fullmatch(s) for s in scopes):
        raise ValueError("invalid user")
    if isinstance(quota, bool) or not isinstance(quota, int) or not 1 <= quota <= 10000:
        raise ValueError("invalid user")
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    password_record = user.get("password_scrypt")
    if not _valid_scrypt(password_record):
        raise ValueError("invalid user")
    value = json.dumps({"principal": f"user:{uid}", "user_id": uid, "client_id": cid,
                        "scopes": scopes, "rate_limit_per_minute": quota,
                        "auth_fingerprint": password_record["hash"]}, separators=(",", ":"))
    result = _store_call(redis.set, _session_key(token, key_prefix), value, ex=ttl_seconds, nx=True)
    if result not in (True, "OK", b"OK"):
        raise SessionStoreError("session storage unavailable")
    return token


def resolve_session(redis: Any, token: str, *, key_prefix: str = "nexus:session:v1") -> dict[str, Any] | None:
    """Resolve an active session; return None for unknown or expired tokens."""
    try:
        key = _session_key(token, key_prefix)
    except (ValueError, UnicodeError):
        return None
    raw = _store_call(redis.get, key)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        uid, cid, scopes, quota = data["user_id"], data["client_id"], data["scopes"], data["rate_limit_per_minute"]
        if (not isinstance(uid, str) or not USER_ID.fullmatch(uid) or data.get("principal") != f"user:{uid}"
            or not isinstance(cid, str) or not CLIENT_ID.fullmatch(cid) or not cid.startswith("user-")
            or not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or not SCOPE.fullmatch(s) for s in scopes)
            or not isinstance(data.get("auth_fingerprint"), str) or not _HEX_64.fullmatch(data["auth_fingerprint"])
            or isinstance(quota, bool) or not isinstance(quota, int) or not 1 <= quota <= 10000):
            raise ValueError("invalid session payload")
        return {"principal": f"user:{uid}", "user_id": uid, "client_id": cid,
                "scopes": scopes, "rate_limit_per_minute": quota,
                "auth_fingerprint": data["auth_fingerprint"]}
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError) as exc:
        raise SessionStoreError("session storage returned invalid data") from exc


def revoke_session(redis: Any, token: str, *, key_prefix: str = "nexus:session:v1") -> bool:
    """Delete a session by token digest; return whether a record existed."""
    try:
        key = _session_key(token, key_prefix)
    except (ValueError, UnicodeError):
        return False
    return bool(_store_call(redis.delete, key))
