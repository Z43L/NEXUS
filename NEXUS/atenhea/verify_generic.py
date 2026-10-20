"""Compare an active generic NRAM adapter against its merged HF checkpoint."""

from __future__ import annotations

import argparse
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM

from nram_generic import load_nram_model, load_tokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--merged", type=Path, required=True)
    parser.add_argument("--prompt", default="Question: What does ENCODE do?\nAnswer:")
    parser.add_argument("--max-diff", type=float, default=2e-4)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()
    manifest, adapted, _ = load_nram_model(args.bundle, local_files_only=args.local_files_only)
    tokenizer_source = manifest["base_model"].get("tokenizer_source") or manifest["base_model"]["source"]
    tokenizer = load_tokenizer(tokenizer_source,
        revision=manifest["base_model"].get("tokenizer_revision", manifest["base_model"].get("revision")),
        local_files_only=args.local_files_only)
    merged = AutoModelForCausalLM.from_pretrained(args.merged, local_files_only=True).eval()
    adapted.eval()
    ids = tokenizer(args.prompt, return_tensors="pt").input_ids
    with torch.inference_mode():
        diff = (adapted(input_ids=ids).logits - merged(input_ids=ids).logits).abs().max().item()
    if diff > args.max_diff:
        raise SystemExit(f"Merged checkpoint drift too high: {diff:.8g} > {args.max_diff}")
    print(f"model_type={manifest['base_model']['model_type']}")
    print(f"nram_version={manifest['version']}")
    print(f"target_count={len(manifest['adapter']['targets'])}")
    print(f"max_logit_diff={diff:.8g}")
    print("adapter and merged checkpoint match")


if __name__ == "__main__":
    main()
