"""Focused black-box tests for the H0 browser-session BFF routes."""
from __future__ import annotations

import http.server
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class _ApiHandler(http.server.BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *_args):
        pass

    def _respond(self):
        body = json.dumps({"authenticated": self.path == "/auth/session"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.path == "/auth/login":
            self.send_header("Set-Cookie", "nexus_session=opaque; Path=/; HttpOnly; SameSite=Lax")
            self.send_header("Set-Cookie", "nexus_aux=keep; Path=/; SameSite=Strict")
        if self.path == "/auth/logout":
            self.send_header("Set-Cookie", "nexus_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.seen.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "cookie": self.headers.get("Cookie"),
            "origin": self.headers.get("Origin"),
            "body": self.rfile.read(length),
        })
        self._respond()

    do_GET = _record
    do_POST = _record


class AuthBffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ApiHandler.seen = []
        cls.api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
        threading.Thread(target=cls.api.serve_forever, daemon=True).start()
        os.environ["NEXUS_H0_API_URL"] = f"http://127.0.0.1:{cls.api.server_port}"
        os.environ["NEXUS_API_TOKEN"] = "test-only-service-token"
        os.environ["NEXUS_H0_UI_BIND_HOST"] = "127.0.0.1"
        os.environ["NEXUS_H0_UI_PORT"] = "18081"
        os.environ["NEXUS_AUTH_COOKIE_SECURE"] = "0"
        spec = importlib.util.spec_from_file_location(
            "nexus_h0_auth_bff_under_test", Path(__file__).with_name("h0_local.py"))
        assert spec and spec.loader
        cls.bff_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.bff_module)
        cls.bff = cls.bff_module.LocalThreadingHTTPServer(("127.0.0.1", 0),
                                                           cls.bff_module.Handler)
        cls.bff_module.PUBLIC_PORT = cls.bff.server_port
        cls.base = f"http://127.0.0.1:{cls.bff.server_port}"
        cls.origin = cls.base
        threading.Thread(target=cls.bff.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.bff.shutdown()
        cls.api.shutdown()
        cls.bff.server_close()
        cls.api.server_close()
        for name in ("NEXUS_H0_API_URL", "NEXUS_API_TOKEN", "NEXUS_H0_UI_BIND_HOST",
                     "NEXUS_H0_UI_PORT", "NEXUS_AUTH_COOKIE_SECURE"):
            os.environ.pop(name, None)

    def _request(self, path, method="GET", body=None, headers=None):
        all_headers = {"Host": f"127.0.0.1:{self.bff.server_port}",
                       "Origin": self.origin}
        all_headers.update(headers or {})
        request = Request(self.base + path, data=body, method=method, headers=all_headers)
        return urlopen(request, timeout=3)

    def test_session_forwards_service_auth_user_cookie_and_origin(self):
        with self._request("/auth/session", headers={"Cookie": "nexus_session=opaque"}) as response:
            self.assertEqual(response.status, 200)
        seen = _ApiHandler.seen[-1]
        self.assertEqual(seen["path"], "/auth/session")
        self.assertEqual(seen["authorization"], "Bearer test-only-service-token")
        self.assertEqual(seen["cookie"], "nexus_session=opaque")
        self.assertEqual(seen["origin"], self.origin)

    def test_login_forwards_credentials_and_all_set_cookie_headers(self):
        body = json.dumps({"username": "alice", "password": "secret"}).encode()
        with self._request("/auth/login", "POST", body, {
                "Content-Type": "application/json"}) as response:
            self.assertEqual(response.status, 200)
            cookies = response.headers.get_all("Set-Cookie")
        self.assertEqual(cookies, [
            "nexus_session=opaque; Path=/; HttpOnly; SameSite=Lax",
            "nexus_aux=keep; Path=/; SameSite=Strict",
        ])
        seen = _ApiHandler.seen[-1]
        self.assertEqual(seen["authorization"], "Bearer test-only-service-token")
        self.assertEqual(json.loads(seen["body"]), {"username": "alice", "password": "secret"})
        self.assertEqual(seen["origin"], self.origin)

    def test_logout_forwards_cookie_and_expiration_cookie(self):
        with self._request("/auth/logout", "POST", b"", {
                "Cookie": "nexus_session=opaque"}) as response:
            self.assertEqual(response.status, 200)
            cookies = response.headers.get_all("Set-Cookie")
        self.assertEqual(cookies, [
            "nexus_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax",
        ])
        seen = _ApiHandler.seen[-1]
        self.assertEqual(seen["path"], "/auth/logout")
        self.assertEqual(seen["authorization"], "Bearer test-only-service-token")
        self.assertEqual(seen["cookie"], "nexus_session=opaque")

    def test_mutation_rejects_foreign_origin_before_upstream(self):
        before = len(_ApiHandler.seen)
        with self.assertRaises(HTTPError) as error:
            self._request("/auth/logout", "POST", b"", {
                "Origin": "https://attacker.example",
                "Cookie": "nexus_session=opaque",
            })
        self.assertEqual(error.exception.code, 403)
        error.exception.close()
        self.assertEqual(len(_ApiHandler.seen), before)

    def test_product_route_rejects_missing_browser_session(self):
        before = len(_ApiHandler.seen)
        with self.assertRaises(HTTPError) as error:
            self._request("/v1/models")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.assertEqual(len(_ApiHandler.seen), before)


if __name__ == "__main__":
    unittest.main()
