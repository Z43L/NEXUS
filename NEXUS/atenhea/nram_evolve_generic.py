"""Train and safely accept a LoRA update for any compatible HF causal LM."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import time
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F
from nram_generic import load_nram_model, load_tokenizer, save_accepted_bundle
from nram_container import load_bundle, save_bundle
from runtime_attribution import build_runtime_activation_profile
from episodic_memory import DEFAULT_MEMORY, EpisodicMemory
from self_improvement import prepare_training, inspect_adapters, proposal_context, request_proposal


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"No examples found in {path}")
    for index, row in enumerate(rows):
        if not isinstance(row.get("prompt"), str) or not isinstance(row.get("completion"), str):
            raise ValueError(f"Example {index} needs string fields 'prompt' and 'completion'")
        if not row["prompt"].strip() or not row["completion"].strip():
            raise ValueError(f"Example {index} has an empty prompt or completion")
    return rows


def encode(tokenizer: Any, row: dict[str, Any], max_length: int) -> dict[str, Any]:
    if getattr(tokenizer, "chat_template", None):
        messages = [{"role": "user", "content": row["prompt"]}]
        prompt_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )
        full_text = tokenizer.apply_chat_template(
            messages + [{"role": "assistant", "content": row["completion"]}],
            tokenize=False, add_generation_prompt=False,
        )
        prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
        ids = tokenizer(full_text, add_special_tokens=False)["input_ids"]
        completion_ids = ids[len(prompt_ids):]
    else:
        prompt_ids = tokenizer(row["prompt"], add_special_tokens=False)["input_ids"]
        completion_ids = tokenizer(row["completion"], add_special_tokens=False)["input_ids"]
        ids = prompt_ids + completion_ids
    if tokenizer.eos_token_id is not None:
        completion_ids = completion_ids + [tokenizer.eos_token_id]
    if not prompt_ids or not completion_ids:
        raise ValueError("Prompt and completion must each tokenize to at least one token")
    ids = ids + ([tokenizer.eos_token_id] if tokenizer.eos_token_id is not None else [])
    ids = ids[:max_length]
    prompt_len = min(len(prompt_ids), len(ids))
    labels = [-100] * prompt_len + ids[prompt_len:]
    if not any(token != -100 for token in labels[1:]):
        raise ValueError("max_length leaves no completion token to score")
    encoded = {"input_ids": ids, "labels": labels,
               "prompt_ids": prompt_ids[:max_length], "target_id": completion_ids[0],
               "prompt": row["prompt"]}
    if "expected_contains" in row:
        encoded["expected_contains"] = row["expected_contains"]
    for key in ("runtime_pair_sha256", "runtime_feedback", "runtime_trace_id"):
        if key in row:
            encoded[key] = row[key]
    return encoded


def collate(rows: list[dict[str, Any]], tokenizer: Any, device: torch.device,
            *, prompts_only: bool = False) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    pad_id = tokenizer.pad_token_id
    if pad_id is None:
        pad_id = tokenizer.eos_token_id if tokenizer.eos_token_id is not None else 0
    sequences = [row["prompt_ids"] if prompts_only else row["input_ids"] for row in rows]
    width = max(map(len, sequences))
    input_ids = torch.full((len(rows), width), pad_id, dtype=torch.long, device=device)
    attention_mask = torch.zeros((len(rows), width), dtype=torch.long, device=device)
    labels = torch.full((len(rows), width), -100, dtype=torch.long, device=device)
    for index, sequence in enumerate(sequences):
        length = len(sequence)
        input_ids[index, :length] = torch.tensor(sequence, dtype=torch.long, device=device)
        attention_mask[index, :length] = 1
        if not prompts_only:
            target = rows[index]["labels"]
            labels[index, :len(target)] = torch.tensor(target, dtype=torch.long, device=device)
    return input_ids, attention_mask, labels


def make_batches(rows: list[dict[str, Any]], batch_size: int, *, shuffle: bool = False
                 ) -> list[list[dict[str, Any]]]:
    ordered = list(rows)
    if shuffle:
        random.shuffle(ordered)
    # Bucket similar lengths to reduce padding while retaining training-order randomness.
    window = batch_size * 8
    batches = []
    for offset in range(0, len(ordered), window):
        group = ordered[offset:offset + window]
        group.sort(key=lambda row: len(row["input_ids"]))
        batches.extend(group[index:index + batch_size] for index in range(0, len(group), batch_size))
    if shuffle:
        random.shuffle(batches)
    return batches


@torch.no_grad()
def score(model: nn.Module, tokenizer: Any, rows: list[dict[str, Any]],
          device: torch.device, batch_size: int) -> float:
    model.eval()
    total_loss = 0.0
    total_tokens = 0
    for batch in make_batches(rows, batch_size):
        ids, attention_mask, labels = collate(batch, tokenizer, device)
        logits = model(input_ids=ids, attention_mask=attention_mask).logits[:, :-1].float()
        targets = labels[:, 1:]
        loss_sum = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1),
                                   ignore_index=-100, reduction="sum")
        total_loss += float(loss_sum)
        total_tokens += int(targets.ne(-100).sum().item())
    return total_loss / total_tokens


@torch.no_grad()
def first_token_rank(model: nn.Module, rows: list[dict[str, Any]], tokenizer: Any,
                     device: torch.device, batch_size: int) -> dict[str, float]:
    model.eval()
    ranks: list[int] = []
    prompts = [{"input_ids": row["prompt_ids"], "prompt_ids": row["prompt_ids"],
                "target_id": row["target_id"]} for row in rows]
    for batch in make_batches(prompts, batch_size):
        ids, attention_mask, _ = collate(batch, tokenizer, device, prompts_only=True)
        logits = model(input_ids=ids, attention_mask=attention_mask).logits.float()
        last_indices = attention_mask.sum(dim=1) - 1
        batch_indices = torch.arange(len(batch), device=device)
        final_logits = logits[batch_indices, last_indices]
        for index, row in enumerate(batch):
            target = row["target_id"]
            ranks.append(int((final_logits[index] > final_logits[index, target]).sum().item()) + 1)
    return {"mean_rank": sum(ranks) / len(ranks),
            "top1_hits": float(sum(rank == 1 for rank in ranks)), "examples": float(len(ranks))}


@torch.no_grad()
def behavior_accuracy(model: nn.Module, tokenizer: Any, rows: list[dict[str, Any]] | None,
                      device: torch.device) -> dict[str, float] | None:
    """Check that generated answers actually contain the held-out fact."""
    cases = [row for row in rows or [] if row.get("expected_contains")]
    if not cases:
        return None
    model.eval()
    correct = 0
    refusals = ("no tengo información", "no puedo saber", "don't have information",
                "cannot know your name", "can't know your name")
    for row in cases:
        if getattr(tokenizer, "chat_template", None):
            rendered = tokenizer.apply_chat_template(
                [{"role": "user", "content": row["prompt"]}],
                tokenize=False, add_generation_prompt=True,
            )
            encoded = tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
        else:
            encoded = tokenizer(row["prompt"], return_tensors="pt")
        encoded = encoded.to(device)
        output = model.generate(**encoded, max_new_tokens=32, do_sample=False,
                                pad_token_id=tokenizer.eos_token_id)
        answer = tokenizer.decode(output[0, encoded["input_ids"].shape[1]:],
                                  skip_special_tokens=True).casefold()
        expected = row["expected_contains"]
        terms = expected if isinstance(expected, list) else [expected]
        if (all(isinstance(term, str) and term.casefold() in answer for term in terms)
                and not any(refusal in answer for refusal in refusals)):
            correct += 1
    return {"accuracy": correct / len(cases), "correct": float(correct),
            "examples": float(len(cases))}


def train_epoch(model: nn.Module, tokenizer: Any, rows: list[dict[str, Any]],
                optimizer: torch.optim.Optimizer, device: torch.device, batch_size: int,
                adapters: dict[str, nn.Module], trainable_parameters: list[nn.Parameter],
                progress: Any = None) -> tuple[float, dict[str, float]]:
    model.eval()
    total_loss = 0.0
    gradient_squares: dict[str, torch.Tensor] = {}
    batches = make_batches(rows, batch_size, shuffle=True)
    for batch_number, batch in enumerate(batches, 1):
        ids, attention_mask, labels = collate(batch, tokenizer, device)
        optimizer.zero_grad(set_to_none=True)
        logits = model(input_ids=ids, attention_mask=attention_mask).logits[:, :-1].float()
        targets = labels[:, 1:]
        token_losses = F.cross_entropy(logits.reshape(-1, logits.shape[-1]), targets.reshape(-1),
                                       ignore_index=-100, reduction="none").view_as(targets)
        mask = targets.ne(-100)
        token_counts = mask.sum(dim=1).clamp_min(1)
        per_example_loss = token_losses.sum(dim=1) / token_counts
        loss = per_example_loss.mean()
        if not torch.isfinite(loss).item():
            raise ValueError("Non-finite training loss; candidate not committed")
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(trainable_parameters, 1.0)
        if not torch.isfinite(norm).item():
            raise ValueError("Non-finite gradients; candidate not committed")
        for name, adapter in adapters.items():
            grads = [parameter.grad.detach().float().square().sum()
                     for parameter in (adapter.lora_A, adapter.lora_B)
                     if parameter.grad is not None]
            if grads:
                value = torch.stack(grads).sum()
                previous = gradient_squares.get(name)
                gradient_squares[name] = value if previous is None else previous + value
        optimizer.step()
        total_loss += float(per_example_loss.detach().mean()) * len(batch)
        if progress:
            progress({"stage": "training", "completed_batches": batch_number,
                      "total_batches": len(batches), "batch_size": len(batch)})
    gradient_rms = {}
    for name, adapter in adapters.items():
        count = sum(parameter.numel() for parameter in (adapter.lora_A, adapter.lora_B))
        total = gradient_squares.get(name)
        gradient_rms[name] = (float((total / (len(batches) * count)).sqrt().cpu())
                              if total is not None else 0.0)
    return total_loss / max(len(rows), 1), gradient_rms


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def select_targets(adapters: dict[str, nn.Module], manifest: dict[str, Any],
                   fraction: float,
                   runtime_layer_scores: dict[int, float] | None = None) -> tuple[set[str], str]:
    previous = manifest.get("inference_attribution") or {}
    layers = previous.get("layers") if isinstance(previous, dict) else None
    scores = {row.get("module"): float(row.get("score", 0.0)) for row in layers or []
              if isinstance(row, dict) and row.get("module") in adapters}
    scores = {name: score for name, score in scores.items() if score > 0}
    runtime_layer_scores = runtime_layer_scores or {}
    use_runtime = len(runtime_layer_scores) >= 2
    layer_match = re.compile(r"(?:layers|layer|blocks|block|h)\.(\d+)\.")
    module_layers = {
        name: int(match.group(1)) for name in adapters
        if (match := layer_match.search(name))
    }
    if len(scores) < 2:
        eligible = set(module_layers.values()) & set(runtime_layer_scores)
        if use_runtime and len(eligible) >= 2:
            keep_layers = max(1, math.ceil(len(eligible) * fraction))
            chosen_layers = {
                layer for layer, _score in sorted(
                    ((layer, runtime_layer_scores[layer]) for layer in eligible),
                    key=lambda item: item[1], reverse=True,
                )[:keep_layers]
            }
            chosen = {name for name, layer in module_layers.items() if layer in chosen_layers}
            if chosen:
                return chosen, "feedback_labeled_gguf_activation_initial_profile"
        return set(adapters), "all_targets_initial_profile"
    if use_runtime:
        maximum = max(runtime_layer_scores.values(), default=0.0)
        if maximum > 0:
            scores = {
                name: score * (0.75 + 0.25 * runtime_layer_scores.get(
                    int(match.group(1)), 0.0) / maximum)
                if (match := layer_match.search(name)) else score * 0.75
                for name, score in scores.items()
            }
    keep = max(1, min(len(adapters), math.ceil(len(adapters) * fraction)))
    chosen = {name for name, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)[:keep]}
    if not chosen:
        return set(adapters), "all_targets_no_signal"
    method = ("previous_gradient_plus_feedback_labeled_gguf_activation"
              if use_runtime else "previous_gradient_and_activation_attribution")
    return chosen, method


def run(args: argparse.Namespace) -> dict[str, Any]:
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    device = resolve_device(args.device)
    threads = args.threads if args.threads > 0 else min(os.cpu_count() or 4, 10)
    torch.set_num_threads(threads)
    batch_size = args.batch_size if args.batch_size > 0 else 4
    started = time.monotonic()

    def emit_progress(values: dict[str, Any]) -> None:
        print("@onram-progress " + json.dumps({**values,
              "elapsed_seconds": round(time.monotonic() - started, 1),
              "device": str(device), "threads": threads, "batch_size": batch_size}), flush=True)

    train_rows = read_jsonl(args.train)
    validation_rows = read_jsonl(args.validation)
    personal_rows = read_jsonl(args.personal_validation) if args.personal_validation else None
    guardrail_rows = read_jsonl(args.guardrail) if args.guardrail else None
    runtime_activation = build_runtime_activation_profile(args.runtime_traces, train_rows)
    runtime_layer_scores = {
        int(layer): float(score)
        for layer, score in runtime_activation.get("layer_scores", {}).items()
    }

    self_knowledge = None
    if getattr(args, "self_knowledge", True):
        memory = EpisodicMemory(getattr(args, "chl_memory", DEFAULT_MEMORY))
        train_rows, self_knowledge = prepare_training(
            train_rows, validation_rows + (personal_rows or []) + (guardrail_rows or []),
            memory, replay_limit=getattr(args, "chl_replay_limit", 32),
            specialization=getattr(args, "specialization", "general"))
        # Code is documentation in the JSON manifest, never executable bundle data.
        analysis_dir = args.bundle.parent / (args.bundle.stem + "-analysis")
        analysis_dir.mkdir(parents=True, exist_ok=True)
        (analysis_dir / "analysis-prompt.txt").write_text(
            proposal_context(self_knowledge), encoding="utf-8")
        emit_progress({"stage": "self_knowledge_prepared",
                       **self_knowledge["training_context"]})

    if self_knowledge is not None:
        self_knowledge["training_context"]["effective_train_sha256"] = hashlib.sha256(
            json.dumps(train_rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    manifest, model, adapters = load_nram_model(
        args.bundle, source=args.model, local_files_only=args.local_files_only,
        trust_remote_code=args.trust_remote_code,
    )
    base = manifest["base_model"]
    tokenizer_source = args.tokenizer or base.get("tokenizer_source") or base["source"]
    tokenizer = load_tokenizer(
        tokenizer_source, revision=base.get("tokenizer_revision", base.get("revision")),
        local_files_only=args.local_files_only,
        trust_remote_code=args.trust_remote_code,
    )
    train_rows = [encode(tokenizer, row, args.max_length) for row in train_rows]
    validation_rows = [encode(tokenizer, row, args.max_length) for row in validation_rows]
    personal_rows = [encode(tokenizer, row, args.max_length) for row in personal_rows] if personal_rows else None
    guardrail_rows = [encode(tokenizer, row, args.max_length) for row in guardrail_rows] if guardrail_rows else None
    model.to(device)
    model.config.use_cache = False

    emit_progress({"stage": "baseline_validation"})
    validation_before = score(model, tokenizer, validation_rows, device, batch_size)
    rank_before = first_token_rank(model, validation_rows, tokenizer, device, batch_size)
    personal_before = score(model, tokenizer, personal_rows, device, batch_size) if personal_rows else None
    behavior_before = behavior_accuracy(model, tokenizer, personal_rows, device)
    guard_before = score(model, tokenizer, guardrail_rows, device, batch_size) if guardrail_rows else None

    if self_knowledge is not None:
        self_knowledge["weight_inspection_before"] = inspect_adapters(adapters)
        if not self_knowledge["weight_inspection_before"]["all_finite"]:
            raise ValueError("Non-finite adapter/base tensors; training refused")

    selected_targets, selection_method = select_targets(
        adapters, manifest, args.adaptive_target_fraction, runtime_layer_scores,
    )
    for name, adapter in adapters.items():
        adapter.lora_A.requires_grad_(name in selected_targets)
        adapter.lora_B.requires_grad_(name in selected_targets)
        adapter.start_attribution_trace()
    params = [parameter for adapter in adapters.values() if adapter.lora_A.requires_grad
              for parameter in (adapter.lora_A, adapter.lora_B)]
    if not params:
        raise RuntimeError("Adaptive target selection produced no trainable adapter weights")
    if self_knowledge is not None:
        self_knowledge["preflight_plan"] = {
            "selected_targets": sorted(selected_targets), "method": selection_method,
            "learning_rate": args.learning_rate, "epochs": args.epochs,
            "evidence": "previous attribution and current baseline; not a model-verified causal explanation",
            "baseline_validation_nll": validation_before,
            "commit_policy": "existing held-out and regression gates"}
        analysis_prompt = proposal_context(self_knowledge, {
            "weights": self_knowledge["weight_inspection_before"],
            "preflight": self_knowledge["preflight_plan"],
            "previous_validation": manifest.get("last_validation"),
            "previous_attribution": manifest.get("inference_attribution")})
        (analysis_dir / "analysis-prompt.txt").write_text(analysis_prompt, encoding="utf-8")
        if getattr(args, "self_analysis", True):
            emit_progress({"stage": "model_self_analysis"})
            self_knowledge["model_analysis"] = request_proposal(
                analysis_prompt, getattr(args, "self_analysis_url", "http://127.0.0.1:11434"))
        else:
            self_knowledge["model_analysis"] = {"status": "disabled", "verified": False}
        (analysis_dir / "preflight.json").write_text(
            json.dumps(self_knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    optimizer = torch.optim.AdamW(params, lr=args.learning_rate, weight_decay=args.weight_decay)
    train_losses = []
    gradient_rms: dict[str, float] = {}
    for epoch in range(args.epochs):
        loss, gradient_rms = train_epoch(
            model, tokenizer, train_rows, optimizer, device, batch_size, adapters, params,
            progress=lambda value: emit_progress({**value, "epoch": epoch + 1,
                                                  "epochs": args.epochs}),
        )
        train_losses.append(loss)
        emit_progress({"stage": "epoch_complete", "epoch": epoch + 1,
                       "epochs": args.epochs, "train_nll": loss})

    for adapter in adapters.values():
        adapter.stop_attribution_trace()
    emit_progress({"stage": "candidate_validation"})
    validation_after = score(model, tokenizer, validation_rows, device, batch_size)
    rank_after = first_token_rank(model, validation_rows, tokenizer, device, batch_size)
    personal_after = score(model, tokenizer, personal_rows, device, batch_size) if personal_rows else None
    behavior_after = behavior_accuracy(model, tokenizer, personal_rows, device)
    guard_after = score(model, tokenizer, guardrail_rows, device, batch_size) if guardrail_rows else None
    attribution_layers = []
    for name, adapter in adapters.items():
        trace = adapter.attribution_trace()
        layer_score = gradient_rms.get(name, 0.0) * trace.get("relative_delta_rms", 0.0)
        attribution_layers.append({"module": name, **trace,
                                  "gradient_rms": gradient_rms.get(name, 0.0),
                                  "score": layer_score,
                                  "updated_this_run": name in selected_targets})
    attribution_layers.sort(key=lambda row: row["score"], reverse=True)
    attribution = {
        "method": "captured_interaction_replay_lora_gradient_and_activation_rms",
        "source": "completed_interactions_and_personal_examples",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_weights_sha256": base.get("weights_sha256"),
        "training_examples": len(train_rows),
        "device": str(device), "threads": threads, "batch_size": batch_size,
        "selection_method": selection_method,
        "runtime_activation_feedback": runtime_activation,
        "selected_targets": sorted(selected_targets),
        "layers": attribution_layers,
    }
    guard_ok = guard_before is None or guard_after <= guard_before * (1.0 + args.max_guardrail_drift)
    rank_ok = rank_after["mean_rank"] <= rank_before["mean_rank"] - args.min_first_token_rank_improvement
    if personal_rows:
        personal_improved = personal_after + args.min_improvement < personal_before
        general_stable = validation_after <= validation_before * (1.0 + args.max_guardrail_drift)
        behavior_ok = (behavior_after is None
                       or behavior_after["accuracy"] >= args.min_behavior_accuracy)
        accepted = personal_improved and general_stable and guard_ok and behavior_ok
    else:
        personal_improved = None
        general_stable = None
        behavior_ok = None
        accepted = validation_after + args.min_improvement < validation_before and guard_ok and rank_ok
    finite_metrics = all(value is None or math.isfinite(value) for value in (
        validation_before, validation_after, personal_before, personal_after,
        guard_before, guard_after, *train_losses))
    accepted = accepted and finite_metrics
    if self_knowledge is not None:
        self_knowledge["weight_inspection_after"] = inspect_adapters(adapters)
        accepted = accepted and self_knowledge["weight_inspection_after"]["all_finite"]
        manifest["self_knowledge"] = self_knowledge
    old_version = int(manifest["version"])
    report: dict[str, Any] = {
        "accepted": accepted,
        "finite_metrics": finite_metrics,
        "self_knowledge": self_knowledge["training_context"] if self_knowledge else None,
        "version": old_version + 1 if accepted else old_version,
        "model_type": base["model_type"],
        "validation_nll_before": validation_before,
        "validation_nll_after": validation_after,
        "first_token_rank_before": rank_before["mean_rank"],
        "first_token_rank_after": rank_after["mean_rank"],
        "first_token_top1_before": rank_before["top1_hits"],
        "first_token_top1_after": rank_after["top1_hits"],
        "personal_validation_nll_before": personal_before,
        "personal_validation_nll_after": personal_after,
        "personal_validation_improved": personal_improved,
        "personal_behavior_before": behavior_before,
        "personal_behavior_after": behavior_after,
        "personal_behavior_ok": behavior_ok,
        "general_validation_stable": general_stable,
        "guardrail_nll_before": guard_before,
        "guardrail_nll_after": guard_after,
        "guardrail_ok": guard_ok,
        "trainable_parameters": sum(parameter.numel() for parameter in params),
        "train_nll_by_epoch": train_losses,
        "device": str(device), "threads": threads, "batch_size": batch_size,
        "selected_targets": sorted(selected_targets),
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    if accepted:
        manifest["version"] = report["version"]
        manifest["dataset"] = {
            "train_file": str(args.train), "train_sha256": sha256(args.train),
            "train_examples": len(train_rows), "validation_file": str(args.validation),
            "validation_sha256": sha256(args.validation), "validation_examples": len(validation_rows),
            "personal_validation_file": str(args.personal_validation) if args.personal_validation else None,
            "personal_validation_sha256": sha256(args.personal_validation) if args.personal_validation else None,
            "guardrail_file": str(args.guardrail) if args.guardrail else None,
            "guardrail_sha256": sha256(args.guardrail) if args.guardrail else None,
        }
    manifest["last_validation"] = report
    manifest.setdefault("journal", []).append({**report, "epochs": args.epochs,
                                                "learning_rate": args.learning_rate})
    manifest["inference_attribution"] = attribution
    if self_knowledge is not None:
        self_knowledge["candidate_accepted"] = accepted
        self_knowledge["candidate_weight_inspection_note"] = "after-statistics describe candidate tensors, including when rejected"
        (analysis_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if accepted:
        save_accepted_bundle(args.bundle, manifest, adapters)
    else:
        # Preserve the diagnostic trace without committing rejected adapter weights.
        original_manifest, original_tensors = load_bundle(args.bundle)
        original_manifest.update({key: manifest[key] for key in
                                  ("last_validation", "journal", "inference_attribution")})
        if self_knowledge is not None:
            original_manifest["self_knowledge"] = self_knowledge
        save_bundle(args.bundle, original_manifest, original_tensors)
    report["output"] = str(args.bundle)
    emit_progress({"stage": "complete", "accepted": accepted,
                   "elapsed_seconds": report["elapsed_seconds"]})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--self-knowledge", action=argparse.BooleanOptionalAction, default=True,
                        help="Embed code/docs and add bounded grounded self-knowledge training examples")
    parser.add_argument("--self-analysis", action=argparse.BooleanOptionalAction, default=True,
                        help="Require a completed local model proposal before optimization; proposal is not executed")
    parser.add_argument("--self-analysis-url", default="http://127.0.0.1:11434")
    parser.add_argument("--chl-memory", type=Path, default=DEFAULT_MEMORY)
    parser.add_argument("--chl-replay-limit", type=int, default=32)
    parser.add_argument("--specialization", choices=["general", "self", "user", "world", "code"], default="general")
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--personal-validation", type=Path,
                        help="Personal fact questions; an improved score can promote a stable candidate")
    parser.add_argument("--guardrail", type=Path)
    parser.add_argument("--runtime-traces", type=Path,
                        help="GGUF trace ledger used only for feedback-labeled examples")
    parser.add_argument("--model", help="Override the HF base source recorded in the bundle")
    parser.add_argument("--tokenizer", help="Override tokenizer source")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--min-improvement", type=float, default=1e-4)
    parser.add_argument("--min-behavior-accuracy", type=float, default=0.75,
                        help="Minimum held-out fact recall accuracy required to accept a personal update")
    parser.add_argument("--min-first-token-rank-improvement", type=float, default=0.0)
    parser.add_argument("--max-guardrail-drift", type=float, default=0.05)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--threads", type=int, default=0,
                        help="CPU threads; 0 selects up to 10 available cores")
    parser.add_argument("--batch-size", type=int, default=4,
                        help="Examples per forward/backward pass; use 1 to disable batching")
    parser.add_argument("--adaptive-target-fraction", type=float, default=0.6,
                        help="After an attribution profile exists, update this fraction of the strongest adapter layers")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="auto",
                        help="auto prefers CUDA, then Apple MPS, then CPU")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--trust-remote-code", action="store_true")
    args = parser.parse_args()
    if args.chl_replay_limit < 0:
        parser.error("--chl-replay-limit must be nonnegative")
    if (args.epochs < 1 or args.learning_rate <= 0 or args.max_length < 2
            or args.batch_size < 0 or args.threads < 0
            or not 0 < args.adaptive_target_fraction <= 1
            or not 0 <= args.min_behavior_accuracy <= 1):
        parser.error("epochs, learning-rate, max-length, batch-size, threads, or adaptive-target-fraction is invalid")
    print(json.dumps(run(args), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
