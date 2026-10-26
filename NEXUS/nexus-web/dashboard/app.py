"""Compatibility entrypoint for the retired Flask dashboard.

The dashboard formerly targeted a placeholder remote API and had no template.
Route it through the canonical local H0 UI/BFF instead, so old launch commands
inherit its host checks, request bounds and server-side API token handling.
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

from h0_local import serve  # noqa: E402


if __name__ == "__main__":
    serve()
