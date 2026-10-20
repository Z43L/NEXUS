"""Run smoke checks on the actual Transformers and GGUF model artifacts."""

from pathlib import Path
import subprocess

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "models" / "distilgpt2"
PROMPT = "NRA-M is an experimental model architecture."


def main() -> None:
    tok = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL, local_files_only=True).eval()
    count = sum(parameter.numel() for parameter in model.parameters())
    assert count == 81_912_576, f"Unexpected parameter count: {count}"
    encoded = tok(PROMPT, return_tensors="pt")
    with torch.inference_mode():
        logits = model(**encoded).logits
        generated = model.generate(
            **encoded,
            max_new_tokens=16,
            do_sample=False,
            pad_token_id=tok.eos_token_id,
        )
    assert torch.isfinite(logits).all(), "Non-finite logits"
    hf_text = tok.decode(generated[0], skip_special_tokens=True)
    assert hf_text.startswith(PROMPT)
    print(f"Transformers OK: {count:,} parameters; {hf_text}")

    runtime = ROOT / "build" / "bin" / "llama-completion"
    for filename in ("distilgpt2-f16.gguf", "distilgpt2-Q4_K_M.gguf"):
        gguf = ROOT / "models" / filename
        assert runtime.is_file() and gguf.is_file(), f"Missing runtime or artifact for {filename}"
        proc = subprocess.run(
            [
                str(runtime), "-m", str(gguf), "-p", PROMPT,
                "-n", "16", "--temp", "0", "--seed", "1", "-t", "4",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        output = proc.stdout + proc.stderr
        assert PROMPT in output and "failed" not in output.lower(), output
        print(f"GGUF OK ({filename}): {output.split(PROMPT, 1)[1].splitlines()[0].strip()}")


if __name__ == "__main__":
    main()
