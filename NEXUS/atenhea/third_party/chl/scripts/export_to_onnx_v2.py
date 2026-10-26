#!/usr/bin/env python3
"""
CHL ONNX Export v2 (plan B de optimizacion para Mac)

Reexporta el modelo CHL fine-tuneado (Qwen 2.5 3B + LoRA + CHL Layer)
a formato ONNX estandar, usando torch.onnx.dynamo_export o el exportador
trazador tradicional, segun lo que funcione mejor en el entorno.

El objetivo es poder luego cargar el modelo con onnxruntime-silicon y usar
CoreML Execution Provider en Apple Silicon para inferencia mas rapida.

Uso:
  CHL_DISABLE_COMPILE=1 python3 scripts/export_to_onnx_v2.py \
      --checkpoint chkpt/best --output chkpt/best/model_v2.onnx
"""

import os
import sys
import argparse
import warnings
from pathlib import Path

import torch

# Configuracion de entorno: evitar advertencias y compilar el modelo base
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("CHL_DISABLE_COMPILE", "1")
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*torch_dtype.*deprecated.*")

sys.path.insert(0, str(Path(__file__).parent))
from serve_model import CHLAugmentedModel


def parse_args():
    parser = argparse.ArgumentParser(description="Reexportar modelo CHL a ONNX v2")
    parser.add_argument("--checkpoint", type=str, default="chkpt/best", help="Ruta al checkpoint")
    parser.add_argument("--output", type=str, default="chkpt/best/model_v2.onnx", help="Ruta ONNX de salida")
    parser.add_argument("--device", type=str, default="cpu", help="Dispositivo para exportar (cpu recomendado para estabilidad)")
    parser.add_argument("--max-context", type=int, default=1024, help="Longitud maxima de secuencia")
    parser.add_argument("--opset", type=int, default=17, help="ONNX opset version")
    parser.add_argument("--dynamo", action="store_true", help="Usar torch.onnx.dynamo_export en lugar del exportador tradicional")
    return parser.parse_args()


@torch.no_grad()
def export_with_dynamo(model, dummy_input, dummy_mask, output_path, opset):
    print("[ONNX v2] Usando torch.onnx.dynamo_export...")
    # dynamic_axes solo sobre sequence_length (dim 1)
    onnx_program = torch.onnx.dynamo_export(
        model,
        dummy_input,
        dummy_mask,
        export_options=torch.onnx.ExportOptions(opset_version=opset),
    )
    onnx_program.save(output_path)
    print(f"[ONNX v2] Guardado en {output_path}")


@torch.no_grad()
def export_with_tracer(model, dummy_input, dummy_mask, output_path, opset, max_context):
    print("[ONNX v2] Usando torch.onnx.export (tradicional)...")
    input_names = ["input_ids", "attention_mask"]
    output_names = ["logits"]
    dynamic_axes = {
        "input_ids": {0: "batch_size", 1: "sequence_length"},
        "attention_mask": {0: "batch_size", 1: "sequence_length"},
        "logits": {0: "batch_size", 1: "sequence_length"},
    }

    torch.onnx.export(
        model,
        (dummy_input, dummy_mask),
        output_path,
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        opset_version=opset,
        do_constant_folding=True,
        export_params=True,
    )
    print(f"[ONNX v2] Guardado en {output_path}")


@torch.no_grad()
def verify_onnx_output(onnx_path, dummy_input, dummy_mask, model_for_ref, device, rtol=1e-2, atol=1e-2):
    try:
        import onnxruntime as ort
    except ImportError:
        print("[ONNX v2] onnxruntime no instalado. No se puede verificar.")
        return

    # Preferir CoreML EP en Mac si esta disponible
    sess_options = ort.SessionOptions()
    providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    try:
        session = ort.InferenceSession(onnx_path, sess_options, providers=providers)
        print(f"[ONNX v2] Proveedores activos: {session.get_providers()}")
    except Exception as e:
        print(f"[ONNX v2] Fallo con CoreML EP: {e}. Probando CPU...")
        session = ort.InferenceSession(onnx_path, sess_options, providers=["CPUExecutionProvider"])

    inputs = {"input_ids": dummy_input.cpu().numpy(), "attention_mask": dummy_mask.cpu().numpy()}
    onnx_out = session.run(None, inputs)[0]

    ref_input = dummy_input.to(device)
    ref_mask = dummy_mask.to(device)
    model_for_ref.eval()
    with torch.no_grad():
        ref_out = model_for_ref(ref_input, ref_mask).cpu().float().numpy()

    import numpy as np
    diff = np.abs(onnx_out - ref_out).max()
    print(f"[ONNX v2] Diferencia maxima entre ONNX y PyTorch: {diff:.6f}")
    if np.allclose(onnx_out, ref_out, rtol=rtol, atol=atol):
        print("[ONNX v2] Verificacion OK.")
    else:
        print("[ONNX v2] ADVERTENCIA: salidas no coinciden dentro de la tolerancia.")


def main():
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[ONNX v2] Cargando modelo desde {args.checkpoint}...")
    model = CHLAugmentedModel.load(args.checkpoint, device=args.device, max_context=args.max_context)
    model.eval()

    # Dummy input corto; dynamic_axes permitira variar longitud en runtime
    seq_len = 16
    dummy_input = torch.randint(0, model.tokenizer.vocab_size, (1, seq_len), dtype=torch.long, device=args.device)
    dummy_mask = torch.ones((1, seq_len), dtype=torch.long, device=args.device)

    try:
        if args.dynamo:
            export_with_dynamo(model, dummy_input, dummy_mask, output_path, args.opset)
        else:
            export_with_tracer(model, dummy_input, dummy_mask, output_path, args.opset, args.max_context)
    except Exception as e:
        print(f"[ONNX v2] ERROR durante exportacion: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Verificacion opcional
    verify_onnx_output(output_path, dummy_input, dummy_mask, model, args.device)

    print("[ONNX v2] Exportacion finalizada.")


if __name__ == "__main__":
    main()
