"""Disconnect resilience (WS-C): a link cut during a batch must not lose or duplicate work.

Runs on localhost with a real Router (in-process), the real H1 worker loop
(worker2.Worker.serve_forever) and a mock engine. A TCP proxy in front of the
Router simulates the network cut.

Scenario 1: the link is cut while a job's result is in flight and stays down for
OUTAGE_S seconds. The batch completes, and every job has exactly one accepted
receipt (no duplicates, no second dispatch).

Scenario 2: a node takes a job and loses its link for good. The Router requeues
the job after the heartbeat TTL, another node completes it, and the late result
from the lost node is refused.

OUTAGE_S defaults to 4 s and stands in for the ~60 s cut. Set
NEXUS_TEST_OUTAGE_S=60 for a full-length run.
Run: python3 test_disconnect_requeue.py   (exit 0 = pass)
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
H1_DIR = BASE.parent.parent / "nexus-h1-node"
sys.path.insert(0, str(BASE))
sys.path.append(str(H1_DIR))
import nexus_common as nc  # noqa: E402  (h0 copy wins, as in test_secure_remote)
import router  # noqa: E402
import worker2  # noqa: E402

OUTAGE_S = float(os.environ.get("NEXUS_TEST_OUTAGE_S", "4"))
HEARTBEAT_TTL_S = 2
ENGINE_LATENCY_S = 0.5
JOBS = 10
TIMEOUT_S = 120
ENGINE_URL = "http://127.0.0.1:11436"  # validated only; scenario 2 never calls it


class Proxy:
    """TCP relay in front of the Router. cut() drops live connections and refuses new ones."""

    def __init__(self, target_port: int):
        self.target_port = target_port
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(64)
        self.port = self.listener.getsockname()[1]
        self.down = False
        self.lock = threading.Lock()
        self.live: set[socket.socket] = set()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self) -> None:
        while True:
            client, _ = self.listener.accept()
            with self.lock:
                if self.down:
                    client.close()
                    continue
                self.live.add(client)
            threading.Thread(target=self._relay, args=(client,), daemon=True).start()

    def _relay(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=10)
        except OSError:
            self._drop(client)
            return
        with self.lock:
            self.live.add(upstream)
        threading.Thread(target=self._pipe, args=(upstream, client), daemon=True).start()
        self._pipe(client, upstream)

    def _pipe(self, src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        finally:
            self._drop(src)
            self._drop(dst)

    def _drop(self, sock: socket.socket) -> None:
        with self.lock:
            self.live.discard(sock)
        for action in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
            try:
                action()
            except OSError:
                pass

    def cut(self) -> None:
        with self.lock:
            self.down = True
            victims = list(self.live)
        for sock in victims:
            self._drop(sock)

    def restore(self) -> None:
        with self.lock:
            self.down = False


class EngineHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            return self._send({"data": [{"id": "mock-model"}]})
        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path != "/v1/chat/completions":
            # Tokenizer endpoints are absent, so the worker falls back to engine usage.
            return self._send({"error": "not found"}, 404)
        with self.server.counter_lock:
            self.server.calls += 1
            call_number = self.server.calls
        if self.server.on_call is not None:
            self.server.on_call(call_number)
        time.sleep(ENGINE_LATENCY_S)
        words = sum(len(str(m.get("content", "")).split()) for m in body.get("messages", []))
        return self._send({"choices": [{"message": {"role": "assistant",
                                                    "content": f"answer {call_number}"}}],
                           "usage": {"prompt_tokens": words, "completion_tokens": 3}})


class Engine(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), EngineHandler)
        self.calls = 0
        self.counter_lock = threading.Lock()
        self.on_call = None


def start_router(base: Path) -> tuple[int, object]:
    """Serve the real Router from this process; state lives under `base`."""
    router._db_path = base / "nexus_h0.db"
    router._router_private_key, router._router_public_pem = nc.load_or_create_router_key(base)
    router._network_mode = False
    router.NODE_HEARTBEAT_TTL_SECONDS = HEARTBEAT_TTL_S
    router.init_db()
    server = router.BoundedThreadingHTTPServer(("127.0.0.1", 0), router.Handler, max_threads=32)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1], server


def scalar(db: Path, sql: str, args: tuple = ()) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql, args).fetchone()[0]


def enqueue(router_url: str, count: int, tag: str) -> list[str]:
    job_ids = []
    for index in range(count):
        body = json.dumps({"messages": [{"role": "user", "content": f"{tag} job {index}"}],
                           "model": "", "nram": [], "params": {"max_tokens": 16}}).encode("utf-8")
        request = urllib.request.Request(router_url + "/jobs", data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            job_ids.append(json.loads(response.read().decode("utf-8"))["job_id"])
    return job_ids


def wait_for(predicate, timeout: float, what: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def scenario_outage_batch() -> None:
    with tempfile.TemporaryDirectory(prefix="nexus-outage-batch-") as folder:
        base = Path(folder)
        db = base / "router" / "nexus_h0.db"
        port, server = start_router(base / "router")
        router_url = f"http://127.0.0.1:{port}"
        proxy = Proxy(port)
        engine = Engine()
        threading.Thread(target=engine.serve_forever, daemon=True).start()
        engine_url = f"http://127.0.0.1:{engine.server_address[1]}"
        cut_at = {"started": False}

        def on_call(call_number: int) -> None:
            # Cut the link while the third job's result is still in flight.
            if call_number == 3 and not cut_at["started"]:
                cut_at["started"] = True
                proxy.cut()
                threading.Timer(OUTAGE_S, proxy.restore).start()

        engine.on_call = on_call
        worker = worker2.Worker(f"http://127.0.0.1:{proxy.port}", engine_url, base / "node", "")
        worker.heartbeat_interval = 0.2
        threading.Thread(target=worker.serve_forever, daemon=True).start()
        wait_for(lambda: scalar(db, "SELECT COUNT(*) FROM nodes") == 1, 30, "worker registration")
        enqueue(router_url, JOBS, "batch")
        started = time.time()
        wait_for(lambda: scalar(db, "SELECT COUNT(*) FROM jobs WHERE status='done'") == JOBS,
                 TIMEOUT_S, "batch completion")
        elapsed = time.time() - started

        assert cut_at["started"], "outage was never triggered"
        assert scalar(db, "SELECT COUNT(*) FROM jobs WHERE status<>'done'") == 0
        assert scalar(db, "SELECT COUNT(*) FROM receipts WHERE verified=1") == JOBS
        assert scalar(db, "SELECT COUNT(DISTINCT job_id) FROM receipts") == JOBS
        # Accepted receipts are counted once per job; a duplicate would raise this above JOBS.
        accepted = scalar(db, "SELECT COALESCE(SUM(jobs_done), 0) FROM nodes")
        assert accepted == JOBS, f"accepted receipts {accepted} != jobs {JOBS}"
        # The job whose result was cut was delivered by the retry, not re-dispatched.
        assert scalar(db, "SELECT MAX(attempts) FROM jobs") == 1
        print(f"outage batch ({OUTAGE_S:g}s cut, {JOBS} jobs): {JOBS} done, "
              f"{JOBS} receipts, no duplicates, {elapsed:.1f}s: PASS")
        proxy.cut()
        server.shutdown()


def scenario_lost_node_requeued() -> None:
    with tempfile.TemporaryDirectory(prefix="nexus-lost-node-") as folder:
        base = Path(folder)
        db = base / "router" / "nexus_h0.db"
        port, server = start_router(base / "router")
        router_url = f"http://127.0.0.1:{port}"
        (job_id,) = enqueue(router_url, 1, "lost")

        lost = worker2.Worker(router_url, ENGINE_URL, base / "lost-node", "")
        lost.register(["mock-model"], [])
        grabbed = lost.next_job()
        assert grabbed is not None and grabbed["job_id"] == job_id
        # The lost node now goes silent: no heartbeat, no result.

        engine = Engine()
        threading.Thread(target=engine.serve_forever, daemon=True).start()
        worker = worker2.Worker(router_url, f"http://127.0.0.1:{engine.server_address[1]}",
                                base / "live-node", "")
        worker.heartbeat_interval = 0.2
        threading.Thread(target=worker.serve_forever, daemon=True).start()
        wait_for(lambda: scalar(db, "SELECT COUNT(*) FROM jobs WHERE status='done'") == 1,
                 TIMEOUT_S, "requeued job completion")

        with sqlite3.connect(db) as conn:
            status, attempts, node_id = conn.execute(
                "SELECT status, attempts, node_id FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        assert status == "done" and attempts == 2, (status, attempts)
        assert node_id == worker.node_id, "requeued job was not run by the live node"
        assert scalar(db, "SELECT COUNT(*) FROM receipts WHERE job_id=?", (job_id,)) == 1

        # The lost node's late result is refused: it is no longer the assigned node.
        late = {"status": "rejected", "error": "late result", "dispatch_jwt": grabbed["dispatch_jwt"]}
        try:
            lost.router_json(f"/jobs/{job_id}/result", late, timeout=10)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403, exc.code
        else:
            raise AssertionError("late result from the lost node was accepted")
        assert scalar(db, "SELECT COUNT(*) FROM receipts WHERE job_id=?", (job_id,)) == 1
        print("lost node: job requeued after heartbeat TTL, completed once by the live node, "
              "late result refused: PASS")
        server.shutdown()


def main() -> None:
    scenario_outage_batch()
    scenario_lost_node_requeued()
    print("disconnect resilience: PASS")


if __name__ == "__main__":
    main()
