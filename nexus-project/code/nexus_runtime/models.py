"""Pick the right client-side head for a published model dir (demo MLP or real Llama)."""
from __future__ import annotations

import json
import os


def load_head(model_dir: str):
    with open(os.path.join(model_dir, "meta.json")) as f:
        kind = json.load(f).get("kind", "mlp")
    if kind == "llama":
        from .llama import LlamaHead  # needs numpy + tokenizers
        return LlamaHead.load(model_dir)
    from .model_demo import DemoModel
    return DemoModel.load_head(model_dir)
