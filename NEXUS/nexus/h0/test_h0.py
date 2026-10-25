"""H0 end-to-end test against the mock Atenhea engine.

Covers: 100-job batch, signed receipts, signature tampering rejected at the
Router API level, metering cross-check, and the tools-probe rejection.
Run: python3 test_h0.py   (exit 0 = pass)
"""
from __future__ import annotations

import json
import os
import asyncio
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import nexus_common as nc  # noqa: E402
import router as router_module  # noqa: E402

H1_COMMON_PATH = BASE.parents[1] / "nexus-h1-node" / "nexus_common.py"
H1_COMMON_SPEC = importlib.util.spec_from_file_location("nexus_h1_common_test", H1_COMMON_PATH)
assert H1_COMMON_SPEC and H1_COMMON_SPEC.loader
h1_common = importlib.util.module_from_spec(H1_COMMON_SPEC)
H1_COMMON_SPEC.loader.exec_module(h1_common)

MOCK_PORT = 11437
ROUTER_PORT = 18081
ROUTER = f"http://127.0.0.1:{ROUTER_PORT}"


def http_json(url, payload=None, timeout=30, expect=None, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 method="GET" if payload is None else "POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
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
        retry_conn = sqlite3.connect(":memory:")
        retry_conn.row_factory = sqlite3.Row
        retry_conn.execute("CREATE TABLE jobs(job_id TEXT, status TEXT, attempts INTEGER, "
                           "node_id TEXT, lease_until TEXT, error TEXT, finished_at TEXT)")
        retry_conn.executemany("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", [
            ("retry-1", "dispatched", 1, "node-a", "2030-01-01T00:00:00Z", None, None),
            ("retry-final", "dispatched", router_module.MAX_JOB_ATTEMPTS,
             "node-b", "2030-01-01T00:00:00Z", None, None),
            ("already-done", "done", 1, "node-a", None, None, "2026-10-25T00:00:00Z"),
        ])
        assert router_module.requeue_dispatched_job(
            retry_conn, "retry-1", "Atenhea temporarily unavailable",
            "2026-10-25T00:00:00Z") == "queued"
        row = retry_conn.execute("SELECT status, attempts, node_id, lease_until, error, finished_at "
                                 "FROM jobs WHERE job_id='retry-1'").fetchone()
        assert row["status"] == "queued" and row["attempts"] == 1
        assert row["node_id"] is None and row["lease_until"] is None
        assert row["error"].startswith("transient worker failure") and row["finished_at"] is None
        assert router_module.requeue_dispatched_job(
            retry_conn, "retry-final", "Atenhea remains unavailable",
            "2026-10-25T00:00:01Z") == "failed"
        row = retry_conn.execute("SELECT status, node_id, lease_until, error, finished_at "
                                 "FROM jobs WHERE job_id='retry-final'").fetchone()
        assert row["status"] == "failed" and row["node_id"] is None and row["lease_until"] is None
        assert "retry limit exhausted" in row["error"] and row["finished_at"] == "2026-10-25T00:00:01Z"
        assert router_module.requeue_dispatched_job(retry_conn, "already-done", "late retry") is None
        retry_conn.close()

        classifier_cases = [
            (urllib.error.URLError("offline"), True),
            (TimeoutError("timed out"), True),
            (urllib.error.HTTPError("https://engine", 429, "busy", None, None), True),
            (urllib.error.HTTPError("https://engine", 503, "unavailable", None, None), True),
            (urllib.error.HTTPError("https://engine", 404, "missing", None, None), False),
            (urllib.error.HTTPError("https://engine", 400, "bad request", None, None), False),
            (ValueError("invalid response"), False),
        ]
        for classifier in (nc.is_transient_transport_error,
                           h1_common.is_transient_transport_error):
            assert all(classifier(exc) == expected for exc, expected in classifier_cases)
        print("transient retry classification and attempt-limit transitions: PASS")

        advertised_models = ["model-a", "model-b:latest"]
        assert nc.resolve_model("model-b", advertised_models) == "model-b:latest"
        assert nc.resolve_model("model-a", advertised_models) == "model-a"
        try:
            nc.resolve_model("model-c", advertised_models)
        except ValueError:
            pass
        else:
            raise AssertionError("worker accepted a model it does not advertise")
        print("multi-model selection and unavailable-model rejection: PASS")

        router_priv, router_pub = nc.load_or_create_router_key(tmp)
        valid_jwt = nc.issue_job_jwt(router_priv, "node_test", "job_test")
        assert nc.verify_job_jwt(router_pub, valid_jwt, "node_test", "job_test")["job_id"] == "job_test"
        for token, node_id, job_id in (
            (valid_jwt + "x", "node_test", "job_test"),
            (valid_jwt, "other_node", "job_test"),
            (nc.issue_job_jwt(router_priv, "node_test", "job_test", ttl_s=-1),
             "node_test", "job_test"),
        ):
            try:
                nc.verify_job_jwt(router_pub, token, node_id, job_id)
            except ValueError:
                continue
            raise AssertionError("invalid JWT was accepted")
        print("dispatch JWT signature, binding and expiry: PASS")

        lease_conn = sqlite3.connect(":memory:")
        lease_conn.row_factory = sqlite3.Row
        lease_conn.execute("CREATE TABLE jobs(job_id TEXT, status TEXT, lease_until TEXT, "
                           "attempts INTEGER, node_id TEXT, error TEXT, finished_at TEXT)")
        lease_conn.executemany("INSERT INTO jobs VALUES(?,?,?,?,?,?,?)", [
            ("retry", "dispatched", "2000-01-01T00:00:00Z", 1, "n1", None, None),
            ("exhausted", "dispatched", "2000-01-01T00:00:00Z", 3, "n2", None, None),
        ])
        assert router_module.recover_expired_jobs(lease_conn, "2026-10-25T00:00:00Z") == 2
        statuses = {row[0]: row[1] for row in lease_conn.execute(
            "SELECT job_id, status FROM jobs")}
        assert statuses == {"retry": "queued", "exhausted": "failed"}, statuses
        lease_conn.close()
        print("expired lease recovery and retry limit: PASS")

        procs.append(subprocess.Popen([py, str(BASE / "mock_atenea.py"), "--port", str(MOCK_PORT)]))
        procs.append(subprocess.Popen([py, str(BASE / "router.py"), "--port", str(ROUTER_PORT),
                                       "--dir", str(tmp)]))
        assert wait_health(ROUTER + "/health"), "router did not start"
        assert http_json(ROUTER + "/ready")[0] == 200
        with urllib.request.urlopen(ROUTER + "/metrics") as metrics_resp:
            assert "nexus_h0_jobs" in metrics_resp.read().decode()
        node_dir = tmp / "node"
        procs.append(subprocess.Popen([py, str(BASE / "worker_agent.py"),
                                       "--router", ROUTER,
                                       "--atenea", f"http://127.0.0.1:{MOCK_PORT}",
                                       "--node-dir", str(node_dir)]))
        time.sleep(3)

        models_status, models = http_json(ROUTER + "/v1/models")
        assert models_status == 200 and any(m["id"] == "athenea-e2b" for m in models["data"]), models

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

        # Customer-facing OpenAI-compatible path must return the worker output,
        # not merely mark the asynchronous job complete.
        status, completion = http_json(ROUTER + "/v1/chat/completions", {
            "model": "athenea-e2b",
            "messages": [{"role": "user", "content": "Responde con una frase."}],
            "max_tokens": 8,
            "timeout_s": 30,
        })
        assert status == 200, f"chat completion failed: {completion}"
        assert completion["choices"][0]["message"]["content"], completion
        assert completion["usage"]["total_tokens"] > 0, completion
        print("OpenAI-compatible chat path: PASS")

        sdk_dir = BASE.parents[1] / "nexus-sdk-python"
        sys.path.insert(0, str(sdk_dir))
        from nexus_client import NexusClient  # noqa: E402
        sdk_completion = asyncio.run(NexusClient(base_url=ROUTER).chat(
            "Respuesta desde el SDK Python", max_tokens=8, timeout_s=30))
        assert sdk_completion["choices"][0]["message"]["content"], sdk_completion
        print("Python SDK ↔ gateway: PASS")

        # The browser UI is served same-origin and proxies only the local H0
        # model and chat endpoints.
        ui_port = 18084
        ui_url = f"http://127.0.0.1:{ui_port}"
        ui_env = dict(os.environ, NEXUS_H0_ROUTER_URL=ROUTER,
                      NEXUS_H0_UI_PORT=str(ui_port))
        ui_script = BASE.parents[1] / "nexus-web" / "h0_local.py"
        procs.append(subprocess.Popen([py, str(ui_script)], env=ui_env))
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(ui_url, timeout=1) as response:
                    page = response.read().decode("utf-8")
                    assert response.status == 200 and "NEXUS H0" in page
                    break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise AssertionError("H0 UI did not start")
        assert http_json(ui_url + "/v1/models")[0] == 200
        ui_status, ui_completion = http_json(ui_url + "/v1/chat/completions", {
            "model": "athenea-e2b",
            "messages": [{"role": "user", "content": "UI proxy check"}],
            "max_tokens": 8, "timeout_s": 30,
        })
        assert ui_status == 200 and ui_completion["choices"][0]["message"]["content"]
        print("same-origin H0 UI proxy → gateway: PASS")

        status, invalid = http_json(ROUTER + "/v1/chat/completions", {"messages": []})
        assert status == 400 and "error" in invalid, (status, invalid)
        status, unknown_node = http_json(ROUTER + "/jobs/next?node_id=not-registered")
        assert status == 403, (status, unknown_node)
        print("request validation and registered-node gate: PASS")

        # --- API-level tamper test -------------------------------------------
        priv, pub_pem, node_id = nc.load_or_create_node_key(node_dir)
        status, out = http_json(ROUTER + "/jobs", {
            "kind": "inference", "model": "athenea-e2b", "nram": [],
            "messages": [{"role": "user", "content": "trabajo de control"}],
            "params": {"max_tokens": 32}})
        job_id = out["job_id"]
        next_path = f"/jobs/next?node_id={node_id}"
        poll_headers = {
            **nc.sign_node_request(priv, "GET", next_path, {}),
            "X-Nexus-Node-ID": node_id,
        }
        status, out = http_json(ROUTER + next_path, headers=poll_headers)
        job = out["job"]
        assert job and job["job_id"] == job_id, "dispatch failed"
        replay_status, _ = http_json(ROUTER + next_path, headers=poll_headers)
        assert replay_status == 401, "replayed polling signature was accepted"
        print("node request replay protection: PASS")
        receipt = {
            "job_id": job_id, "node_id": node_id, "model": "athenea-e2b",
            "input_tokens": 3, "output_tokens": 5, "engine_prompt_tokens": 3,
            "engine_completion_tokens": 5, "nram_used": [], "started_at": nc.utc_now_iso(),
            "finished_at": nc.utc_now_iso(), "elapsed_s": 0.1,
            "output_sha256": nc.sha256_hex(b"control"), "price_micro_usd": 1,
            "shares": nc.split_payment(1, False),
        }
        good_sig = nc.sign_receipt(priv, receipt)
        # A worker must not redirect the royalty to an author identifier that
        # was not attached to the persisted job, even with a valid signature.
        mismatched_receipt = dict(receipt, nram_used=["author_not_requested"],
                                  shares=nc.split_payment(1, True))
        mismatched_result = {
            "status": "done", "receipt": mismatched_receipt,
            "signature": nc.sign_receipt(priv, mismatched_receipt),
            "dispatch_jwt": job["dispatch_jwt"], "output_text": "control"}
        mismatch_path = f"/jobs/{job_id}/result"
        status, mismatch = http_json(ROUTER + mismatch_path, mismatched_result, headers={
            **nc.sign_node_request(priv, "POST", mismatch_path, mismatched_result),
            "X-Nexus-Node-ID": node_id,
        })
        assert status == 400 and "NRAM" in mismatch.get("error", ""), mismatch
        print("unrequested NRAM royalty: REJECTED ok")
        invalid_result = {
            "status": "done", "receipt": receipt, "signature": "00" * 64,
            "dispatch_jwt": job["dispatch_jwt"]}
        invalid_path = f"/jobs/{job_id}/result"
        status, _ = http_json(ROUTER + invalid_path, invalid_result, headers={
            **nc.sign_node_request(priv, "POST", invalid_path, invalid_result),
            "X-Nexus-Node-ID": node_id,
        })
        assert status == 400, f"tampered signature accepted (status {status})"
        print("tampered signature: REJECTED ok")

        wrong_model_receipt = dict(receipt, model="different-model")
        wrong_model_result = {
            "status": "done", "receipt": wrong_model_receipt,
            "signature": nc.sign_receipt(priv, wrong_model_receipt),
            "dispatch_jwt": job["dispatch_jwt"], "output_text": "control"}
        status, wrong_model = http_json(ROUTER + invalid_path, wrong_model_result, headers={
            **nc.sign_node_request(priv, "POST", invalid_path, wrong_model_result),
            "X-Nexus-Node-ID": node_id,
        })
        assert status == 400 and "model" in wrong_model.get("error", ""), wrong_model
        print("receipt model must match requested job model: REJECTED ok")

        # The assigned node may request one transient retry using the active
        # JWT/signature. The job is requeued without a fabricated receipt.
        procs[2].terminate()
        procs[2].wait(timeout=5)
        retry_path = f"/jobs/{job_id}/result"
        retry_body = {"status": "retry", "error": "transient Atenhea timeout",
                      "dispatch_jwt": job["dispatch_jwt"]}
        retry_status, retried = http_json(ROUTER + retry_path, retry_body, headers={
            **nc.sign_node_request(priv, "POST", retry_path, retry_body),
            "X-Nexus-Node-ID": node_id,
        })
        assert retry_status == 200 and retried["status"] == "queued", retried
        with sqlite3.connect(tmp / "nexus_h0.db") as retry_db:
            retry_state = retry_db.execute(
                "SELECT status, attempts, node_id, lease_until FROM jobs WHERE job_id=?",
                (job_id,)).fetchone()
        assert retry_state == ("queued", 1, None, None), retry_state
        print("signed worker transient retry requeues without receipt: PASS")

        priv2, pub2, node2 = nc.load_or_create_node_key(tmp / "node2")
        register_body = {"node_id": node2, "pubkey_pem": pub2,
                         "models": ["athenea-e2b"], "nram": [], "region": "test"}
        register_path = "/nodes/register"
        status, registered = http_json(ROUTER + register_path, register_body, headers={
            **nc.sign_node_request(priv2, "POST", register_path, register_body),
            "X-Nexus-Node-ID": node2,
        })
        assert status == 200, registered
        next_path2 = f"/jobs/next?node_id={node2}"
        status, redispatched = http_json(ROUTER + next_path2, headers={
            **nc.sign_node_request(priv2, "GET", next_path2, {}),
            "X-Nexus-Node-ID": node2,
        })
        assert status == 200 and redispatched["job"]["job_id"] == job_id, redispatched
        stale_status, _ = http_json(ROUTER + invalid_path, invalid_result, headers={
            **nc.sign_node_request(priv, "POST", invalid_path, invalid_result),
            "X-Nexus-Node-ID": node_id,
        })
        assert stale_status == 403, "stale worker was allowed to submit after reassignment"
        receipt["node_id"] = node2
        good_sig = nc.sign_receipt(priv2, receipt)
        print("retry reassignment and stale-worker rejection: PASS")

        valid_result = {
            "status": "done", "receipt": receipt, "signature": good_sig,
            "dispatch_jwt": redispatched["job"]["dispatch_jwt"], "output_text": "control"}
        status, out = http_json(ROUTER + invalid_path, valid_result, headers={
            **nc.sign_node_request(priv2, "POST", invalid_path, valid_result),
            "X-Nexus-Node-ID": node2,
        })
        assert status == 200 and out["status"] == "done", f"valid receipt rejected: {out}"
        print("valid control receipt: ACCEPTED ok")
        status, state = http_json(ROUTER + f"/jobs/{job_id}")
        assert status == 200 and state["output_text"] == "control", state
        print("completed result retrieval: PASS")

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

        # Two H1 workers use node-signed requests and router-issued JWTs;
        # staggered mock inference forces the scheduler to distribute work.
        mock3_port, router3_port = 11439, 18083
        router3 = f"http://127.0.0.1:{router3_port}"
        tmp3 = Path(tempfile.mkdtemp(prefix="nexus-h0-test3-"))
        # Atenhea commonly publishes a :latest model ID while H0 job templates
        # use the canonical untagged name; both must route to the same worker.
        env3 = dict(os.environ, MOCK_INFERENCE_DELAY_MS="250",
                    MOCK_MODEL_ID="athenea-e2b:latest")
        p1 = subprocess.Popen([py, str(BASE / "mock_atenea.py"), "--port", str(mock3_port)], env=env3)
        p2 = subprocess.Popen([py, str(BASE / "router.py"), "--port", str(router3_port),
                               "--dir", str(tmp3)])
        h1_dir = BASE.parents[1] / "nexus-h1-node"
        p3 = subprocess.Popen([py, str(h1_dir / "worker2.py"), "--router", router3,
                               "--atenea", f"http://127.0.0.1:{mock3_port}",
                               "--node-dir", str(tmp3 / "node1")])
        p4 = subprocess.Popen([py, str(h1_dir / "worker2.py"), "--router", router3,
                               "--atenea", f"http://127.0.0.1:{mock3_port}",
                               "--node-dir", str(tmp3 / "node2")])
        procs += [p1, p2, p3, p4]
        assert wait_health(router3 + "/health"), "router3 did not start"
        time.sleep(3)
        h1_job_ids = []
        for i in range(12):
            status, created = http_json(router3 + "/jobs", {
                "kind": "inference", "model": "athenea-e2b", "nram": [],
                "messages": [{"role": "user", "content": f"Trabajo distribuido {i}."}],
                "params": {"max_tokens": 16},
            })
            assert status == 200, created
            h1_job_ids.append(created["job_id"])
        deadline = time.time() + 60
        h1_states = {}
        while time.time() < deadline:
            h1_states = {jid: http_json(router3 + f"/jobs/{jid}")[1] for jid in h1_job_ids}
            if all(state["status"] == "done" for state in h1_states.values()):
                break
            time.sleep(0.25)
        assert all(state["status"] == "done" and state.get("verified")
                   for state in h1_states.values()), h1_states
        served_by = {state["node_id"] for state in h1_states.values()}
        assert len(served_by) == 2, f"expected two active workers, got {served_by}"
        print("two H1 workers, signed dispatch and job distribution: PASS")

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
