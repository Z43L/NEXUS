"""Verify saved NRA-M adapters, merged checkpoint, and exported GGUF."""

from pathlib import Path
import subprocess

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from nram_container import load_bundle
from nram_evolve import MODEL_DIR, attach_adapters, first_token_metrics, read_jsonl, restore_adapters, score

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / "models" / "distilgpt2-nra-qa.nram"
VALIDATION = ROOT / "data" / "nra_qa_validation.jsonl"
GUARDRAIL = ROOT / "data" / "general_guardrail.jsonl"


def main() -> None:
    manifest, tensors = load_bundle(BUNDLE)
    assert [entry["version"] for entry in manifest["journal"]] == list(range(1, manifest["version"] + 1))
    assert manifest["last_validation"]["version"] == manifest["version"]
    version = manifest["version"]
    merged_candidates = [
        ROOT / "models" / f"onram-nram-v{version}-hf",
        ROOT / "models" / f"distilgpt2-nra-qa-v{version}-hf",
        ROOT / "models" / "distilgpt2-nra-qa-v2-hf",
    ]
    merged_dir = next((path for path in merged_candidates if path.is_dir()), None)
    if merged_dir is None:
        raise FileNotFoundError(f"No merged HF checkpoint found for NRA-M version {version}")
    spec = manifest["adapter"]
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    evolved = AutoModelForCausalLM.from_pretrained(MODEL_DIR, local_files_only=True).eval()
    adapters = attach_adapters(evolved, spec["targets"], spec["rank"], spec["alpha"])
    restore_adapters(adapters, tensors)
    merged = AutoModelForCausalLM.from_pretrained(merged_dir, local_files_only=True).eval()

    prompt = "Question: What does ENCODE do in NRA-M?\nAnswer:"
    ids = tokenizer(prompt, return_tensors="pt").input_ids
    with torch.inference_mode():
        delta = (evolved(input_ids=ids).logits - merged(input_ids=ids).logits).abs().max().item()
    assert delta < 2e-4, f"Merged checkpoint differs from LoRA model: max-logit error {delta}"

    val = read_jsonl(VALIDATION)
    guardrail = read_jsonl(GUARDRAIL)
    evolved_val = score(evolved, tokenizer, val, 128)
    guardrail_loss = score(evolved, tokenizer, guardrail, 128)
    first = first_token_metrics(evolved, tokenizer, val)
    recorded_val = manifest["last_validation"]["validation_nll_after"]
    assert abs(evolved_val - recorded_val) < 1e-4, f"Validation loss differs from accepted report: {evolved_val} vs {recorded_val}"
    assert guardrail_loss <= manifest["last_validation"]["guardrail_nll_before"] * 1.05
    assert first["mean_rank"] <= manifest["last_validation"]["first_token_rank_before"]

    runtime = ROOT / "build" / "bin" / "llama-completion"
    gguf_candidates = [
        ROOT / "models" / f"onram-nram-v{version}-f16.gguf",
        ROOT / "models" / f"distilgpt2-nra-qa-v{version}-f16.gguf",
        ROOT / "models" / "distilgpt2-nra-qa-v2-f16.gguf",
    ]
    gguf = next((path for path in gguf_candidates if path.is_file()), None)
    if gguf is None:
        raise FileNotFoundError(f"No F16 GGUF found for NRA-M version {version}")
    proc = subprocess.run(
        [str(runtime), "-m", str(gguf), "-p", prompt.replace("\n", " "), "-n", "16", "--temp", "0", "-t", "4"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "failed" not in (proc.stdout + proc.stderr).lower()
    print(f"NRA-M version: {manifest['version']}")
    print(f"Adapter -> merged max-logit difference: {delta:.8f}")
    print(f"Validation completion NLL: {evolved_val:.4f}")
    print(f"General guardrail NLL: {guardrail_loss:.4f}")
    print(f"First answer-token mean rank / top-1: {first['mean_rank']:.3f} / {first['top1_hits']:.0f}/{first['examples']:.0f}")
    print("Merged GGUF loads and generates: OK")


if __name__ == "__main__":
    main()
