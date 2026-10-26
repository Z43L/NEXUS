from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import container_healthcheck as healthcheck


class WorkerHealthcheckTests(unittest.TestCase):
    def _run(self, ready_file: Path,
             atenea_url: str = "https://host.docker.internal:11436") -> int:
        key_file = ready_file.parent / "atenea_api.key"
        key_file.write_text("k" * 32)
        key_file.chmod(0o600)
        responses = {
            "https://router/ready": {"ok": True},
            f"{atenea_url}/v1/models": {"data": [{"id": "athenea-e2b"}]},
        }
        received_headers = []
        def fake_get_json(url, context=None, headers=None):
            received_headers.append(headers or {})
            return responses[url]
        with (
            patch.object(sys, "argv", ["container_healthcheck.py", "worker"]),
            patch.dict(os.environ, {
                "ROUTER_URL": "https://router",
                "ATENHEA_URL": atenea_url,
                "ATENHEA_API_KEY_FILE": str(key_file),
                "NEXUS_WORKER_READY_FILE": str(ready_file),
            }, clear=False),
            patch.object(healthcheck.ssl, "create_default_context"),
            patch.object(healthcheck, "get_json", side_effect=fake_get_json),
        ):
            result = healthcheck.main()
        if result == 0:
            self.assertEqual(received_headers[-1], {"Authorization": "Bearer " + "k" * 32})
        return result

    def test_worker_is_not_ready_until_registration_marker_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._run(Path(tmp) / ".worker-ready"), 1)

    def test_worker_is_ready_with_recent_registration_and_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready_file = Path(tmp) / ".worker-ready"
            ready_file.touch()
            self.assertEqual(self._run(ready_file), 0)

    def test_worker_is_unhealthy_when_heartbeat_marker_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready_file = Path(tmp) / ".worker-ready"
            ready_file.touch()
            old_time = ready_file.stat().st_mtime - 60
            os.utime(ready_file, (old_time, old_time))
            self.assertEqual(self._run(ready_file), 1)

    def test_worker_is_unhealthy_for_plaintext_remote_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready_file = Path(tmp) / ".worker-ready"
            ready_file.touch()
            self.assertEqual(self._run(ready_file, "http://192.168.1.20:11436"), 1)

    def test_worker_is_unhealthy_for_plaintext_docker_host_gateway(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready_file = Path(tmp) / ".worker-ready"
            ready_file.touch()
            self.assertEqual(self._run(ready_file, "http://host.docker.internal:11436"), 1)

if __name__ == "__main__":
    unittest.main()
