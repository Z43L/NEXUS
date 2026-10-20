"""Create a zero-initialized, architecture-adapted NRAM bundle from an HF CausalLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nram_container import save_bundle
from nram_generic import (adapter_tensors, attach_adapters, discover_targets,
                          load_base_model, load_model_structure, load_tokenizer, weight_fingerprint)


def convert(args: argparse.Namespace) -> dict:
    low_memory = getattr(args, "low_memory", False)
    loader = load_model_structure if low_memory else load_base_model
    model = loader(args.model, revision=args.revision,
                   trust_remote_code=args.trust_remote_code, dtype=args.dtype)
    revision = args.revision or getattr(model.config, "_commit_hash", None)
    # A trainable causal-LM needs a matching tokenizer; fail early if the source
    # is only a tensor dump without tokenizer/config metadata.
    source = str(Path(args.model).resolve()) if Path(args.model).exists() else args.model
    tokenizer_source = args.tokenizer or source
    tokenizer_revision = args.tokenizer_revision or (revision if not args.tokenizer else None)
    tokenizer = load_tokenizer(
        tokenizer_source, revision=tokenizer_revision,
        trust_remote_code=args.trust_remote_code,
    )
    target_layouts = discover_targets(model, last_k_blocks=args.last_k_blocks,
                                      explicit=args.targets or None)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    adapters = attach_adapters(model, target_layouts, args.rank, args.alpha,
                               adapter_device="cpu" if low_memory else None)
    trainable = sum(parameter.numel() for adapter in adapters.values()
                    for parameter in adapter.parameters() if parameter.requires_grad)
    manifest = {
        "model_family": "hf-causal-lm-dense-lora",
        "model_name": Path(args.output).stem,
        "version": 0,
        "base_model": {
            "source": source,
            "revision": revision,
            "model_type": getattr(model.config, "model_type", "unknown"),
            "architectures": getattr(model.config, "architectures", None),
            "compute_dtype": args.dtype,
            "source_kind": "nram-v1-base-only" if Path(source).is_file() and Path(source).suffix == ".nram" else "transformers-checkpoint",
            "weights_sha256": weight_fingerprint(args.model),
            "tokenizer_source": tokenizer_source,
            "tokenizer_revision": tokenizer_revision,
        },
        "adapter": {
            "kind": "LoRA",
            "rank": args.rank,
            "alpha": args.alpha,
            "target_layouts": target_layouts,
            "targets": list(target_layouts),
            "selection": "explicit" if args.targets else "auto-last-block-projections",
            "last_k_blocks": args.last_k_blocks,
        },
        "graph": ["ENCODE", "READ", "TRANSFORM", "REFINE", "EVALUATE", "COMMIT", "DECODE", "HALT"],
        "tokenizer": {"class": tokenizer.__class__.__name__, "source": args.tokenizer or source},
        "evolution": {"objective": "lower held-out completion NLL", "optimizer_state_saved": False},
        "dataset": None,
        "last_validation": None,
        "journal": [],
    }
    if low_memory:
        from safetensors import safe_open
        source_path = Path(source)
        if not source_path.is_dir():
            raise ValueError("--low-memory requires a downloaded local checkpoint directory")
        # Validate target tensor topology from Safetensors headers, without loading the tensors.
        tensor_shapes = {}
        for shard in sorted(source_path.glob("*.safetensors")):
            with safe_open(shard, framework="pt", device="cpu") as handle:
                for key in handle.keys():
                    tensor_shapes[key] = list(handle.get_slice(key).get_shape())
        if not tensor_shapes:
            raise ValueError("No downloaded Safetensors weights found")
        for name in target_layouts:
            expected = list(adapters[name].base.weight.shape)
            if tensor_shapes.get(name + ".weight") != expected:
                raise ValueError(f"Checkpoint projection shape mismatch: {name}")
        manifest["conversion"] = {"method": "meta_structure_cpu_adapters_verified_checkpoint_headers",
                                  "base_weights_loaded": False, "target_shapes_verified": True}
    upstream_source = Path(source) / "onram-source.json"
    if upstream_source.is_file():
        upstream = json.loads(upstream_source.read_text())
        manifest["base_model"]["upstream"] = {
            "repo_id": upstream["repo_id"], "revision": upstream["revision"],
            "weight_files": [{"name": item["rfilename"], "size": item["size"],
                              "sha256": item.get("lfs", {}).get("sha256")}
                             for item in upstream["files"] if item["rfilename"].endswith(".safetensors")]}
    from self_improvement import build_snapshot
    manifest["self_knowledge"] = build_snapshot()
    manifest["episodic_memory"] = {"path": str(Path(__file__).resolve().parent / "models/athenea.memory")}
    save_bundle(args.output, manifest, adapter_tensors(adapters))
    return {"output": str(args.output), "model_type": manifest["base_model"]["model_type"],
            "revision": revision, "targets": list(target_layouts), "trainable_parameters": trainable,
            "rank": args.rank, "alpha": args.alpha, "compute_dtype": args.dtype, "format_version": 2}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Hugging Face causal-LM ID or local Transformers checkpoint")
    parser.add_argument("--tokenizer", help="Tokenizer ID/path if different from --model")
    parser.add_argument("--tokenizer-revision", help="Pinned tokenizer revision when --tokenizer is separate")
    parser.add_argument("--revision", help="Pinned Hub branch, tag, or commit")
    parser.add_argument("--dtype", choices=("float32", "float16", "bfloat16"), default="float32",
                        help="Frozen base/LoRA storage dtype; use bfloat16 to reduce memory on supported hardware")
    parser.add_argument("--output", type=Path, required=True, help="Output .nram bundle")
    parser.add_argument("--low-memory", action="store_true",
                        help="Create CPU LoRA adapters from a meta model; verify local Safetensors target shapes")
    parser.add_argument("--rank", type=int, default=4)
    parser.add_argument("--alpha", type=float, default=8.0)
    parser.add_argument("--last-k-blocks", type=int, default=1)
    parser.add_argument("--targets", nargs="+", help="Exact projection names or module suffixes; overrides auto selection")
    parser.add_argument("--trust-remote-code", action="store_true",
                        help="Allow executing custom model/tokenizer code from the model source")
    args = parser.parse_args()
    if args.rank < 1 or args.alpha <= 0:
        parser.error("rank must be positive and alpha must be greater than zero")
    print(json.dumps(convert(args), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
