"""NEXUS H0 dogfood client: submits the batch, waits, and writes the H0 report.

Gate checks (spec section 11, H0):
- 100 inference jobs reach status 'done' with verified signed receipts.
- Ledger token totals vs engine-reported totals discrepancy <= 1%.
- The tools probe job is 'rejected'.
- Cost per 1M tokens computed from the real elapsed time and totals.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent


def http_json(url: str, payload: dict | None = None, timeout=60) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="GET" if payload is None else "POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--router", default="http://127.0.0.1:18080")
    ap.add_argument("--jobs", default=str(BASE / "jobs.jsonl"))
    ap.add_argument("--timeout-s", type=int, default=7200)
    ap.add_argument("--out", default=str(BASE / "h0_report.json"))
    args = ap.parse_args()
    router = args.router.rstrip("/")

    lines = [json.loads(l) for l in Path(args.jobs).read_text(encoding="utf-8").splitlines() if l.strip()]
    inference = [j for j in lines if j.get("kind") != "probe_tools"]
    probes = [j for j in lines if j.get("kind") == "probe_tools"]
    print(f"submitting {len(inference)} inference jobs + {len(probes)} probe(s)", flush=True)

    t0 = time.time()
    ids: dict[str, str] = {}
    for job in inference + probes:
        out = http_json(router + "/jobs", job)
        ids[out["job_id"]] = job.get("kind", "inference")

    pending = set(ids)
    while pending and time.time() - t0 < args.timeout_s:
        for job_id in list(pending):
            st = http_json(router + f"/jobs/{job_id}")
            if st["status"] in ("done", "rejected"):
                pending.discard(job_id)
        if pending:
            done = len(ids) - len(pending)
            print(f"progress: {done}/{len(ids)}", flush=True)
            time.sleep(5)
    elapsed = time.time() - t0

    states = {jid: http_json(router + f"/jobs/{jid}") for jid in ids}
    summary = http_json(router + "/ledger/summary")

    done_ids = [j for j, s in states.items() if s["status"] == "done"]
    probe_states = [states[j]["status"] for j, k in ids.items() if k == "probe_tools"]
    receipts = [states[j].get("receipt") for j in done_ids]
    max_disc = max((states[j].get("discrepancy_pct") or 0.0) for j in done_ids) if done_ids else 100.0
    out_tokens = summary["output_tokens"]
    total_elapsed_engine = sum((r or {}).get("elapsed_s", 0.0) for r in receipts)

    report = {
        "when": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "jobs_submitted": len(inference),
        "jobs_done": len(done_ids),
        "probe_status": probe_states,
        "verified_receipts": summary["verified_receipts"],
        "input_tokens": summary["input_tokens"],
        "output_tokens": out_tokens,
        "max_discrepancy_pct": max_disc,
        "total_price_usd_at_reference": summary["total_price_usd"],
        "splits_usd": {k: v / 1_000_000 for k, v in summary["splits_micro_usd"].items()},
        "wall_time_s": round(elapsed, 1),
        "engine_time_s": round(total_elapsed_engine, 1),
        "output_tokens_per_s_engine": round(out_tokens / total_elapsed_engine, 2) if total_elapsed_engine else None,
        "gate": {
            "100_jobs_done": len(done_ids) == len(inference) == 100,
            "all_receipts_verified": summary["verified_receipts"] == len(done_ids) and len(done_ids) > 0,
            "discrepancy_le_1pct": max_disc <= 1.0,
            "tools_probe_rejected": probe_states == ["rejected"] * len(probe_states) and len(probe_states) > 0,
        },
    }
    report["gate_passed"] = all(report["gate"].values())
    Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    print(f"report written to {args.out}", flush=True)


if __name__ == "__main__":
    main()
