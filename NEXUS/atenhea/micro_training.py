"""Cache the frozen E2B prefix once, then train one external expert using its exact final tail."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import time
import torch
from torch import nn
from torch.nn import functional as F
from safetensors.torch import load_file, save_file
from transformers.activations import ACT2FN
from transformers.models.gemma4.modeling_gemma4 import Gemma4RMSNorm

from micro_extensions import load_extension, bank_tensors
from nram_container import save_bundle, load_bundle


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class CachedTail(nn.Module):
    def __init__(self, spec):
        super().__init__()
        self.spec = spec
        h, ple, eps = spec['hidden'], spec['ple'], spec['eps']
        self.post_norm = Gemma4RMSNorm(h, eps)
        self.final_norm = Gemma4RMSNorm(h, eps)
        self.head = nn.Linear(h, spec['vocab'], bias=False)
        self.register_buffer('layer_scalar', torch.ones(1))
        if ple:
            self.ple_gate = nn.Linear(h, ple, bias=False)
            self.ple_projection = nn.Linear(ple, h, bias=False)
            self.ple_norm = Gemma4RMSNorm(h, eps)
        self.act_fn = ACT2FN[spec['activation']]

    @classmethod
    def from_model(cls, model, module_path):
        decoder_path = module_path.removesuffix('.mlp')
        block = model.get_submodule(decoder_path)
        text = model.get_submodule(decoder_path.rsplit('.layers.', 1)[0])
        if block.enable_moe_block:
            raise ValueError('Cached tail currently supports dense E2B only')
        if not decoder_path.endswith(f'.{text.config.num_hidden_layers - 1}'):
            raise ValueError('Efficient caching requires the final decoder layer')
        spec = {'hidden': block.hidden_size, 'ple': block.hidden_size_per_layer_input,
                'eps': text.config.rms_norm_eps, 'vocab': model.lm_head.out_features,
                'activation': text.config.hidden_activation,
                'softcap': text.config.final_logit_softcapping}
        with torch.device('meta'):
            tail = cls(spec)
        # Reuse frozen tensors, with no duplicate copy of the large vocabulary head.
        tail.post_norm = block.post_feedforward_layernorm
        tail.final_norm = text.norm
        tail.head = model.lm_head
        tail.layer_scalar = block.layer_scalar.detach()
        if spec['ple']:
            tail.ple_gate = block.per_layer_input_gate
            tail.ple_projection = block.per_layer_projection
            tail.ple_norm = block.post_per_layer_input_norm
        for parameter in tail.parameters():
            parameter.requires_grad_(False)
        return tail

    def hidden_state(self, data, bank):
        hidden = data['residual'] + self.post_norm(data['base_mlp'] + bank(data['features']))
        if self.spec['ple']:
            hidden = hidden + self.ple_norm(self.ple_projection(
                self.act_fn(self.ple_gate(hidden)) * data['per_layer_input']))
        hidden = hidden * self.layer_scalar
        return self.final_norm(hidden)

    def forward(self, data, bank, vocabulary=None):
        hidden = self.hidden_state(data, bank)
        logits = (self.head(hidden) if vocabulary is None else
                  F.linear(hidden.float(), self.head.weight[vocabulary].float()))
        if self.spec['softcap'] is not None:
            cap = self.spec['softcap']
            logits = torch.tanh(logits / cap) * cap
        return logits.float()


def cache_examples(model, rows, tokenizer, module_path, bank, max_length=64):
    from nram_evolve_generic import encode
    block = model.get_submodule(module_path.removesuffix('.mlp'))
    captured = {}
    def capture_block(module, inputs):
        captured['per_layer_input'] = inputs[1] if len(inputs) > 1 else None
    def capture_residual(module, inputs):
        captured['residual'] = inputs[0]
    def capture_mlp(module, inputs, output):
        captured['features'], captured['base_mlp'] = inputs[0], output
    handles = [block.register_forward_pre_hook(capture_block),
        block.pre_feedforward_layernorm.register_forward_pre_hook(capture_residual),
        block.mlp.register_forward_hook(capture_mlp)]
    previous = bank.enabled
    bank.enabled = False
    arrays = {name: [] for name in ('features', 'residual', 'base_mlp', 'per_layer_input', 'labels')}
    model.eval()
    try:
        with torch.no_grad():
            for row in rows:
                encoded = encode(tokenizer, row, max_length)
                ids = torch.tensor([encoded['input_ids']], device=next(model.parameters()).device)
                model(input_ids=ids, attention_mask=torch.ones_like(ids), use_cache=False)
                labels = torch.tensor(encoded['labels'][1:])
                mask = labels != -100
                arrays['labels'].append(labels[mask])
                for name in ('features', 'residual', 'base_mlp'):
                    arrays[name].append(captured[name][0, :-1].detach().cpu()[mask].clone())
                ple = captured['per_layer_input']
                arrays['per_layer_input'].append(ple[0, :-1].detach().cpu()[mask].clone()
                    if ple is not None else torch.zeros(int(mask.sum()), 0))
    finally:
        bank.enabled = previous
        for handle in handles:
            handle.remove()
    return {name: torch.cat(values).contiguous() for name, values in arrays.items()}



@torch.no_grad()
def full_vocabulary_nll(tail, data, bank, chunk_size=2048):
    """Exact full-vocabulary normalization in bounded FP32 projection chunks."""
    hidden = tail.hidden_state(data, bank).float()
    normalizer = torch.full((len(hidden),), -torch.inf)
    targets = torch.zeros(len(hidden))
    labels = data['labels']
    for start in range(0, tail.spec['vocab'], chunk_size):
        logits = F.linear(hidden, tail.head.weight[start:start+chunk_size].float())
        if tail.spec['softcap'] is not None:
            cap = tail.spec['softcap']; logits = torch.tanh(logits / cap) * cap
        normalizer = torch.logaddexp(normalizer, torch.logsumexp(logits, dim=-1))
        mask = (labels >= start) & (labels < start + logits.shape[1])
        if mask.any():
            targets[mask] = logits[mask, labels[mask] - start]
    return (normalizer - targets).sum()


def make_cache(bundle, train, validation, output, max_length=64):
    from nram_generic import load_nram_model, load_tokenizer
    from nram_evolve_generic import read_jsonl
    from self_improvement import validate_separation
    if output.exists():
        raise ValueError('Choose a new cache output directory')
    train_rows, validation_rows = read_jsonl(train), read_jsonl(validation)
    validate_separation(train_rows, validation_rows)
    manifest, model, _ = load_nram_model(bundle, local_files_only=True)
    if not hasattr(model, 'onram_micro_extensions'):
        raise ValueError('Create the external micro-extension first')
    bank = model.onram_micro_extensions
    spec, _ = load_extension(Path(manifest['micro_extension']['path']))
    module_path = spec['micro_extensions']['module']
    tokenizer = load_tokenizer(manifest['base_model'].get('tokenizer_source') or manifest['base_model']['source'], local_files_only=True)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    tail = CachedTail.from_model(model, module_path)
    output.mkdir(parents=True)
    for name, rows in (('train', train_rows), ('validation', validation_rows)):
        tensors = cache_examples(model, rows, tokenizer, module_path, bank, max_length)
        save_file(tensors, output / (name + '.safetensors'))
    save_file({name: value.detach().cpu().contiguous() for name, value in tail.state_dict().items()}, output / 'tail.safetensors')
    metadata = {'schema': 'onram-e2b-micro-cache-v1', 'tail': tail.spec,
        'base_weights_sha256': manifest['base_model']['weights_sha256'], 'bundle_sha256': sha(bundle),
        'module': module_path, 'train_sha256': sha(train), 'validation_sha256': sha(validation),
        'max_length': max_length, 'note': 'Fixed prefix features; rebuild if upstream base or LoRA weights change'}
    (output / 'cache.json').write_text(json.dumps(metadata, indent=2))
    return metadata


def train_cached(extension, cache, output, *, expert=0, epochs=3, tokens_per_batch=8, learning_rate=1e-3, sampled_vocabulary=2048):
    if output.exists():
        raise ValueError('Use a new candidate output; active extension is preserved')
    manifest, bank = load_extension(extension)
    metadata = json.loads((cache / 'cache.json').read_text())
    if (metadata['base_weights_sha256'] != manifest['base_weights_sha256']
            or metadata['module'] != manifest['micro_extensions']['module']):
        raise ValueError('Cache belongs to another model or attachment point')
    parent = Path(manifest['parent_bundle'])
    if parent.exists() and metadata['bundle_sha256'] != sha(parent):
        raise ValueError('Upstream bundle changed; rebuild cached features')
    if not 0 <= expert < len(bank.experts):
        raise ValueError('Unknown expert index')
    with torch.device('meta'):
        tail = CachedTail(metadata['tail'])
    tail.load_state_dict(load_file(cache / 'tail.safetensors'), assign=True)
    for parameter in tail.parameters():
        parameter.requires_grad_(False)
    train = load_file(cache / 'train.safetensors')
    validation = load_file(cache / 'validation.safetensors')
    for index, module in enumerate(bank.experts):
        for parameter in module.parameters():
            parameter.requires_grad_(index == expert)
    for parameter in bank.router.parameters():
        parameter.requires_grad_(True)
    parameters = [p for p in bank.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(parameters, lr=learning_rate)
    started = time.monotonic()
    def batches(data):
        for start in range(0, len(data['labels']), tokens_per_batch):
            yield {name: value[start:start+tokens_per_batch] for name, value in data.items()}
    @torch.no_grad()
    def score(data):
        bank.force_expert = None
        total, tokens = 0.0, 0
        for batch in batches(data):
            total += float(full_vocabulary_nll(tail, batch, bank))
            tokens += len(batch['labels'])
        if not tokens:
            raise ValueError('Cache has no supervised completion tokens')
        return total / tokens
    before = score(validation)
    guard_path = cache / 'guardrail.safetensors'
    guard = load_file(guard_path) if guard_path.exists() else None
    guard_before = score(guard) if guard is not None else None
    frozen_before = {name: value.clone() for name, value in bank.state_dict().items()
                     if name != 'active_mask' and not name.startswith((f'experts.{expert}.', 'router.'))}
    bank.active_mask[expert] = True
    for epoch in range(epochs):
        for batch in batches(train):
            bank.force_expert = expert
            optimizer.zero_grad(set_to_none=True)
            vocabulary = torch.unique(torch.cat((batch['labels'],
                torch.randint(0, tail.spec['vocab'], (sampled_vocabulary,)))))
            logits = tail(batch, bank, vocabulary)
            sampled_labels = torch.searchsorted(vocabulary, batch['labels'])
            loss = F.cross_entropy(logits, sampled_labels) + 0.1 * bank.routing_loss
            if not torch.isfinite(loss):
                raise ValueError('Non-finite candidate loss; active extension preserved')
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            if not torch.isfinite(norm):
                raise ValueError('Non-finite candidate gradient')
            optimizer.step()
    bank.force_expert = None
    after = score(validation)
    guard_after = score(guard) if guard is not None else None
    guard_ok = guard_before is None or (math.isfinite(guard_after) and guard_after <= guard_before * 1.02)
    unchanged = all(torch.equal(value, bank.state_dict()[name]) for name, value in frozen_before.items())
    accepted = math.isfinite(before) and math.isfinite(after) and after < before - 1e-4 and unchanged and guard_ok
    report = {'accepted': accepted, 'validation_nll_before': before, 'validation_nll_after': after,
        'guardrail_nll_before': guard_before, 'guardrail_nll_after': guard_after, 'guardrail_ok': guard_ok,
        'expert': expert, 'trainable_parameters': sum(p.numel() for p in parameters),
        'other_experts_unchanged': unchanged, 'base_model_loaded_during_training': False,
        'training_objective': 'sampled_vocabulary_cross_entropy_plus_router_loss',
        'sampled_vocabulary': sampled_vocabulary, 'validation_objective': 'full_vocabulary_nll',
        'elapsed_seconds': round(time.monotonic() - started, 3), 'runtime_promoted': False,
        'limitation': 'Local held-out improvement alone does not establish general quality; use a separate regression benchmark'}
    manifest['last_validation'] = report
    manifest.setdefault('journal', []).append(report)
    manifest['micro_extensions']['status'] = 'candidate_accepted' if accepted else 'candidate_rejected'
    if accepted:
        manifest['version'] += 1
    save_bundle(output, manifest, bank_tensors(bank))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    cache = sub.add_parser('cache')
    cache.add_argument('--bundle', type=Path, required=True)
    cache.add_argument('--train', type=Path, required=True)
    cache.add_argument('--validation', type=Path, required=True)
    cache.add_argument('--output', type=Path, required=True)
    cache.add_argument('--max-length', type=int, default=64)
    train = sub.add_parser('train')
    train.add_argument('--extension', type=Path, required=True)
    train.add_argument('--cache', type=Path, required=True)
    train.add_argument('--output', type=Path, required=True)
    train.add_argument('--expert', type=int, default=0)
    train.add_argument('--epochs', type=int, default=3)
    train.add_argument('--tokens-per-batch', type=int, default=8)
    train.add_argument('--learning-rate', type=float, default=1e-3)
    train.add_argument('--sampled-vocabulary', type=int, default=2048)
    args = parser.parse_args()
    if args.action == 'cache':
        if args.max_length < 2:
            parser.error('max-length must be at least 2')
        result = make_cache(args.bundle, args.train, args.validation, args.output, args.max_length)
    else:
        if args.epochs < 1 or args.tokens_per_batch < 1 or args.sampled_vocabulary < 1 or not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
            parser.error('Training settings must be positive and finite')
        result = train_cached(args.extension, args.cache, args.output, expert=args.expert,
            epochs=args.epochs, tokens_per_batch=args.tokens_per_batch, learning_rate=args.learning_rate, sampled_vocabulary=args.sampled_vocabulary)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
