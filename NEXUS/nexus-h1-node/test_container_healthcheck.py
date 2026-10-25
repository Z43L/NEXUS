from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import container_healthcheck as healthcheck


class WorkerHealthcheckTests(unittest.TestCase):
    def _run(self, ready_file: Path) -> int:
        responses = {
            "https://router/ready": {"ok": True},
            "http://engine/v1/models": {"data": [{"id": "athenea-e2b"}]},
        }
        with (
            patch.object(sys, "argv", ["container_healthcheck.py", "worker"]),
            patch.dict(os.environ, {
                "ROUTER_URL": "https://router",
                "ATENHEA_URL": "http://engine",
                "NEXUS_WORKER_READY_FILE": str(ready_file),
            }, clear=False),
            patch.object(healthcheck.ssl, "create_default_context"),
            patch.object(healthcheck, "get_json", side_effect=lambda url, _context=None: responses[url]),
        ):
            return healthcheck.main()

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

if __name__ == "__main__":
    unittest.main()
