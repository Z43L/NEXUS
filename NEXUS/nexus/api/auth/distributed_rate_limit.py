"""Atomic fixed-window rate limiting backed by Redis or Valkey.

The caller supplies an opaque principal key. The key is never included in logs
or exception messages. Redis errors raise :class:`RateLimitBackendError`, so
callers can fail closed instead of accidentally bypassing a configured quota.
"""

from __future__ import annotations

from typing import Any


_CONSUME_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return count
"""


class RateLimitBackendError(RuntimeError):
    """The shared rate-limit store could not enforce a quota."""


def consume(
    redis: Any,
    key: str,
    limit: int,
    now_ms: int | None = None,
    window_ms: int = 60_000,
) -> tuple[int, int, int, bool]:
    """Consume one request in the current fixed window.

    Returns ``(limit, remaining, reset_epoch_seconds, allowed)``. The Redis
    key is namespaced by the fixed-window start, so callers can pass a stable
    opaque identity and requests in different windows cannot share a counter.
    Redis applies the window-end TTL atomically with the first increment.

    Backend failures raise ``RateLimitBackendError`` (fail closed). Invalid
    arguments raise ``ValueError`` before contacting Redis.
    """
    if not isinstance(key, str) or not key:
        raise ValueError("key must be a non-empty string")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if isinstance(window_ms, bool) or not isinstance(window_ms, int) or window_ms < 1:
        raise ValueError("window_ms must be a positive integer")
    if now_ms is None:
        import time

        now_ms = time.time_ns() // 1_000_000
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms < 0:
        raise ValueError("now_ms must be a non-negative integer")

    window_start_ms = (now_ms // window_ms) * window_ms
    window_end_ms = window_start_ms + window_ms
    ttl_ms = window_end_ms - now_ms
    bucket_key = f"{key}:{window_start_ms}"
    try:
        count = int(redis.eval(_CONSUME_SCRIPT, 1, bucket_key, ttl_ms))
    except Exception as exc:
        # Do not chain backend details: client exceptions may contain the key.
        raise RateLimitBackendError("shared rate-limit backend unavailable") from None

    reset_epoch_seconds = (window_end_ms + 999) // 1000
    remaining = max(0, limit - count)
    return limit, remaining, reset_epoch_seconds, count <= limit
