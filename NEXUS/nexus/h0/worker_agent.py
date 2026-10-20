"""NEXUS H0 worker sidecar for Atenhea.

Runs NEXT TO Atenhea, never inside it (spec H0 adaptation of section 5.2):
- Polls the Router for jobs.
- Talks to the Atenhea ENGINE directly (default :11436, not the :11434 agent
  proxy), so remote jobs never touch CHL episodic memory or local tools.
- Enforces: no tools, token limits, FIFO serial execution (Atenhea is serial).
- Meters with Atenhea's own tokenizer endpoint, signs an Ed25519 receipt.

Run:  python3 worker_agent.py --router http://127.0.0.1:18080
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

import nexus_common as nc

BASE = Path(__file__).resolve().parent


def http_json(url: str, payload: dict | None = None, timeout=600) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if payload is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Worker:
    def __init__(self, router: str, atenea: str, node_dir: Path):
        self.router = router.rstrip("/")
        self.atenea = atenea.rstrip("/")
        self.priv, self.pub_pem, self.node_id = nc.load_or_create_node_key(node_dir)
        self.model_id = None

    # -- Atenhea -------------------------------------------------------------
    def atenea_models(self) -> list[str]:
        out = http_json(self.atenea + "/v1/models", timeout=15)
        return [m.get("id", "") for m in out.get("data", []) if m.get("id")]

    def count_input_tokens(self, messages: list[dict]) -> int | None:
        """Token count from the engine's own tokenizer.

        Endpoint dialects seen in the wild:
        - GitHub Atenhea engine: POST /v1/chat/completions/input_tokens
        - David's local Atenhea engine: POST /v1/messages/count_tokens only
        Returns None if the engine exposes neither; the caller then falls back
        to the usage block of the generation response (meter_source records it).
        """
        for path in ("/v1/chat/completions/input_tokens", "/v1/messages/count_tokens"):
            try:
                out = http_json(self.atenea + path,
                                {"model": self.model_id, "messages": messages}, timeout=120)
                return int(out["input_tokens"])
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
            except Exception:
                raise
        return None

    def run_inference(self, job: dict) -> dict:
        params = job.get("params") or {}
        payload = {
            "model": self.model_id,
            "messages": job["messages"],
            "temperature": params.get("temperature", 0.3),
            "max_tokens": min(int(params.get("max_tokens", 220)), 4096),
            "stream": False,
        }
        return http_json(self.atenea + "/v1/chat/completions", payload, timeout=1200)

    # -- Router ----------------------------------------------------------------
    def register(self, models: list[str], nram: list[str]) -> None:
        http_json(self.router + "/nodes/register", {
            "node_id": self.node_id, "pubkey_pem": self.pub_pem,
            "models": models, "nram": nram, "region": "local",
        }, timeout=15)

    def heartbeat(self) -> None:
        try:
            http_json(self.router + "/nodes/heartbeat", {"node_id": self.node_id}, timeout=10)
        except Exception:
            pass

    def next_job(self) -> dict | None:
        out = http_json(self.router + f"/jobs/next?node_id={self.node_id}", timeout=15)
        return out.get("job")

    def post_result(self, job_id: str, payload: dict) -> dict:
        return http_json(self.router + f"/jobs/{job_id}/result", payload, timeout=30)

    # -- Main loop ---------------------------------------------------------------
    def process(self, job: dict) -> None:
        job_id = job["job_id"]
        # Spec 5.2.3: remote jobs never run with tools.
        if job.get("tools"):
            self.post_result(job_id, {"status": "rejected",
                                      "error": "tools_not_allowed_in_remote_jobs"})
            print(f"[{job_id}] rejected: tools requested", flush=True)
            return
        started = time.time()
        started_iso = nc.utc_now_iso()
        counted_in = self.count_input_tokens(job["messages"])
        resp = self.run_inference(job)
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
            "model": self.model_id,
            "input_tokens": counted_in,
            "output_tokens": eng_out,
            "engine_prompt_tokens": eng_in,
            "engine_completion_tokens": eng_out,
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
                                  "dispatch_token": job.get("dispatch_token", ""),
                                  "output_text": output_text})
        print(f"[{job_id}] done in={counted_in} out={eng_out} "
              f"{receipt['elapsed_s']}s price={price}µ$", flush=True)

    def serve_forever(self) -> None:
        models = self.atenea_models()
        if not models:
            raise SystemExit("Atenhea engine returned no models at " + self.atenea)
        self.model_id = models[0]
        self.register(models, [])
        print(f"worker {self.node_id} model={self.model_id} atenea={self.atenea}", flush=True)
        idle = 0
        while True:
            try:
                job = self.next_job()
            except Exception as exc:
                print(f"router unreachable: {exc}", flush=True)
                time.sleep(3)
                continue
            if job is None:
                idle += 1
                if idle % 10 == 0:
                    self.heartbeat()
                time.sleep(1)
                continue
            idle = 0
            try:
                self.process(job)
            except Exception as exc:
                print(f"job {job.get('job_id')} failed: {exc}", flush=True)
                try:
                    self.post_result(job["job_id"], {"status": "rejected",
                                                      "error": f"worker_error: {exc}"})
                except Exception:
                    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", default="http://127.0.0.1:18080")
    ap.add_argument("--atenea", default="http://127.0.0.1:11436",
                    help="Atenhea ENGINE base URL (not the :11434 agent proxy)")
    ap.add_argument("--node-dir", default=str(BASE / "node"))
    args = ap.parse_args()
    Worker(args.router, args.atenea, Path(args.node_dir)).serve_forever()


if __name__ == "__main__":
    main()
