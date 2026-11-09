"""OpenAI-compatible HTTP gateway (non-streaming subset).

Endpoints: GET /healthz (open), GET /v1/models, POST /v1/chat/completions.
Auth: `Authorization: Bearer <key>`; only SHA-256 hashes of keys are stored.
Rate limit: per-key token bucket. Transport is plain HTTP (testnet): terminate TLS
in front of it.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from typing import Dict, Optional

from nexus_runtime.httpx import JsonServer
from .engine import EngineAdapter

MAX_TOKENS_CAP = 256


class ApiKeyStore:
    def __init__(self, path: Optional[str] = None):
        self.path, self._lock = path, threading.Lock()
        self.keys: Dict[str, Dict] = {}
        if path and os.path.exists(path):
            with open(path) as f:
                self.keys = json.load(f)

    @staticmethod
    def hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    def create(self, name: str, rate_per_min: int = 60) -> str:
        raw = "nxs-" + secrets.token_urlsafe(24)
        with self._lock:
            self.keys[self.hash_key(raw)] = {"name": name, "rate_per_min": rate_per_min,
                                             "created": int(time.time())}
            if self.path:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w") as f:
                    json.dump(self.keys, f)
        return raw

    def lookup(self, raw: str) -> Optional[Dict]:
        with self._lock:
            return self.keys.get(self.hash_key(raw))


class RateLimiter:
    def __init__(self, clock=time.monotonic):
        self.clock, self._b, self._lock = clock, {}, threading.Lock()

    def allow(self, key_hash: str, per_min: int) -> bool:
        now = self.clock()
        with self._lock:
            tokens, last = self._b.get(key_hash, (float(per_min), now))
            tokens = min(float(per_min), tokens + (now - last) * per_min / 60.0)
            if tokens < 1.0:
                self._b[key_hash] = (tokens, now)
                return False
            self._b[key_hash] = (tokens - 1.0, now)
            return True


def _err(code, typ, msg):
    return code, {"error": {"message": msg, "type": typ, "code": typ}}


class Gateway:
    def __init__(self, engine: EngineAdapter, keys: ApiKeyStore, limiter: Optional[RateLimiter] = None):
        self.engine, self.keys, self.limiter = engine, keys, limiter or RateLimiter()
        self.server: Optional[JsonServer] = None

    def handle(self, method, path, q, body, headers):
        if method == "GET" and path == "/healthz":
            return 200, {"status": "ok"}
        auth = {k.lower(): v for k, v in headers.items()}.get("authorization", "")
        if not auth.startswith("Bearer ") or not auth[7:].strip():
            return _err(401, "invalid_api_key", "Missing API key. Use 'Authorization: Bearer <key>'.")
        info = self.keys.lookup(auth[7:].strip())
        if info is None:
            return _err(401, "invalid_api_key", "Invalid API key.")
        if not self.limiter.allow(ApiKeyStore.hash_key(auth[7:].strip()), int(info.get("rate_per_min", 60))):
            return _err(429, "rate_limit_exceeded", "Rate limit exceeded.")
        if method == "GET" and path == "/v1/models":
            return 200, {"object": "list", "data": [
                {"id": m["id"], "object": "model", "created": 0, "owned_by": m.get("owned_by", "nexus")}
                for m in self.engine.list_models()]}
        if method == "POST" and path == "/v1/chat/completions":
            return self._chat(body)
        return _err(404, "not_found", "Unknown endpoint.")

    def _chat(self, b):
        if not isinstance(b, dict) or not isinstance(b.get("messages"), list) or not b["messages"]:
            return _err(400, "invalid_request", "'messages' must be a non-empty list.")
        if b.get("stream"):
            return _err(400, "unsupported", "stream=true is not supported in v0.1.")
        msgs = b["messages"]
        if not all(isinstance(m, dict) and isinstance(m.get("content", ""), str) for m in msgs):
            return _err(400, "invalid_request", "Each message needs a string 'content'.")
        if sum(len(m.get("content", "")) for m in msgs) > 8000:
            return _err(400, "invalid_request", "Prompt too long (max 8000 chars).")
        try:
            max_tokens = min(int(b.get("max_tokens", 16)), MAX_TOKENS_CAP)
            temperature = float(b.get("temperature", 0.0))
            seed = int(b.get("seed", 0))
        except (TypeError, ValueError):
            return _err(400, "invalid_request", "Bad numeric parameter.")
        if max_tokens < 1 or not (0.0 <= temperature <= 2.0):
            return _err(400, "invalid_request", "max_tokens>=1 and 0<=temperature<=2 required.")
        model = b.get("model", "")
        try:
            r = self.engine.chat(model, msgs, max_tokens, temperature, seed)
        except KeyError:
            return _err(404, "model_not_found", "Unknown model '%s'." % model)
        except Exception as e:  # engine / network failure
            return _err(502, "engine_error", "Engine failure: %s" % type(e).__name__)
        return 200, {"id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
                     "created": int(time.time()), "model": model,
                     "choices": [{"index": 0, "message": {"role": "assistant", "content": r["text"]},
                                  "finish_reason": r.get("finish_reason", "length")}],
                     "usage": {"prompt_tokens": r["prompt_tokens"],
                               "completion_tokens": r["completion_tokens"],
                               "total_tokens": r["prompt_tokens"] + r["completion_tokens"]},
                     "nexus": r.get("extra", {})}

    def serve(self, host="127.0.0.1", port=0) -> JsonServer:
        self.server = JsonServer(host, port, self.handle).start()
        return self.server
