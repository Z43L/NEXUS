"""Local integration checks for remote-mode TLS, auth, enrolment and retention.

Run with the H0 environment (cryptography installed):
    python3 test_secure_remote.py

The Router binds only to 127.0.0.1 in this test; no remote interface is opened.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

BASE = Path(__file__).resolve().parent
H1_DIR = BASE.parent.parent / "nexus-h1-node"
sys.path.insert(0, str(BASE))
sys.path.append(str(H1_DIR))
import nexus_common as nc  # noqa: E402
import router  # noqa: E402
import worker2  # noqa: E402


def write_secret(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(0o600)


def make_ca(tmp: Path, name: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
                           critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True,
                                         crl_sign=True, encipher_only=None, decipher_only=None),
                           critical=True)
            .sign(key, hashes.SHA256()))
    cert_path = tmp / f"{name}.crt"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert, cert_path


def make_server_cert(tmp: Path, ca_key, ca_cert):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(
                __import__("ipaddress").ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                           critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_cert.public_key()), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    cert_path, key_path = tmp / "router.crt", tmp / "router.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    key_path.chmod(0o600)
    return cert_path, key_path


def get(url: str, context, token: str | None = None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=2, context=context) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_migration_and_purge() -> None:
    with tempfile.TemporaryDirectory(prefix="nexus-retention-") as folder:
        path = Path(folder) / "old.db"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE jobs(job_id TEXT PRIMARY KEY, kind TEXT, model TEXT, nram TEXT, "
                     "payload TEXT, status TEXT, node_id TEXT, created_at TEXT, finished_at TEXT, "
                     "error TEXT, result_text TEXT, lease_until TEXT, attempts INTEGER DEFAULT 0)")
        conn.execute("INSERT INTO jobs(job_id, created_at, payload, result_text, status) "
                     "VALUES('old','2020-01-01T00:00:00Z','prompt','answer','done')")
        conn.execute("INSERT INTO jobs(job_id, created_at, payload, result_text, status) "
                     "VALUES('old-pending','2020-01-01T00:00:00Z','pending prompt',NULL,'queued')")
        conn.commit(); conn.close()

        previous_db = router._db_path
        router._db_path = path
        try:
            router.init_db()
            with router.db() as conn:
                row = conn.execute("SELECT content_expires_at, content_purged FROM jobs "
                                   "WHERE job_id='old'").fetchone()
                assert row["content_expires_at"] == "2020-01-31T00:00:00Z", dict(row)
                assert row["content_purged"] == 0
                conn.execute("INSERT INTO receipts(job_id, receipt) VALUES('old','receipt-metadata')")
                assert router.purge_expired_content(conn, "2026-10-25T00:00:00Z") == 2
                assert router.purge_expired_content(conn, "2026-10-25T00:00:00Z") == 0
                row = conn.execute("SELECT status, payload, result_text, content_purged "
                                   "FROM jobs WHERE job_id='old'").fetchone()
                assert row["status"] == "done" and row["payload"] == "{}"
                assert row["result_text"] is None and row["content_purged"] == 1
                pending = conn.execute("SELECT status, error, payload FROM jobs "
                                       "WHERE job_id='old-pending'").fetchone()
                assert tuple(pending) == ("failed", "content expired under retention policy", "{}")
                assert conn.execute("SELECT receipt FROM receipts WHERE job_id='old'").fetchone()[0] == "receipt-metadata"
        finally:
            router._db_path = previous_db
    print("legacy schema migration + idempotent content purge: PASS")


def test_purge_scrubs_live_database_file() -> None:
    with tempfile.TemporaryDirectory(prefix="nexus-secure-delete-") as folder:
        path = Path(folder) / "retention.db"
        previous_db = router._db_path
        router._db_path = path
        prompt_marker = "UNIQUE_PROMPT_RETENTION_MARKER_" + "p" * 96
        output_marker = "UNIQUE_OUTPUT_RETENTION_MARKER_" + "o" * 96
        try:
            router.init_db()
            conn = router.db()
            try:
                assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
                assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
                conn.execute(
                    "INSERT INTO jobs(job_id, created_at, payload, result_text, status, "
                    "content_expires_at) VALUES(?,?,?,?,?,?)",
                    ("retention", "2020-01-01T00:00:00Z", prompt_marker,
                     output_marker, "done", "2000-01-01T00:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()
            assert prompt_marker.encode() in path.read_bytes()
            assert output_marker.encode() in path.read_bytes()

            conn = router.db()
            try:
                assert router.purge_expired_content(conn, "2026-10-25T00:00:00Z") == 1
                conn.commit()
            finally:
                conn.close()

            database_bytes = path.read_bytes()
            assert prompt_marker.encode() not in database_bytes
            assert output_marker.encode() not in database_bytes
            assert not Path(str(path) + "-journal").exists()
        finally:
            router._db_path = previous_db
    print("live SQLite file scrub on content expiry: PASS")


def test_secure_remote() -> None:
    from unittest.mock import patch

    with patch.object(router.socket, "getaddrinfo", return_value=[
        (router.socket.AF_INET, router.socket.SOCK_STREAM, 6, "", ("172.18.0.2", 0)),
    ]):
        assert router.resolve_bind_host("auto") == "172.18.0.2"
    for unsafe_address in ("127.0.0.1", "169.254.1.2", "8.8.8.8"):
        with patch.object(router.socket, "getaddrinfo", return_value=[
            (router.socket.AF_INET, router.socket.SOCK_STREAM, 6, "", (unsafe_address, 0)),
        ]):
            try:
                router.resolve_bind_host("auto")
            except ValueError:
                pass
            else:
                raise AssertionError(f"container auto bind accepted unsafe address {unsafe_address}")

    with tempfile.TemporaryDirectory(prefix="nexus-remote-") as folder:
        tmp = Path(folder)
        try:
            worker2.Worker("http://192.168.1.20:18080", "http://127.0.0.1:11436",
                           tmp / "insecure-node", "")
        except ValueError:
            pass
        else:
            raise AssertionError("worker allowed plaintext Router traffic off loopback")
        try:
            worker2.Worker("http://127.0.0.1:18080", "http://192.168.1.20:11436",
                           tmp / "insecure-engine-node", "")
        except ValueError:
            pass
        else:
            raise AssertionError("worker allowed plaintext Atenhea traffic to a remote host")
        try:
            worker2.Worker("http://127.0.0.1:18080", "http://host.docker.internal:11436",
                           tmp / "desktop-engine-node", "")
        except ValueError:
            pass
        else:
            raise AssertionError("worker allowed plaintext Atenhea traffic to host.docker.internal")
        engine_key = tmp / "engine.key"
        write_secret(engine_key, "engine-" + os.urandom(16).hex())
        worker2.Worker("http://127.0.0.1:18080", "https://engine.example:11436",
                       tmp / "tls-engine-node", "", atenea_api_key_file=str(engine_key))
        ca_key, ca_cert, ca_path = make_ca(tmp, "NEXUS-test-CA")
        wrong_ca_key, wrong_ca_cert, wrong_ca_path = make_ca(tmp, "NEXUS-wrong-CA")
        cert_path, key_path = make_server_cert(tmp, ca_key, ca_cert)
        api_token = "api-" + os.urandom(32).hex()
        api_path = tmp / "api.token"
        write_secret(api_path, api_token)

        # Incomplete secure setup must fail closed before binding a socket.
        incomplete = subprocess.run(
            [sys.executable, str(BASE / "router.py"), "--mode", "remote",
             "--dir", str(tmp / "incomplete")], capture_output=True, text=True, timeout=10)
        assert incomplete.returncode != 0
        assert api_token not in incomplete.stdout + incomplete.stderr

        base_cmd = [sys.executable, str(BASE / "router.py"), "--mode", "remote",
                    "--port", "1", "--dir", str(tmp / "rejected"),
                    "--tls-cert", str(cert_path), "--tls-key", str(key_path),
                    "--client-token-file", str(api_path)]
        public_bind = subprocess.run(base_cmd + ["--host", "0.0.0.0"],
                                     capture_output=True, text=True, timeout=10)
        assert public_bind.returncode != 0 and "private or loopback" in public_bind.stderr
        insecure_token = tmp / "world-readable.token"
        insecure_token.write_text(api_token, encoding="utf-8"); insecure_token.chmod(0o644)
        insecure_mode = subprocess.run(
            [arg if arg != str(api_path) else str(insecure_token) for arg in base_cmd],
            capture_output=True, text=True, timeout=10)
        assert insecure_mode.returncode != 0 and "permissions must be 0600" in insecure_mode.stderr
        key_path.chmod(0o644)
        insecure_key = subprocess.run(base_cmd, capture_output=True, text=True, timeout=10)
        key_path.chmod(0o600)
        assert insecure_key.returncode != 0 and "TLS private key file permissions must be 0600" in insecure_key.stderr
        local_with_tls = subprocess.run(
            [sys.executable, str(BASE / "router.py"), "--mode", "local",
             "--tls-cert", str(cert_path)], capture_output=True, text=True, timeout=10)
        assert local_with_tls.returncode != 0 and "require --mode remote" in local_with_tls.stderr

        # Test server is loopback-only even though it exercises remote mode.
        import socket
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        router_proc = subprocess.Popen(
            [sys.executable, str(BASE / "router.py"), "--mode", "remote",
             "--host", "127.0.0.1", "--port", str(port), "--dir", str(tmp / "state"),
             "--tls-cert", str(cert_path), "--tls-key", str(key_path),
             "--client-token-file", str(api_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        url = f"https://127.0.0.1:{port}"
        context = ssl.create_default_context(cafile=str(ca_path))
        try:
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    status, _ = get(url + "/ready", context)
                    if status == 200: break
                except Exception:
                    if router_proc.poll() is not None:
                        raise AssertionError("secure Router exited: " + (router_proc.stderr.read() or ""))
                    time.sleep(0.1)
            else:
                raise AssertionError("secure Router did not become ready")

            assert get(url + "/v1/models", context)[0] == 401
            assert get(url + "/v1/models", context, "wrong-token")[0] == 401
            assert get(url + "/v1/models", context, api_token)[0] == 200

            # A key the operator has not approved cannot register, even with a
            # validly signed request. Enrolment is the registered key itself.
            enrollment_priv, enrollment_pub, enrollment_node = nc.load_or_create_node_key(
                tmp / "unapproved-node")
            register_path = "/nodes/register"
            body = {"node_id": enrollment_node, "pubkey_pem": enrollment_pub,
                    "models": ["blocked-model"], "nram": [], "region": "test"}
            headers = {"Content-Type": "application/json", "X-Nexus-Node-ID": enrollment_node,
                       **nc.sign_node_request(enrollment_priv, "POST", register_path, body)}
            request = urllib.request.Request(url + register_path, data=json.dumps(body).encode(),
                                             headers=headers, method="POST")
            try:
                urllib.request.urlopen(request, timeout=2, context=context)
            except urllib.error.HTTPError as exc:
                assert exc.code == 403
            else:
                raise AssertionError("unapproved node registered")

            # A worker with an unrelated CA cannot register; a correctly
            # provisioned H1 worker validates the server and enrolls securely.
            bad_worker = worker2.Worker(url, "http://127.0.0.1:11436", tmp / "bad-node", "",
                                        str(wrong_ca_path))
            try:
                bad_worker.register(["test-model"], [])
            except Exception as exc:
                assert "CERTIFICATE_VERIFY_FAILED" in str(exc) or isinstance(exc, ssl.SSLError), repr(exc)
            else:
                raise AssertionError("worker accepted Router certificate from untrusted CA")

            worker = worker2.Worker(url, "http://127.0.0.1:11436", tmp / "node", "",
                                    str(ca_path))
            assert worker.router_ssl_context.check_hostname
            assert worker.router_ssl_context.verify_mode == ssl.CERT_REQUIRED
            approved = subprocess.run(
                [sys.executable, str(BASE / "router.py"), "--dir", str(tmp / "state"),
                 "--approve-node", str(tmp / "node" / "node_pub.pem")],
                capture_output=True, text=True, timeout=10)
            assert approved.returncode == 0 and f"approved node_id={worker.node_id}" in approved.stdout, approved.stderr
            worker.register(["test-model"], [])
            assert get(url + "/v1/models", context, api_token)[1]["data"][0]["id"] == "test-model"

            # A valid token gets through chat auth and receives a queued-timeout
            # response; the same request without auth is rejected immediately.
            chat_payload = {"model": "test-model", "messages": [{"role": "user", "content": "test"}],
                            "max_tokens": 1, "timeout_s": 1}
            data = json.dumps(chat_payload).encode()
            request = urllib.request.Request(url + "/v1/chat/completions", data=data,
                                             headers={"Content-Type": "application/json"}, method="POST")
            try:
                urllib.request.urlopen(request, timeout=3, context=context)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            request = urllib.request.Request(url + "/v1/chat/completions", data=data,
                                             headers={"Content-Type": "application/json",
                                                      "Authorization": f"Bearer {api_token}"}, method="POST")
            try:
                urllib.request.urlopen(request, timeout=4, context=context)
            except urllib.error.HTTPError as exc:
                assert exc.code == 504
            else:
                raise AssertionError("chat should timeout with no worker engine attached")

            state_db = tmp / "state" / "nexus_h0.db"
            with sqlite3.connect(state_db) as conn:
                job_id = conn.execute("SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0]
                conn.execute("UPDATE jobs SET status='done', result_text='delivered response', "
                             "content_expires_at='2099-01-01T00:00:00Z' WHERE job_id=?", (job_id,))
                conn.execute("INSERT OR REPLACE INTO receipts VALUES(?,?,?,?,?,?,?,?,?)",
                             (job_id, worker.node_id, "{}", "test-signature", 0, 0, 0, 1, 0.0))
            assert get(url + f"/jobs/{job_id}", context)[0] == 401
            status, before_expiry = get(url + f"/jobs/{job_id}", context, api_token)
            assert status == 200 and before_expiry["output_text"] == "delivered response"
            with sqlite3.connect(state_db) as conn:
                conn.execute("UPDATE jobs SET content_expires_at='2000-01-01T00:00:00Z' "
                             "WHERE job_id=?", (job_id,))
            status, expired = get(url + f"/jobs/{job_id}", context, api_token)
            assert status == 200 and expired["content_expired"] is True
            assert expired["output_text"] is None and expired["receipt"] == {}

            assert get(url + "/metrics", context)[0] == 401
            assert get(url + "/ledger/summary", context)[0] == 401

            # Revocation removes the key's session at once: polling and
            # re-enrolment both fail, and the enrolment cannot be reused.
            revoked = subprocess.run(
                [sys.executable, str(BASE / "router.py"), "--dir", str(tmp / "state"),
                 "--revoke-node", worker.node_id],
                capture_output=True, text=True, timeout=10)
            assert revoked.returncode == 0 and "revoked node_id=" in revoked.stdout, revoked.stderr
            for attempt in (lambda: worker.next_job(), lambda: worker.register(["test-model"], [])):
                try:
                    attempt()
                except urllib.error.HTTPError as exc:
                    assert exc.code == 403, exc.code
                else:
                    raise AssertionError("revoked node kept its access")
        finally:
            router_proc.terminate()
            try:
                router_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                router_proc.kill(); router_proc.wait(timeout=5)
    print("remote TLS verification, client auth, node enrolment: PASS")


if __name__ == "__main__":
    test_migration_and_purge()
    test_purge_scrubs_live_database_file()
    test_secure_remote()
    print("ALL SECURE REMOTE TESTS PASS")
