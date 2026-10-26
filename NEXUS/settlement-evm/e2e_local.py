#!/usr/bin/env python3
"""Run a receipt_to_batch -> deployment -> claimMany E2E on disposable Anvil.

All identities, keys, token balances, and EVM state are generated for this run.
The default Anvil account key is a public test key and must never hold value.
The RPC binds only to 127.0.0.1; this harness refuses non-loopback RPC URLs.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from http.client import HTTPConnection
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from batch_builder import keccak256
from cryptography.hazmat.primitives import serialization
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

# Keep generated Python bytecode out of the source tree during this disposable run.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
H0 = ROOT.parent / "nexus" / "h0"
ANVIL_TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ANVIL_SIGNER_KEY = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
ANVIL_SIGNER_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
NODE_ONE = "0x" + "a1" * 20
NODE_TWO = "0x" + "a2" * 20
AUTHOR = "0x" + "b1" * 20
CHAIN_ID = 31337
E2E_FUNDING = 1_000_000_000_000


def stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def rpc(url: str, method: str, params: list | None = None):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                          "params": params or []}).encode()
    request = Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=1) as response:
        body = json.loads(response.read())
    if "error" in body:
        raise RuntimeError(f"Anvil RPC {method} failed: {body['error']}")
    return body["result"]


def contract_call(url: str, address: str, signature: str) -> bytes:
    selector = keccak256(signature.encode("ascii"))[:4].hex()
    result = rpc(url, "eth_call", [{"to": address, "data": "0x" + selector}, "latest"])
    return bytes.fromhex(result.removeprefix("0x"))


def create_router_tls_credentials(directory: Path) -> dict[str, Path | str]:
    """Create disposable CA/server credentials and separate Router secrets."""
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NEXUS E2E CA")])
    ca_certificate = (
        x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
        .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                     key_encipherment=False, data_encipherment=False,
                                     key_agreement=False, key_cert_sign=True,
                                     crl_sign=True, encipher_only=None, decipher_only=None),
                       critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    server_certificate = (
        x509.CertificateBuilder().subject_name(server_name).issuer_name(ca_name)
        .public_key(server_key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost"),
        ]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    def write_private(name: str, value: bytes) -> Path:
        path = directory / name
        path.write_bytes(value)
        path.chmod(0o600)
        return path

    ca_path = write_private("router-ca.crt", ca_certificate.public_bytes(
        serialization.Encoding.PEM
    ))
    certificate_path = write_private("router.crt", server_certificate.public_bytes(
        serialization.Encoding.PEM
    ))
    key_path = write_private("router.key", server_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    service_token = "service-" + os.urandom(32).hex()
    enrollment_token = "enroll-" + os.urandom(32).hex()
    service_token_path = write_private("router-client.token", (service_token + "\n").encode())
    enrollment_token_path = write_private(
        "router-enrollment.token", (enrollment_token + "\n").encode()
    )
    return {
        "ca": ca_path,
        "certificate": certificate_path,
        "key": key_path,
        "service_token": service_token,
        "service_token_file": service_token_path,
        "enrollment_token": enrollment_token,
        "enrollment_token_file": enrollment_token_path,
    }


def start_h0_fixture(directory: Path) -> tuple[Path, Path, dict[str, object], list[subprocess.Popen]]:
    """Run FastAPI, the real H0 router, mock engine and signed worker."""
    sys.path.insert(0, str(H0))
    import nexus_common as nc
    key_dir = directory / "node-key"
    _, public_pem, node_id = nc.load_or_create_node_key(key_dir)
    public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    public_der = public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    public_key_fingerprint = hashlib.sha256(public_der).hexdigest()
    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    mock_port, router_port, api_port = free_port(), free_port(), free_port()
    ui_port = free_port()
    ui_public_port = 8080
    router_url = f"https://127.0.0.1:{router_port}"
    api_url = f"http://127.0.0.1:{api_port}"
    router_credentials = create_router_tls_credentials(directory / "router-tls")
    # Match the current Compose path: FastAPI authenticates against a private
    # digest-only client registry, while the BFF keeps the one-time key.
    sys.path.insert(0, str(ROOT.parent))
    from nexus.api import manage_api_clients
    registry_dir = directory / "api-secrets"
    registry_dir.mkdir(mode=0o700)
    registry_dir.chmod(0o700)
    registry_path = registry_dir / "api_clients.json"
    api_token = manage_api_clients.manage(
        registry_path, "add", "e2e-ui", "inference,models:read,jobs:read", quota=60
    )
    observer_token = manage_api_clients.manage(
        registry_path, "add", "e2e-observer", "jobs:read", quota=60
    )
    assert api_token and observer_token
    registry_contents = registry_path.read_text(encoding="utf-8")
    if (api_token in registry_contents or observer_token in registry_contents
            or registry_path.stat().st_mode & 0o077):
        raise RuntimeError("API client registry contains plaintext or is not private")
    logs = [directory / "mock.log", directory / "router.log", directory / "worker.log",
            directory / "api.log", directory / "web.log"]
    streams = [path.open("w+") for path in logs]
    procs = [
        subprocess.Popen([sys.executable, str(H0 / "mock_atenea.py"), "--port", str(mock_port)],
                         cwd=H0, stdout=streams[0], stderr=subprocess.STDOUT),
        subprocess.Popen([
            sys.executable, str(H0 / "router.py"), "--mode", "remote",
            "--host", "127.0.0.1", "--port", str(router_port), "--dir", str(directory),
            "--tls-cert", str(router_credentials["certificate"]),
            "--tls-key", str(router_credentials["key"]),
            "--client-token-file", str(router_credentials["service_token_file"]),
            "--enrollment-token-file", str(router_credentials["enrollment_token_file"]),
        ], cwd=H0, stdout=streams[1], stderr=subprocess.STDOUT),
    ]
    try:
        router_context = ssl.create_default_context(cafile=str(router_credentials["ca"]))
        for _ in range(200):
            if any(proc.poll() is not None for proc in procs):
                for stream in streams:
                    stream.flush()
                    stream.seek(0)
                details = "\n".join(stream.read() for stream in streams)
                raise RuntimeError("an H0 E2E process exited during startup:\n" + details)
            try:
                with urlopen(router_url + "/ready", timeout=0.5,
                             context=router_context) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("H0 Router did not become ready")
        # Start the worker only after the Router is reachable, avoiding an
        # immediate registration race on slower CI/host startup.
        procs.append(subprocess.Popen([sys.executable, str(ROOT.parent / "nexus-h1-node" / "worker2.py"),
                                       "--router", router_url,
                                       "--atenea", f"http://127.0.0.1:{mock_port}",
                                       "--node-dir", str(key_dir),
                                       "--router-ca", str(router_credentials["ca"]),
                                       "--enrollment-token-file",
                                       str(router_credentials["enrollment_token_file"])], cwd=H0,
                                      stdout=streams[2], stderr=subprocess.STDOUT))
        # Wait until the worker has registered its signing key.
        for _ in range(100):
            with sqlite3.connect(directory / "nexus_h0.db") as conn:
                if conn.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone():
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("H0 worker did not register")
        api_env = {
            **os.environ,
            "NEXUS_H0_ROUTER_URL": router_url,
            "NEXUS_H0_ROUTER_CA_FILE": str(router_credentials["ca"]),
            "NEXUS_H0_CLIENT_TOKEN_FILE": str(router_credentials["service_token_file"]),
            "NEXUS_API_CLIENTS_FILE": str(registry_path),
        }
        # The gateway and BFF carry credentials and prompts; prove the full
        # integration bypasses hostile ambient proxy configuration.
        proxy_env = "http://127.0.0.1:1"
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                     "ALL_PROXY", "all_proxy"):
            api_env[name] = proxy_env
        api_env["NO_PROXY"] = api_env["no_proxy"] = ""
        api_env.pop("NEXUS_API_TOKEN", None)
        api_env.pop("NEXUS_API_TOKEN_FILE", None)
        api_env.pop("NEXUS_H0_CLIENT_TOKEN", None)
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "nexus.api.core.api_server:app",
             "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=ROOT.parent, env=api_env, stdout=streams[3], stderr=subprocess.STDOUT,
        ))
        for _ in range(100):
            if procs[-1].poll() is not None:
                streams[3].flush()
                streams[3].seek(0)
                raise RuntimeError("FastAPI exited during startup:\n" + streams[3].read())
            try:
                with urlopen(api_url + "/ready", timeout=0.5) as response:
                    if response.status == 200 and json.loads(response.read()).get("success"):
                        break
            except (URLError, TimeoutError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("FastAPI facade did not become ready")

        web_env = {
            **os.environ,
            "NEXUS_H0_API_URL": api_url,
            "NEXUS_API_TOKEN": api_token,
            "NEXUS_H0_UI_PORT": str(ui_port),
            # Model a Compose port mapping where the public Host port differs
            # from the ephemeral port used by this local fixture.
            "NEXUS_H0_UI_PUBLIC_PORT": str(ui_public_port),
        }
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                     "ALL_PROXY", "all_proxy"):
            web_env[name] = proxy_env
        web_env["NO_PROXY"] = web_env["no_proxy"] = ""
        procs.append(subprocess.Popen(
            [sys.executable, str(ROOT.parent / "nexus-web" / "h0_local.py")],
            cwd=ROOT.parent, env=web_env, stdout=streams[4], stderr=subprocess.STDOUT,
        ))
        ui_url = f"http://127.0.0.1:{ui_port}"
        ui_host = f"127.0.0.1:{ui_public_port}"

        def ui_request(path: str, body: bytes | None = None,
                       content_type: str | None = None) -> Request:
            headers = {"Host": ui_host}
            if content_type:
                headers["Content-Type"] = content_type
            return Request(ui_url + path, data=body, headers=headers)

        for _ in range(100):
            if procs[-1].poll() is not None:
                streams[4].flush()
                streams[4].seek(0)
                raise RuntimeError("same-origin UI exited during startup:\n" + streams[4].read())
            try:
                with urlopen(ui_request("/"), timeout=0.5) as response:
                    page = response.read()
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("same-origin UI did not become ready")
        if api_token.encode() in page:
            raise RuntimeError("same-origin UI exposed its server-side API token")
        with urlopen(ui_request("/v1/models"), timeout=5) as response:
            models = json.loads(response.read())
        if not models.get("data"):
            raise RuntimeError("same-origin UI could not retrieve models through FastAPI")
        try:
            with urlopen(Request(ui_url + "/v1/models", headers={
                "Host": ui_host, "Origin": f"http://evil.example:{ui_public_port}",
            }), timeout=5):
                raise RuntimeError("same-origin UI accepted a foreign browser Origin")
        except HTTPError as exc:
            if exc.code != 403:
                raise RuntimeError(f"same-origin UI foreign Origin returned HTTP {exc.code}") from exc

        # The public client path must reject an absent token before the Router
        # creates a job. Then use the Python SDK through the authenticated API.
        unauthorized_payload = json.dumps({
            "model": "athenea-e2b", "messages": [{"role": "user", "content": "must be rejected"}],
            "max_tokens": 3,
        }).encode()
        try:
            with urlopen(Request(api_url + "/v1/chat/completions", data=unauthorized_payload,
                                 headers={"Content-Type": "application/json"}), timeout=5):
                raise RuntimeError("FastAPI accepted a chat request without its client token")
        except HTTPError as exc:
            if exc.code != 401:
                raise RuntimeError(f"FastAPI unauthenticated request returned HTTP {exc.code}") from exc

        api_address = urlsplit(api_url)
        oversized = HTTPConnection(api_address.hostname, api_address.port, timeout=5)
        oversized.putrequest("POST", "/v1/chat/completions")
        oversized.putheader("X-API-Key", api_token)
        oversized.putheader("Content-Type", "application/json")
        oversized.putheader("Content-Length", str(1_048_576 + 1))
        oversized.endheaders()
        oversized_response = oversized.getresponse()
        oversized_status = oversized_response.status
        oversized.close()
        if oversized_status != 413:
            raise RuntimeError(f"FastAPI oversized request returned HTTP {oversized_status}")

        # Exercise the browser-facing same-origin proxy with no client credential.
        ui_payload = json.dumps({
            "model": "athenea-e2b", "messages": [{"role": "user", "content": "E2E settlement job one"}],
            "max_tokens": 3,
        }).encode()
        with urlopen(ui_request("/v1/chat/completions", ui_payload, "application/json"),
                     timeout=310) as response:
            ui_completion = json.loads(response.read())
        ui_job_id = ui_completion.get("id")
        if not isinstance(ui_job_id, str) or not ui_job_id.startswith("job_"):
            raise RuntimeError("same-origin UI returned no Router job ID")
        with urlopen(ui_request("/jobs/" + ui_job_id), timeout=5) as response:
            ui_job = json.loads(response.read())
        if ui_job.get("id", ui_job.get("job_id")) != ui_job_id:
            raise RuntimeError("same-origin UI status route did not return the requested job")
        try:
            with urlopen(Request(api_url + "/jobs/" + ui_job_id,
                                 headers={"Authorization": f"Bearer {observer_token}"}),
                         timeout=5):
                raise RuntimeError("an unrelated API client could read another client's job")
        except HTTPError as exc:
            if exc.code != 404:
                raise RuntimeError(
                    f"cross-client job lookup returned HTTP {exc.code}, expected 404"
                ) from exc

        sys.path.insert(0, str(ROOT.parent / "nexus-sdk-python"))
        proxy_names = ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy",
                       "ALL_PROXY", "all_proxy", "NO_PROXY", "no_proxy")
        old_proxy_env = {name: os.environ.get(name) for name in proxy_names}
        try:
            for name in proxy_names[:6]:
                os.environ[name] = "http://127.0.0.1:1"
            os.environ["NO_PROXY"] = os.environ["no_proxy"] = ""
            from nexus_client import NexusClient
            client = NexusClient(api_key=api_token, base_url=api_url, timeout=310)
            completion = asyncio.run(client.chat(
                "E2E settlement job two", model="athenea-e2b", max_tokens=3, timeout_s=300
            ))
            job_id = completion.get("id")
            if not isinstance(job_id, str) or not job_id.startswith("job_"):
                raise RuntimeError(f"Authenticated API returned no Router job ID: {completion}")
            with sqlite3.connect(directory / "nexus_h0.db") as conn:
                job_row = conn.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                receipt_row = conn.execute("SELECT verified FROM receipts WHERE job_id=?", (job_id,)).fetchone()
            if job_row != ("done",) or receipt_row != (1,):
                row = (job_row, receipt_row)
                raise RuntimeError(f"FastAPI -> Router -> worker job was not verified: {job_id} {row}")
        finally:
            for name, value in old_proxy_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        db_path = directory / "nexus_h0.db"
    except Exception:
        for proc in reversed(procs):
            stop_process(proc)
        for stream in streams:
            stream.close()
        raise
    for stream in streams:
        stream.close()
    # The bridge binds the registered worker identity to an explicit wallet.
    config = {
        "batchId": "0x" + "ab" * 32,
        "depositAmount": 1_000_000_000,
        "token": {"symbol": "NEXUS-TEST", "decimals": 6,
                  "usdPerTokenNumerator": 1, "usdPerTokenDenominator": 10_000},
        "nodeWallets": {node_id: NODE_ONE},
        "nodePublicKeyFingerprints": {node_id: public_key_fingerprint},
        "authorWallets": {"author_e2e_test": AUTHOR},
    }
    config_path = directory / "test-policy.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return db_path, config_path, config, procs


def broadcast_contracts(path: Path, required: set[str] | None = None) -> dict[str, str]:
    """Read contract addresses from Foundry's local broadcast record."""
    document = json.loads(path.read_text(encoding="utf-8"))
    contracts = {}
    for transaction in document.get("transactions", []):
        name = transaction.get("contractName")
        address = transaction.get("contractAddress")
        if name in {"MockSettlementToken", "InferenceEscrow"} and isinstance(address, str):
            contracts[name] = address
    required = required or {"MockSettlementToken", "InferenceEscrow"}
    missing = required - set(contracts)
    if missing:
        raise RuntimeError(f"Foundry broadcast record missing deployments: {', '.join(sorted(missing))}")
    return contracts


def main() -> int:
    anvil = os.environ.get("ANVIL_BIN") or shutil.which("anvil")
    forge = os.environ.get("FORGE_BIN") or shutil.which("forge")
    if not anvil:
        candidate = Path("/private/tmp/nexus-foundry-v1.8.6/anvil")
        anvil = str(candidate) if candidate.is_file() else None
    if not forge:
        candidate = Path("/private/tmp/nexus-foundry-v1.8.6/forge")
        forge = str(candidate) if candidate.is_file() else None
    if not anvil or not forge:
        raise SystemExit("forge and anvil are required (set FORGE_BIN and ANVIL_BIN)")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    rpc_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="nexus-bridge-e2e-") as temp_name:
        workspace = Path(temp_name)
        db_path, config_path, config, h0_procs = start_h0_fixture(workspace)
        anvil_proc = None
        try:
            anvil_proc = subprocess.Popen(
                [anvil, "--host", "127.0.0.1", "--port", str(port), "--chain-id", "31337"],
                cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            ready = False
            for _ in range(100):
                if anvil_proc.poll() is not None:
                    raise RuntimeError(f"Anvil exited unexpectedly ({anvil_proc.returncode})")
                try:
                    if rpc(rpc_url, "eth_chainId") == "0x7a69":
                        ready = True
                        break
                except (URLError, TimeoutError, OSError, ValueError):
                    time.sleep(0.1)
            if not ready:
                raise RuntimeError("Anvil did not become ready on loopback")

            env = {**os.environ, "NEXUS_E2E_PRIVATE_KEY": ANVIL_TEST_KEY,
                   "NEXUS_E2E_FUNDING": str(E2E_FUNDING)}
            broadcast_root = workspace / "broadcast"
            env["FOUNDRY_BROADCAST"] = str(broadcast_root)
            env["FOUNDRY_CACHE_PATH"] = str(workspace / "cache")
            env["FOUNDRY_OUT"] = str(workspace / "out")
            subprocess.run([forge, "build"], cwd=ROOT, env=env, check=True)
            deployment = subprocess.run(
                [forge, "script", "script/DeployBridgeE2E.s.sol:DeployBridgeE2E",
                 "--rpc-url", rpc_url, "--broadcast", "--non-interactive",
                 "--private-key", ANVIL_TEST_KEY, "-vvv"],
                cwd=ROOT, env=env, check=False, capture_output=True, text=True,
            )
            if deployment.returncode:
                sys.stderr.write(deployment.stdout)
                sys.stderr.write(deployment.stderr)
                raise RuntimeError(f"forge deployment script failed with exit code {deployment.returncode}")
            deployments = broadcast_contracts(
                broadcast_root / "DeployBridgeE2E.s.sol" / str(CHAIN_ID) / "run-latest.json",
                required={"MockSettlementToken"},
            )

            deploy_env = {
                **env,
                "NEXUS_SETTLEMENT_EXPECTED_CHAIN_ID": str(CHAIN_ID),
                "NEXUS_SETTLEMENT_DEPLOYER_PRIVATE_KEY": ANVIL_TEST_KEY,
                "NEXUS_SETTLEMENT_OWNER": "0x0000000000000000000000000000000000001003",
                "NEXUS_SETTLEMENT_TOKEN": deployments["MockSettlementToken"],
                "NEXUS_SETTLEMENT_TOKEN_DECIMALS": "6",
                "NEXUS_SETTLEMENT_BATCH_SIGNER": ANVIL_SIGNER_ADDRESS,
                "NEXUS_SETTLEMENT_TREASURY": "0x0000000000000000000000000000000000001001",
                "NEXUS_SETTLEMENT_VERIFICATION_POOL": "0x0000000000000000000000000000000000001002",
                "NEXUS_SETTLEMENT_MAX_CLAIM_WINDOW": str(24 * 60 * 60),
            }
            deploy_script = "script/DeploySettlementEscrow.s.sol:DeploySettlementEscrow"
            wrong_chain_env = {**deploy_env, "NEXUS_SETTLEMENT_EXPECTED_CHAIN_ID": "1"}
            preflight = subprocess.run(
                [forge, "script", deploy_script, "--rpc-url", rpc_url, "--non-interactive", "-vvv"],
                cwd=ROOT, env=wrong_chain_env, check=False, capture_output=True, text=True,
            )
            if preflight.returncode == 0 or "NEXUS_SETTLEMENT_CHAIN_MISMATCH" not in (
                preflight.stdout + preflight.stderr
            ):
                raise RuntimeError("deployment preflight did not reject the wrong chain ID")
            wrong_decimals_env = {**deploy_env, "NEXUS_SETTLEMENT_TOKEN_DECIMALS": "18"}
            token_preflight = subprocess.run(
                [forge, "script", deploy_script, "--rpc-url", rpc_url, "--non-interactive", "-vvv"],
                cwd=ROOT, env=wrong_decimals_env, check=False, capture_output=True, text=True,
            )
            if token_preflight.returncode == 0 or "NEXUS_SETTLEMENT_DECIMALS_MISMATCH" not in (
                token_preflight.stdout + token_preflight.stderr
            ):
                raise RuntimeError("deployment preflight did not reject mismatched token decimals")
            deployment = subprocess.run(
                [forge, "script", deploy_script, "--rpc-url", rpc_url,
                 "--broadcast", "--non-interactive", "--private-key", ANVIL_TEST_KEY, "-vvv"],
                cwd=ROOT, env=deploy_env, check=False, capture_output=True, text=True,
            )
            if deployment.returncode:
                sys.stderr.write(deployment.stdout)
                sys.stderr.write(deployment.stderr)
                raise RuntimeError("production escrow deployment script failed on local Anvil")
            operational_deployment = broadcast_contracts(
                broadcast_root / "DeploySettlementEscrow.s.sol" / str(CHAIN_ID) / "run-latest.json",
                required={"InferenceEscrow"},
            )
            operational_escrow = operational_deployment["InferenceEscrow"]
            if rpc(rpc_url, "eth_getCode", [operational_escrow, "latest"]) == "0x":
                raise RuntimeError("deployment script did not create an escrow contract")
            deploy_record_path = (
                broadcast_root / "DeploySettlementEscrow.s.sol" / str(CHAIN_ID) / "run-latest.json"
            )
            deploy_record = json.loads(deploy_record_path.read_text(encoding="utf-8"))
            deployment_tx = next((tx for tx in deploy_record.get("transactions", [])
                                  if tx.get("contractName") == "InferenceEscrow"), None)
            if not deployment_tx or not deployment_tx.get("hash"):
                raise RuntimeError("Foundry deployment record has no escrow creation transaction hash")
            deployment_receipt = rpc(rpc_url, "eth_getTransactionReceipt", [deployment_tx["hash"]])
            configured_topic = "0x" + keccak256(
                b"EscrowConfigured(address,address,address,address,address,uint8,uint64)"
            ).hex()
            if not any(log.get("address", "").lower() == operational_escrow.lower()
                       and log.get("topics", [""])[0].lower() == configured_topic.lower()
                       for log in deployment_receipt.get("logs", [])):
                raise RuntimeError("on-chain escrow creation receipt has no EscrowConfigured event")
            expected_address = deploy_env["NEXUS_SETTLEMENT_OWNER"]
            expected_token = bytes.fromhex(deploy_env["NEXUS_SETTLEMENT_TOKEN"][2:]).rjust(32, b"\x00")
            expected_signer = bytes.fromhex(deploy_env["NEXUS_SETTLEMENT_BATCH_SIGNER"][2:]).rjust(32, b"\x00")
            actual_config = {
                "owner": "0x" + contract_call(rpc_url, operational_escrow, "owner()")[-20:].hex(),
                "token": contract_call(rpc_url, operational_escrow, "token()")[-32:],
                "signer": contract_call(rpc_url, operational_escrow, "batchSigner()")[-32:],
                "decimals": int.from_bytes(contract_call(rpc_url, operational_escrow, "tokenDecimals()"), "big"),
                "claim_window": int.from_bytes(contract_call(rpc_url, operational_escrow, "maxClaimWindow()"), "big"),
            }
            if (actual_config["owner"].lower() != expected_address.lower()
                    or actual_config["token"] != expected_token
                    or actual_config["signer"] != expected_signer
                    or actual_config["decimals"] != 6
                    or actual_config["claim_window"] != 24 * 60 * 60):
                raise RuntimeError(f"on-chain deployment configuration mismatch: {actual_config}")

            config["settlementContext"] = {
                "chainId": CHAIN_ID,
                "escrowAddress": operational_escrow,
                "tokenAddress": deployments["MockSettlementToken"],
            }
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            batch_path = workspace / "settlement-batch.json"
            with batch_path.open("w", encoding="utf-8") as batch_output:
                subprocess.run([sys.executable, str(ROOT / "receipt_to_batch.py"),
                                "--db", str(db_path), "--config", str(config_path)],
                               cwd=ROOT, check=True, stdout=batch_output)
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            if len(batch["claims"]) != 2 or batch["rootSum"] <= 0:
                raise RuntimeError("receipt bridge did not produce the expected two-claim test batch")
            if batch["settlementContext"] != config["settlementContext"]:
                raise RuntimeError("bridge output settlement context does not match deployed contracts")
            if batch.get("tokenDecimals") != config["token"]["decimals"]:
                raise RuntimeError("bridge output token decimals do not match settlement policy")
            source_ids = {row["routerJobId"] for row in batch["sourceReceipts"].values()}
            if source_ids != {"job_000001", "job_000002"}:
                raise RuntimeError("bridge did not preserve Router-native receipt references")

            latest_block = rpc(rpc_url, "eth_getBlockByNumber", ["latest", False])
            deadline = int(latest_block["timestamp"], 16) + 3600
            policy_hash = "0x" + hashlib.sha256(
                json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            publish_env = {
                **env,
                "NEXUS_SETTLEMENT_EXPECTED_CHAIN_ID": str(CHAIN_ID),
                "NEXUS_SETTLEMENT_ESCROW": operational_escrow,
                "NEXUS_SETTLEMENT_TOKEN": deployments["MockSettlementToken"],
                "NEXUS_SETTLEMENT_TREASURY": "0x0000000000000000000000000000000000001001",
                "NEXUS_SETTLEMENT_VERIFICATION_POOL": "0x0000000000000000000000000000000000001002",
                "NEXUS_SETTLEMENT_EXPECTED_POLICY_HASH": policy_hash,
                "NEXUS_SETTLEMENT_EXPECTED_BATCH_COMMITMENT": batch["settlementBatchCommitment"],
                "NEXUS_SETTLEMENT_PAYER_PRIVATE_KEY": ANVIL_TEST_KEY,
                "NEXUS_SETTLEMENT_SIGNER_PRIVATE_KEY": ANVIL_SIGNER_KEY,
                "NEXUS_SETTLEMENT_CLAIM_DEADLINE": str(deadline),
                "NEXUS_SETTLEMENT_MIN_GAS_BALANCE": "1000000000000000",
            }
            publish_script = "script/PublishSettlementBatch.s.sol:PublishSettlementBatch"
            bad_signer_env = {
                **publish_env,
                "NEXUS_SETTLEMENT_SIGNER_PRIVATE_KEY": "0x" + "00" * 31 + "01",
            }
            signer_preflight = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url, "--non-interactive",
                 "--sig", "run(string)", batch_path.read_text(encoding="utf-8"), "-vvv"],
                cwd=ROOT, env=bad_signer_env, check=False, capture_output=True, text=True,
            )
            if signer_preflight.returncode == 0 or "NEXUS_SETTLEMENT_SIGNER_MISMATCH" not in (
                signer_preflight.stdout + signer_preflight.stderr
            ):
                raise RuntimeError("batch publisher did not reject a mismatched signer key:\n"
                                   + signer_preflight.stdout + signer_preflight.stderr)
            bad_policy_env = {**publish_env, "NEXUS_SETTLEMENT_EXPECTED_POLICY_HASH": "0x" + "00" * 32}
            policy_preflight = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url, "--non-interactive",
                 "--sig", "run(string)", batch_path.read_text(encoding="utf-8"), "-vvv"],
                cwd=ROOT, env=bad_policy_env, check=False, capture_output=True, text=True,
            )
            if policy_preflight.returncode == 0 or "NEXUS_SETTLEMENT_POLICY_HASH_MISMATCH" not in (
                policy_preflight.stdout + policy_preflight.stderr
            ):
                raise RuntimeError("batch publisher did not reject an unapproved settlement policy hash:\n"
                                   + policy_preflight.stdout + policy_preflight.stderr)
            tampered_batch = {**batch, "root": "0x" + "11" * 32}
            commitment_preflight = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url, "--non-interactive",
                 "--sig", "run(string)", json.dumps(tampered_batch), "-vvv"],
                cwd=ROOT, env=publish_env, check=False, capture_output=True, text=True,
            )
            if (commitment_preflight.returncode == 0
                    or "NEXUS_SETTLEMENT_BATCH_COMMITMENT_MISMATCH" not in (
                        commitment_preflight.stdout + commitment_preflight.stderr
                    )):
                raise RuntimeError("batch publisher did not reject a substituted Merkle root:\n"
                                   + commitment_preflight.stdout + commitment_preflight.stderr)
            bad_context = {**publish_env, "NEXUS_SETTLEMENT_TOKEN": operational_escrow}
            context_preflight = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url, "--non-interactive",
                 "--sig", "run(string)", batch_path.read_text(encoding="utf-8"), "-vvv"],
                cwd=ROOT, env=bad_context, check=False, capture_output=True, text=True,
            )
            if context_preflight.returncode == 0 or "NEXUS_SETTLEMENT_BATCH_TOKEN_MISMATCH" not in (
                context_preflight.stdout + context_preflight.stderr
            ):
                raise RuntimeError("batch publisher did not reject mismatched batch token context:\n"
                                   + context_preflight.stdout + context_preflight.stderr)
            over_cap_batch = {**batch, "depositAmount": batch["rootSum"] - 1}
            cap_preflight = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url, "--non-interactive",
                 "--sig", "run(string)", json.dumps(over_cap_batch), "-vvv"],
                cwd=ROOT, env=publish_env, check=False, capture_output=True, text=True,
            )
            if cap_preflight.returncode == 0 or "NEXUS_SETTLEMENT_ROOT_EXCEEDS_POLICY_DEPOSIT" not in (
                cap_preflight.stdout + cap_preflight.stderr
            ):
                raise RuntimeError("batch publisher did not reject a root above the policy deposit cap:\n"
                                   + cap_preflight.stdout + cap_preflight.stderr)
            simulated_publish = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url, "--non-interactive",
                 "--sig", "run(string)", batch_path.read_text(encoding="utf-8"), "-vvv"],
                cwd=ROOT, env=publish_env, check=False, capture_output=True, text=True,
            )
            if simulated_publish.returncode:
                sys.stderr.write(simulated_publish.stdout)
                sys.stderr.write(simulated_publish.stderr)
                raise RuntimeError("batch publisher preflight simulation failed")
            published = subprocess.run(
                [forge, "script", publish_script, "--rpc-url", rpc_url,
                 "--broadcast", "--non-interactive", "--sig", "run(string)",
                 batch_path.read_text(encoding="utf-8"), "-vvv"],
                cwd=ROOT, env=publish_env, check=False, capture_output=True, text=True,
            )
            if published.returncode:
                sys.stderr.write(published.stdout)
                sys.stderr.write(published.stderr)
                raise RuntimeError("batch publisher broadcast failed")
            publish_record = json.loads((broadcast_root / "PublishSettlementBatch.s.sol" / str(CHAIN_ID)
                                         / "run-latest.json").read_text(encoding="utf-8"))
            publish_transactions = publish_record.get("transactions", [])
            if len(publish_transactions) < 4:
                raise RuntimeError("publisher broadcast did not record approve, fund, and publish transactions")
            senders = [str((tx.get("transaction") or {}).get("from", "")).lower()
                       for tx in publish_transactions]
            if senders.count("0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266") < 3:
                raise RuntimeError(f"payer did not send the expected approval and funding transactions: {senders}")
            if senders.count(ANVIL_SIGNER_ADDRESS.lower()) < 1:
                raise RuntimeError(f"gateway signer did not send the publication transaction: {senders}")

            result = subprocess.run(
                [forge, "script", "script/RunBridgeE2E.s.sol:RunBridgeE2E",
                 "--rpc-url", rpc_url, "--broadcast", "--non-interactive", "--private-key", ANVIL_TEST_KEY,
                 "--sig", "run(string)", batch_path.read_text(encoding="utf-8"), "-vvv"],
                cwd=ROOT, env=env, check=False, capture_output=True, text=True,
            )
            if result.returncode:
                sys.stderr.write(result.stdout)
                sys.stderr.write(result.stderr)
                raise RuntimeError(f"forge script failed with exit code {result.returncode}")
            print(result.stdout)
            print("NEXUS BRIDGE -> ANVIL E2E PASS")
            print("settlement deployment chain guard + Anvil deployment PASS")
            print(f"claims={len(batch['claims'])} rootSum={batch['rootSum']}")
            return 0
        finally:
            if anvil_proc is not None:
                stop_process(anvil_proc)
            for proc in reversed(h0_procs):
                stop_process(proc)


if __name__ == "__main__":
    raise SystemExit(main())
