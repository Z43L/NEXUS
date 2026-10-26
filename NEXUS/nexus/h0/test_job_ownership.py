"""Tests for Router job-result isolation between API clients."""

import unittest
import json
import sqlite3
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import router


class JobOwnershipTests(unittest.TestCase):
    def test_owner_can_read_but_other_client_cannot(self):
        self.assertTrue(router.job_access_allowed("client-a", "client-a", False))
        self.assertFalse(router.job_access_allowed("client-a", "client-b", False))
        self.assertFalse(router.job_access_allowed("client-a", None, False))

    def test_admin_can_read_any_job(self):
        self.assertTrue(router.job_access_allowed("client-a", "operator", True))
        self.assertTrue(router.job_access_allowed(None, "operator", True))

    def test_unowned_legacy_jobs_are_not_exposed_to_api_clients(self):
        self.assertTrue(router.job_access_allowed(None, None, False))
        self.assertFalse(router.job_access_allowed(None, "client-a", False))

    def test_http_job_read_isolation_hides_output_and_receipt(self):
        with tempfile.TemporaryDirectory(prefix="nexus-job-owner-") as folder:
            old_path = router._db_path
            old_network_mode = router._network_mode
            old_token = router._client_api_token
            router._db_path = Path(folder) / "router.db"
            router._network_mode = True
            router._client_api_token = "router-test-token"
            router.init_db()
            server = ThreadingHTTPServer(("127.0.0.1", 0), router.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                create = Request(
                    base + "/jobs",
                    data=json.dumps({
                        "model": "test-model",
                        "messages": [{"role": "user", "content": "private prompt"}],
                    }).encode(),
                    headers={
                        "Authorization": "Bearer router-test-token",
                        "X-Nexus-Client-ID": "client-a",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urlopen(create, timeout=3) as response:
                    job_id = json.loads(response.read())["job_id"]
                with router.db() as conn:
                    conn.execute(
                        "UPDATE jobs SET status='done', node_id='node-test', "
                        "result_text='private answer' WHERE job_id=?", (job_id,)
                    )
                    conn.execute(
                        "INSERT INTO receipts(job_id, node_id, receipt, verified) "
                        "VALUES(?,?,?,1)",
                        (job_id, "node-test", json.dumps({"marker": "private-receipt"})),
                    )

                def read_job(client_id, admin=False):
                    headers = {
                        "Authorization": "Bearer router-test-token",
                        "X-Nexus-Client-ID": client_id,
                    }
                    if admin:
                        headers["X-Nexus-Client-Admin"] = "1"
                    request = Request(base + f"/jobs/{job_id}", headers=headers)
                    try:
                        with urlopen(request, timeout=3) as response:
                            return response.status, json.loads(response.read())
                    except HTTPError as exc:
                        return exc.code, json.loads(exc.read())

                owner_status, owner_data = read_job("client-a")
                self.assertEqual(owner_status, 200)
                self.assertEqual(owner_data["output_text"], "private answer")
                self.assertEqual(owner_data["receipt"]["marker"], "private-receipt")

                other_status, other_data = read_job("client-b")
                self.assertEqual(other_status, 404)
                self.assertNotIn("private answer", json.dumps(other_data))
                self.assertNotIn("private-receipt", json.dumps(other_data))

                admin_status, admin_data = read_job("operator", admin=True)
                self.assertEqual(admin_status, 200)
                self.assertEqual(admin_data["receipt"]["marker"], "private-receipt")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                router._db_path = old_path
                router._network_mode = old_network_mode
                router._client_api_token = old_token


if __name__ == "__main__":
    unittest.main()
