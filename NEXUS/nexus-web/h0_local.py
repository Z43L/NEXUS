"""Tiny same-origin UI/proxy for the local NEXUS H0 gateway.

Run from any directory with ``python3 NEXUS/nexus-web/h0_local.py``.
The service binds to loopback and forwards only the H0 models/chat routes.
"""
from __future__ import annotations

import json
import os
import re
import threading
from http.cookies import SimpleCookie
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler

BASE = Path(__file__).resolve().parent
ROUTER = os.environ.get("NEXUS_H0_ROUTER_URL", "http://127.0.0.1:18080").rstrip("/")
API_URL = os.environ.get("NEXUS_H0_API_URL", "").rstrip("/")
ALLOW_HTTP_SERVICE_NAME = os.environ.get("NEXUS_H0_API_ALLOW_HTTP_SERVICE_NAME") == "1"
PORT = int(os.environ.get("NEXUS_H0_UI_PORT", "18081"))
PUBLIC_PORT = int(os.environ.get("NEXUS_H0_UI_PUBLIC_PORT", str(PORT)))
BIND_HOST = os.environ.get("NEXUS_H0_UI_BIND_HOST", "127.0.0.1")
ALLOWED_HOSTS = {item.strip().lower() for item in
                 os.environ.get("NEXUS_H0_UI_ALLOWED_HOSTS", "").split(",") if item.strip()}
ALLOWED_ORIGINS = {item.strip().rstrip("/") for item in
                   os.environ.get("NEXUS_H0_UI_ALLOWED_ORIGINS", "").split(",") if item.strip()}
SESSION_COOKIE = ("nexus_session" if os.environ.get("NEXUS_AUTH_COOKIE_SECURE", "1") == "0"
                  else "__Host-nexus_session")
MAX_BODY = 1_048_576
MAX_RESPONSE = 2_097_152
MAX_CONCURRENT = 8
REQUEST_TIMEOUT = 15
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)


def _loopback(host: str | None) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


if API_URL:
    _api = urlsplit(API_URL)
    if (_api.scheme not in {"http", "https"} or not _api.hostname or _api.username
            or _api.password or _api.path not in {"", "/"} or _api.query or _api.fragment
            or (_api.scheme == "http" and not _loopback(_api.hostname)
                and not (ALLOW_HTTP_SERVICE_NAME and _api.hostname == "api"))):
        raise RuntimeError(
            "NEXUS_H0_API_URL must be an HTTP(S) origin; HTTP is allowed only for loopback or explicitly enabled Compose API"
        )
    API_URL = API_URL.rstrip("/")
    API_TOKEN = os.environ.get("NEXUS_API_TOKEN", "")
    token_file = os.environ.get("NEXUS_API_TOKEN_FILE", "")
    if not API_TOKEN and token_file:
        try:
            API_TOKEN = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("configured API token file is unavailable") from exc
    if not API_TOKEN:
        raise RuntimeError("NEXUS_API_TOKEN or NEXUS_API_TOKEN_FILE is required in API mode")
else:
    API_TOKEN = ""
    _router = urlsplit(ROUTER)
    if _router.scheme != "http" or not _loopback(_router.hostname):
        raise RuntimeError("local H0 UI may proxy only to an HTTP loopback router")
if not 1 <= PORT <= 65535 or not 1 <= PUBLIC_PORT <= 65535:
    raise RuntimeError("UI ports must be between 1 and 65535")
if BIND_HOST not in {"127.0.0.1", "0.0.0.0", "::1"}:
    raise RuntimeError("NEXUS_H0_UI_BIND_HOST must be loopback or 0.0.0.0")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# The BFF carries the API credential and inference prompts. Never route them
# through ambient HTTP(S)_PROXY settings inherited from the host/container.
_opener = build_opener(ProxyHandler({}), _NoRedirect())


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT)

    def log_message(self, *_args):
        pass

    def local_request_allowed(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        allowed_hosts = ALLOWED_HOSTS or {f"127.0.0.1:{PUBLIC_PORT}", f"localhost:{PUBLIC_PORT}"}
        if host not in allowed_hosts:
            self.send_bytes(b'{"error":"invalid host"}', 403, "application/json")
            return False
        origin = self.headers.get("Origin")
        if self.command in {"POST", "PUT", "PATCH", "DELETE"} and self.headers.get("Cookie") and not origin:
            self.send_bytes(b'{"error":"origin required"}', 403, "application/json")
            return False
        if origin:
            if ALLOWED_ORIGINS:
                valid_origin = origin.rstrip("/") in ALLOWED_ORIGINS
            else:
                try:
                    parsed = urlsplit(origin)
                    valid_origin = (
                        parsed.scheme == "http"
                        and parsed.hostname in {"127.0.0.1", "localhost"}
                        and parsed.port == PUBLIC_PORT
                        and parsed.username is None and parsed.password is None
                        and not parsed.path and not parsed.query and not parsed.fragment
                    )
                except ValueError:
                    valid_origin = False
            if not valid_origin:
                self.send_bytes(b'{"error":"invalid origin"}', 403, "application/json")
                return False
        return True

    def send_bytes(self, body: bytes, status: int, content_type: str,
                   extra_headers: tuple[tuple[str, str], ...] = ()) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in extra_headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self.local_request_allowed():
            return
        if self.path == "/" or self.path == "/index.html":
            page = (BASE / "h0.html").read_bytes()
            return self.send_bytes(page, 200, "text/html; charset=utf-8")
        if self.path == "/auth/session":
            return self.proxy("GET", "/auth/session", b"")
        if self.path == "/v1/models":
            return self.proxy("GET", "/v1/models", b"")
        match = re.fullmatch(r"/jobs/(job_[0-9]{1,12})", self.path)
        if match:
            return self.proxy("GET", match.group(0), b"")
        self.send_bytes(b'{"error":"not found"}', 404, "application/json")

    def do_POST(self) -> None:
        if not self.local_request_allowed():
            return
        if self.path not in {"/v1/chat/completions", "/auth/login", "/auth/logout"}:
            return self.send_bytes(b'{"error":"not found"}', 404, "application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_bytes(b'{"error":"invalid content length"}', 400,
                                   "application/json")
        if self.headers.get("Transfer-Encoding"):
            return self.send_bytes(b'{"error":"transfer encoding is not supported"}',
                                   400, "application/json")
        if self.path == "/auth/logout" and length == 0:
            body = b""
        elif not 0 < length <= MAX_BODY:
            return self.send_bytes(b'{"error":"request body must be 1 byte to 1 MiB"}',
                                   413, "application/json")
        elif self.headers.get_content_type() != "application/json":
            return self.send_bytes(b'{"error":"application/json required"}',
                                   415, "application/json")
        else:
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
                if self.path == "/auth/login" and not all(
                        isinstance(payload.get(field), str) and payload[field]
                        for field in ("username", "password")):
                    raise ValueError("username and password are required")
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
                return self.send_bytes(json.dumps({"error": str(exc)}).encode(),
                                       400, "application/json")
        return self.proxy("POST", self.path, body)

    def proxy(self, method: str, path: str, body: bytes) -> None:
        if API_URL and not path.startswith("/auth/"):
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
            except Exception:
                cookies = SimpleCookie()
            if SESSION_COOKIE not in cookies:
                return self.send_bytes(b'{"detail":"Invalid or missing session"}', 401,
                                       "application/json")
        if method == "POST":
            # Inference can take as long as the Router's 30-minute deadline.
            # Keep the short header/body read timeout for incoming requests.
            self.connection.settimeout(1805)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        upstream = API_URL if API_URL else ROUTER
        if API_URL:
            headers["Authorization"] = f"Bearer {API_TOKEN}"
            # The API's service credential identifies this BFF. The browser
            # cookie identifies the user session; neither replaces the other.
            cookie = self.headers.get("Cookie")
            if cookie:
                headers["Cookie"] = cookie
            origin = self.headers.get("Origin")
            if origin:
                headers["Origin"] = origin
        request = Request(upstream + path, data=body or None, method=method, headers=headers)
        try:
            with _opener.open(request, timeout=1805) as response:
                result = response.read(MAX_RESPONSE + 1)
                status = response.status
                set_cookies = response.headers.get_all("Set-Cookie", [])
                if len(result) > MAX_RESPONSE:
                    result, status = b'{"error":"router response exceeds 2 MiB"}', 502
        except HTTPError as exc:
            result, status = exc.read(MAX_RESPONSE + 1), exc.code
            set_cookies = exc.headers.get_all("Set-Cookie", [])
            if len(result) > MAX_RESPONSE:
                result, status = b'{"error":"router response exceeds 2 MiB"}', 502
        except (URLError, TimeoutError) as exc:
            result = json.dumps({"error": "H0 upstream unavailable"}).encode()
            status = 502
            set_cookies = []
        self.send_bytes(result, status, "application/json",
                        tuple(("Set-Cookie", value) for value in set_cookies))


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = MAX_CONCURRENT

    def process_request(self, request, client_address):
        if not _slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n"
                    b"Content-Length: 0\r\n\r\n"
                )
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


def serve() -> None:
    server = LocalThreadingHTTPServer((BIND_HOST, PORT), Handler)
    print(f"NEXUS H0 UI listening on {BIND_HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
