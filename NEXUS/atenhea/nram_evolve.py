"""Train and transactionally validate a low-rank mutation on DistilGPT2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer

from nram_container import load_bundle, save_bundle

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models" / "distilgpt2"
MODEL_ID = "distilbert/distilgpt2"
MODEL_REVISION = "2290a62682d06624634c1f46a6ad5be0f47f38aa"
DEFAULT_TARGETS = ["transformer.h.5.attn.c_attn", "transformer.h.5.mlp.c_proj"]


class LoRAConv1D(nn.Module):
    """Frozen GPT-2 Conv1D plus a trainable rank-r residual projection."""

    def __init__(self, base: nn.Module, rank: int, alpha: float):
        super().__init__()
        self.base = base
        in_features, out_features = base.weight.shape
        self.lora_A = nn.Parameter(torch.empty(rank, in_features, dtype=base.weight.dtype))
        self.lora_B = nn.Parameter(torch.zeros(out_features, rank, dtype=base.weight.dtype))
        nn.init.kaiming_uniform_(self.lora_A, a=5**0.5)
        self.scale = float(alpha) / rank

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = F.linear(F.linear(x, self.lora_A), self.lora_B) * self.scale
        return self.base(x) + residual


def replace_submodule(model: nn.Module, name: str, replacement: nn.Module | None = None) -> nn.Module:
    parent_name, _, child_name = name.rpartition(".")
    parent = model.get_submodule(parent_name) if parent_name else model
    old = getattr(parent, child_name)
    if replacement is not None:
        setattr(parent, child_name, replacement)
    return old


def attach_adapters(model: nn.Module, targets: list[str], rank: int, alpha: float) -> dict[str, LoRAConv1D]:
    adapters: dict[str, LoRAConv1D] = {}
    for name in targets:
        base = replace_submodule(model, name)
        if not hasattr(base, "weight") or base.weight.ndim != 2:
            raise TypeError(f"Target {name} is not a supported 2D GPT-2 projection")
        adapter = LoRAConv1D(base, rank, alpha)
        replace_submodule(model, name, adapter)
        adapters[name] = adapter
    return adapters


def adapter_tensors(adapters: dict[str, LoRAConv1D]) -> dict[str, torch.Tensor]:
    return {
        f"{name}.{part}": getattr(module, part).detach().cpu().clone()
        for name, module in adapters.items()
        for part in ("lora_A", "lora_B")
    }


def restore_adapters(adapters: dict[str, LoRAConv1D], tensors: dict[str, torch.Tensor]) -> None:
    expected = {f"{name}.{part}" for name in adapters for part in ("lora_A", "lora_B")}
    if set(tensors) != expected:
        raise ValueError("Adapter tensor names do not match requested graph targets")
    with torch.no_grad():
        for name, module in adapters.items():
            for part in ("lora_A", "lora_B"):
                getattr(module, part).copy_(tensors[f"{name}.{part}"].to(getattr(module, part).device))


def read_jsonl(path: Path) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"No examples found in {path}")
    for i, row in enumerate(rows):
        if not isinstance(row.get("prompt"), str) or not isinstance(row.get("completion"), str):
            raise ValueError(f"Example {i} must have string fields 'prompt' and 'completion'")
        if not row["prompt"].strip() or not row["completion"].strip():
            raise ValueError(f"Example {i} has an empty prompt or completion")
    return rows


def encode_example(tokenizer: Any, row: dict[str, str], max_length: int) -> tuple[torch.Tensor, torch.Tensor, int]:
    prompt_ids = tokenizer(row["prompt"], add_special_tokens=False)["input_ids"]
    completion_ids = tokenizer(row["completion"], add_special_tokens=False)["input_ids"]
    if tokenizer.eos_token_id is not None:
        completion_ids = completion_ids + [tokenizer.eos_token_id]
    if not prompt_ids or not completion_ids:
        raise ValueError("Each example must tokenize to at least one prompt and target token")
    ids = (prompt_ids + completion_ids)[:max_length]
    prompt_len = min(len(prompt_ids), len(ids))
    labels = [-100] * prompt_len + ids[prompt_len:]
    if not any(token != -100 for token in labels[1:]):
        raise ValueError("max_length leaves no completion token to score")
    return torch.tensor([ids], dtype=torch.long), torch.tensor([labels], dtype=torch.long), len([x for x in labels[1:] if x != -100])


def score(model: nn.Module, tokenizer: Any, rows: list[dict[str, str]], max_length: int) -> float:
    model.eval()
    total_loss = 0.0
    total_tokens = 0
    with torch.no_grad():
        for row in rows:
            ids, labels, count = encode_example(tokenizer, row, max_length)
            loss = model(input_ids=ids, labels=labels).loss
            total_loss += float(loss) * count
            total_tokens += count
    return total_loss / total_tokens


def first_token_metrics(model: nn.Module, tokenizer: Any, rows: list[dict[str, str]]) -> dict[str, float]:
    """Measure the rank of the first expected answer token at generation time."""
    model.eval()
    ranks = []
    with torch.no_grad():
        for row in rows:
            prompt_ids = tokenizer(row["prompt"], add_special_tokens=False, return_tensors="pt").input_ids
            target_ids = tokenizer(row["completion"], add_special_tokens=False)["input_ids"]
            logits = model(input_ids=prompt_ids).logits[0, -1]
            target_id = target_ids[0]
            ranks.append(int((logits > logits[target_id]).sum()) + 1)
    return {
        "mean_rank": sum(ranks) / len(ranks),
        "top1_hits": float(sum(rank == 1 for rank in ranks)),
        "examples": float(len(ranks)),
    }


def train_epoch(model: nn.Module, tokenizer: Any, rows: list[dict[str, str]], optimizer: torch.optim.Optimizer, max_length: int) -> float:
    model.eval()  # keep the frozen base deterministic; LoRA has no dropout
    random.shuffle(rows)
    total_loss = 0.0
    total_tokens = 0
    for row in rows:
        ids, labels, count = encode_example(tokenizer, row, max_length)
        optimizer.zero_grad(set_to_none=True)
        loss = model(input_ids=ids, labels=labels).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
        optimizer.step()
        total_loss += float(loss.detach()) * count
        total_tokens += count
    return total_loss / total_tokens


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(args: argparse.Namespace) -> dict[str, Any]:
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    torch.set_num_threads(args.threads)
    train_rows = read_jsonl(args.train)
    validation_rows = read_jsonl(args.validation)
    guardrail_rows = read_jsonl(args.guardrail) if args.guardrail else None

    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, local_files_only=True)
    base_weights = MODEL_DIR / "model.safetensors"
    base_hash = file_sha256(base_weights)
    model.config.use_cache = False
    for param in model.parameters():
        param.requires_grad_(False)
    adapters = attach_adapters(model, args.targets, args.rank, args.alpha)
    trainable_count = sum(p.numel() for module in adapters.values() for p in module.parameters() if p.requires_grad)

    existing_manifest = None
    if args.output.exists():
        existing_manifest, existing_tensors = load_bundle(args.output)
        if existing_manifest.get("base_model", {}).get("revision") != MODEL_REVISION:
            raise ValueError("Existing NRA-M bundle is pinned to a different base model revision")
        if existing_manifest.get("base_model", {}).get("weights_sha256") != base_hash:
            raise ValueError("Local base weights differ from those recorded in the NRA-M bundle")
        if existing_manifest.get("adapter", {}).get("targets") != args.targets:
            raise ValueError("Existing NRA-M bundle uses different graph targets")
        if existing_manifest.get("adapter", {}).get("rank") != args.rank:
            raise ValueError("Existing NRA-M bundle uses a different LoRA rank")
        restore_adapters(adapters, existing_tensors)

    val_before = score(model, tokenizer, validation_rows, args.max_length)
    first_token_before = first_token_metrics(model, tokenizer, validation_rows)
    guardrail_before = score(model, tokenizer, guardrail_rows, args.max_length) if guardrail_rows else None
    trainable = [p for module in adapters.values() for p in module.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate, weight_decay=args.weight_decay)
    epoch_losses = []
    for epoch in range(args.epochs):
        epoch_losses.append(train_epoch(model, tokenizer, list(train_rows), optimizer, args.max_length))
        print(f"epoch {epoch + 1}/{args.epochs}: train_nll={epoch_losses[-1]:.5f}", flush=True)

    val_after = score(model, tokenizer, validation_rows, args.max_length)
    first_token_after = first_token_metrics(model, tokenizer, validation_rows)
    guardrail_after = score(model, tokenizer, guardrail_rows, args.max_length) if guardrail_rows else None
    guardrail_ok = guardrail_before is None or guardrail_after <= guardrail_before * (1.0 + args.max_guardrail_drift)
    first_token_ok = first_token_after["mean_rank"] <= first_token_before["mean_rank"] - args.min_first_token_rank_improvement
    accepted = val_after + args.min_improvement < val_before and guardrail_ok and first_token_ok
    current_version = int(existing_manifest["version"]) if existing_manifest else 0
    report = {
        "accepted": accepted,
        "validation_nll_before": val_before,
        "validation_nll_after": val_after,
        "first_token_rank_before": first_token_before["mean_rank"],
        "first_token_rank_after": first_token_after["mean_rank"],
        "first_token_top1_hits_before": first_token_before["top1_hits"],
        "first_token_top1_hits_after": first_token_after["top1_hits"],
        "guardrail_nll_before": guardrail_before,
        "guardrail_nll_after": guardrail_after,
        "guardrail_ok": guardrail_ok,
        "trainable_parameters": trainable_count,
        "version": current_version,
    }

    if not accepted:
        print(json.dumps(report, indent=2))
        return report

    version = current_version + 1
    report["version"] = version
    journal = list(existing_manifest.get("journal", [])) if existing_manifest else []
    journal.append({**report, "version": version, "epochs": args.epochs, "learning_rate": args.learning_rate})
    manifest = {
        "model_name": f"DistilGPT2 NRA-M v{version}",
        "version": version,
        "base_model": {
            "repo_id": MODEL_ID,
            "revision": MODEL_REVISION,
            "weights_sha256": base_hash,
        },
        "adapter": {"kind": "LoRA", "rank": args.rank, "alpha": args.alpha, "targets": args.targets},
        "graph": ["ENCODE", "READ", "TRANSFORM", "REFINE", "EVALUATE", "BRANCH", "COMMIT", "DECODE", "HALT"],
        "evolution": {"objective": "lower held-out completion-token NLL", "optimizer_state_saved": False},
        "dataset": {
            "train_file": str(args.train),
            "train_sha256": file_sha256(args.train),
            "train_examples": len(train_rows),
            "validation_file": str(args.validation),
            "validation_sha256": file_sha256(args.validation),
            "validation_examples": len(validation_rows),
            "guardrail_file": str(args.guardrail) if args.guardrail else None,
            "guardrail_sha256": file_sha256(args.guardrail) if args.guardrail else None,
        },
        "last_validation": report,
        "journal": journal,
    }
    save_bundle(args.output, manifest, adapter_tensors(adapters))
    report["output"] = str(args.output)
    print(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--guardrail", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "models" / "distilgpt2-nra-qa.nram")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--rank", type=int, default=4)
    parser.add_argument("--alpha", type=float, default=8.0)
    parser.add_argument("--learning-rate", type=float, default=5e-4)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--min-improvement", type=float, default=1e-4)
    parser.add_argument("--min-first-token-rank-improvement", type=float, default=0.0)
    parser.add_argument("--max-guardrail-drift", type=float, default=0.05)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--targets", nargs="+", default=DEFAULT_TARGETS)
    args = parser.parse_args()
    if args.epochs < 1 or args.rank < 1:
        parser.error("--epochs and --rank must be positive")
    run(args)


if __name__ == "__main__":
    main()
