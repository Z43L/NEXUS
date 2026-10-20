"""External residual micro-MLP experts, seeded from a frozen model's actual projections."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import torch
from torch import nn
from torch.nn import functional as F

from nram_container import load_bundle, save_bundle


class MicroExpert(nn.Module):
    def __init__(self, hidden, rank):
        super().__init__()
        self.down = nn.Linear(hidden, rank, bias=False)
        self.up = nn.Linear(rank, hidden, bias=False)
        nn.init.zeros_(self.up.weight)

    def forward(self, hidden):
        return self.up(F.silu(self.down(hidden)))


class MicroExtensions(nn.Module):
    def __init__(self, hidden, rank, experts):
        super().__init__()
        self.router = nn.Linear(hidden, experts, bias=False)
        self.experts = nn.ModuleList([MicroExpert(hidden, rank) for _ in range(experts)])
        self.enabled = True
        self.register_buffer('active_mask', torch.ones(experts, dtype=torch.bool))
        self.force_expert = None
        self.routing_loss = None
        self.last_counts = []

    def forward(self, hidden):
        shape = hidden.shape
        if not self.enabled:
            self.routing_loss = None
            return torch.zeros_like(hidden)
        # With a frozen base these features have no upstream gradient graph.
        features = hidden.reshape(-1, shape[-1]).to(self.router.weight.dtype)
        logits = self.router(features)
        logits = logits.masked_fill(~self.active_mask, -torch.inf)
        probabilities = logits.softmax(dim=-1)
        if self.force_expert is None:
            selected = logits.argmax(dim=-1)
            self.routing_loss = None
        else:
            selected = torch.full((len(features),), self.force_expert, device=features.device, dtype=torch.long)
            self.routing_loss = F.cross_entropy(logits, selected)
        if features.device.type == 'mps':
            # Avoid scalar GPU synchronizations and variable-size boolean gathers
            # on Metal. These micro-MLPs are tiny relative to the frozen base.
            return self.dense_residual(features,probabilities,selected).view(shape).to(hidden.dtype)
        residual = torch.zeros_like(features)
        counts = []
        for index, expert in enumerate(self.experts):
            mask = selected == index
            count = int(mask.sum().item())
            counts.append(count)
            if count:
                # Keep selected probability unnormalized so task loss also reaches router weights.
                residual[mask] = expert(features[mask]) * probabilities[mask, index, None]
        self.last_counts = counts
        return residual.view(shape).to(hidden.dtype)

    def dense_residual(self,features,probabilities,selected):
        masks=selected[:,None]==torch.arange(len(self.experts),device=selected.device)[None,:]
        self.last_counts=masks.sum(dim=0).detach()
        residual=torch.zeros_like(features)
        for index,expert in enumerate(self.experts):
            residual=residual+expert(features)*probabilities[:,index,None]*masks[:,index,None]
        return residual



def bank_tensors(bank):
    return {name: value.detach().cpu().contiguous().clone() for name, value in bank.state_dict().items()}


def load_extension(path):
    manifest, tensors = load_bundle(path)
    if manifest.get('model_family') != 'onram-external-micro-mlp-v1':
        raise ValueError('Not an Onram micro-extension bundle')
    spec = manifest['micro_extensions']
    bank = MicroExtensions(spec['hidden_size'], spec['rank'], spec['experts'])
    tensors.setdefault('active_mask', torch.ones(spec['experts'], dtype=torch.bool))
    bank.load_state_dict(tensors, strict=True)
    for parameter in bank.parameters():
        parameter.requires_grad_(False)
    return manifest, bank


def attach_extension(model, bank, module_path):
    if hasattr(model, 'onram_micro_extensions'):
        raise ValueError('Micro-extension already attached')
    layer = model.get_submodule(module_path)
    model.add_module('onram_micro_extensions', bank)
    def add_residual(module, inputs, output):
        if not isinstance(output, torch.Tensor) or not inputs:
            raise ValueError('Micro-extension requires a tensor-output MLP')
        return output + bank(inputs[0]).to(output.dtype)
    return layer.register_forward_hook(add_residual)


def initialize(bundle: Path, output: Path, *, rank=8, experts=3, layer=34):
    """Read only a few real projection rows; no full base model allocation."""
    from safetensors import safe_open
    if output.exists():
        raise ValueError('Extension exists; preserve its trained weights or choose a new output')
    if not 1 <= rank <= 128 or not 1 <= experts <= 16:
        raise ValueError('Use rank 1..128 and experts 1..16')
    base_manifest, tensors = load_bundle(bundle)
    base = base_manifest['base_model']
    source = Path(base['source'])
    key = f'model.language_model.layers.{layer}.mlp.gate_proj.weight'
    index_path = source / 'model.safetensors.index.json'
    candidates = [source / json.loads(index_path.read_text())['weight_map'][key]] if index_path.exists() else list(source.glob('*.safetensors'))
    seed = None
    for shard in candidates:
        with safe_open(shard, framework='pt', device='cpu') as handle:
            if key not in handle.keys():
                continue
            sliced = handle.get_slice(key)
            channels, hidden = sliced.get_shape()
            if rank * experts > channels:
                raise ValueError('Requested seed rows exceed projection width')
            bank = MicroExtensions(hidden, rank, experts)
            with torch.no_grad():
                for expert in range(experts):
                    first = expert * channels // experts
                    rows = sliced[first:first+rank, :].float()
                    rows = F.normalize(rows, dim=1)
                    bank.experts[expert].down.weight.copy_(rows)
                    bank.router.weight[expert].copy_(F.normalize(rows.mean(dim=0), dim=0))
            seed = {'weight': key, 'method': 'normalized_pretrained_gate_rows_and_centroid',
                    'channel_partitions': experts,
                    'semantic_assignment': 'unvalidated; partitions have no factual labels'}
            break
    if seed is None:
        raise ValueError('Requested text MLP projection is not present in this checkpoint')
    manifest = {'model_family': 'onram-external-micro-mlp-v1', 'version': 0,
        'base_weights_sha256': base['weights_sha256'], 'parent_bundle': str(bundle.resolve()),
        'micro_extensions': {'hidden_size': hidden, 'rank': rank, 'experts': experts,
            'module': key.removesuffix('.gate_proj.weight'), 'routing': 'activation_top1',
            'seed': seed, 'status': 'zero_residual_not_trained',
            'limitations': ['Base forward compute remains necessary',
                'Only selected residual expert and router are trained',
                'Requires Onram Transformers hooks; existing GGUF runtime cannot execute these micro-MLPs']},
        'journal': []}
    save_bundle(output, manifest, bank_tensors(bank))
    base_manifest['micro_extension'] = {'path': str(output.resolve()), 'enabled': True,
                                       'base_weights_sha256': base['weights_sha256']}
    save_bundle(bundle, base_manifest, tensors)
    return {'bundle': str(output), 'experts': experts, 'rank': rank,
            'parameters': sum(p.numel() for p in bank.parameters()),
            'parameters_per_expert': sum(p.numel() for p in bank.experts[0].parameters()),
            'base_weights_changed': False, 'initial_residual': 'exactly_zero'}



def grow(extension, output):
    if output.exists():
        raise ValueError('Choose a new extension output')
    manifest, old = load_extension(extension)
    spec = manifest['micro_extensions']
    count = spec['experts']
    if count >= 16:
        raise ValueError('Maximum of 16 micro-experts per bank')
    bank = MicroExtensions(spec['hidden_size'], spec['rank'], count + 1)
    with torch.no_grad():
        bank.router.weight[:count].copy_(old.router.weight)
        bank.router.weight[count].copy_(old.router.weight[0])
        bank.active_mask[:count].copy_(old.active_mask)
        bank.active_mask[count] = False
        for index in range(count):
            bank.experts[index].load_state_dict(old.experts[index].state_dict())
        bank.experts[count].down.weight.copy_(old.experts[0].down.weight)
    spec['experts'] = count + 1
    spec['status'] = 'new_expert_inactive_pending_training'
    manifest.setdefault('journal', []).append({'growth': count, 'enabled': False,
        'policy': 'new expert excluded from routing until separately trained and evaluated'})
    save_bundle(output, manifest, bank_tensors(bank))
    return {'extension': str(output), 'new_expert_index': count,
            'active_extension_changed': False, 'new_expert_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('create')
    create.add_argument('--bundle', type=Path, required=True)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--rank', type=int, default=8)
    create.add_argument('--experts', type=int, default=3)
    create.add_argument('--layer', type=int, default=34)
    growth = sub.add_parser('grow')
    growth.add_argument('--extension', type=Path, required=True)
    growth.add_argument('--output', type=Path, required=True)
    inspect = sub.add_parser('inspect')
    inspect.add_argument('--extension', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'create':
        result = initialize(args.bundle, args.output, rank=args.rank, experts=args.experts, layer=args.layer)
    elif args.action == 'grow':
        result = grow(args.extension, args.output)
    else:
        manifest, bank = load_extension(args.extension)
        result = {'manifest': manifest, 'parameters': sum(p.numel() for p in bank.parameters())}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
