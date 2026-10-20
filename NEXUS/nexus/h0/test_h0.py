"""H0 end-to-end test against the mock Atenhea engine.

Covers: 100-job batch, signed receipts, signature tampering rejected at the
Router API level, metering cross-check, and the tools-probe rejection.
Run: python3 test_h0.py   (exit 0 = pass)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import nexus_common as nc  # noqa: E402

MOCK_PORT = 11437
ROUTER_PORT = 18081
ROUTER = f"http://127.0.0.1:{ROUTER_PORT}"


def http_json(url, payload=None, timeout=30, expect=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 method="GET" if payload is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read().decode("utf-8"))
            return resp.status, out
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def wait_health(url, seconds=30):
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            status, _ = http_json(url)
            if status == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="nexus-h0-test-"))
    procs: list[subprocess.Popen] = []
    py = sys.executable
    try:
        procs.append(subprocess.Popen([py, str(BASE / "mock_atenea.py"), "--port", str(MOCK_PORT)]))
        procs.append(subprocess.Popen([py, str(BASE / "router.py"), "--port", str(ROUTER_PORT),
                                       "--dir", str(tmp)]))
        assert wait_health(ROUTER + "/health"), "router did not start"
        node_dir = tmp / "node"
        procs.append(subprocess.Popen([py, str(BASE / "worker_agent.py"),
                                       "--router", ROUTER,
                                       "--atenea", f"http://127.0.0.1:{MOCK_PORT}",
                                       "--node-dir", str(node_dir)]))
        time.sleep(3)

        subprocess.run([py, str(BASE / "gen_jobs.py")], check=True, capture_output=True)
        report_path = tmp / "report.json"
        run = subprocess.run([py, str(BASE / "dogfood_client.py"), "--router", ROUTER,
                              "--timeout-s", "600", "--out", str(report_path)],
                             capture_output=True, text=True, timeout=900)
        print(run.stdout[-2000:])
        assert run.returncode == 0, run.stderr[-2000:]
        report = json.loads(report_path.read_text())
        assert report["gate_passed"], f"gate failed: {report['gate']}"
        print("E2E gate: PASS", report["gate"])

        # --- API-level tamper test -------------------------------------------
        priv, pub_pem, node_id = nc.load_or_create_node_key(node_dir)
        status, out = http_json(ROUTER + "/jobs", {
            "kind": "inference", "model": "athenea-e2b", "nram": [],
            "messages": [{"role": "user", "content": "trabajo de control"}],
            "params": {"max_tokens": 32}})
        job_id = out["job_id"]
        status, out = http_json(ROUTER + f"/jobs/next?node_id={node_id}")
        job = out["job"]
        assert job and job["job_id"] == job_id, "dispatch failed"
        receipt = {
            "job_id": job_id, "node_id": node_id, "model": "athenea-e2b",
            "input_tokens": 3, "output_tokens": 5, "engine_prompt_tokens": 3,
            "engine_completion_tokens": 5, "nram_used": [], "started_at": nc.utc_now_iso(),
            "finished_at": nc.utc_now_iso(), "elapsed_s": 0.1,
            "output_sha256": nc.sha256_hex(b"control"), "price_micro_usd": 1,
            "shares": nc.split_payment(1, False),
        }
        good_sig = nc.sign_receipt(priv, receipt)
        status, _ = http_json(ROUTER + f"/jobs/{job_id}/result", {
            "status": "done", "receipt": receipt, "signature": "00" * 64,
            "dispatch_token": job["dispatch_token"]})
        assert status == 400, f"tampered signature accepted (status {status})"
        print("tampered signature: REJECTED ok")
        status, out = http_json(ROUTER + f"/jobs/{job_id}/result", {
            "status": "done", "receipt": receipt, "signature": good_sig,
            "dispatch_token": job["dispatch_token"]})
        assert status == 200 and out["status"] == "done", f"valid receipt rejected: {out}"
        print("valid control receipt: ACCEPTED ok")

        # --- Phase 2: engine without the chat counting endpoint -------------
        # Mirrors David's local Atenhea: only /v1/messages/count_tokens exists.
        mock2_port, router2_port = 11438, 18082
        router2 = f"http://127.0.0.1:{router2_port}"
        tmp2 = Path(tempfile.mkdtemp(prefix="nexus-h0-test2-"))
        env = dict(os.environ, MOCK_DISABLE_CHAT_COUNT="1")
        p1 = subprocess.Popen([py, str(BASE / "mock_atenea.py"), "--port", str(mock2_port)], env=env)
        p2 = subprocess.Popen([py, str(BASE / "router.py"), "--port", str(router2_port), "--dir", str(tmp2)])
        p3 = subprocess.Popen([py, str(BASE / "worker_agent.py"), "--router", router2,
                               "--atenea", f"http://127.0.0.1:{mock2_port}",
                               "--node-dir", str(tmp2 / "node")])
        procs += [p1, p2, p3]
        assert wait_health(router2 + "/health"), "router2 did not start"
        time.sleep(3)
        ids2 = []
        for i in range(5):
            status, out = http_json(router2 + "/jobs", {
                "kind": "resumen", "model": "athenea-e2b", "nram": [],
                "messages": [{"role": "user", "content": f"Resume el fragmento numero {i} del puerto."}],
                "params": {"max_tokens": 48}})
            ids2.append(out["job_id"])
        deadline = time.time() + 120
        done2 = 0
        while time.time() < deadline:
            done2 = 0
            for jid in ids2:
                status, st = http_json(router2 + f"/jobs/{jid}")
                if st["status"] == "done":
                    done2 += 1
                    assert (st.get("discrepancy_pct") or 0) <= 1.0, st
            if done2 == len(ids2):
                break
            time.sleep(1)
        assert done2 == len(ids2), f"phase2: {done2}/5 jobs done"
        print("phase2 (messages/count_tokens fallback): PASS")

        print("ALL H0 TESTS PASS")
        return 0
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
