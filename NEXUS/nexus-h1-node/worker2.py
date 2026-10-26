"""NEXUS H1 worker: H0 sidecar + JWT verification + heartbeat + wallet.

Differences vs H0 worker:
- Registers with an EVM wallet address (settlement identity) and receives the
  Router's public key; every dispatched job must carry a valid EdDSA JWT
  binding this node + job, verified BEFORE any execution (spec 6.1).
- Heartbeat thread (5 s) so the Router can detect death and fail over.
- Chat payloads carry "nexus_worker": true - engines built from this repo
  honor it by NOT injecting their agent training tool into remote jobs
  (H1 engine patch); other engines ignore the unknown field.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import ssl
import stat
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit

import nexus_common as nc
import jwt_auth

BASE = Path(__file__).resolve().parent


def validate_atenea_url(value: str) -> str:
    """Allow HTTP only for loopback or an explicitly named test service."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError:
        raise ValueError("Atenhea URL is malformed") from None
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host.lower() == "localhost"
    allowed_service = os.environ.get("NEXUS_H1_ALLOW_HTTP_SERVICE_NAME", "").strip().lower()
    if allowed_service and not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", allowed_service):
        raise ValueError("NEXUS_H1_ALLOW_HTTP_SERVICE_NAME must be one DNS service label")
    if allowed_service and allowed_service != "mock-atenea":
        raise ValueError("NEXUS_H1_ALLOW_HTTP_SERVICE_NAME is reserved for the private mock service")
    if (parsed.scheme not in {"http", "https"} or not host
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or port == 0):
        raise ValueError("Atenhea URL must be a plain HTTP(S) origin")
    if (parsed.scheme == "http" and not loopback and host.lower() != allowed_service):
        raise ValueError("Atenhea HTTP requires loopback or an explicitly allowed Compose test service")
    return value.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_ENGINE_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirect(),
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
)


def http_json(url: str, payload: dict | None = None, timeout=600,
              headers: dict[str, str] | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=data, method="GET" if payload is None else "POST",
                                 headers=request_headers)
    with _ENGINE_OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read_atenea_api_key(path: str | None) -> str | None:
    if path is None:
        return None
    key_path = Path(path)
    try:
        key_stat = key_path.stat()
        if key_path.is_symlink() or not stat.S_ISREG(key_stat.st_mode) or key_stat.st_mode & 0o077:
            raise ValueError("Atenhea API key file permissions must be 0600")
        value = key_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("cannot read Atenhea API key file") from exc
    if len(value) < 32:
        raise ValueError("Atenhea API key must contain at least 32 characters")
    return value


class Worker:
    def __init__(self, router: str, atenea: str, node_dir: Path, wallet: str,
                 router_ca: str | None = None, enrollment_token_file: str | None = None,
                 atenea_api_key_file: str | None = None):
        self.router = router.rstrip("/")
        self.atenea = validate_atenea_url(atenea)
        self.atenea_api_key = self._read_atenea_api_key(atenea_api_key_file)
        host = urlsplit(self.atenea).hostname or ""
        # Only a loopback engine shares this process' trust boundary. Docker's
        # host gateway and named services cross a container boundary and must
        # authenticate even when they use an explicitly permitted HTTP route.
        is_local_engine = host.lower() == "localhost"
        try:
            is_local_engine = is_local_engine or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if not is_local_engine and self.atenea_api_key is None:
            raise ValueError("remote Atenhea requires an API key file")
        self.wallet = wallet
        parsed_router = urlsplit(self.router)
        if (not parsed_router.hostname or parsed_router.username or parsed_router.password
                or parsed_router.path not in ("", "/") or parsed_router.query or parsed_router.fragment):
            raise ValueError("Router URL must contain only scheme, host and optional port")
        self.router_ssl_context = None
        self.enrollment_token = ""
        if parsed_router.scheme == "https":
            if not router_ca or not enrollment_token_file:
                raise ValueError("HTTPS Router requires a CA file and enrollment-token file")
            self.router_ssl_context = ssl.create_default_context(cafile=router_ca)
            self.enrollment_token = self._read_enrollment_token(enrollment_token_file)
        elif parsed_router.scheme == "http":
            try:
                is_loopback = ipaddress.ip_address(parsed_router.hostname or "").is_loopback
            except ValueError:
                is_loopback = (parsed_router.hostname or "").lower() == "localhost"
            if not is_loopback or router_ca or enrollment_token_file:
                raise ValueError("HTTP Router is allowed only on loopback without remote security options")
        else:
            raise ValueError("Router URL must use HTTPS remotely or HTTP on loopback locally")
        self.router_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
            urllib.request.HTTPSHandler(context=self.router_ssl_context),
        )
        self.priv, self.pub_pem, self.node_id = nc.load_or_create_node_key(node_dir)
        self.ready_file = node_dir / ".worker-ready"
        # A previous container run may have left its marker in the persistent
        # node volume. Readiness is restored only after engine discovery and
        # successful Router registration in this process.
        self.ready_file.unlink(missing_ok=True)
        self.model_id = None
        self.models: list[str] = []
        self.scaffolding_tokens = 0
        self.router_pub_pem = ""

    @staticmethod
    def _read_atenea_api_key(path: str | None) -> str | None:
        return read_atenea_api_key(path)

    def _atenea_headers(self) -> dict[str, str]:
        if self.atenea_api_key is None:
            return {}
        return {"Authorization": f"Bearer {self.atenea_api_key}"}

    @staticmethod
    def _read_enrollment_token(path: str) -> str:
        token_path = Path(path)
        try:
            if token_path.stat().st_mode & 0o077:
                raise ValueError("enrollment-token file permissions must be 0600")
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError("cannot read enrollment-token file") from exc
        if len(token) < 32:
            raise ValueError("enrollment token must contain at least 32 characters")
        return token

    def router_json(self, path: str, payload: dict | None = None, timeout=30) -> dict:
        method = "GET" if payload is None else "POST"
        body = payload or {}
        headers = {"Content-Type": "application/json"}
        headers.update(nc.sign_node_request(self.priv, method, path, body))
        headers["X-Nexus-Node-ID"] = self.node_id
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.router + path, data=data, method=method, headers=headers)
        with self.router_opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def atenea_models(self) -> list[str]:
        out = http_json(self.atenea + "/v1/models", timeout=15,
                        headers=self._atenea_headers())
        return [m.get("id", "") for m in out.get("data", []) if m.get("id")]

    def count_input_tokens(self, messages: list[dict]) -> int | None:
        for path in ("/v1/chat/completions/input_tokens", "/v1/messages/count_tokens"):
            try:
                out = http_json(self.atenea + path,
                                {"model": self.model_id, "messages": messages}, timeout=120,
                                headers=self._atenea_headers())
                return int(out["input_tokens"])
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
        return None

    def calibrate_scaffolding(self) -> int:
        probe = [{"role": "user", "content": "nexus calibration ping"}]
        counted = self.count_input_tokens(probe)
        if counted is None:
            return 0
        resp = http_json(self.atenea + "/v1/chat/completions", {
            "model": self.model_id, "messages": probe,
            "temperature": 0.0, "max_tokens": 1, "stream": False,
        }, timeout=1200, headers=self._atenea_headers())
        eng_prompt = int((resp.get("usage") or {}).get("prompt_tokens", counted))
        return max(0, eng_prompt - counted)

    def run_inference(self, job: dict, model_id: str) -> dict:
        params = job.get("params") or {}
        payload = {
            "model": model_id,
            "messages": job["messages"],
            "temperature": params.get("temperature", 0.3),
            "max_tokens": min(int(params.get("max_tokens", 220)), 4096),
            "stream": False,
            "nexus_worker": True,
        }
        owner = job.get("owner_client_id")
        if owner is not None:
            payload["nexus_user"] = owner
        return http_json(self.atenea + "/v1/chat/completions", payload, timeout=1200,
                         headers=self._atenea_headers())

    def register(self, models: list[str], nram: list[str]) -> None:
        out = self.router_json("/nodes/register", {
            "node_id": self.node_id, "pubkey_pem": self.pub_pem,
            "models": models, "nram": nram, "region": "local",
            "wallet": self.wallet,
            **({"enrollment_token": self.enrollment_token}
               if self.enrollment_token else {}),
        }, timeout=15)
        self.router_pub_pem = out.get("router_pubkey_pem", "")

    def heartbeat_loop(self) -> None:
        while True:
            try:
                self.router_json("/nodes/heartbeat", {"node_id": self.node_id}, timeout=10)
                self.ready_file.touch()
            except Exception:
                self.ready_file.unlink(missing_ok=True)
            time.sleep(5)

    def next_job(self) -> dict | None:
        out = self.router_json(f"/jobs/next?node_id={self.node_id}", timeout=15)
        return out.get("job")

    def post_result(self, job_id: str, payload: dict) -> dict:
        return self.router_json(f"/jobs/{job_id}/result", payload, timeout=30)

    def process(self, job: dict) -> None:
        job_id = job["job_id"]
        # JWT gate: nothing executes without a Router signature binding
        # this node to this job.
        try:
            jwt_auth.verify_job_jwt(self.router_pub_pem, job.get("dispatch_jwt", ""),
                                    self.node_id, job_id)
        except ValueError as exc:
            print(f"[{job_id}] refused: invalid dispatch jwt ({exc})", flush=True)
            return
        if job.get("tools"):
            self.post_result(job_id, {"status": "rejected",
                                      "error": "tools_not_allowed_in_remote_jobs",
                                      "dispatch_jwt": job.get("dispatch_jwt", "")})
            print(f"[{job_id}] rejected: tools requested", flush=True)
            return
        started = time.time()
        started_iso = nc.utc_now_iso()
        model_id = nc.resolve_model(job.get("model", ""), self.models)
        counted_in = self.count_input_tokens(job["messages"])
        resp = self.run_inference(job, model_id)
        finished = time.time()
        choice = (resp.get("choices") or [{}])[0]
        output_text = ((choice.get("message") or {}).get("content")
                       or choice.get("text") or "")
        usage = resp.get("usage") or {}
        eng_in = int(usage.get("prompt_tokens", counted_in or 0))
        eng_out = int(usage.get("completion_tokens", 0))
        if counted_in is None:
            counted_in = eng_in
            meter_source = "engine_usage_fallback"
        else:
            meter_source = "engine_tokenizer_endpoint"
        nram_used = bool(job.get("nram"))
        price = nc.price_micro_usd(counted_in, eng_out)
        receipt = {
            "job_id": job_id,
            "node_id": self.node_id,
            "model": model_id,
            "input_tokens": counted_in,
            "output_tokens": eng_out,
            "engine_prompt_tokens": eng_in,
            "engine_completion_tokens": eng_out,
            "scaffolding_tokens": self.scaffolding_tokens,
            "meter_source": meter_source,
            "nram_used": job.get("nram", []),
            "started_at": started_iso,
            "finished_at": nc.utc_now_iso(),
            "elapsed_s": round(finished - started, 3),
            "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest(),
            "price_micro_usd": price,
            "shares": nc.split_payment(price, nram_used),
        }
        signature = nc.sign_receipt(self.priv, receipt)
        self.post_result(job_id, {"status": "done", "receipt": receipt,
                                  "signature": signature,
                                  "dispatch_jwt": job.get("dispatch_jwt", ""),
                                  "output_text": output_text})
        print(f"[{job_id}] done in={counted_in} out={eng_out} "
              f"{receipt['elapsed_s']}s price={price}µ$", flush=True)

    def serve_forever(self) -> None:
        models = self.atenea_models()
        if not models:
            raise SystemExit("engine returned no models at " + self.atenea)
        self.model_id = models[0]
        self.models = models
        self.scaffolding_tokens = self.calibrate_scaffolding()
        self.register(models, [])
        self.ready_file.touch()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        print(f"worker {self.node_id} model={self.model_id} wallet={self.wallet} "
              f"scaffolding_tokens={self.scaffolding_tokens}", flush=True)
        while True:
            try:
                job = self.next_job()
            except Exception as exc:
                print(f"router unreachable: {exc}", flush=True)
                time.sleep(3)
                continue
            if job is None:
                time.sleep(1)
                continue
            try:
                self.process(job)
            except Exception as exc:
                transient = nc.is_transient_transport_error(exc)
                status = "retry" if transient else "rejected"
                error = (f"transient {type(exc).__name__}" if transient
                         else f"worker_error: {exc}")
                print(f"job {job.get('job_id')} {status}: {error}", flush=True)
                try:
                    self.post_result(job["job_id"], {"status": status,
                                                      "error": error,
                                                      "dispatch_jwt": job.get("dispatch_jwt", "")})
                except Exception:
                    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", default="http://127.0.0.1:18090")
    ap.add_argument("--atenea", default="http://127.0.0.1:11436")
    ap.add_argument("--node-dir", default=str(BASE / "node"))
    ap.add_argument("--wallet", default="")
    ap.add_argument("--router-ca", help="CA PEM used to verify an HTTPS Router")
    ap.add_argument("--enrollment-token-file",
                    help="0600 file containing the one-time node enrollment token")
    ap.add_argument("--atenea-api-key-file",
                    help="0600 file containing the worker credential for Atenhea")
    args = ap.parse_args()
    try:
        worker = Worker(args.router, args.atenea, Path(args.node_dir), args.wallet,
                        router_ca=args.router_ca,
                        enrollment_token_file=args.enrollment_token_file,
                        atenea_api_key_file=args.atenea_api_key_file)
    except (ValueError, OSError, ssl.SSLError) as exc:
        ap.error(f"invalid Router security configuration: {exc}")
    worker.serve_forever()


if __name__ == "__main__":
    main()
