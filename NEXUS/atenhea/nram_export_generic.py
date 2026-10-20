"""Merge a generic NRAM bundle and export GGUF using llama.cpp converters."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from nram_merge_generic import merge

ROOT = Path(__file__).resolve().parent


def _llama_cpp_dir() -> Path:
    candidates = []
    if os.environ.get("ONRAM_LLAMA_CPP_DIR"):
        candidates.append(Path(os.environ["ONRAM_LLAMA_CPP_DIR"]))
    candidates.extend((ROOT / "third_party" / "llama.cpp",
                      ROOT.parent.parent / "deps" / "llama.cpp"))
    for candidate in candidates:
        if (candidate / "convert_hf_to_gguf.py").is_file():
            return candidate
    raise FileNotFoundError(
        "llama.cpp converter not found; run `./onram runtime-setup` or set ONRAM_LLAMA_CPP_DIR"
    )


def _quantizer() -> Path:
    candidates = [ROOT / "build" / "bin" / "llama-quantize",
                  ROOT.parent.parent / "deps" / "llama.cpp" / "build" / "bin" / "llama-quantize"]
    if os.environ.get("ONRAM_LLAMA_CPP_DIR"):
        candidates.insert(0, Path(os.environ["ONRAM_LLAMA_CPP_DIR"]) / "build" / "bin" / "llama-quantize")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "llama-quantize not found; run `./onram runtime-setup` or set ONRAM_LLAMA_CPP_DIR"
    )


def export(bundle: Path, prefix: Path, *, model: str | None = None,
           tokenizer: str | None = None, quantization: str | None = "Q4_K_M",
           trust_remote_code: bool = False) -> list[Path]:
    hf_dir = prefix.with_name(prefix.name + "-hf")
    f16_file = prefix.with_name(prefix.name + "-f16.gguf")
    merge(bundle, hf_dir, model, tokenizer, trust_remote_code)
    converter = _llama_cpp_dir() / "convert_hf_to_gguf.py"
    subprocess.run([sys.executable, str(converter), str(hf_dir), "--outfile", str(f16_file),
                    "--outtype", "f16"], cwd=ROOT, check=True)
    outputs = [f16_file]
    if quantization:
        quantizer = _quantizer()
        q_file = prefix.with_name(f"{prefix.name}-{quantization}.gguf")
        subprocess.run([str(quantizer), str(f16_file), str(q_file), quantization], cwd=ROOT, check=True)
        outputs.append(q_file)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True,
                        help="Output path prefix, e.g. models/my-nram")
    parser.add_argument("--model", help="Override base source recorded in the bundle")
    parser.add_argument("--tokenizer")
    parser.add_argument("--quantization", default="Q4_K_M",
                        help="llama-quantize method; use 'none' to emit only F16")
    parser.add_argument("--trust-remote-code", action="store_true")
    args = parser.parse_args()
    quantization = None if args.quantization.lower() == "none" else args.quantization
    outputs = export(args.bundle, args.output_prefix, model=args.model,
                     tokenizer=args.tokenizer, quantization=quantization,
                     trust_remote_code=args.trust_remote_code)
    print("Exported:\n" + "\n".join(str(path) for path in outputs))


if __name__ == "__main__":
    main()
