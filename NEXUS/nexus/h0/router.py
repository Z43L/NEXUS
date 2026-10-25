"""NEXUS H0 Router + ledger (single machine, no chain).

Implements spec v0.1 sections 3, 6.1 and 7 for H0:
- node registry (in SQLite), job queue, signed-receipt verification,
  metering cross-check and an aggregated ledger summary.

Stdlib HTTP server + sqlite3. Run:  python3 router.py --port 18080 --dir .
"""
from __future__ import annotations

import argparse
import datetime as dt
import hmac
import hashlib
import ipaddress
import json
import math
import sqlite3
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import nexus_common as nc

BASE = Path(__file__).resolve().parent
_lock = threading.Lock()
_router_private_key = None
_router_public_pem = ""
_db_path: Path = BASE / "nexus_h0.db"
_network_mode = False
_client_api_token = ""
_node_enrollment_token = ""
_content_retention_days = 30
MAX_ACTIVE_JOBS = 1000
MAX_JOB_MESSAGES = 256
MAX_JOB_CHARS = 300_000
MAX_JOB_ATTEMPTS = 3
JOB_LEASE_SECONDS = 1800


def models_match(requested: str, reported: str) -> bool:
    """Treat only the engine's explicit :latest alias as equivalent."""
    if not isinstance(requested, str) or not isinstance(reported, str):
        return False
    return (requested == reported
            or (requested.endswith(":latest") and requested[:-len(":latest")] == reported)
            or (reported.endswith(":latest") and reported[:-len(":latest")] == requested))


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA secure_delete=ON")
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
            finished_at TEXT, error TEXT, result_text TEXT,
            lease_until TEXT, attempts INTEGER DEFAULT 0,
            content_expires_at TEXT, content_purged INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS receipts(
            job_id TEXT PRIMARY KEY, node_id TEXT, receipt TEXT, signature TEXT,
            input_tokens INTEGER, output_tokens INTEGER, price_micro INTEGER,
            verified INTEGER, discrepancy_pct REAL);
        CREATE TABLE IF NOT EXISTS node_nonces(
            node_id TEXT NOT NULL, nonce TEXT NOT NULL, timestamp INTEGER NOT NULL,
            PRIMARY KEY(node_id, nonce));
        """)
        # Upgrade databases created by earlier H0 revisions in place.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        if "result_text" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN result_text TEXT")
        if "lease_until" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN lease_until TEXT")
            conn.execute("UPDATE jobs SET lease_until=? WHERE status='dispatched'",
                         (nc.utc_now_iso(),))
        if "attempts" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN attempts INTEGER DEFAULT 0")
        if "content_expires_at" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN content_expires_at TEXT")
        if "content_purged" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN content_purged INTEGER DEFAULT 0")
        # Backfill old rows from their creation time; malformed legacy dates
        # expire immediately rather than extending their retention silently.
        rows = conn.execute("SELECT job_id, created_at FROM jobs WHERE content_expires_at IS NULL").fetchall()
        now = utc_now_iso()
        for row in rows:
            try:
                created = dt.datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
                expiry = (created + dt.timedelta(days=_content_retention_days)).astimezone(dt.timezone.utc)
                expiry_iso = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
            except (AttributeError, TypeError, ValueError):
                expiry_iso = now
            conn.execute("UPDATE jobs SET content_expires_at=? WHERE job_id=?",
                         (expiry_iso, row["job_id"]))


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def purge_expired_content(conn: sqlite3.Connection, now_iso: str | None = None) -> int:
    """Idempotently erase prompts and output while preserving ledger metadata."""
    now_iso = now_iso or utc_now_iso()
    # Old queued/leased work cannot be dispatched without its prompt. Fail it
    # explicitly at the retention boundary; completed jobs keep their status.
    cur = conn.execute(
        "UPDATE jobs SET payload='{}', result_text=NULL, content_purged=1, "
        "status=CASE WHEN status IN ('queued','dispatched') THEN 'failed' ELSE status END, "
        "error=CASE WHEN status IN ('queued','dispatched') THEN "
        "'content expired under retention policy' ELSE error END, "
        "finished_at=CASE WHEN status IN ('queued','dispatched') THEN ? ELSE finished_at END, "
        "lease_until=CASE WHEN status IN ('queued','dispatched') THEN NULL ELSE lease_until END "
        "WHERE content_purged=0 AND content_expires_at IS NOT NULL "
        "AND content_expires_at <= ?", (now_iso, now_iso))
    return cur.rowcount


def _purge_loop() -> None:
    while True:
        try:
            with db() as conn:
                purged = purge_expired_content(conn)
            if purged:
                print(f"privacy retention purged content from {purged} jobs", flush=True)
        except sqlite3.Error:
            pass
        time.sleep(60)


def _read_secret_file(path: str, label: str) -> str:
    secret_path = Path(path)
    try:
        if secret_path.stat().st_mode & 0o077:
            raise ValueError(f"{label} file permissions must be 0600")
        secret = secret_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"cannot read {label} file") from exc
    if len(secret) < 32:
        raise ValueError(f"{label} must contain at least 32 characters")
    return secret


def validate_bind_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("remote bind host must be a literal private or loopback IP") from exc
    private_ranges = (ipaddress.ip_network("10.0.0.0/8"),
                      ipaddress.ip_network("172.16.0.0/12"),
                      ipaddress.ip_network("192.168.0.0/16"))
    if not address.is_loopback and not any(address in network for network in private_ranges):
        raise ValueError("remote bind host must be a private or loopback IP, never a public interface")
    return str(address)


def new_job_id(conn) -> str:
    cur = conn.execute("SELECT COUNT(*) FROM jobs")
    return f"job_{cur.fetchone()[0] + 1:06d}"


def recover_expired_jobs(conn, now_iso: str | None = None) -> int:
    """Requeue expired worker leases or fail jobs that exhausted retries."""
    now_iso = now_iso or nc.utc_now_iso()
    expired = conn.execute(
        "SELECT job_id, attempts FROM jobs WHERE status='dispatched' "
        "AND lease_until IS NOT NULL AND lease_until < ?", (now_iso,)).fetchall()
    for row in expired:
        if int(row["attempts"] or 0) >= MAX_JOB_ATTEMPTS:
            conn.execute("UPDATE jobs SET status='failed', error=?, finished_at=?, lease_until=NULL "
                         "WHERE job_id=?", ("worker lease expired after retry limit", now_iso, row["job_id"]))
        else:
            conn.execute("UPDATE jobs SET status='queued', node_id=NULL, error=NULL, lease_until=NULL "
                         "WHERE job_id=?", (row["job_id"],))
    return len(expired)


def requeue_dispatched_job(conn: sqlite3.Connection, job_id: str, error: str,
                           now_iso: str | None = None) -> str | None:
    """Apply a worker-requested transient retry to its dispatched job."""
    now_iso = now_iso or nc.utc_now_iso()
    row = conn.execute("SELECT attempts FROM jobs WHERE job_id=? AND status='dispatched'",
                       (job_id,)).fetchone()
    if row is None:
        return None
    reason = (error.strip() or "transient worker failure")[:500]
    attempts = int(row["attempts"] or 0)
    if attempts >= MAX_JOB_ATTEMPTS:
        conn.execute("UPDATE jobs SET status='failed', node_id=NULL, lease_until=NULL, "
                     "error=?, finished_at=? WHERE job_id=? AND status='dispatched'",
                     (f"retry limit exhausted after {attempts} attempts: {reason}", now_iso, job_id))
        return "failed"
    conn.execute("UPDATE jobs SET status='queued', node_id=NULL, lease_until=NULL, "
                 "error=?, finished_at=NULL WHERE job_id=? AND status='dispatched'",
                 (f"transient worker failure on attempt {attempts}: {reason}", job_id))
    return "queued"


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

    def _text(self, value: str, status=200, content_type="text/plain; charset=utf-8"):
        body = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0:
            raise ValueError("invalid Content-Length")
        if length > 1_048_576:
            raise ValueError("request body exceeds 1 MiB")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def _create_job(self, body: dict) -> str:
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages or len(messages) > MAX_JOB_MESSAGES:
            raise ValueError(f"messages must contain 1 to {MAX_JOB_MESSAGES} items")
        if any(not isinstance(m, dict) or m.get("role") not in
               ("system", "user", "assistant") or not isinstance(m.get("content"), str)
               for m in messages):
            raise ValueError("each message requires a supported role and text content")
        if sum(len(m["content"]) for m in messages) > MAX_JOB_CHARS:
            raise ValueError(f"combined message content exceeds {MAX_JOB_CHARS} characters")
        nram = body.get("nram", [])
        if (not isinstance(nram, list)
                or any(not isinstance(author, str) or not author for author in nram)
                or len(set(nram)) != len(nram)):
            raise ValueError("nram must be a list of unique non-empty author identifiers")
        model = body.get("model", "")
        if not isinstance(model, str) or len(model) > 120:
            raise ValueError("model must be a string of at most 120 characters")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        try:
            max_tokens = int(params.get("max_tokens", 256))
            temperature = float(params.get("temperature", 0.3))
        except (TypeError, ValueError):
            raise ValueError("max_tokens and temperature must be numeric") from None
        if not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be between 1 and 4096")
        if not math.isfinite(temperature) or not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        with _lock, db() as conn:
            recover_expired_jobs(conn)
            purge_expired_content(conn)
            active = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','dispatched')"
            ).fetchone()[0]
            if active >= MAX_ACTIVE_JOBS:
                raise OverflowError("job queue is at capacity")
            job_id = new_job_id(conn)
            created_at = utc_now_iso()
            content_expires_at = (
                dt.datetime.now(dt.timezone.utc)
                + dt.timedelta(days=_content_retention_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            conn.execute(
                "INSERT INTO jobs(job_id, kind, model, nram, payload, status, created_at, "
                "content_expires_at, content_purged) VALUES(?,?,?,?,?,?,?,?,0)",
                (job_id, body.get("kind", "inference"), body.get("model", ""),
                json.dumps(nram), json.dumps(body), "queued",
                 created_at, content_expires_at))
        return job_id

    def _consume_node_signature(self, node_id: str, public_pem: str, body: dict) -> bool:
        if self.headers.get("X-Nexus-Node-ID", "") != node_id:
            return False
        timestamp = self.headers.get("X-Nexus-Timestamp", "")
        nonce = self.headers.get("X-Nexus-Nonce", "")
        signature = self.headers.get("X-Nexus-Signature", "")
        if not nc.verify_node_request(public_pem, self.command, self.path, body,
                                      timestamp, nonce, signature):
            return False
        with _lock, db() as conn:
            conn.execute("DELETE FROM node_nonces WHERE timestamp < ?",
                         (int(time.time()) - 120,))
            try:
                conn.execute("INSERT INTO node_nonces(node_id, nonce, timestamp) VALUES(?,?,?)",
                             (node_id, nonce, int(timestamp)))
            except sqlite3.IntegrityError:
                return False
        return True

    def _authorize_client(self) -> bool:
        if not _network_mode:
            return True
        scheme, _, supplied = self.headers.get("Authorization", "").partition(" ")
        return (scheme.lower() == "bearer" and bool(supplied)
                and hmac.compare_digest(supplied.encode("utf-8"),
                                        _client_api_token.encode("utf-8")))

    def _requires_client_auth(self, method: str, path: str) -> bool:
        if not _network_mode:
            return False
        if method == "GET":
            return (path in ("/v1/models", "/metrics", "/ledger/summary")
                    or (path.startswith("/jobs/") and path != "/jobs/next"))
        if method == "POST":
            return path in ("/v1/chat/completions", "/jobs")
        return False

    # -- GET -----------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path
        with _lock, db() as conn:
            purge_expired_content(conn)
        if self._requires_client_auth("GET", path) and not self._authorize_client():
            return self._json({"error": "unauthorized"}, 401)
        if path == "/health":
            return self._json({"ok": True, "service": "nexus-h0-router"})
        if path == "/ready":
            try:
                with db() as conn:
                    conn.execute("SELECT 1").fetchone()
                return self._json({"ok": True, "service": "nexus-h0-router"})
            except sqlite3.Error:
                return self._json({"ok": False, "service": "nexus-h0-router"}, 503)
        if path == "/metrics":
            with db() as conn:
                job_rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
                receipts = conn.execute("SELECT COUNT(*) AS n, SUM(input_tokens) AS input, "
                                        "SUM(output_tokens) AS output FROM receipts "
                                        "WHERE verified=1").fetchone()
                nodes = conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()["n"]
            metrics = [
                "# HELP nexus_h0_jobs Current jobs grouped by state.",
                "# TYPE nexus_h0_jobs gauge",
            ]
            metrics.extend(f'nexus_h0_jobs{{status="{row["status"]}"}} {row["n"]}'
                           for row in job_rows)
            metrics += [
                "# HELP nexus_h0_nodes_registered Registered worker nodes.",
                "# TYPE nexus_h0_nodes_registered gauge",
                f"nexus_h0_nodes_registered {nodes}",
                "# HELP nexus_h0_receipts_verified_total Verified receipts.",
                "# TYPE nexus_h0_receipts_verified_total counter",
                f"nexus_h0_receipts_verified_total {receipts['n'] or 0}",
                "# HELP nexus_h0_tokens_total Tokens reported by verified receipts.",
                "# TYPE nexus_h0_tokens_total counter",
                f'nexus_h0_tokens_total{{direction="input"}} {receipts["input"] or 0}',
                f'nexus_h0_tokens_total{{direction="output"}} {receipts["output"] or 0}',
            ]
            return self._text("\n".join(metrics) + "\n",
                              content_type="text/plain; version=0.0.4; charset=utf-8")
        if path == "/v1/models":
            with db() as conn:
                rows = conn.execute("SELECT models FROM nodes ORDER BY node_id").fetchall()
            models = sorted({model for row in rows for model in json.loads(row["models"] or "[]")})
            return self._json({"object": "list", "data": [
                {"id": model, "object": "model", "owned_by": "nexus-network"}
                for model in models
            ]})
        if path == "/jobs/next":
            node_id = (qs.get("node_id") or [""])[0]
            with db() as conn:
                registered = conn.execute("SELECT pubkey_pem FROM nodes WHERE node_id=?",
                                          (node_id,)).fetchone()
            if registered is None:
                return self._json({"error": "node is not registered"}, 403)
            if not self._consume_node_signature(node_id, registered["pubkey_pem"], {}):
                return self._json({"error": "invalid or replayed node signature"}, 401)
            with _lock, db() as conn:
                recover_expired_jobs(conn)
                node = conn.execute("SELECT models FROM nodes WHERE node_id=?",
                                    (node_id,)).fetchone()
                if node is None:
                    return self._json({"error": "node is not registered"}, 403)
                node_models = sorted(json.loads(node["models"] or "[]"))
                if node_models:
                    compatible_models = set(node_models)
                    for model_id in node_models:
                        if model_id.endswith(":latest"):
                            compatible_models.add(model_id[:-len(":latest")])
                        else:
                            compatible_models.add(model_id + ":latest")
                    compatible_models = sorted(compatible_models)
                    placeholders = ",".join("?" for _ in compatible_models)
                    query = ("SELECT * FROM jobs WHERE status='queued' "
                             f"AND (model='' OR model IN ({placeholders})) "
                             "ORDER BY created_at, job_id LIMIT 1")
                    row = conn.execute(query, compatible_models).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM jobs WHERE status='queued' AND model='' "
                        "ORDER BY created_at, job_id LIMIT 1").fetchone()
                if row is None:
                    return self._json({"job": None})
                lease_until = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                            time.gmtime(time.time() + JOB_LEASE_SECONDS))
                conn.execute("UPDATE jobs SET status='dispatched', node_id=?, lease_until=?, "
                             "attempts=attempts+1 WHERE job_id=?",
                             (node_id, lease_until, row["job_id"]))
                job = json.loads(row["payload"])
                job["job_id"] = row["job_id"]
                job["dispatch_jwt"] = nc.issue_job_jwt(
                    _router_private_key, node_id, row["job_id"], ttl_s=JOB_LEASE_SECONDS)
                return self._json({"job": job})
        if path.startswith("/jobs/"):
            job_id = path.split("/")[2]
            with db() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                if row is None:
                    return self._json({"error": "unknown job"}, 404)
                rec = conn.execute("SELECT * FROM receipts WHERE job_id=?", (job_id,)).fetchone()
                out = {"job_id": job_id, "status": row["status"], "node_id": row["node_id"],
                       "error": row["error"], "output_text": row["result_text"],
                       "content_expired": bool(row["content_purged"])}
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
        if self._requires_client_auth("POST", path) and not self._authorize_client():
            return self._json({"error": "unauthorized"}, 401)
        with _lock, db() as conn:
            purge_expired_content(conn)
        try:
            body = self._body()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._json({"error": "invalid_request", "detail": str(exc)}, 400)
        if path == "/v1/chat/completions":
            if not self.server.acquire_chat_slot():
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Retry-After", "1")
                payload = json.dumps({"error": {"type": "server_busy",
                                                  "message": "chat concurrency limit reached"}}).encode("utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            try:
                return self._handle_chat_completion(body)
            finally:
                self.server.release_chat_slot()
        if path == "/nodes/register":
            try:
                expected_node_id = nc.node_id_from_public_pem(body["pubkey_pem"])
            except (KeyError, ValueError, TypeError, UnicodeError):
                return self._json({"error": "invalid node public key"}, 400)
            if body.get("node_id") != expected_node_id:
                return self._json({"error": "node_id does not match public key"}, 400)
            if _network_mode:
                with db() as conn:
                    existing = conn.execute("SELECT 1 FROM nodes WHERE node_id=?",
                                             (expected_node_id,)).fetchone()
                supplied_token = body.get("enrollment_token", "")
                if (existing is None and (not isinstance(supplied_token, str)
                        or not hmac.compare_digest(supplied_token.encode("utf-8"),
                                                   _node_enrollment_token.encode("utf-8")))):
                    return self._json({"error": "invalid enrollment token"}, 401)
            if not self._consume_node_signature(expected_node_id, body["pubkey_pem"], body):
                return self._json({"error": "invalid or replayed node signature"}, 401)
            with _lock, db() as conn:
                conn.execute(
                    "INSERT INTO nodes(node_id, pubkey_pem, models, nram, region, last_heartbeat) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(node_id) DO UPDATE SET "
                    "pubkey_pem=excluded.pubkey_pem, models=excluded.models, nram=excluded.nram, "
                    "region=excluded.region, last_heartbeat=excluded.last_heartbeat",
                    (body["node_id"], body["pubkey_pem"], json.dumps(body.get("models", [])),
                     json.dumps(body.get("nram", [])), body.get("region", ""),
                     nc.utc_now_iso()))
            return self._json({"ok": True, "node_id": body["node_id"],
                               "router_pubkey_pem": _router_public_pem})
        if path == "/nodes/heartbeat":
            node_id = body.get("node_id", "")
            with db() as conn:
                node = conn.execute("SELECT pubkey_pem FROM nodes WHERE node_id=?",
                                    (node_id,)).fetchone()
            if node is None:
                return self._json({"error": "unknown node"}, 404)
            if not self._consume_node_signature(node_id, node["pubkey_pem"], body):
                return self._json({"error": "invalid or replayed node signature"}, 401)
            with _lock, db() as conn:
                conn.execute("UPDATE nodes SET last_heartbeat=? WHERE node_id=?",
                             (nc.utc_now_iso(), node_id))
            return self._json({"ok": True})
        if path == "/jobs":
            try:
                job_id = self._create_job(body)
            except OverflowError as exc:
                return self._json({"error": "queue_full", "detail": str(exc)}, 429)
            except ValueError as exc:
                return self._json({"error": "invalid_request", "detail": str(exc)}, 400)
            return self._json({"job_id": job_id, "status": "queued"})
        if path.startswith("/jobs/") and path.endswith("/result"):
            return self._handle_worker_result(path, body)
        return self._json({"error": "not found"}, 404)

    def _handle_chat_completion(self, body: dict):
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": "messages must be a non-empty array"}}, 400)
        if body.get("stream", False):
            return self._json({"error": {"type": "unsupported_parameter",
                                          "message": "streaming is not supported by H0"}}, 400)
        if any(not isinstance(m, dict) or m.get("role") not in
               ("system", "user", "assistant") or not isinstance(m.get("content"), str)
               for m in messages):
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": "each message requires a supported role and text content"}}, 400)
        tools = body.get("tools")
        if tools:
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": "remote tools are not supported"}}, 400)
        max_tokens = body.get("max_tokens", body.get("max_completion_tokens", 256))
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": "max_tokens must be an integer"}}, 400)
        if not 1 <= max_tokens <= 4096:
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": "max_tokens must be between 1 and 4096"}}, 400)
        timeout_s = body.get("timeout_s", 300)
        try:
            timeout_s = min(max(int(timeout_s), 1), 1800)
        except (TypeError, ValueError):
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": "timeout_s must be an integer"}}, 400)
        job_payload = {
            "kind": "inference", "model": body.get("model", ""), "nram": [],
            "messages": messages,
            "params": {"temperature": body.get("temperature", 0.3),
                       "max_tokens": max_tokens, "stream": False},
        }
        try:
            job_id = self._create_job(job_payload)
        except OverflowError as exc:
            return self._json({"error": {"type": "queue_full", "message": str(exc)}}, 429)
        except ValueError as exc:
            return self._json({"error": {"type": "invalid_request_error",
                                          "message": str(exc)}}, 400)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with db() as conn:
                row = conn.execute("SELECT status, result_text, error FROM jobs WHERE job_id=?",
                                   (job_id,)).fetchone()
            if row["status"] == "done":
                with db() as conn:
                    rec = conn.execute("SELECT receipt FROM receipts WHERE job_id=?",
                                       (job_id,)).fetchone()
                usage = json.loads(rec["receipt"]) if rec else {}
                return self._json({
                    "id": job_id, "object": "chat.completion", "created": int(time.time()),
                    "model": body.get("model", ""),
                    "choices": [{"index": 0, "message": {"role": "assistant",
                                  "content": row["result_text"] or ""}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": usage.get("input_tokens", 0),
                              "completion_tokens": usage.get("output_tokens", 0),
                              "total_tokens": usage.get("input_tokens", 0) +
                                              usage.get("output_tokens", 0)},
                })
            if row["status"] in ("rejected", "failed"):
                return self._json({"error": {"type": "job_failed", "job_id": job_id,
                                              "message": row["error"] or row["status"]}}, 502)
            time.sleep(0.1)
        return self._json({"error": {"type": "job_timeout", "job_id": job_id,
                                      "message": "job is still pending; poll /jobs/{job_id}"}}, 504)
    def _handle_worker_result(self, path: str, body: dict):
        job_id = path.split("/")[2]
        receipt = body.get("receipt")
        signature = body.get("signature", "")
        request_node_id = self.headers.get("X-Nexus-Node-ID", "")
        with db() as conn:
            dispatched = conn.execute("SELECT node_id FROM jobs WHERE job_id=?",
                                      (job_id,)).fetchone()
            signed_node = conn.execute("SELECT pubkey_pem FROM nodes WHERE node_id=?",
                                       (request_node_id,)).fetchone()
        if dispatched is None:
            return self._json({"error": "unknown job"}, 404)
        if request_node_id != dispatched["node_id"] or signed_node is None:
            return self._json({"error": "node is not assigned to this job"}, 403)
        if not self._consume_node_signature(request_node_id, signed_node["pubkey_pem"], body):
            return self._json({"error": "invalid or replayed node signature"}, 401)
        with _lock, db() as conn:
            job = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if job is None:
                return self._json({"error": "unknown job"}, 404)
            node = conn.execute("SELECT * FROM nodes WHERE node_id=?",
                                (job["node_id"],)).fetchone()
            if node is None:
                return self._json({"error": "unknown node"}, 400)
            try:
                nc.verify_job_jwt(_router_public_pem, body.get("dispatch_jwt", ""),
                                  job["node_id"], job_id)
            except ValueError as exc:
                return self._json({"error": "bad dispatch JWT", "detail": str(exc)}, 403)
            if job["status"] not in ("dispatched",):
                return self._json({"error": "job is not awaiting a result"}, 409)
            if body.get("status") == "retry":
                error = body.get("error", "transient worker failure")
                if not isinstance(error, str):
                    return self._json({"error": "retry error must be a string"}, 400)
                retry_status = requeue_dispatched_job(conn, job_id, error)
                if retry_status is None:
                    return self._json({"error": "job is not awaiting a result"}, 409)
                return self._json({"ok": True, "status": retry_status,
                                   "attempts": job["attempts"],
                                   "max_attempts": MAX_JOB_ATTEMPTS})
            if body.get("status") == "rejected":
                conn.execute("UPDATE jobs SET status='rejected', error=?, finished_at=? "
                             ", lease_until=NULL WHERE job_id=?",
                             (body.get("error", "rejected"), nc.utc_now_iso(), job_id))
                return self._json({"ok": True, "status": "rejected"})
            if receipt is None:
                return self._json({"error": "missing receipt"}, 400)
            verified = nc.verify_receipt(node["pubkey_pem"], receipt, signature)
            if not verified:
                return self._json({"error": "bad receipt signature"}, 400)
            if receipt.get("job_id") != job_id or receipt.get("node_id") != job["node_id"]:
                return self._json({"error": "receipt does not match dispatched job/node"}, 400)
            requested_model = job["model"] or ""
            if requested_model and not models_match(requested_model, receipt.get("model")):
                return self._json({"error": "receipt model does not match requested job model"}, 400)
            try:
                requested_nram = json.loads(job["nram"] or "[]")
            except (TypeError, json.JSONDecodeError):
                return self._json({"error": "stored job NRAM metadata is invalid"}, 500)
            if receipt.get("nram_used") != requested_nram:
                return self._json({"error": "receipt NRAM authors do not match the requested job"}, 400)
            output_text = body.get("output_text")
            if not isinstance(output_text, str):
                return self._json({"error": "missing output_text"}, 400)
            if hashlib.sha256(output_text.encode("utf-8")).hexdigest() != receipt.get("output_sha256"):
                return self._json({"error": "output hash does not match receipt"}, 400)
            try:
                input_tokens = int(receipt["input_tokens"])
                output_tokens = int(receipt["output_tokens"])
                price_micro = int(receipt["price_micro_usd"])
                scaffolding_tokens = int(receipt.get("scaffolding_tokens", 0))
            except (KeyError, TypeError, ValueError):
                return self._json({"error": "receipt has invalid metering fields"}, 400)
            if min(input_tokens, output_tokens, price_micro, scaffolding_tokens) < 0:
                return self._json({"error": "receipt metering fields cannot be negative"}, 400)
            if nc.price_micro_usd(input_tokens, output_tokens) != price_micro:
                return self._json({"error": "receipt price does not match token usage"}, 400)
            expected_shares = nc.split_payment(price_micro, bool(receipt.get("nram_used")))
            if receipt.get("shares") != expected_shares:
                return self._json({"error": "receipt payment split is invalid"}, 400)
            # Metering cross-check (spec 7.1): engine-reported counts vs receipt.
            eng_in = receipt.get("engine_prompt_tokens", receipt["input_tokens"])
            eng_out = receipt.get("engine_completion_tokens", receipt["output_tokens"])
            # Metering amendment: the engine renders fixed per-request
            # scaffolding (agent instruction + training-tool schema) into
            # its prompt count. The worker calibrates it at startup and
            # reports it per receipt; it is node overhead, never billed,
            # and is subtracted before comparing like with like.
            eng_in_adj = max(0, eng_in - scaffolding_tokens)
            base = max(eng_in_adj + eng_out, 1)
            disc = abs((input_tokens + output_tokens)
                       - (eng_in_adj + eng_out)) / base * 100.0
            if disc > 1.0:
                return self._json({"error": "receipt metering discrepancy exceeds 1%",
                                   "discrepancy_pct": disc}, 400)
            conn.execute(
                "INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, job["node_id"], json.dumps(receipt), signature,
                 input_tokens, output_tokens, price_micro, 1, disc))
            conn.execute("UPDATE jobs SET status='done', finished_at=?, result_text=?, "
                         "lease_until=NULL WHERE job_id=?",
                         (nc.utc_now_iso(), output_text, job_id))
            conn.execute("UPDATE nodes SET jobs_done=jobs_done+1 WHERE node_id=?",
                         (job["node_id"],))
        return self._json({"ok": True, "status": "done", "discrepancy_pct": disc})


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server with a hard cap on simultaneous request handlers."""
    daemon_threads = True

    def __init__(self, server_address, handler_class, max_threads=64):
        self._handler_slots = threading.BoundedSemaphore(max_threads)
        worker_reserve = min(8, max(1, max_threads // 8))
        self._chat_slots = threading.BoundedSemaphore(max_threads - worker_reserve)
        super().__init__(server_address, handler_class)

    def acquire_chat_slot(self) -> bool:
        return self._chat_slots.acquire(blocking=False)

    def release_chat_slot(self) -> None:
        self._chat_slots.release()

    def process_request(self, request, client_address):
        if not self._handler_slots.acquire(blocking=False):
            body = b'{"error":{"type":"server_busy","message":"router handler capacity reached"}}'
            response = (b"HTTP/1.1 503 Service Unavailable\r\n"
                        b"Content-Type: application/json\r\n"
                        b"Retry-After: 1\r\n"
                        b"Connection: close\r\n"
                        + f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                        + body)
            try:
                request.sendall(response)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._handler_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._handler_slots.release()


def main():
    global _router_private_key, _router_public_pem, _db_path
    global _network_mode, _client_api_token, _node_enrollment_token, _content_retention_days
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--max-threads", type=int, default=64)
    ap.add_argument("--dir", default=str(BASE))
    ap.add_argument("--mode", choices=("local", "remote"), default="local")
    ap.add_argument("--host", default="127.0.0.1",
                    help="remote mode only: a private or loopback IPv4 address")
    ap.add_argument("--tls-cert", help="TLS server certificate PEM path")
    ap.add_argument("--tls-key", help="TLS private key PEM path")
    ap.add_argument("--client-token-file", help="0600 file containing the chat/models bearer token")
    ap.add_argument("--enrollment-token-file", help="0600 file authorizing new node keys")
    ap.add_argument("--content-retention-days", type=int, default=30)
    args = ap.parse_args()
    if not 2 <= args.max_threads <= 512:
        ap.error("--max-threads must be between 2 and 512")
    if not 1 <= args.content_retention_days <= 3650:
        ap.error("--content-retention-days must be between 1 and 3650")
    _content_retention_days = args.content_retention_days

    tls_context = None
    if args.mode == "remote":
        if not all((args.tls_cert, args.tls_key, args.client_token_file,
                    args.enrollment_token_file)):
            ap.error("remote mode requires --tls-cert, --tls-key, --client-token-file, "
                     "and --enrollment-token-file")
        try:
            host = validate_bind_host(args.host)
            if ipaddress.ip_address(host).version != 4:
                raise ValueError("remote mode currently supports IPv4 bind addresses only")
            _client_api_token = _read_secret_file(args.client_token_file, "client token")
            _node_enrollment_token = _read_secret_file(args.enrollment_token_file, "enrollment token")
            if Path(args.tls_key).stat().st_mode & 0o077:
                raise ValueError("TLS private key file permissions must be 0600")
            tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls_context.minimum_version = ssl.TLSVersion.TLSv1_2
            tls_context.load_cert_chain(args.tls_cert, args.tls_key)
        except (ValueError, OSError, ssl.SSLError) as exc:
            ap.error(f"invalid remote security configuration: {exc}")
        _network_mode = True
        bind_host = host
    else:
        if any((args.tls_cert, args.tls_key, args.client_token_file,
                args.enrollment_token_file)):
            ap.error("TLS/token options require --mode remote")
        if args.host != "127.0.0.1":
            ap.error("local mode is fixed to 127.0.0.1; use remote mode for a private network address")
        _network_mode = False
        bind_host = "127.0.0.1"

    base = Path(args.dir)
    base.mkdir(parents=True, exist_ok=True)
    _db_path = base / "nexus_h0.db"
    _router_private_key, _router_public_pem = nc.load_or_create_router_key(base)
    init_db()
    with db() as conn:
        purge_expired_content(conn)
    threading.Thread(target=_purge_loop, daemon=True).start()
    server = BoundedThreadingHTTPServer((bind_host, args.port), Handler,
                                        max_threads=args.max_threads)
    if tls_context:
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
    print(f"nexus-h0 router mode={args.mode} on {bind_host}:{args.port} db={_db_path} "
          f"content_retention_days={_content_retention_days}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
