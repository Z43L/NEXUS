"""Tests for the Redis/Valkey fixed-window quota helper."""

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import unittest

from nexus.api.auth.distributed_rate_limit import (
    RateLimitBackendError,
    consume,
)


class FakeRedis:
    """Small, atomic fake implementing only the eval contract used here."""

    def __init__(self):
        self.counts = defaultdict(int)
        self.ttls = {}
        self.lock = Lock()

    def eval(self, script, numkeys, key, ttl_ms):
        if "INCR" not in script or "PEXPIRE" not in script or numkeys != 1:
            raise AssertionError("unexpected Redis script contract")
        with self.lock:
            self.counts[key] += 1
            if self.counts[key] == 1:
                self.ttls[key] = int(ttl_ms)
            return self.counts[key]


class FailingRedis:
    def eval(self, *_args):
        raise OSError("backend unavailable for secret-customer-key")


class DistributedRateLimitTests(unittest.TestCase):
    def test_limit_and_remaining(self):
        redis = FakeRedis()
        results = [consume(redis, "principal-digest", 2, now_ms=10_000)]
        results.append(consume(redis, "principal-digest", 2, now_ms=10_100))
        results.append(consume(redis, "principal-digest", 2, now_ms=10_200))

        self.assertEqual(results, [
            (2, 1, 60, True),
            (2, 0, 60, True),
            (2, 0, 60, False),
        ])
        self.assertEqual(list(redis.ttls.values()), [50_000])

    def test_concurrent_consumes_are_atomic_and_only_first_sets_expiry(self):
        redis = FakeRedis()
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(
                lambda _: consume(redis, "same-principal", 7, now_ms=123_456),
                range(64),
            ))

        self.assertEqual(sum(1 for result in results if result[3]), 7)
        self.assertEqual(redis.counts["same-principal:120000"], 64)
        self.assertEqual(redis.ttls["same-principal:120000"], 56_544)

    def test_fixed_window_resets_at_boundary(self):
        redis = FakeRedis()
        self.assertTrue(consume(redis, "principal", 1, now_ms=59_999)[3])
        self.assertFalse(consume(redis, "principal", 1, now_ms=59_999)[3])
        self.assertTrue(consume(redis, "principal", 1, now_ms=60_000)[3])
        self.assertIn("principal:0", redis.counts)
        self.assertIn("principal:60000", redis.counts)

    def test_backend_failure_fails_closed_without_disclosing_key(self):
        secret_key = "secret-customer-key"
        with self.assertRaises(RateLimitBackendError) as caught:
            consume(FailingRedis(), secret_key, 5, now_ms=1)
        self.assertNotIn(secret_key, str(caught.exception))

    def test_rejects_invalid_configuration(self):
        for args in (("", 1), ("key", 0), ("key", -1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                consume(FakeRedis(), args[0], args[1], now_ms=0)
        with self.assertRaises(ValueError):
            consume(FakeRedis(), "key", 1, now_ms=0, window_ms=0)


if __name__ == "__main__":
    unittest.main()
