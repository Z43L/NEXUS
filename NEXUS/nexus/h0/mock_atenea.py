"""Deterministic mock of the Atenhea engine API, for H0 tests on any machine.

Implements exactly the endpoints the worker uses:
- GET  /v1/models
- POST /v1/chat/completions/input_tokens  -> {"input_tokens": N}
- POST /v1/chat/completions               -> OpenAI-style + usage

Tokenization is a simple regex tokenizer, applied consistently to inputs and
outputs so metering cross-checks can be exact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def count_tokens(text: str) -> int:
    return len(TOKEN_RE.findall(text))


def messages_text(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content", "")) for m in messages)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self):
        if self.path == "/v1/models":
            return self._json({"object": "list",
                               "data": [{"id": os.environ.get("MOCK_MODEL_ID", "athenea-e2b"),
                                         "object": "model"}]})
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._body()
        if self.path == "/v1/chat/completions/input_tokens":
            if os.environ.get("MOCK_DISABLE_CHAT_COUNT") == "1":
                return self._json({"error": "unsupported endpoint"}, 404)
            return self._json({"input_tokens": count_tokens(messages_text(body.get("messages", [])))})
        if self.path == "/v1/messages/count_tokens":
            return self._json({"input_tokens": count_tokens(messages_text(body.get("messages", [])))})
        if self.path == "/v1/chat/completions":
            delay_ms = int(os.environ.get("MOCK_INFERENCE_DELAY_MS", "0"))
            if delay_ms > 0:
                time.sleep(min(delay_ms, 5000) / 1000)
            prompt = messages_text(body.get("messages", []))
            seed = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
            max_tokens = int(body.get("max_tokens", 220))
            n_out = min(max_tokens, 60)
            text = " ".join(f"tok{seed}-{i}" for i in range(n_out))
            # Like the real engine, usage.prompt_tokens includes fixed
            # per-request scaffolding the counting endpoint does not see.
            scaffold = int(os.environ.get("MOCK_SCAFFOLD", "25"))
            return self._json({
                "id": "chatcmpl-mock", "object": "chat.completion",
                "model": body.get("model", "athenea-e2b"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": count_tokens(prompt) + scaffold,
                          "completion_tokens": count_tokens(text),
                          "total_tokens": count_tokens(prompt) + scaffold + count_tokens(text)},
            })
        return self._json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; use 0.0.0.0 only for isolated container tests")
    ap.add_argument("--port", type=int, default=11436)
    args = ap.parse_args()
    print(f"mock atenea on {args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
