"""Compose health checks for the private H1 Router/worker image."""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def get_json(url: str, context: ssl.SSLContext | None = None) -> dict:
    with urlopen(url, timeout=5, context=context) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    ca_path = os.environ.get("ROUTER_CA_FILE", "/run/secrets/router_ca")
    context = ssl.create_default_context(cafile=ca_path)
    router = os.environ.get("ROUTER_URL", "https://router:18080").rstrip("/")
    try:
        if get_json(router + "/ready", context).get("ok") is not True:
            return 1
        if mode == "router":
            return 0
        if mode == "worker":
            ready_file = Path(os.environ.get(
                "NEXUS_WORKER_READY_FILE", "/var/lib/nexus/node/.worker-ready"
            ))
            try:
                age_seconds = time.time() - ready_file.stat().st_mtime
            except OSError:
                return 1
            if age_seconds < -5 or age_seconds > 30:
                return 1
            atenea = os.environ["ATENHEA_URL"].rstrip("/")
            models = get_json(atenea + "/v1/models").get("data")
            return 0 if isinstance(models, list) and any(
                isinstance(item, dict) and isinstance(item.get("id"), str)
                and item["id"].strip() for item in models
            ) else 1
    except (KeyError, OSError, ValueError, ssl.SSLError):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
