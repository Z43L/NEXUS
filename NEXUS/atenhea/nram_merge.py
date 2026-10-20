"""Merge an accepted NRA-M LoRA bundle into a fresh HF checkpoint copy."""

import argparse
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from nram_container import load_bundle
from nram_evolve import MODEL_DIR, attach_adapters, replace_submodule, restore_adapters


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent / "models" / "distilgpt2-nra-qa.nram")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest, tensors = load_bundle(args.bundle)
    adapter_spec = manifest["adapter"]
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, local_files_only=True)
    adapters = attach_adapters(model, adapter_spec["targets"], int(adapter_spec["rank"]), float(adapter_spec["alpha"]))
    restore_adapters(adapters, tensors)

    with torch.no_grad():
        for name, adapter in adapters.items():
            # GPT-2 Conv1D stores weights as [input, output].
            delta = adapter.lora_A.T @ adapter.lora_B.T
            adapter.base.weight.add_(delta.to(adapter.base.weight.dtype), alpha=adapter.scale)
            replace_submodule(model, name, adapter.base)

    args.output.mkdir(parents=True, exist_ok=True)
    model.config.use_cache = True
    model.save_pretrained(args.output, safe_serialization=True)
    AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True).save_pretrained(args.output)
    print(f"Merged NRA-M version {manifest['version']} -> {args.output}")


if __name__ == "__main__":
    main()
