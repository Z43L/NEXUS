"""Tiny JSON-over-HTTP helpers (stdlib only): threaded server + keep-alive client.

Testnet transport: plain HTTP, no TLS, no transport authentication. Put it behind
a trusted network / reverse proxy. Receipts are signed at the application layer.
"""
from __future__ import annotations

import http.client
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, Optional, Tuple

Handler = Callable[[str, str, Dict, Optional[Dict], Dict], Tuple[int, Dict]]
# handler(method, path, query, body, headers) -> (status, json_obj)


class JsonServer:
    def __init__(self, host: str, port: int, handler: Handler):
        outer = handler
        outer_srv = self
        self.conns, self.conn_lock = set(), threading.Lock()

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # quiet
                pass

            def setup(self):
                super().setup()
                with outer_srv.conn_lock:
                    outer_srv.conns.add(self.connection)

            def finish(self):
                try:
                    super().finish()
                finally:
                    with outer_srv.conn_lock:
                        outer_srv.conns.discard(self.connection)

            def _do(self, method):
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                n = int(self.headers.get("Content-Length") or 0)
                if n > 32 * 1024 * 1024:
                    return self._send(413, {"error": "too large"})
                raw = self.rfile.read(n) if n else b""
                body = None
                if raw:
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        return self._send(400, {"error": "invalid json"})
                try:
                    code, obj = outer(method, u.path, q, body, dict(self.headers))
                except Exception as e:  # noqa
                    code, obj = 500, {"error": "internal: %s" % type(e).__name__}
                self._send(code, obj)

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self): self._do("GET")
            def do_POST(self): self._do("POST")

        class S(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True
            request_queue_size = 64

        self.httpd = S((host, port), H)
        self.host, self.port = host, self.httpd.server_address[1]
        self._t = None

    def start(self):
        self._t = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1},
                                   daemon=True)
        self._t.start()
        return self

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        with self.conn_lock:  # drop keep-alive connections too (a dead node must look dead)
            for c in list(self.conns):
                try:
                    c.shutdown(2); c.close()
                except OSError:
                    pass


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__("HTTP %s: %s" % (status, body))
        self.status, self.body = status, body


_tls = threading.local()


def call(url: str, path: str, body: Optional[Dict] = None, *, method: str = None,
         timeout: float = 5.0, headers: Dict = None) -> Dict:
    """JSON request with per-thread keep-alive connection reuse. Raises on any failure."""
    method = method or ("POST" if body is not None else "GET")
    u = urllib.parse.urlparse(url)
    key = (u.hostname, u.port)
    conns = getattr(_tls, "conns", None)
    if conns is None:
        conns = _tls.conns = {}
    data = json.dumps(body).encode() if body is not None else None
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    for attempt in (0, 1):
        c = conns.get(key)
        fresh = c is None
        if fresh:
            c = conns[key] = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        c.timeout = timeout
        if c.sock is not None:
            c.sock.settimeout(timeout)
        try:
            c.request(method, path, body=data, headers=hdrs)
            r = c.getresponse()
            raw = r.read()
            break
        except (http.client.HTTPException, OSError):
            c.close(); conns.pop(key, None)
            if fresh or attempt == 1:
                raise
    try:
        obj = json.loads(raw) if raw else {}
    except ValueError:
        obj = {"raw": raw[:200].decode("latin1")}
    if r.status >= 400:
        raise HttpError(r.status, obj)
    return obj
