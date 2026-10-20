"""Architecture-aware LoRA helpers for dense Hugging Face causal LMs.

The base weights stay in their original Transformers checkpoint. A .nram file
stores the adapter, its target/layout map, source identity, and evolution record.
"""

from __future__ import annotations

import hashlib
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import torch
from torch import nn
from torch.nn import functional as F
from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

from nram_container import load_bundle, save_bundle

LAYER_INDEX = re.compile(r"(?:layers|layer|h|blocks|block)\.(\d+)\.")
PROJECTION_LEAVES = {
    "q_proj", "k_proj", "v_proj", "o_proj", "query", "key", "value",
    "q", "k", "v", "o", "query_key_value", "qkv_proj", "out_proj",
    "proj_in", "proj_out", "dense", "c_attn", "c_proj", "c_fc", "fc1", "fc2", "fc_in", "fc_out", "dense_h_to_4h",
    "dense_4h_to_h", "gate_proj", "up_proj", "down_proj", "w1", "w2",
    "w3", "wi", "wi_0", "wi_1", "wo",
}
EXCLUDED_PARTS = {"lm_head", "embed_tokens", "word_embeddings", "wte", "wpe", "classifier"}
NRAM_V2_MAGIC = b"NRAM\x00\x02"


@contextmanager
def _transformers_source(source: str | Path) -> Iterator[str | Path]:
    """Open a Transformers directory or a workspace NRAM v1 base tensor bank."""
    path = Path(source)
    if path.is_file() and path.suffix == ".nram":
        with path.open("rb") as stream:
            prefix = stream.read(len(NRAM_V2_MAGIC))
        if prefix == NRAM_V2_MAGIC:
            raise ValueError("An adapter-only NRAM v2 bundle cannot be used as a base checkpoint")
        workspace = Path(__file__).resolve().parents[2]
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        from nra_m.nram import materialize_runtime_view

        with materialize_runtime_view(path) as (model_dir, _manifest, _route):
            # NRAM v1's append-only graph, memory, and deltas are not applied
            # here: this bridge intentionally exposes its immutable base tensors.
            yield model_dir
        return
    yield source


def load_tokenizer(source: str | Path, *, revision: str | None = None,
                   local_files_only: bool = False, trust_remote_code: bool = False):
    with _transformers_source(source) as local_source:
        return AutoTokenizer.from_pretrained(
            str(local_source), revision=revision, local_files_only=local_files_only,
            trust_remote_code=trust_remote_code,
        )


def module_layout(module: nn.Module) -> str | None:
    """Return supported projection storage layout, else None."""
    if isinstance(module, nn.Linear) and module.weight.ndim == 2:
        return "linear_out_in"
    # GPT-2 Transformers Conv1D stores its weight as [input, output]. Avoid
    # importing a private Transformers class and detect its public shape API.
    if module.__class__.__name__ == "Conv1D" and getattr(module, "weight", None) is not None:
        if module.weight.ndim == 2 and hasattr(module, "nf"):
            return "conv1d_in_out"
    return None


def discover_targets(model: nn.Module, *, last_k_blocks: int = 1,
                     explicit: list[str] | None = None) -> dict[str, str]:
    if last_k_blocks < 1:
        raise ValueError("last_k_blocks must be positive")
    candidates: list[tuple[str, str, int | None]] = []
    for name, module in model.named_modules():
        if not name or module_layout(module) is None:
            continue
        parts = set(name.lower().split("."))
        if parts & EXCLUDED_PARTS:
            continue
        layout = module_layout(module)
        candidates.append((name, layout or "", _layer_number(name)))
    if explicit:
        selected = {name: layout for name, layout, _ in candidates
                    if any(name == target or name.endswith("." + target) for target in explicit)}
        missing = [target for target in explicit if not any(name == target or name.endswith("." + target) for name in selected)]
        if missing:
            raise ValueError("Requested adapter target(s) not found among supported dense projections: " + ", ".join(missing))
        return selected

    named = [(name, layout, index) for name, layout, index in candidates
             if name.rsplit(".", 1)[-1].lower() in PROJECTION_LEAVES]
    if not named:
        raise ValueError("No recognized dense attention/MLP projections found; pass --targets explicitly")
    indexed = [index for _, _, index in named if index is not None]
    if indexed:
        cutoff = max(indexed) - last_k_blocks + 1
        named = [(name, layout, index) for name, layout, index in named if index is not None and index >= cutoff]
    elif last_k_blocks == 1:
        # Some architectures do not encode block indices in module names.
        # Keep the final attention/MLP projection group rather than adapting
        # every arbitrary linear layer in the model.
        named = named[-min(8, len(named)):]
    return {name: layout for name, layout, _ in named}


def _layer_number(name: str) -> int | None:
    match = LAYER_INDEX.search(name)
    return int(match.group(1)) if match else None


class LoRAProjection(nn.Module):
    def __init__(self, base: nn.Module, rank: int, alpha: float, layout: str,
                 adapter_device: str | torch.device | None = None):
        super().__init__()
        self.base = base
        self.layout = layout
        if layout == "linear_out_in":
            out_features, in_features = base.weight.shape
        elif layout == "conv1d_in_out":
            in_features, out_features = base.weight.shape
        else:
            raise ValueError(f"Unsupported weight layout: {layout}")
        # Keep trainable adapter weights and AdamW state in FP32 even when the
        # frozen base model is loaded in FP16. FP16 epsilon/gradient underflow
        # on Apple MPS can otherwise turn a complete epoch into NaN losses.
        self.lora_A = nn.Parameter(torch.empty(rank, in_features, dtype=torch.float32,
                                               device=adapter_device or base.weight.device))
        self.lora_B = nn.Parameter(torch.zeros(out_features, rank, dtype=torch.float32,
                                               device=adapter_device or base.weight.device))
        nn.init.kaiming_uniform_(self.lora_A, a=5**0.5)
        self.scale = float(alpha) / rank
        self._trace_enabled = False
        self._trace_values: dict[str, torch.Tensor | int] = {}

    def start_attribution_trace(self) -> None:
        self._trace_enabled = True
        self._trace_values = {"input_sq": 0.0, "input_n": 0,
                              "base_sq": 0.0, "delta_sq": 0.0, "output_n": 0}

    def stop_attribution_trace(self) -> None:
        self._trace_enabled = False

    def attribution_trace(self) -> dict[str, float]:
        values = self._trace_values
        input_n = int(values.get("input_n", 0))
        output_n = int(values.get("output_n", 0))
        if not input_n or not output_n:
            return {}

        def scalar(name: str) -> float:
            value = values[name]
            return float(value.detach().cpu()) if isinstance(value, torch.Tensor) else float(value)

        input_rms = (scalar("input_sq") / input_n) ** 0.5
        base_rms = (scalar("base_sq") / output_n) ** 0.5
        delta_rms = (scalar("delta_sq") / output_n) ** 0.5
        return {"input_rms": input_rms, "base_output_rms": base_rms,
                "adapter_delta_rms": delta_rms,
                "relative_delta_rms": delta_rms / max(base_rms, 1e-12)}

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # F.linear's weight convention gives the same low-rank residual for
        # nn.Linear [out,in] and GPT-2 Conv1D [in,out].
        base_output = self.base(x)
        adapter_input = x.to(dtype=self.lora_A.dtype)
        residual = F.linear(F.linear(adapter_input, self.lora_A), self.lora_B) * self.scale
        if self._trace_enabled:
            # Keep device-side scalar accumulators; reading each statistic back
            # to Python in the forward pass would synchronize Metal/CUDA.
            with torch.no_grad():
                values = self._trace_values
                for key, value in (("input_sq", x), ("base_sq", base_output),
                                   ("delta_sq", residual)):
                    total = value.detach().float().square().sum()
                    previous = values[key]
                    values[key] = previous + total if isinstance(previous, torch.Tensor) else total
                values["input_n"] = int(values["input_n"]) + x.numel()
                values["output_n"] = int(values["output_n"]) + residual.numel()
        return base_output + residual.to(dtype=base_output.dtype)


def _parent_and_leaf(root: nn.Module, path: str) -> tuple[nn.Module, str]:
    parent_path, _, leaf = path.rpartition(".")
    return (root.get_submodule(parent_path) if parent_path else root), leaf


def attach_adapters(model: nn.Module, target_layouts: dict[str, str], rank: int,
                    alpha: float, *, adapter_device: str | torch.device | None = None) -> dict[str, LoRAProjection]:
    adapters: dict[str, LoRAProjection] = {}
    for name, layout in target_layouts.items():
        parent, leaf = _parent_and_leaf(model, name)
        base = getattr(parent, leaf)
        if module_layout(base) != layout:
            raise ValueError(f"Projection layout changed for {name}: expected {layout}, got {module_layout(base)}")
        wrapped = LoRAProjection(base, rank, alpha, layout, adapter_device=adapter_device)
        setattr(parent, leaf, wrapped)
        adapters[name] = wrapped
    return adapters


def adapter_tensors(adapters: dict[str, LoRAProjection]) -> dict[str, torch.Tensor]:
    return {f"{name}.{part}": getattr(adapter, part).detach().cpu().clone()
            for name, adapter in adapters.items() for part in ("lora_A", "lora_B")}


def restore_adapters(adapters: dict[str, LoRAProjection], tensors: dict[str, torch.Tensor]) -> None:
    expected = {f"{name}.{part}" for name in adapters for part in ("lora_A", "lora_B")}
    if set(tensors) != expected:
        raise ValueError("Adapter tensors do not match the NRAM target graph")
    with torch.no_grad():
        for name, adapter in adapters.items():
            for part in ("lora_A", "lora_B"):
                param = getattr(adapter, part)
                param.copy_(tensors[f"{name}.{part}"].to(device=param.device, dtype=param.dtype))


def merge_adapters(model: nn.Module, adapters: dict[str, LoRAProjection]) -> None:
    with torch.no_grad():
        for name, adapter in adapters.items():
            delta = adapter.lora_B @ adapter.lora_A
            if adapter.layout == "conv1d_in_out":
                delta = delta.T
            adapter.base.weight.add_(delta.to(adapter.base.weight.dtype), alpha=adapter.scale)
            parent, leaf = _parent_and_leaf(model, name)
            setattr(parent, leaf, adapter.base)



def load_model_structure(source: str | Path, *, revision: str | None = None,
                         dtype: str = "bfloat16", trust_remote_code: bool = False):
    """Discover the real architecture without allocating base weights."""
    config = AutoConfig.from_pretrained(str(source), revision=revision,
                                       trust_remote_code=trust_remote_code)
    with torch.device("meta"):
        model = AutoModelForCausalLM.from_config(config, trust_remote_code=trust_remote_code,
                                                dtype=getattr(torch, dtype))
    return model


def load_base_model(source: str | Path, *, revision: str | None = None, local_files_only: bool = False,
                    trust_remote_code: bool = False, dtype: str | torch.dtype = "float32",
                    device_map=None) -> nn.Module:
    dtypes = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    model_dtype = dtypes.get(dtype) if isinstance(dtype, str) else dtype
    if model_dtype not in dtypes.values():
        raise ValueError("dtype must be float32, float16, or bfloat16")
    with _transformers_source(source) as local_source:
        return AutoModelForCausalLM.from_pretrained(
            str(local_source), local_files_only=local_files_only, trust_remote_code=trust_remote_code,
            dtype=model_dtype, revision=revision,
            **({"device_map": device_map} if device_map is not None else {}),
        )


def weight_fingerprint(source: str | Path) -> str | None:
    path = Path(source)
    if path.is_file() and path.suffix == ".nram":
        with path.open("rb") as stream:
            prefix = stream.read(len(NRAM_V2_MAGIC))
        if prefix == NRAM_V2_MAGIC:
            return None
        workspace = Path(__file__).resolve().parents[2]
        if str(workspace) not in sys.path:
            sys.path.insert(0, str(workspace))
        from nra_m.nram import read_manifest_and_route

        _info, manifest, _records, _route = read_manifest_and_route(path)
        return str(manifest["base_sha256"])
    if not path.is_dir():
        return None
    files = sorted(p for p in path.rglob("*") if p.is_file() and
                   (p.name.endswith(".safetensors") or
                    (p.name.startswith("pytorch_model") and p.suffix == ".bin")))
    if not files:
        return None
    digest = hashlib.sha256()
    for file in files:
        digest.update(str(file.relative_to(path)).encode())
        with file.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def load_nram_model(bundle_path: str | Path, source: str | Path | None = None, *,
                    local_files_only: bool = False, trust_remote_code: bool = False, device_map=None):
    manifest, tensors = load_bundle(bundle_path)
    if manifest.get("model_family") != "hf-causal-lm-dense-lora":
        raise ValueError("This is not a generic Hugging Face causal-LM NRAM bundle")
    spec = manifest["adapter"]
    base = manifest["base_model"]
    source = str(source or base["source"])
    model = load_base_model(source, revision=base.get("revision"), local_files_only=local_files_only,
                            trust_remote_code=trust_remote_code,
                            dtype=base.get("compute_dtype", "float32"), device_map=device_map)
    expected_hash = base.get("weights_sha256")
    actual_hash = weight_fingerprint(source)
    if expected_hash and actual_hash and expected_hash != actual_hash:
        raise ValueError("Base weight fingerprint does not match this NRAM bundle")
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    adapters = attach_adapters(model, spec["target_layouts"], spec["rank"], spec["alpha"])
    restore_adapters(adapters, tensors)
    extension = manifest.get("micro_extension")
    if extension and extension.get("enabled"):
        from micro_extensions import load_extension, attach_extension
        extension_manifest, bank = load_extension(Path(extension["path"]))
        if extension_manifest["base_weights_sha256"] != base.get("weights_sha256"):
            raise ValueError("Micro-extension belongs to a different base checkpoint")
        if device_map is not None:
            bank.to(next(model.parameters()).device)
        attach_extension(model, bank, extension_manifest["micro_extensions"]["module"])
    return manifest, model, adapters


def save_accepted_bundle(path: str | Path, manifest: dict[str, Any],
                         adapters: dict[str, LoRAProjection]) -> None:
    save_bundle(path, manifest, adapter_tensors(adapters))
