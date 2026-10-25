"""Regression for worker capacity while synchronous chat requests wait.

Run: python3 test_router_concurrency.py
"""
from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import nexus_common as nc  # noqa: E402


def request_json(url: str, method="GET", payload=None, headers=None, timeout=5):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def main() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    root = Path(tempfile.mkdtemp(prefix="nexus-router-concurrency-"))
    base_url = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, str(BASE / "router.py"), "--port", str(port),
                             "--dir", str(root), "--max-threads", "4"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    chat_results: list[tuple[int, dict] | Exception] = []
    chat_threads: list[threading.Thread] = []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                status, _ = request_json(base_url + "/health")
                if status == 200:
                    break
            except (OSError, TimeoutError):
                time.sleep(0.05)
        else:
            raise AssertionError("Router did not start")

        priv, pub_pem, node_id = nc.load_or_create_node_key(root / "node")
        register_path = "/nodes/register"
        register_body = {"node_id": node_id, "pubkey_pem": pub_pem,
                         "models": ["test-model"], "nram": [], "region": "test"}
        status, registration = request_json(base_url + register_path, "POST", register_body, {
            **nc.sign_node_request(priv, "POST", register_path, register_body),
            "X-Nexus-Node-ID": node_id,
        })
        assert status == 200, registration

        def chat_call():
            try:
                chat_results.append(request_json(
                    base_url + "/v1/chat/completions", "POST",
                    {"model": "test-model", "messages": [{"role": "user", "content": "wait"}],
                     "timeout_s": 30}, timeout=35))
            except Exception as exc:  # surfaced below as an assertion
                chat_results.append(exc)

        # At four total handlers, the Router reserves one slot for node traffic.
        for _ in range(3):
            thread = threading.Thread(target=chat_call, daemon=True)
            chat_threads.append(thread)
            thread.start()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with sqlite3.connect(root / "nexus_h0.db") as conn:
                queued = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
            if queued == 3:
                break
            time.sleep(0.05)
        assert queued == 3, f"expected 3 waiting chat jobs, got {queued}"

        # Extra synchronous chats are rejected promptly instead of consuming
        # the worker-reserved handler slot.
        busy_status, busy = request_json(
            base_url + "/v1/chat/completions", "POST",
            {"model": "test-model", "messages": [{"role": "user", "content": "busy"}],
             "timeout_s": 30})
        assert busy_status == 503 and busy.get("error", {}).get("type") == "server_busy", busy

        poll_path = f"/jobs/next?node_id={node_id}"
        poll_status, dispatched = request_json(base_url + poll_path, headers={
            **nc.sign_node_request(priv, "GET", poll_path, {}),
            "X-Nexus-Node-ID": node_id,
        })
        assert poll_status == 200 and dispatched.get("job"), dispatched
        job = dispatched["job"]
        result_path = f"/jobs/{job['job_id']}/result"
        result_body = {"status": "rejected", "error": "concurrency regression probe",
                       "dispatch_jwt": job["dispatch_jwt"]}
        result_status, result = request_json(base_url + result_path, "POST", result_body, {
            **nc.sign_node_request(priv, "POST", result_path, result_body),
            "X-Nexus-Node-ID": node_id,
        })
        assert result_status == 200 and result.get("status") == "rejected", result

        # The completed worker result releases a waiting chat; stop the others
        # early so the regression does not wait for their 30-second deadlines.
        with sqlite3.connect(root / "nexus_h0.db") as conn:
            conn.execute("UPDATE jobs SET status='failed', error='test cleanup' WHERE status='queued'")
        for thread in chat_threads:
            thread.join(timeout=3)
        assert len(chat_results) == 3 and all(not isinstance(r, Exception) for r in chat_results), chat_results
        assert any(isinstance(r, tuple) and r[0] == 502 for r in chat_results), chat_results
        print("worker polling/result succeeds with chat concurrency at reserved limit: PASS")
        print("additional synchronous chat receives 503 Retry-After instead of taking worker capacity: PASS")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
