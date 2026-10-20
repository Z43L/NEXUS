"""NEXUS H0 Router + ledger (single machine, no chain).

Implements spec v0.1 sections 3, 6.1 and 7 for H0:
- node registry (in SQLite), job queue, signed-receipt verification,
  metering cross-check and an aggregated ledger summary.

Stdlib HTTP server + sqlite3. Run:  python3 router.py --port 18080 --dir .
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import nexus_common as nc

BASE = Path(__file__).resolve().parent
_lock = threading.Lock()
_secret: bytes = b""
_db_path: Path = BASE / "nexus_h0.db"


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes(
            node_id TEXT PRIMARY KEY, pubkey_pem TEXT, models TEXT,
            nram TEXT, region TEXT, last_heartbeat TEXT, jobs_done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS jobs(
            job_id TEXT PRIMARY KEY, kind TEXT, model TEXT, nram TEXT,
            payload TEXT, status TEXT, node_id TEXT, created_at TEXT,
            finished_at TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS receipts(
            job_id TEXT PRIMARY KEY, node_id TEXT, receipt TEXT, signature TEXT,
            input_tokens INTEGER, output_tokens INTEGER, price_micro INTEGER,
            verified INTEGER, discrepancy_pct REAL);
        """)


def new_job_id(conn) -> str:
    cur = conn.execute("SELECT COUNT(*) FROM jobs")
    return f"job_{cur.fetchone()[0] + 1:06d}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep stdout clean
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    # -- GET -----------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path
        if path == "/health":
            return self._json({"ok": True, "service": "nexus-h0-router"})
        if path == "/jobs/next":
            node_id = (qs.get("node_id") or [""])[0]
            with _lock, db() as conn:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at, job_id LIMIT 1"
                ).fetchone()
                if row is None:
                    return self._json({"job": None})
                conn.execute("UPDATE jobs SET status='dispatched', node_id=? WHERE job_id=?",
                             (node_id, row["job_id"]))
                job = json.loads(row["payload"])
                job["job_id"] = row["job_id"]
                job["dispatch_token"] = nc.job_token(_secret, row["job_id"])
                return self._json({"job": job})
        if path.startswith("/jobs/"):
            job_id = path.split("/")[2]
            with db() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                if row is None:
                    return self._json({"error": "unknown job"}, 404)
                rec = conn.execute("SELECT * FROM receipts WHERE job_id=?", (job_id,)).fetchone()
                out = {"job_id": job_id, "status": row["status"], "node_id": row["node_id"],
                       "error": row["error"]}
                if rec:
                    out["receipt"] = json.loads(rec["receipt"])
                    out["verified"] = bool(rec["verified"])
                    out["discrepancy_pct"] = rec["discrepancy_pct"]
                return self._json(out)
        if path == "/ledger/summary":
            with db() as conn:
                rows = conn.execute("SELECT * FROM receipts").fetchall()
                jobs = conn.execute(
                    "SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()
                splits = {"node": 0, "nram_author": 0, "verification": 0, "burn": 0, "treasury": 0}
                tot_in = tot_out = tot_price = 0
                max_disc = 0.0
                for r in rows:
                    receipt = json.loads(r["receipt"])
                    for k in splits:
                        splits[k] += receipt["shares"].get(k, 0)
                    tot_in += r["input_tokens"]
                    tot_out += r["output_tokens"]
                    tot_price += r["price_micro"]
                    max_disc = max(max_disc, r["discrepancy_pct"] or 0.0)
                return self._json({
                    "jobs_by_status": {r["status"]: r["c"] for r in jobs},
                    "receipts": len(rows),
                    "verified_receipts": sum(1 for r in rows if r["verified"]),
                    "input_tokens": tot_in, "output_tokens": tot_out,
                    "total_price_micro_usd": tot_price,
                    "total_price_usd": tot_price / 1_000_000,
                    "splits_micro_usd": splits,
                    "max_discrepancy_pct": max_disc,
                })
        return self._json({"error": "not found"}, 404)

    # -- POST ----------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/nodes/register":
            body = self._body()
            with _lock, db() as conn:
                conn.execute(
                    "INSERT INTO nodes(node_id, pubkey_pem, models, nram, region, last_heartbeat) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET "
                    "pubkey_pem=excluded.pubkey_pem, models=excluded.models, nram=excluded.nram, "
                    "region=excluded.region, last_heartbeat=excluded.last_heartbeat",
                    (body["node_id"], body["pubkey_pem"], json.dumps(body.get("models", [])),
                     json.dumps(body.get("nram", [])), body.get("region", ""),
                     nc.utc_now_iso()))
            return self._json({"ok": True, "node_id": body["node_id"]})
        if path == "/nodes/heartbeat":
            body = self._body()
            with _lock, db() as conn:
                conn.execute("UPDATE nodes SET last_heartbeat=? WHERE node_id=?",
                             (nc.utc_now_iso(), body.get("node_id", "")))
            return self._json({"ok": True})
        if path == "/jobs":
            body = self._body()
            with _lock, db() as conn:
                job_id = new_job_id(conn)
                conn.execute(
                    "INSERT INTO jobs(job_id, kind, model, nram, payload, status, created_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (job_id, body.get("kind", "inference"), body.get("model", ""),
                     json.dumps(body.get("nram", [])), json.dumps(body), "queued",
                     nc.utc_now_iso()))
            return self._json({"job_id": job_id, "status": "queued"})
        if path.startswith("/jobs/") and path.endswith("/result"):
            job_id = path.split("/")[2]
            body = self._body()
            receipt = body.get("receipt")
            signature = body.get("signature", "")
            with _lock, db() as conn:
                job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                if job is None:
                    return self._json({"error": "unknown job"}, 404)
                node = conn.execute("SELECT * FROM nodes WHERE node_id=?",
                                    (job["node_id"],)).fetchone()
                if node is None:
                    return self._json({"error": "unknown node"}, 400)
                if body.get("status") == "rejected":
                    conn.execute("UPDATE jobs SET status='rejected', error=?, finished_at=? "
                                 "WHERE job_id=?",
                                 (body.get("error", "rejected"), nc.utc_now_iso(), job_id))
                    return self._json({"ok": True, "status": "rejected"})
                if receipt is None:
                    return self._json({"error": "missing receipt"}, 400)
                if not nc.check_job_token(_secret, job_id, body.get("dispatch_token", "")):
                    return self._json({"error": "bad dispatch token"}, 403)
                verified = nc.verify_receipt(node["pubkey_pem"], receipt, signature)
                if not verified:
                    return self._json({"error": "bad receipt signature"}, 400)
                # Metering cross-check (spec 7.1): engine-reported counts vs receipt.
                eng_in = receipt.get("engine_prompt_tokens", receipt["input_tokens"])
                eng_out = receipt.get("engine_completion_tokens", receipt["output_tokens"])
                base = max(eng_in + eng_out, 1)
                disc = abs((receipt["input_tokens"] + receipt["output_tokens"])
                           - (eng_in + eng_out)) / base * 100.0
                conn.execute(
                    "INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
                    (job_id, job["node_id"], json.dumps(receipt), signature,
                     receipt["input_tokens"], receipt["output_tokens"],
                     receipt["price_micro_usd"], 1, disc))
                conn.execute("UPDATE jobs SET status='done', finished_at=? WHERE job_id=?",
                             (nc.utc_now_iso(), job_id))
                conn.execute("UPDATE nodes SET jobs_done=jobs_done+1 WHERE node_id=?",
                             (job["node_id"],))
            return self._json({"ok": True, "status": "done", "discrepancy_pct": disc})
        return self._json({"error": "not found"}, 404)


def main():
    global _secret, _db_path
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--dir", default=str(BASE))
    args = ap.parse_args()
    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)
    _db_path = base / "nexus_h0.db"
    _secret = nc.load_router_secret(base)
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"nexus-h0 router on 127.0.0.1:{args.port} db={_db_path}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
