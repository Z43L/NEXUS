"""Regression tests for the local API facade's authentication and quotas."""

import asyncio
import datetime as dt
import ipaddress
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.responses import Response

from nexus.api.core import api_server


class FakeRequest:
    def __init__(self, path="/v1/chat/completions", method="POST", headers=None,
                 host="127.0.0.1"):
        self.url = SimpleNamespace(path=path)
        self.method = method
        self.headers = {key.lower(): value for key, value in (headers or {}).items()}
        self.client = SimpleNamespace(host=host)


class ApiSecurityTests(unittest.TestCase):
    def setUp(self):
        api_server._rate_buckets.clear()

    def test_auth_accepts_bearer_and_api_key_and_rejects_bad_token(self):
        request = FakeRequest(headers={"Authorization": "Bearer local-secret"})
        with patch.dict(os.environ, {"NEXUS_API_TOKEN": "local-secret"}):
            api_server._enforce_client_auth(request)
            with self.assertRaises(api_server.HTTPException) as caught:
                api_server._enforce_client_auth(FakeRequest(headers={"Authorization": "Bearer wrong"}))
            self.assertEqual(caught.exception.status_code, 401)
            api_server._enforce_client_auth(FakeRequest(headers={"X-API-Key": "local-secret"}))

    def test_auth_fails_closed_without_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(api_server.HTTPException) as caught:
                api_server._enforce_client_auth(FakeRequest())
            self.assertEqual(caught.exception.status_code, 503)

    def test_router_url_policy_accepts_loopback_http_and_https_only(self):
        for url in ("http://127.0.0.1:18080", "http://localhost:18080",
                    "https://router.internal:18080"):
            self.assertEqual(api_server._validate_router_url(url), url)
        for url in ("http://router.internal:18080", "http://user:secret@127.0.0.1:18080",
                    "https://router.internal/path", "https://router.internal:bad"):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                api_server._validate_router_url(url)

    def test_request_safety_limits_declared_and_streamed_body_sizes(self):
        async def run_request(headers, chunks):
            called = []
            sent = []

            async def app(scope, receive, send):
                called.append(True)
                await receive()
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

            async def receive():
                return chunks.pop(0)

            async def send(message):
                sent.append(message)

            middleware = api_server.RequestSafetyMiddleware(app, max_body_bytes=4)
            scope = {"type": "http", "method": "POST", "path": "/v1/chat/completions",
                     "headers": headers + [(b"x-api-key", b"test-token")]}
            await middleware(scope, receive, send)
            return called, sent

        with patch.dict(os.environ, {"NEXUS_API_TOKEN": "test-token"}):
            declared, sent = asyncio.run(run_request(
                [(b"content-length", b"5")],
                [{"type": "http.request", "body": b"12345", "more_body": False}],
            ))
        self.assertFalse(declared)
        self.assertEqual(sent[0]["status"], 413)
        with patch.dict(os.environ, {"NEXUS_API_TOKEN": "test-token"}):
            streamed, sent = asyncio.run(run_request(
                [], [{"type": "http.request", "body": b"12345", "more_body": False}],
            ))
        self.assertTrue(streamed)
        self.assertEqual(sent[0]["status"], 413)

    def test_request_safety_rejects_excess_inflight_inferences(self):
        called = []

        async def app(_scope, _receive, _send):
            called.append(True)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message):
            pass

        middleware = api_server.RequestSafetyMiddleware(app, max_inflight_inferences=1)
        self.assertTrue(middleware.inference_slots.acquire(blocking=False))
        try:
            with patch.dict(os.environ, {"NEXUS_API_TOKEN": "test-token"}):
                asyncio.run(middleware(
                    {"type": "http", "method": "POST", "path": "/v1/chat/completions",
                     "headers": [(b"x-api-key", b"test-token")]}, receive, send,
                ))
        finally:
            middleware.inference_slots.release()
        self.assertFalse(called)

    def test_file_backed_client_and_service_tokens_are_read(self):
        with tempfile.TemporaryDirectory() as directory:
            api_token = Path(directory) / "api.token"
            router_token = Path(directory) / "router.token"
            api_token.write_text("api-secret\n", encoding="utf-8")
            router_token.write_text("service-secret\n", encoding="utf-8")
            with patch.dict(os.environ, {
                "NEXUS_API_TOKEN_FILE": str(api_token),
                "NEXUS_H0_CLIENT_TOKEN_FILE": str(router_token),
            }, clear=True):
                api_server._enforce_client_auth(FakeRequest(headers={"X-API-Key": "api-secret"}))
                self.assertEqual(api_server._upstream_auth(), "service-secret")

    def test_health_responses_do_not_disclose_router_url(self):
        async def invoke():
            return await api_server.health_check(), await api_server.readiness_check()

        with patch.object(api_server, "_gateway_ready", return_value=True), patch.dict(
            os.environ, {"NEXUS_API_TOKEN": "test-client-token"}
        ):
            health, ready = asyncio.run(invoke())
        for response in (health, ready):
            self.assertNotIn("gateway_url", response.data)
            self.assertNotIn(api_server.H0_ROUTER_URL, json.dumps(response.model_dump(), default=str))

    def test_upstream_redirect_is_rejected_without_following_it(self):
        requests = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                self.send_response(302)
                self.send_header("Location", "/steal")
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original = api_server.H0_ROUTER_URL
        try:
            api_server.H0_ROUTER_URL = f"http://127.0.0.1:{server.server_port}"
            with patch.dict(os.environ, {"NEXUS_H0_CLIENT_TOKEN": "service-only-token"}):
                with self.assertRaises(api_server.HTTPException) as caught:
                    api_server._get_gateway("/v1/models")
                self.assertEqual(caught.exception.status_code, 502)
                self.assertEqual(requests, [("/v1/models", "Bearer service-only-token")])
        finally:
            api_server.H0_ROUTER_URL = original
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_upstream_https_uses_pinned_ca_and_service_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                                      - dt.timedelta(minutes=1))
                    .not_valid_after(dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                                     + dt.timedelta(days=1))
                    .add_extension(x509.SubjectAlternativeName([
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))
                    ]), critical=False)
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            cert_path, key_path = root / "router.crt", root / "router.key"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
            seen = []

            class JsonHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    seen.append(self.headers.get("Authorization"))
                    result = ({"ok": True} if self.path == "/ready" else
                              {"data": [{"id": "athenea-e2b"}]})
                    body = json.dumps(result).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)

                def log_message(self, *_args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), JsonHandler)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(certfile=cert_path, keyfile=key_path)
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            original = api_server.H0_ROUTER_URL
            try:
                api_server.H0_ROUTER_URL = f"https://127.0.0.1:{server.server_port}"
                with patch.dict(os.environ, {
                    "NEXUS_H0_ROUTER_CA_FILE": str(cert_path),
                    "NEXUS_H0_CLIENT_TOKEN": "service-only-token",
                    "NEXUS_API_TOKEN": "api-client-token",
                }, clear=True):
                    api_server._tls_context.cache_clear()
                    self.assertTrue(api_server._gateway_ready())
                    result = api_server._get_gateway("/v1/models")
                    self.assertEqual(result["data"][0]["id"], "athenea-e2b")
                    self.assertEqual(seen, [None, "Bearer service-only-token"])
                    with patch.dict(os.environ, {
                        "NEXUS_H0_ROUTER_CA_FILE": str(root / "missing-ca.crt"),
                    }):
                        api_server._tls_context.cache_clear()
                        self.assertFalse(api_server._gateway_ready())
                        with self.assertRaises(api_server.HTTPException) as caught:
                            api_server._get_gateway("/v1/models")
                        self.assertEqual(caught.exception.status_code, 502)
                        self.assertEqual(len(seen), 2)
            finally:
                api_server._tls_context.cache_clear()
                api_server.H0_ROUTER_URL = original
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_upstream_uses_only_server_credential(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(api_server._upstream_auth())
        with patch.dict(os.environ, {"NEXUS_H0_CLIENT_TOKEN": "router-token"}):
            self.assertEqual(api_server._upstream_auth(), "router-token")
        with patch.object(api_server, "H0_ROUTER_URL", "https://router.internal"):
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(api_server.HTTPException) as caught:
                    api_server._upstream_auth()
                self.assertEqual(caught.exception.status_code, 503)

    def test_rate_limit_allows_exact_quota_then_rejects_and_isolates_tokens(self):
        request = FakeRequest(headers={"Authorization": "Bearer token-a"})
        with patch.dict(os.environ, {
            "NEXUS_API_TOKEN": "token-a",
            "NEXUS_API_RATE_LIMIT_PER_MINUTE": "2",
        }):
            first = api_server._consume_rate_limit(request)
            second = api_server._consume_rate_limit(request)
            third = api_server._consume_rate_limit(request)
            other = api_server._consume_rate_limit(
                FakeRequest(headers={"Authorization": "Bearer token-b"})
            )
        self.assertTrue(first[3])
        self.assertTrue(second[3])
        self.assertFalse(third[3])
        self.assertTrue(other[3])
        self.assertEqual(second[1], 0)

    def test_middleware_returns_auth_and_quota_statuses_with_retry_headers(self):
        async def invoke():
            request = FakeRequest(headers={"Authorization": "Bearer token-a"})

            async def next_response(_request):
                return Response("ok", status_code=200)

            with patch.dict(os.environ, {
                "NEXUS_API_TOKEN": "token-a",
                "NEXUS_API_RATE_LIMIT_PER_MINUTE": "1",
            }):
                permitted = await api_server.local_api_controls(request, next_response)
                limited = await api_server.local_api_controls(request, next_response)
            return permitted, limited

        permitted, limited = asyncio.run(invoke())
        self.assertEqual(permitted.status_code, 200)
        self.assertEqual(permitted.headers["x-ratelimit-remaining"], "0")
        self.assertEqual(limited.status_code, 429)
        self.assertIn("retry-after", limited.headers)

    def test_gateway_error_handler_preserves_router_error_envelope(self):
        async def invoke():
            return await api_server.preserve_gateway_error(
                None,
                api_server.HTTPException(
                    status_code=504,
                    detail={"error": {
                        "type": "job_timeout", "job_id": "job_123",
                        "message": "still pending",
                    }},
                ),
            )

        response = asyncio.run(invoke())
        self.assertEqual(response.status_code, 504)
        self.assertEqual(
            json.loads(response.body),
            {"error": {
                "type": "job_timeout", "job_id": "job_123",
                "message": "still pending",
            }},
        )

    def test_timeout_parser_rejects_non_integral_numbers_and_booleans(self):
        for value in (1.5, True, None, "not-a-number"):
            with self.subTest(value=value), self.assertRaises(api_server.HTTPException) as caught:
                api_server._bounded_timeout(value, "timeout_s")
            self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(api_server._bounded_timeout("1801", "timeout_s"), 1800)


if __name__ == "__main__":
    unittest.main()
