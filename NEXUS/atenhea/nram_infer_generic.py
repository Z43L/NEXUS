"""Text-only inference using a generic NRA-M LoRA bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

from episodic_memory import DEFAULT_MEMORY

import torch

from nram_generic import load_nram_model, load_tokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=48)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--chl-memory", type=Path, default=DEFAULT_MEMORY,
                        help="Persistent CHL archive (default: models/athenea.memory)")
    args = parser.parse_args()
    memory = None
    prompt = args.prompt
    if args.chl_memory:
        from episodic_memory import EpisodicMemory
        memory = EpisodicMemory(args.chl_memory)
        prompt = memory.augment(prompt)
    if args.max_new_tokens < 1:
        parser.error("--max-new-tokens must be positive")

    manifest, model, _adapters = load_nram_model(
        args.bundle, local_files_only=args.local_files_only,
    )
    base = manifest["base_model"]
    tokenizer_source = base.get("tokenizer_source") or base["source"]
    tokenizer = load_tokenizer(
        tokenizer_source,
        revision=base.get("tokenizer_revision", base.get("revision")),
        local_files_only=args.local_files_only,
    )
    model.to(args.device).eval()
    if getattr(tokenizer, "chat_template", None):
        rendered = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False, add_generation_prompt=True,
        )
        encoded = tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
    else:
        encoded = tokenizer(prompt, return_tensors="pt")
    encoded = encoded.to(args.device)
    with torch.inference_mode():
        output = model.generate(
            **encoded,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0, encoded["input_ids"].shape[1]:]
    completion = tokenizer.decode(generated, skip_special_tokens=True)
    print(completion)
    if memory and completion.strip():
        memory.remember(args.prompt, completion, model=str(args.bundle.resolve()))


if __name__ == "__main__":
    main()
