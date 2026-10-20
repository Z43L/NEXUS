#!/usr/bin/env python3
"""Instrument a Transformers/NRAM generation and report layer/adapter signals.

This is a replay debugger: it runs the bundle through Transformers, not through
the GGUF llama-server process used by the coding-agent proxy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from nram_generic import LoRAProjection, load_nram_model, load_tokenizer


BLOCK_PATH = re.compile(r"(?:^|\.)(?:layers|h|blocks|block)\.(\d+)$")


def _device(name: str) -> torch.device:
    if name != "auto":
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _hidden_output(output: Any) -> torch.Tensor | None:
    if isinstance(output, torch.Tensor):
        return output
    if isinstance(output, (tuple, list)) and output and isinstance(output[0], torch.Tensor):
        return output[0]
    value = getattr(output, "last_hidden_state", None)
    return value if isinstance(value, torch.Tensor) else None


def _activation_hook(name: str, rows: dict[str, dict[str, Any]]):
    def capture(_module, _inputs, output):
        value = _hidden_output(output)
        if value is None or value.ndim < 2:
            return
        with torch.no_grad():
            flat = value.detach().float().reshape(-1, value.shape[-1])
            row = rows.get(name)
            squared = flat.square().sum()
            absolute = flat.abs().sum(dim=0)
            if row is None:
                rows[name] = {"sum_sq": squared, "sum_abs": absolute,
                              "values": flat.shape[0], "calls": 1,
                              "hidden_size": flat.shape[-1]}
            else:
                row["sum_sq"] = row["sum_sq"] + squared
                row["sum_abs"] = row["sum_abs"] + absolute
                row["values"] += flat.shape[0]
                row["calls"] += 1
    return capture


def _finish_layer_rows(rows: dict[str, dict[str, Any]], top_channels: int) -> list[dict[str, Any]]:
    finished = []
    for name, row in rows.items():
        values = int(row["values"])
        sum_sq = float(row["sum_sq"].detach().cpu())
        mean_abs = (row["sum_abs"] / max(values, 1)).detach().cpu()
        count = min(top_channels, int(mean_abs.numel()))
        scores, indices = torch.topk(mean_abs, count)
        match = BLOCK_PATH.search(name)
        finished.append({
            "module": name,
            "layer": int(match.group(1)) if match else None,
            "calls": int(row["calls"]),
            "tokens_or_positions": values,
            "hidden_size": int(row["hidden_size"]),
            "output_rms": (sum_sq / max(values * int(row["hidden_size"]), 1)) ** 0.5,
            "top_mean_abs_channels": [
                {"channel": int(index), "mean_abs": float(score)}
                for score, index in zip(scores.tolist(), indices.tolist())
            ],
        })
    return sorted(finished, key=lambda item: (-1 if item["layer"] is None else item["layer"]))


def _gradient_attribution(model: torch.nn.Module, adapters: dict[str, LoRAProjection],
                          prompt_ids: torch.Tensor, generated_ids: torch.Tensor,
                          device: torch.device) -> tuple[float, list[dict[str, Any]]]:
    if generated_ids.numel() == 0:
        return 0.0, []
    full_ids = torch.cat((prompt_ids, generated_ids), dim=1).to(device)
    labels = full_ids.clone()
    labels[:, :prompt_ids.shape[1]] = -100
    for adapter in adapters.values():
        adapter.zero_grad(set_to_none=True)
    model.zero_grad(set_to_none=True)
    with torch.enable_grad():
        logits = model(input_ids=full_ids,
                       attention_mask=torch.ones_like(full_ids),
                       use_cache=False).logits
        loss = F.cross_entropy(
            logits[:, :-1, :].float().reshape(-1, logits.shape[-1]),
            labels[:, 1:].reshape(-1), ignore_index=-100,
        )
        loss.backward()
    result = []
    for name, adapter in adapters.items():
        gradient_sq = 0.0
        alignment = 0.0
        parameter_count = 0
        for parameter in (adapter.lora_A, adapter.lora_B):
            gradient = parameter.grad
            if gradient is None:
                continue
            grad = gradient.detach().float()
            weights = parameter.detach().float()
            gradient_sq += float(grad.square().sum().cpu())
            alignment += float((grad * weights).abs().sum().cpu())
            parameter_count += grad.numel()
        result.append({
            "module": name,
            "gradient_rms": (gradient_sq / max(parameter_count, 1)) ** 0.5,
            "absolute_gradient_weight_product": alignment,
            "parameter_count": parameter_count,
        })
    for parameter in model.parameters():
        parameter.grad = None
    return float(loss.detach().cpu()), sorted(
        result, key=lambda item: item["absolute_gradient_weight_product"], reverse=True,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    device = _device(args.device)
    manifest, model, adapters = load_nram_model(
        args.bundle, source=args.model, local_files_only=args.local_files_only,
    )
    base = manifest["base_model"]
    tokenizer_source = base.get("tokenizer_source") or args.model or base["source"]
    tokenizer = load_tokenizer(
        tokenizer_source,
        revision=base.get("tokenizer_revision", base.get("revision")),
        local_files_only=args.local_files_only,
    )
    model.to(device).eval()
    if getattr(tokenizer, "chat_template", None):
        rendered = tokenizer.apply_chat_template(
            [{"role": "user", "content": args.prompt}],
            tokenize=False, add_generation_prompt=True,
        )
        encoded = tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
    else:
        encoded = tokenizer(args.prompt, return_tensors="pt")
    encoded = encoded.to(device)
    prompt_ids = encoded["input_ids"]

    activation_rows: dict[str, dict[str, Any]] = {}
    handles = []
    for name, module in model.named_modules():
        if BLOCK_PATH.search(name):
            handles.append(module.register_forward_hook(_activation_hook(name, activation_rows)))
    for adapter in adapters.values():
        adapter.start_attribution_trace()

    started = time.monotonic()
    try:
        generation_options = {
            "max_new_tokens": args.max_new_tokens,
            "do_sample": args.temperature > 0,
            "pad_token_id": tokenizer.eos_token_id,
            "return_dict_in_generate": True,
        }
        if args.temperature > 0:
            generation_options["temperature"] = args.temperature
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                **generation_options,
            ).sequences
    finally:
        for handle in handles:
            handle.remove()
        for adapter in adapters.values():
            adapter.stop_attribution_trace()
    elapsed = time.monotonic() - started
    generated_ids = generated[:, prompt_ids.shape[1]:]
    answer = tokenizer.decode(generated_ids[0], skip_special_tokens=True).strip()

    adapter_rows = []
    for name, adapter in adapters.items():
        trace = adapter.attribution_trace()
        if trace:
            adapter_rows.append({"module": name, **trace})
    adapter_rows.sort(key=lambda item: item.get("relative_delta_rms", 0.0), reverse=True)

    loss = None
    gradient_rows = []
    if args.gradient_attribution:
        loss, gradient_rows = _gradient_attribution(
            model, adapters, prompt_ids, generated_ids, device,
        )
    gradient_by_name = {item["module"]: item for item in gradient_rows}
    for row in adapter_rows:
        gradient_row = gradient_by_name.get(row["module"])
        if gradient_row:
            row.update(gradient_row)
            row["attribution_score"] = (
                row["relative_delta_rms"] * row["gradient_rms"]
            )
    if args.gradient_attribution:
        adapter_rows.sort(key=lambda item: item.get("attribution_score", 0.0), reverse=True)

    prompt_sha = hashlib.sha256(args.prompt.encode("utf-8")).hexdigest()
    answer_sha = hashlib.sha256(answer.encode("utf-8")).hexdigest()
    report = {
        "format": "ONRAM_INFERENCE_DEBUG_V1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend": "transformers-nram-replay",
        "bundle": str(args.bundle.resolve()),
        "bundle_version": manifest.get("version"),
        "base_model": base.get("source"),
        "base_weights_sha256": base.get("weights_sha256"),
        "device": str(device),
        "prompt_sha256": prompt_sha,
        "prompt_tokens": int(prompt_ids.shape[1]),
        "generated_tokens": int(generated_ids.shape[1]),
        "generation_seconds": round(elapsed, 4),
        "tokens_per_second": round(generated_ids.shape[1] / max(elapsed, 1e-9), 3),
        "answer_sha256": answer_sha,
        "layer_activations": _finish_layer_rows(activation_rows, args.top_channels),
        "adapter_contributions": adapter_rows,
        "gradient_attribution": {
            "enabled": args.gradient_attribution,
            "teacher_forced_generated_text_loss": loss,
            "targets": gradient_rows,
            "method": "gradient_rms multiplied by inference adapter-delta relative RMS",
            "warning": "This is a salience estimate on the generated answer, not proof of causal weight importance.",
        },
        "limitations": [
            "This is a Transformers replay of the prompt, not instrumentation inside the live llama-server GGUF process.",
            "Activation and adapter RMS values measure magnitude; they do not establish causal importance.",
            "Gradient attribution scores the model's own generated text and can reinforce its existing errors.",
            "No weights are modified by this debugger.",
        ],
    }
    if args.output:
        path = args.output.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        report["report_path"] = str(path)
    print("\n--- generated answer ---")
    print(answer)
    print("\n--- inference debugger summary ---")
    print(json.dumps({
        "backend": report["backend"], "device": report["device"],
        "prompt_tokens": report["prompt_tokens"],
        "generated_tokens": report["generated_tokens"],
        "generation_seconds": report["generation_seconds"],
        "layers_captured": len(report["layer_activations"]),
        "adapter_targets": len(report["adapter_contributions"]),
        "gradient_attribution": report["gradient_attribution"]["enabled"],
        "report_path": report.get("report_path"),
    }, ensure_ascii=False, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", help="Prompt to run and inspect")
    parser.add_argument("--bundle", type=Path, required=True, help="Generic Onram .nram LoRA bundle")
    parser.add_argument("--model", help="Override the bundle's Transformers base model source")
    parser.add_argument("--device", default="auto", help="auto, cpu, mps, or cuda")
    parser.add_argument("--max-new-tokens", type=int, default=96)
    parser.add_argument("--temperature", type=float, default=0.0,
                        help="0 uses greedy decoding; values above 0 enable sampling")
    parser.add_argument("--top-channels", type=int, default=12,
                        help="Top mean-absolute hidden channels recorded per layer")
    parser.add_argument("--gradient-attribution", action="store_true",
                        help="Run an extra gradient pass over the generated text (slower and more memory)")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--output", type=Path,
                        help="Write the JSON report here; existing files are never overwritten")
    args = parser.parse_args()
    if args.max_new_tokens < 1 or args.max_new_tokens > 2048:
        parser.error("--max-new-tokens must be between 1 and 2048")
    if not 0 <= args.temperature <= 2:
        parser.error("--temperature must be between 0 and 2")
    if not 1 <= args.top_channels <= 256:
        parser.error("--top-channels must be between 1 and 256")
    if args.output and args.output.exists():
        parser.error(f"refusing to overwrite existing report: {args.output}")
    if args.bundle.suffix != ".nram":
        parser.error("--bundle must point to a generic .nram LoRA bundle")
    try:
        run(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"onram-debug: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
