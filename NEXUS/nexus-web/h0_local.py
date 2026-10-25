"""Tiny same-origin UI/proxy for the local NEXUS H0 gateway.

Run from any directory with ``python3 NEXUS/nexus-web/h0_local.py``.
The service binds to loopback and forwards only the H0 models/chat routes.
"""
from __future__ import annotations

import json
import os
import re
import threading
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent
ROUTER = os.environ.get("NEXUS_H0_ROUTER_URL", "http://127.0.0.1:18080").rstrip("/")
PORT = int(os.environ.get("NEXUS_H0_UI_PORT", "18081"))
MAX_BODY = 1_048_576
MAX_RESPONSE = 2_097_152
MAX_CONCURRENT = 8
REQUEST_TIMEOUT = 15
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_router = urlsplit(ROUTER)
if _router.scheme != "http" or _router.hostname not in {"127.0.0.1", "localhost", "::1"}:
    raise RuntimeError("local H0 UI may proxy only to an HTTP loopback router")
if not 1 <= PORT <= 65535:
    raise RuntimeError("NEXUS_H0_UI_PORT must be between 1 and 65535")


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT)

    def log_message(self, *_args):
        pass

    def local_request_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        allowed_hosts = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
        if host not in allowed_hosts:
            self.send_bytes(b'{"error":"invalid host"}', 403, "application/json")
            return False
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                valid_origin = (
                    parsed.scheme == "http"
                    and parsed.hostname in {"127.0.0.1", "localhost"}
                    and parsed.port == PORT
                    and not parsed.path and not parsed.query and not parsed.fragment
                )
            except ValueError:
                valid_origin = False
            if not valid_origin:
                self.send_bytes(b'{"error":"invalid origin"}', 403, "application/json")
                return False
        return True

    def send_bytes(self, body: bytes, status: int, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.local_request_allowed():
            return
        if self.path == "/" or self.path == "/index.html":
            page = (BASE / "h0.html").read_bytes()
            return self.send_bytes(page, 200, "text/html; charset=utf-8")
        if self.path == "/v1/models":
            return self.proxy("GET", "/v1/models", b"")
        match = re.fullmatch(r"/jobs/(job_[0-9]{1,12})", self.path)
        if match:
            return self.proxy("GET", match.group(0), b"")
        self.send_bytes(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        if not self.local_request_allowed():
            return
        if self.path != "/v1/chat/completions":
            return self.send_bytes(b'{"error":"not found"}', 404, "application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_bytes(b'{"error":"invalid content length"}', 400,
                                   "application/json")
        if not 0 < length <= MAX_BODY:
            return self.send_bytes(b'{"error":"request body must be 1 byte to 1 MiB"}',
                                   413, "application/json")
        if self.headers.get("Transfer-Encoding"):
            return self.send_bytes(b'{"error":"transfer encoding is not supported"}',
                                   400, "application/json")
        if self.headers.get_content_type() != "application/json":
            return self.send_bytes(b'{"error":"application/json required"}',
                                   415, "application/json")
        try:
            body = self.rfile.read(length)
        except (TimeoutError, OSError):
            return self.send_bytes(b'{"error":"request body timed out"}', 408,
                                   "application/json")
        if len(body) != length:
            return self.send_bytes(b'{"error":"incomplete request body"}', 400,
                                   "application/json")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("body must be a JSON object")
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            return self.send_bytes(json.dumps({"error": str(exc)}).encode(),
                                   400, "application/json")
        return self.proxy("POST", "/v1/chat/completions", body)

    def proxy(self, method: str, path: str, body: bytes) -> None:
        request = Request(ROUTER + path, data=body or None, method=method,
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json"})
        try:
            with urlopen(request, timeout=1805) as response:
                result = response.read(MAX_RESPONSE + 1)
                status = response.status
                if len(result) > MAX_RESPONSE:
                    result, status = b'{"error":"router response exceeds 2 MiB"}', 502
        except HTTPError as exc:
            result, status = exc.read(MAX_RESPONSE + 1), exc.code
            if len(result) > MAX_RESPONSE:
                result, status = b'{"error":"router response exceeds 2 MiB"}', 502
        except (URLError, TimeoutError) as exc:
            result = json.dumps({"error": f"H0 router unavailable: {exc}"}).encode()
            status = 502
        self.send_bytes(result, status, "application/json")


if __name__ == "__main__":
    class LocalThreadingHTTPServer(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = MAX_CONCURRENT

        def process_request(self, request, client_address):
            if not _slots.acquire(blocking=False):
                try:
                    request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                except OSError:
                    pass
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, client_address)
            except Exception:
                _slots.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                _slots.release()

    server = LocalThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"NEXUS H0 UI: http://127.0.0.1:{PORT} (router: {ROUTER})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
