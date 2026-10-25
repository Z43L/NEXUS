#!/usr/bin/env python3
"""Run a receipt_to_batch -> deployment -> claimMany E2E on disposable Anvil.

All identities, keys, token balances, and EVM state are generated for this run.
The default Anvil account key is a public test key and must never hold value.
The RPC binds only to 127.0.0.1; this harness refuses non-loopback RPC URLs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

# Keep generated Python bytecode out of the source tree during this disposable run.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
H0 = ROOT.parent / "nexus" / "h0"
ANVIL_TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
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


def start_h0_fixture(directory: Path) -> tuple[Path, Path, dict[str, object], list[subprocess.Popen]]:
    """Run the real H0 router, mock engine and signed worker for two jobs."""
    sys.path.insert(0, str(H0))
    import nexus_common as nc
    key_dir = directory / "node-key"
    _, _, node_id = nc.load_or_create_node_key(key_dir)
    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
    mock_port, router_port = free_port(), free_port()
    router_url = f"http://127.0.0.1:{router_port}"
    logs = [directory / "mock.log", directory / "router.log"]
    streams = [path.open("w+") for path in logs]
    procs = [
        subprocess.Popen([sys.executable, str(H0 / "mock_atenea.py"), "--port", str(mock_port)],
                         cwd=H0, stdout=streams[0], stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, str(H0 / "router.py"), "--port", str(router_port),
                          "--dir", str(directory)], cwd=H0, stdout=streams[1], stderr=subprocess.STDOUT),
    ]
    procs.append(subprocess.Popen([sys.executable, str(H0 / "worker_agent.py"),
                                   "--router", router_url,
                                   "--atenea", f"http://127.0.0.1:{mock_port}",
                                   "--node-dir", str(key_dir)], cwd=H0,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    try:
        for _ in range(200):
            if any(proc.poll() is not None for proc in procs):
                for stream in streams:
                    stream.flush()
                    stream.seek(0)
                details = "\n".join(stream.read() for stream in streams)
                raise RuntimeError("an H0 E2E process exited during startup:\n" + details)
            try:
                with urlopen(router_url + "/ready", timeout=0.5) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, OSError):
                time.sleep(0.1)
        else:
            raise RuntimeError("H0 Router did not become ready")
        # Wait until the worker has registered its signing key.
        for _ in range(100):
            with __import__("sqlite3").connect(directory / "nexus_h0.db") as conn:
                if conn.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone():
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("H0 worker did not register")
        jobs = [
            {"kind": "inference", "model": "athenea-e2b", "nram": ["author_e2e_test"],
             "messages": [{"role": "user", "content": "E2E settlement job one"}],
             "params": {"max_tokens": 3}},
            {"kind": "inference", "model": "athenea-e2b", "nram": [],
             "messages": [{"role": "user", "content": "E2E settlement job two"}],
             "params": {"max_tokens": 3}},
        ]
        for job in jobs:
            request = Request(router_url + "/jobs", data=json.dumps(job).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=5) as response:
                job_id = json.loads(response.read())["job_id"]
            for _ in range(200):
                with urlopen(router_url + f"/jobs/{job_id}", timeout=2) as response:
                    status = json.loads(response.read())
                if status["status"] == "done":
                    if not status.get("verified"):
                        raise RuntimeError(f"Router did not verify receipt for {job_id}")
                    break
                if status["status"] in ("failed", "rejected"):
                    raise RuntimeError(f"H0 job failed: {status}")
                time.sleep(0.1)
            else:
                raise RuntimeError(f"H0 job timed out: {job_id}")
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
        "authorWallets": {"author_e2e_test": AUTHOR},
    }
    config_path = directory / "test-policy.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return db_path, config_path, config, procs


def broadcast_contracts(path: Path) -> dict[str, str]:
    """Read contract addresses from Foundry's local broadcast record."""
    document = json.loads(path.read_text(encoding="utf-8"))
    contracts = {}
    for transaction in document.get("transactions", []):
        name = transaction.get("contractName")
        address = transaction.get("contractAddress")
        if name in {"MockSettlementToken", "InferenceEscrow"} and isinstance(address, str):
            contracts[name] = address
    missing = {"MockSettlementToken", "InferenceEscrow"} - set(contracts)
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
                broadcast_root / "DeployBridgeE2E.s.sol" / str(CHAIN_ID) / "run-latest.json"
            )
            config["settlementContext"] = {
                "chainId": CHAIN_ID,
                "escrowAddress": deployments["InferenceEscrow"],
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
            source_ids = {row["routerJobId"] for row in batch["sourceReceipts"].values()}
            if source_ids != {"job_000001", "job_000002"}:
                raise RuntimeError("bridge did not preserve Router-native receipt references")
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
            print(f"claims={len(batch['claims'])} rootSum={batch['rootSum']}")
            return 0
        finally:
            if anvil_proc is not None:
                stop_process(anvil_proc)
            for proc in reversed(h0_procs):
                stop_process(proc)


if __name__ == "__main__":
    raise SystemExit(main())
