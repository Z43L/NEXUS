"""H0 worker with a multi-model engine: each job is billed with its own model's overhead.

Run from this directory: python3 -m unittest test_worker_multimodel -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_nram_registry import finished_job, free_port, request, wait_for

BASE = Path(__file__).resolve().parent
MODELS = {"alpha-1b": 10, "beta-3b": 40}


class WorkerMultiModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.mock_port, cls.router_port = free_port(), free_port()
        cls.router = f"http://127.0.0.1:{cls.router_port}"
        mock_env = dict(os.environ, MOCK_MODEL_IDS=",".join(MODELS),
                        MOCK_SCAFFOLD_MAP=json.dumps(MODELS))
        cls.procs = [
            subprocess.Popen([sys.executable, str(BASE / "mock_atenea.py"),
                              "--port", str(cls.mock_port)], env=mock_env),
            subprocess.Popen([sys.executable, str(BASE / "router.py"),
                              "--port", str(cls.router_port), "--dir", str(root / "router")]),
        ]
        wait_for(lambda: request(cls.router + "/health")[0] == 200)
        cls.procs.append(subprocess.Popen(
            [sys.executable, str(BASE / "worker_agent.py"), "--router", cls.router,
             "--atenea", f"http://127.0.0.1:{cls.mock_port}", "--node-dir", str(root / "node")]))
        wait_for(lambda: len(advertised(cls.router)) == len(MODELS), seconds=60)

    @classmethod
    def tearDownClass(cls):
        for proc in cls.procs:
            proc.terminate()
        for proc in cls.procs:
            proc.wait(timeout=10)
        cls.tmp.cleanup()

    def run_job(self, model):
        payload = {"kind": "inference", "model": model,
                   "messages": [{"role": "user", "content": "hola"}],
                   "params": {"max_tokens": 8}}
        status, body = request(self.router + "/jobs", data=json.dumps(payload).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
        self.assertEqual(status, 200)
        job_id = json.loads(body)["job_id"]
        return wait_for(lambda: finished_job(self.router, job_id), seconds=60)

    def test_both_models_are_advertised(self):
        self.assertEqual(sorted(advertised(self.router)), sorted(MODELS))

    def test_each_job_is_billed_with_its_own_model_overhead(self):
        for model, overhead in MODELS.items():
            with self.subTest(model=model):
                job = self.run_job(model)
                self.assertEqual(job["status"], "done")
                receipt = job["receipt"]
                self.assertEqual(receipt["model"], model)
                self.assertEqual(receipt["scaffolding_tokens"], overhead)


def advertised(router):
    status, body = request(router + "/v1/models")
    return [item["id"] for item in json.loads(body)["data"]] if status == 200 else []


if __name__ == "__main__":
    unittest.main()
