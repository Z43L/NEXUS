import hashlib
import json
import os
import tempfile
import traceback
import unittest
from pathlib import Path

from nexus.api.auth.user_sessions import (
    RegistryError,
    SessionStoreError,
    create_session,
    hash_password,
    load_user_registry,
    resolve_session,
    revoke_session,
    validate_registry,
    verify_password,
)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expiries = {}
        self.fail = False

    def set(self, key, value, *, ex, nx):
        if self.fail:
            raise OSError(f"offline while accessing {key}")
        if nx and key in self.values:
            return None
        self.values[key] = value
        self.expiries[key] = ex
        return True

    def get(self, key):
        if self.fail:
            raise OSError(f"offline while accessing {key}")
        return self.values.get(key)

    def delete(self, key):
        if self.fail:
            raise OSError(f"offline while accessing {key}")
        return int(self.values.pop(key, None) is not None)


def make_registry():
    return {"version": 1, "users": [{
        "user_id": "alice", "password_scrypt": hash_password("correct horse", salt=b"s" * 16, n=1024),
        "client_id": "user-alice", "scopes": ["inference", "jobs:read"],
        "rate_limit_per_minute": 27,
    }]}


class UserSessionTests(unittest.TestCase):
    def assert_registry_invalid(self, mutate):
        value = make_registry()
        mutate(value)
        with self.assertRaises(RegistryError):
            validate_registry(value)

    def test_registry_validates_and_exposes_user_principal(self):
        parsed = validate_registry(make_registry())
        self.assertEqual(parsed["alice"]["principal"], "user:alice")
        self.assertEqual(parsed["alice"]["client_id"], "user-alice")
        self.assertEqual(parsed["alice"]["rate_limit_per_minute"], 27)

    def test_registry_rejects_invalid_data(self):
        mutations = (
            lambda d: d.update(version=2),
            lambda d: d["users"][0].update(user_id="../bad"),
            lambda d: d["users"][0].update(rate_limit_per_minute=True),
            lambda d: d["users"][0].update(scopes=["inference", "inference"]),
            lambda d: d["users"][0]["password_scrypt"].update(n=1000),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.assert_registry_invalid(mutate)

    def test_load_registry_requires_private_file_and_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "private"
            directory.mkdir(mode=0o700)
            path = directory / "users.json"
            path.write_text(json.dumps(make_registry()), encoding="utf-8")
            path.chmod(0o600)
            os.chmod(directory, 0o700)
            self.assertIn("alice", load_user_registry(path))
            path.chmod(0o644)
            with self.assertRaises(RegistryError):
                load_user_registry(path)

    def test_password_verification_is_correct_and_rejects_unknown_or_bad(self):
        user = validate_registry(make_registry())["alice"]
        self.assertTrue(verify_password("correct horse", user))
        self.assertFalse(verify_password("wrong", user))
        self.assertFalse(verify_password("correct horse", None))
        self.assertFalse(verify_password("", user))

    def test_session_round_trip_uses_hashed_token_key_and_ttl(self):
        redis = FakeRedis()
        user = validate_registry(make_registry())["alice"]
        token = create_session(redis, user, ttl_seconds=900)
        self.assertEqual(len(token), 43)
        key, payload = next(iter(redis.values.items()))
        self.assertNotIn(token, key)
        self.assertTrue(key.endswith(hashlib.sha256(token.encode()).hexdigest()))
        self.assertNotIn(token, payload)
        self.assertEqual(redis.expiries[key], 900)
        self.assertEqual(resolve_session(redis, token), {
            "principal": "user:alice", "user_id": "alice", "client_id": "user-alice",
            "scopes": ["inference", "jobs:read"], "rate_limit_per_minute": 27,
            "auth_fingerprint": user["password_scrypt"]["hash"],
        })
        self.assertTrue(revoke_session(redis, token))
        self.assertIsNone(resolve_session(redis, token))
        self.assertFalse(revoke_session(redis, token))

    def test_unknown_tokens_and_storage_fail_closed_without_leaking_keys(self):
        redis = FakeRedis()
        self.assertIsNone(resolve_session(redis, "invalid"))
        redis.fail = True
        user = validate_registry(make_registry())["alice"]
        operations = (
            lambda: create_session(redis, user),
            lambda: resolve_session(redis, "A" * 43),
            lambda: revoke_session(redis, "A" * 43),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(SessionStoreError) as raised:
                    operation()
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn("nexus:session:v1:", str(raised.exception))
                self.assertNotIn("nexus:session:v1:", rendered)
                self.assertIsNone(raised.exception.__cause__)

    def test_malformed_stored_session_fails_closed(self):
        redis = FakeRedis()
        token = create_session(redis, validate_registry(make_registry())["alice"])
        key = next(iter(redis.values))
        redis.values[key] = '{"principal":"user:mallory"}'
        with self.assertRaises(SessionStoreError):
            resolve_session(redis, token)


if __name__ == "__main__":
    unittest.main()
