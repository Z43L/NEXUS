"""H2 local .nram registry: bundle validation and Router publish/list/fetch flow.

Run from this directory: python3 -m unittest test_nram_registry -v

Publishing is tested against a remote-mode Router (TLS, bearer tokens bound to
client ids), because the author of a bundle must come from the authenticated
token, never from the X-Nexus-Client-ID header.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import nram_registry as nr
from test_secure_remote import make_ca, make_server_cert, write_secret
import worker_agent

BASE = Path(__file__).resolve().parent


def build_bundle(name="expert-a", version="1.0.0", tensors=b"tensor-bytes", **extra) -> bytes:
    manifest = {"container": "NRA-M", "format_version": 2, "name": name,
                "version": version, "tensor_sha256": hashlib.sha256(tensors).hexdigest()}
    manifest.update(extra)
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return (nr.MAGIC + nr.HEADER.pack(len(manifest_bytes), len(tensors))
            + manifest_bytes + tensors)


class InspectBundleTests(unittest.TestCase):
    def test_accepts_consistent_bundle(self):
        info = nr.inspect_bundle(build_bundle(task="summary"))
        self.assertEqual(info["name"], "expert-a")
        self.assertEqual(info["version"], "1.0.0")
        self.assertEqual(info["manifest"]["task"], "summary")

    def test_rejects_bad_magic(self):
        data = b"XXXX" + build_bundle()[4:]
        with self.assertRaises(nr.NramError):
            nr.inspect_bundle(data)

    def test_rejects_truncated_file(self):
        with self.assertRaises(nr.NramError):
            nr.inspect_bundle(build_bundle()[:-1])

    def test_rejects_tensor_checksum_mismatch(self):
        good = build_bundle()
        tampered = good[:-1] + bytes([good[-1] ^ 1])
        with self.assertRaisesRegex(nr.NramError, "checksum"):
            nr.inspect_bundle(tampered)

    def test_rejects_unsafe_name(self):
        with self.assertRaises(nr.NramError):
            nr.inspect_bundle(build_bundle(name="../evil"))

    def test_rejects_wrong_format_version(self):
        tensors = b"t"
        manifest = {"container": "NRA-M", "format_version": 1, "name": "a",
                    "version": "1", "tensor_sha256": hashlib.sha256(tensors).hexdigest()}
        mb = json.dumps(manifest).encode()
        data = nr.MAGIC + nr.HEADER.pack(len(mb), len(tensors)) + mb + tensors
        with self.assertRaisesRegex(nr.NramError, "unsupported"):
            nr.inspect_bundle(data)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url, data=None, headers=None, method=None, context=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10, context=context) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read()


class RouterRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        ca_key, ca_cert, ca_path = make_ca(root, "NEXUS-test-CA")
        cert_path, key_path = make_server_cert(root, ca_key, ca_cert)
        # Test-only credentials, generated per run. None of them is a real secret.
        cls.alice = "alice-" + os.urandom(32).hex()
        cls.bob = "bob-" + os.urandom(32).hex()
        cls.shared = "shared-" + os.urandom(32).hex()
        write_secret(root / "shared.token", cls.shared)
        write_secret(root / "enrollment.token", "enroll-" + os.urandom(32).hex())
        write_secret(root / "clients.json", json.dumps({"alice": cls.alice, "bob": cls.bob}))
        cls.context = ssl.create_default_context(cafile=str(ca_path))
        cls.port = free_port()
        cls.url = f"https://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen(
            [sys.executable, str(BASE / "router.py"), "--mode", "remote",
             "--host", "127.0.0.1", "--port", str(cls.port), "--dir", str(root / "state"),
             "--tls-cert", str(cert_path), "--tls-key", str(key_path),
             "--client-token-file", str(root / "shared.token"),
             "--enrollment-token-file", str(root / "enrollment.token"),
             "--client-registry-file", str(root / "clients.json")],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        try:
            wait_for(lambda: request(cls.url + "/health", context=cls.context)[0] == 200)
        except RuntimeError:
            cls.proc.kill()
            raise RuntimeError("router did not become healthy")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.tmp.cleanup()

    def call(self, path, data=None, headers=None, method=None, token=None):
        headers = dict(headers or {})
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        return request(self.url + path, data=data, headers=headers, method=method,
                       context=self.context)

    def publish(self, data, token=None, claimed=None):
        headers = {"Content-Type": "application/octet-stream"}
        if claimed is not None:
            headers["X-Nexus-Client-ID"] = claimed
        return self.call("/nram", data=data, headers=headers, method="POST", token=token)

    def test_publish_list_fetch_and_verify(self):
        data = build_bundle()
        status, body = self.publish(data, self.alice)
        self.assertEqual(status, 201)
        published = json.loads(body)
        nram_id = hashlib.sha256(data).hexdigest()
        self.assertEqual(published["nram_id"], nram_id)
        self.assertEqual(published["author_id"], "alice")

        status, body = self.call("/nram", token=self.alice)
        self.assertIn(nram_id, [item["nram_id"] for item in json.loads(body)["data"]])

        status, body = self.call(f"/nram/{nram_id}", token=self.alice)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["manifest"]["name"], "expert-a")

        status, blob = self.call(f"/nram/{nram_id}/blob", token=self.alice)
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), nram_id)
        nr.inspect_bundle(blob)

    def test_author_is_the_token_bound_client_not_the_header(self):
        data = build_bundle(name="expert-owned")
        nram_id = nr.bundle_id(data)
        # Token A with header B is refused, and nothing is stored.
        status, body = self.publish(data, self.alice, claimed="bob")
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "forbidden")
        self.assertEqual(self.call(f"/nram/{nram_id}", token=self.alice)[0], 404)

        # Token B with header A is refused the same way.
        self.assertEqual(self.publish(data, self.bob, claimed="alice")[0], 403)

        # Without a header, or with the token's own id, the token's client is the author.
        status, body = self.publish(data, self.alice)
        self.assertEqual((status, json.loads(body)["author_id"]), (201, "alice"))
        other = build_bundle(name="expert-owned-b")
        status, body = self.publish(other, self.bob, claimed="bob")
        self.assertEqual((status, json.loads(body)["author_id"]), (201, "bob"))

    def test_shared_token_and_anonymous_requests_cannot_publish(self):
        # The shared chat/models token authenticates but binds no publisher id.
        self.assertEqual(self.publish(build_bundle(name="expert-shared"), self.shared)[0], 403)
        self.assertEqual(self.publish(build_bundle(name="expert-anon"))[0], 401)
        self.assertEqual(self.publish(build_bundle(name="expert-bad"), "wrong-token")[0], 401)

    def test_duplicate_and_invalid_uploads_are_rejected(self):
        data = build_bundle(name="expert-dup")
        self.assertEqual(self.publish(data, self.alice)[0], 201)
        self.assertEqual(self.publish(data, self.alice)[0], 409)
        self.assertEqual(self.publish(data[:-1], self.alice)[0], 400)
        self.assertEqual(self.publish(build_bundle(), self.alice, claimed="bad id!")[0], 403)
        self.assertEqual(self.call(f"/nram/{'0' * 64}", token=self.alice)[0], 404)
        self.assertEqual(self.call("/nram/not-an-id", token=self.alice)[0], 400)

    def test_job_may_reference_only_published_bundles(self):
        payload = {"kind": "inference", "model": "athenea-e2b",
                   "messages": [{"role": "user", "content": "hola"}],
                   "params": {"max_tokens": 8}}
        headers = {"Content-Type": "application/json"}
        unknown = dict(payload, nram=["a" * 64])
        status, _ = self.call("/jobs", data=json.dumps(unknown).encode(),
                              headers=headers, method="POST", token=self.alice)
        self.assertEqual(status, 400)

        nram_id = nr.bundle_id(build_bundle(name="expert-job"))
        self.assertEqual(self.publish(build_bundle(name="expert-job"), self.alice)[0], 201)
        known = dict(payload, nram=[nram_id])
        status, _ = self.call("/jobs", data=json.dumps(known).encode(),
                              headers=headers, method="POST", token=self.alice)
        self.assertEqual(status, 200)

        two = dict(payload, nram=[nram_id, nram_id])
        status, _ = self.call("/jobs", data=json.dumps(two).encode(),
                              headers=headers, method="POST", token=self.alice)
        self.assertEqual(status, 400)

    def test_ledger_reports_royalty_map(self):
        status, body = self.call("/ledger/summary", token=self.alice)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["royalties_micro_usd_by_author"], {})

    def test_tampered_stored_bundle_is_refused_on_download(self):
        data = build_bundle(name="expert-tamper-router")
        nram_id = hashlib.sha256(data).hexdigest()
        self.assertEqual(self.publish(data)[0], 201)
        stored = Path(self.tmp.name) / "nram" / f"{nram_id}.nram"
        stored.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        status, body = request(f"{self.url}/nram/{nram_id}/blob")
        self.assertEqual(status, 500)
        self.assertIn(b"corrupt", body)


class _BlobServer(BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):
        pass


class WorkerDownloadIntegrityTests(unittest.TestCase):
    """ensure_adapter must refuse bytes that do not hash to the requested id."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.good = build_bundle(name="expert-download")
        self.nram_id = nr.bundle_id(self.good)
        self.adapter_dir = Path(self.tmp.name) / "adapters"

    def _serve(self, payload):
        handler = type("Handler", (_BlobServer,), {"payload": payload})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def _worker(self, router):
        return worker_agent.Worker(router, "http://127.0.0.1:1", Path(self.tmp.name) / "node",
                                   adapter_dir=self.adapter_dir)

    def test_accepts_download_that_matches_requested_id(self):
        worker = self._worker(self._serve(self.good))
        worker.ensure_adapter(self.nram_id)
        self.assertEqual(nr.read_bundle(self.adapter_dir, self.nram_id), self.good)

    def test_rejects_tampered_download_and_stores_nothing(self):
        tampered = self.good[:-1] + bytes([self.good[-1] ^ 1])
        worker = self._worker(self._serve(tampered))
        with self.assertRaisesRegex(nr.NramError, "does not match its id"):
            worker.ensure_adapter(self.nram_id)
        self.assertFalse((self.adapter_dir / f"{self.nram_id}.nram").exists())

    def test_rejects_cached_bundle_altered_on_disk(self):
        worker = self._worker(self._serve(self.good))
        worker.ensure_adapter(self.nram_id)
        cached = self.adapter_dir / f"{self.nram_id}.nram"
        cached.write_bytes(self.good[:-1] + bytes([self.good[-1] ^ 1]))
        with self.assertRaisesRegex(nr.NramError, "does not match its id"):
            worker.ensure_adapter(self.nram_id)


class WorkerAdapterTests(unittest.TestCase):
    """A .nram job must be refused when the engine does not confirm the adapter.

    The mock engine ignores nram_adapter, so the worker must not sign a receipt
    that would pay the author for weights nobody applied.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.mock_port, cls.router_port = free_port(), free_port()
        cls.router = f"http://127.0.0.1:{cls.router_port}"
        cls.procs = [
            subprocess.Popen([sys.executable, str(BASE / "mock_atenea.py"),
                              "--port", str(cls.mock_port)]),
            subprocess.Popen([sys.executable, str(BASE / "router.py"),
                              "--port", str(cls.router_port), "--dir", str(root / "router")]),
        ]
        wait_for(lambda: request(cls.router + "/health")[0] == 200)
        cls.procs.append(subprocess.Popen(
            [sys.executable, str(BASE / "worker_agent.py"), "--router", cls.router,
             "--atenea", f"http://127.0.0.1:{cls.mock_port}",
             "--node-dir", str(root / "node"), "--engine-adapter-dir", str(root / "adapters")]))
        cls.model = wait_for(lambda: first_model(cls.router))

    @classmethod
    def tearDownClass(cls):
        for proc in cls.procs:
            proc.terminate()
        for proc in cls.procs:
            proc.wait(timeout=10)
        cls.tmp.cleanup()

    def test_job_with_unapplied_adapter_is_rejected(self):
        data = build_bundle(name="expert-worker")
        status, _ = request(self.router + "/nram", data=data, method="POST",
                            headers={"Content-Type": "application/octet-stream",
                                     "X-Nexus-Client-ID": "alice"})
        self.assertEqual(status, 201)
        payload = {"kind": "inference", "model": self.model, "nram": [nr.bundle_id(data)],
                   "messages": [{"role": "user", "content": "hola"}],
                   "params": {"max_tokens": 8}}
        status, body = request(self.router + "/jobs", data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
        self.assertEqual(status, 200)
        job_id = json.loads(body)["job_id"]
        job = wait_for(lambda: finished_job(self.router, job_id), seconds=60)
        self.assertEqual(job["status"], "rejected")
        self.assertEqual(job["error"], "nram_not_applied")
        self.assertIsNone(job.get("receipt"))


def wait_for(check, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError("condition not reached in time")


def first_model(router):
    status, body = request(router + "/v1/models")
    data = json.loads(body)["data"] if status == 200 else []
    return data[0]["id"] if data else None


def finished_job(router, job_id):
    status, body = request(f"{router}/jobs/{job_id}")
    job = json.loads(body) if status == 200 else {}
    return job if job.get("status") in ("rejected", "failed", "done") else None


if __name__ == "__main__":
    unittest.main()
