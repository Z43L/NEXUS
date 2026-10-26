#!/usr/bin/env python3
"""
Exports the fine-tuned CHLAugmentedModel to ONNX format.
"""

import os
import sys
import argparse
import torch
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from scripts.serve_model import CHLAugmentedModel

def main():
    parser = argparse.ArgumentParser(description="Export CHL model to ONNX")
    parser.add_argument("--checkpoint", type=str, default="chkpt/best", help="Path to checkpoint")
    parser.add_argument("--output", type=str, default="chkpt/best/model.onnx", help="Path to output ONNX file")
    args = parser.parse_args()

    print(f"[ONNX] Loading model from {args.checkpoint} on CPU...")
    # Load model on CPU for ONNX export
    try:
        model = CHLAugmentedModel.load(args.checkpoint, device="cpu")
        model.eval()
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        sys.exit(1)

    # Disable kv cache for tracing
    if hasattr(model.model, "config"):
        model.model.config.use_cache = False

    print("[ONNX] Creating dummy inputs...")
    dummy_input_ids = torch.ones(1, 8, dtype=torch.long)
    dummy_attention_mask = torch.ones(1, 8, dtype=torch.long)

    print("[ONNX] Starting export (this may take a few minutes)...")
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    try:
        torch.onnx.export(
            model,
            (dummy_input_ids, dummy_attention_mask),
            args.output,
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch_size", 1: "sequence_length"},
                "attention_mask": {0: "batch_size", 1: "sequence_length"},
                "logits": {0: "batch_size", 1: "sequence_length"}
            },
            opset_version=17,
            do_constant_folding=True
        )
        print(f"✅ Success! ONNX model exported to {args.output}")
    except Exception as e:
        print(f"❌ Export failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
