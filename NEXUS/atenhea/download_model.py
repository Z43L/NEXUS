import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models" / "distilgpt2"
REVISION = "2290a62682d06624634c1f46a6ad5be0f47f38aa"
FILES = [
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
]

def main() -> None:
    parser = argparse.ArgumentParser(description="Download the pinned DistilGPT2 checkpoint")
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR,
                        help="Destination directory (default: models/distilgpt2)")
    args = parser.parse_args()
    if not (args.model_dir / "model.safetensors").exists():
        snapshot_download(
            "distilbert/distilgpt2",
            revision=REVISION,
            local_dir=args.model_dir,
            allow_patterns=FILES,
        )
    else:
        print(f"Checkpoint already present: {args.model_dir}")


if __name__ == "__main__":
    main()
