"""Merge a generic HF causal-LM NRAM LoRA bundle into a Transformers checkpoint."""

from __future__ import annotations

import argparse
from pathlib import Path

from nram_generic import load_nram_model, load_tokenizer, merge_adapters


def merge(bundle: Path, output: Path, model: str | None, tokenizer_source: str | None,
          trust_remote_code: bool) -> None:
    manifest, base, adapters = load_nram_model(
        bundle, source=model, trust_remote_code=trust_remote_code,
    )
    if manifest.get("micro_extension", {}).get("enabled"):
        raise ValueError("Nonlinear micro-MLPs require the Transformers hook runtime; disable the extension explicitly before ordinary GGUF export")
    merge_adapters(base, adapters)
    output.mkdir(parents=True, exist_ok=True)
    base.config.use_cache = True
    base.save_pretrained(output, safe_serialization=True)
    tok_source = tokenizer_source or manifest["base_model"].get("tokenizer_source") or manifest["base_model"]["source"]
    tokenizer = load_tokenizer(
        tok_source, revision=manifest["base_model"].get("tokenizer_revision", manifest["base_model"].get("revision")),
        trust_remote_code=trust_remote_code,
    )
    tokenizer.save_pretrained(output)
    print(f"Merged NRA-M v{manifest['version']} ({manifest['base_model']['model_type']}) -> {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", help="Override the base model source stored in the bundle")
    parser.add_argument("--tokenizer")
    parser.add_argument("--trust-remote-code", action="store_true")
    args = parser.parse_args()
    merge(args.bundle, args.output, args.model, args.tokenizer, args.trust_remote_code)


if __name__ == "__main__":
    main()
