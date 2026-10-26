"""H2 local .nram registry: bundle validation and Router publish/list/fetch flow.

Run from this directory: python3 -m unittest test_nram_registry -v
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import nram_registry as nr

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


def request(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class RouterRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.port = free_port()
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.proc = subprocess.Popen([sys.executable, str(BASE / "router.py"),
                                     "--port", str(cls.port), "--dir", cls.tmp.name])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if request(cls.url + "/health")[0] == 200:
                    break
            except OSError:
                time.sleep(0.1)
        else:
            cls.proc.kill()
            raise RuntimeError("router did not become healthy")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.tmp.cleanup()

    def publish(self, data, author="alice"):
        return request(self.url + "/nram", data=data, method="POST",
                       headers={"Content-Type": "application/octet-stream",
                                "X-Nexus-Client-ID": author})

    def test_publish_list_fetch_and_verify(self):
        data = build_bundle()
        status, body = self.publish(data)
        self.assertEqual(status, 201)
        published = json.loads(body)
        nram_id = hashlib.sha256(data).hexdigest()
        self.assertEqual(published["nram_id"], nram_id)
        self.assertEqual(published["author_id"], "alice")

        status, body = request(self.url + "/nram")
        self.assertIn(nram_id, [item["nram_id"] for item in json.loads(body)["data"]])

        status, body = request(f"{self.url}/nram/{nram_id}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["manifest"]["name"], "expert-a")

        status, blob = request(f"{self.url}/nram/{nram_id}/blob")
        self.assertEqual(status, 200)
        self.assertEqual(hashlib.sha256(blob).hexdigest(), nram_id)
        nr.inspect_bundle(blob)

    def test_duplicate_and_invalid_uploads_are_rejected(self):
        data = build_bundle(name="expert-dup")
        self.assertEqual(self.publish(data)[0], 201)
        self.assertEqual(self.publish(data)[0], 409)
        self.assertEqual(self.publish(data[:-1])[0], 400)
        self.assertEqual(self.publish(build_bundle(), author="bad id!")[0], 400)
        self.assertEqual(request(f"{self.url}/nram/{'0' * 64}")[0], 404)
        self.assertEqual(request(f"{self.url}/nram/not-an-id")[0], 400)

    def test_job_may_reference_only_published_bundles(self):
        payload = {"kind": "inference", "model": "athenea-e2b",
                   "messages": [{"role": "user", "content": "hola"}],
                   "params": {"max_tokens": 8}}
        headers = {"Content-Type": "application/json"}
        unknown = dict(payload, nram=["a" * 64])
        status, _ = request(self.url + "/jobs", data=json.dumps(unknown).encode(),
                            headers=headers, method="POST")
        self.assertEqual(status, 400)

        nram_id = hashlib.sha256(build_bundle(name="expert-job")).hexdigest()
        self.assertEqual(self.publish(build_bundle(name="expert-job"))[0], 201)
        known = dict(payload, nram=[nram_id])
        status, _ = request(self.url + "/jobs", data=json.dumps(known).encode(),
                            headers=headers, method="POST")
        self.assertEqual(status, 200)

        two = dict(payload, nram=[nram_id, nram_id])
        status, _ = request(self.url + "/jobs", data=json.dumps(two).encode(),
                            headers=headers, method="POST")
        self.assertEqual(status, 400)

    def test_ledger_reports_royalty_map(self):
        status, body = request(self.url + "/ledger/summary")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["royalties_micro_usd_by_author"], {})


if __name__ == "__main__":
    unittest.main()
