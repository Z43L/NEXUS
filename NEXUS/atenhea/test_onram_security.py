import ssl
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from onram import create_listener_tls_context, load_api_key_file


class OnramListenerSecurityTests(unittest.TestCase):
    def test_loopback_can_remain_plain_http(self):
        self.assertIsNone(create_listener_tls_context("127.0.0.1", None, None, None))
        self.assertIsNone(create_listener_tls_context("localhost", "x" * 32, None, None))

    def test_remote_listener_requires_api_key_and_tls_pair(self):
        with self.assertRaisesRegex(ValueError, "requires an API key"):
            create_listener_tls_context("0.0.0.0", None, None, None)
        with self.assertRaisesRegex(ValueError, "requires TLS"):
            create_listener_tls_context("0.0.0.0", "x" * 32, None, None)
        with self.assertRaisesRegex(ValueError, "configured together"):
            create_listener_tls_context("0.0.0.0", "x" * 32, Path("cert.pem"), None)
        with self.assertRaisesRegex(ValueError, "requires an API key"):
            create_listener_tls_context("0.0.0.0", "short", Path("cert.pem"), Path("key.pem"))

    def test_remote_listener_loads_tls_with_modern_minimum_and_private_key(self):
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "server.crt"
            key = Path(directory) / "server.key"
            cert.write_text("certificate")
            key.write_text("private key")
            key.chmod(0o600)
            context = Mock()
            with patch("onram.ssl.SSLContext", return_value=context) as factory:
                result = create_listener_tls_context("192.0.2.10", "x" * 32, cert, key)
            self.assertIs(result, context)
            factory.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)
            self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
            context.load_cert_chain.assert_called_once_with(certfile=str(cert), keyfile=str(key))

    def test_api_key_file_must_be_private_and_long_enough(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "api.key"
            path.write_text("k" * 32)
            path.chmod(0o600)
            self.assertEqual(load_api_key_file(path), "k" * 32)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private file"):
                load_api_key_file(path)
            path.chmod(0o600)
            path.write_text("short")
            with self.assertRaisesRegex(ValueError, "at least 32"):
                load_api_key_file(path)
            fifo = Path(directory) / "api.fifo"
            os.mkfifo(fifo, 0o600)
            with self.assertRaisesRegex(ValueError, "regular private file"):
                load_api_key_file(fifo)


if __name__ == "__main__":
    unittest.main()
