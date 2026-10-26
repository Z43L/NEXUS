from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

import worker2


class EngineUrlPolicyTests(unittest.TestCase):
    def test_plaintext_remote_engine_and_credential_urls_are_rejected(self):
        for value in (
            "http://192.168.1.20:11436",
            "http://host.docker.internal:11436",
            "http://user:secret@host.docker.internal:11436",
            "https://engine.example/private/path",
            "https://engine.example:11436?token=secret",
        ):
            with self.subTest(url=value), self.assertRaises(ValueError):
                worker2.validate_atenea_url(value)

    def test_loopback_local_host_and_verified_https_origins_are_allowed(self):
        self.assertEqual(
            worker2.validate_atenea_url("http://127.0.0.1:11436/"),
            "http://127.0.0.1:11436",
        )
        self.assertEqual(worker2.validate_atenea_url("https://host.docker.internal:11436"),
                         "https://host.docker.internal:11436")
        self.assertEqual(
            worker2.validate_atenea_url("https://engine.example:11436"),
            "https://engine.example:11436",
        )

    def test_http_compose_service_requires_an_exact_explicit_allowlist(self):
        with patch.dict(os.environ, {"NEXUS_H1_ALLOW_HTTP_SERVICE_NAME": "mock-atenea"}):
            self.assertEqual(
                worker2.validate_atenea_url("http://mock-atenea:11436"),
                "http://mock-atenea:11436",
            )
            with self.assertRaisesRegex(ValueError, "explicitly allowed"):
                worker2.validate_atenea_url("http://another-service:11436")

        with patch.dict(os.environ, {"NEXUS_H1_ALLOW_HTTP_SERVICE_NAME": "mock-atenea.invalid"}):
            with self.assertRaisesRegex(ValueError, "one DNS service label"):
                worker2.validate_atenea_url("http://mock-atenea:11436")

        with patch.dict(os.environ, {"NEXUS_H1_ALLOW_HTTP_SERVICE_NAME": "other-engine"}):
            with self.assertRaisesRegex(ValueError, "reserved for the private mock"):
                worker2.validate_atenea_url("http://other-engine:11436")

    def test_engine_redirect_is_not_followed_to_another_authority(self):
        reached_target = threading.Event()

        class TargetHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                reached_target.set()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"data":[]}')

            def log_message(self, *_args):
                pass

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_url = f"http://127.0.0.1:{target.server_port}/v1/models"

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", target_url)
                self.end_headers()

            def log_message(self, *_args):
                pass

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        threads = [threading.Thread(target=server.serve_forever, daemon=True)
                   for server in (target, redirect)]
        for thread in threads:
            thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                worker2.http_json(
                    f"http://127.0.0.1:{redirect.server_port}/v1/models", timeout=2
                )
            self.assertEqual(caught.exception.code, 302)
            self.assertFalse(reached_target.is_set())
        finally:
            for server in (redirect, target):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=2)

    def test_engine_requests_ignore_ambient_proxy_environment(self):
        class JsonHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"local-model"}]}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), JsonHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9",
                "NO_PROXY": "",
                "no_proxy": "",
            }):
                result = worker2.http_json(
                    f"http://127.0.0.1:{server.server_port}/v1/models", timeout=2
                )
            self.assertEqual(result["data"][0]["id"], "local-model")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_engine_requests_forward_service_bearer_and_remote_engine_requires_key_file(self):
        received = {}

        class JsonHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                received["authorization"] = self.headers.get("Authorization")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[]}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), JsonHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            worker2.http_json(f"http://127.0.0.1:{server.server_port}/v1/models",
                              timeout=2, headers={"Authorization": "Bearer " + "k" * 32})
            self.assertEqual(received["authorization"], "Bearer " + "k" * 32)
            with self.assertRaisesRegex(ValueError, "remote Atenhea requires an API key file"):
                worker2.Worker("http://127.0.0.1:18080", "https://engine.example:11436",
                               Path(tempfile.gettempdir()) / "nexus-worker-remote-no-key",
                               "wallet")
            with self.assertRaisesRegex(ValueError, "remote Atenhea requires an API key file"):
                worker2.Worker("http://127.0.0.1:18080", "https://host.docker.internal:11436",
                               Path(tempfile.gettempdir()) / "nexus-worker-host-gateway-no-key",
                               "wallet")
            with tempfile.TemporaryDirectory() as directory:
                key_path = Path(directory) / "atenea.key"
                key_path.write_text("s" * 32)
                key_path.chmod(0o600)
                worker = worker2.Worker(
                    "http://127.0.0.1:18080", "https://engine.example:11436",
                    Path(directory) / "node", "wallet", atenea_api_key_file=str(key_path),
                )
                self.assertEqual(worker._atenea_headers(), {"Authorization": "Bearer " + "s" * 32})
                fifo = Path(directory) / "atenea.fifo"
                os.mkfifo(fifo, 0o600)
                with self.assertRaisesRegex(ValueError, "permissions must be 0600"):
                    worker2.read_atenea_api_key(str(fifo))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_router_requests_ignore_ambient_proxy_environment(self):
        class JsonHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), JsonHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="nexus-router-proxy-") as tmp:
                with patch.object(worker2.nc, "load_or_create_node_key",
                                  return_value=(object(), "public", "node-test")), \
                     patch.object(worker2.nc, "sign_node_request", return_value={}), \
                     patch.dict(os.environ, {
                         "HTTP_PROXY": "http://127.0.0.1:9",
                         "HTTPS_PROXY": "http://127.0.0.1:9",
                         "ALL_PROXY": "http://127.0.0.1:9",
                         "NO_PROXY": "", "no_proxy": "",
                     }):
                    instance = worker2.Worker(
                        f"http://127.0.0.1:{server.server_port}",
                        "http://127.0.0.1:11436", Path(tmp), "wallet",
                    )
                    self.assertEqual(instance.router_json("/health"), {"ok": True})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
