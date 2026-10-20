"""Local compute benchmark with real E2B tail weights and synthetic cached features."""
import json
from pathlib import Path
import sys
import time
import resource

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import torch
from torch.nn import functional as F
from safetensors import safe_open
from micro_extensions import load_extension
from micro_training import CachedTail, full_vocabulary_nll


def main():
    torch.set_num_threads(4)
    source = ROOT / 'models/gemma4-e2b-trainable'
    config = json.loads((source / 'config.json').read_text())['text_config']
    _, bank = load_extension(ROOT / 'models/athenea-e2b.extensions.nram')
    prefix = 'model.language_model.layers.34.'
    mapping = {'post_norm.weight': prefix + 'post_feedforward_layernorm.weight',
        'final_norm.weight': 'model.language_model.norm.weight',
        'head.weight': 'model.language_model.embed_tokens.weight',
        'layer_scalar': prefix + 'layer_scalar',
        'ple_gate.weight': prefix + 'per_layer_input_gate.weight',
        'ple_projection.weight': prefix + 'per_layer_projection.weight',
        'ple_norm.weight': prefix + 'post_per_layer_input_norm.weight'}
    spec = {'hidden': config['hidden_size'], 'ple': config['hidden_size_per_layer_input'],
            'eps': config['rms_norm_eps'], 'vocab': config['vocab_size'],
            'activation': config['hidden_activation'], 'softcap': config['final_logit_softcapping']}
    with safe_open(source / 'model.safetensors', framework='pt', device='cpu') as handle:
        weights = {name: handle.get_tensor(key) for name, key in mapping.items()}
    with torch.device('meta'):
        tail = CachedTail(spec)
    tail.load_state_dict(weights, assign=True)
    for p in tail.parameters(): p.requires_grad_(False)
    for p in bank.router.parameters(): p.requires_grad_(True)
    for p in bank.experts[0].parameters(): p.requires_grad_(True)
    params = [p for p in bank.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=1e-3)
    batch = 8
    torch.manual_seed(7)
    data = {key: torch.randn(batch, spec['hidden'], dtype=torch.bfloat16)
            for key in ('features', 'residual', 'base_mlp')}
    data['per_layer_input'] = torch.randn(batch, spec['ple'], dtype=torch.bfloat16)
    labels = torch.randint(0, spec['vocab'], (batch,))
    vocabulary = torch.randperm(spec['vocab'])[:2048].sort().values
    labels = labels.remainder(len(vocabulary))
    times = []
    for step in range(6):
        bank.force_expert = 0
        started = time.perf_counter()
        optimizer.zero_grad(set_to_none=True)
        logits = tail(data, bank, vocabulary)
        loss = F.cross_entropy(logits, labels) + 0.1 * bank.routing_loss
        loss.backward()
        optimizer.step()
        times.append(time.perf_counter() - started)
    elapsed = sum(times[1:])
    bank.force_expert = None
    data['labels'] = vocabulary[labels]
    started_validation = time.perf_counter()
    nll = float(full_vocabulary_nll(tail, data, bank))
    validation_seconds = time.perf_counter() - started_validation
    report = {'scope': 'real E2B frozen tail weights; synthetic cached features; CPU, 4 threads',
        'full_model_forward_included': False, 'sampled_vocabulary': 2048,
        'full_validation_included': False,
        'separate_full_validation_seconds_for_8_tokens': validation_seconds,
        'validation_projection': 'chunked_fp32_all_262144_tokens', 'cache_creation_included': False,
        'production_weights_changed': False, 'batch_tokens': batch, 'measured_steps': 5,
        'mean_step_seconds': elapsed / 5, 'supervised_tokens_per_second': 5 * batch / elapsed,
        'warmup_seconds': times[0], 'trainable_parameters': sum(p.numel() for p in params),
        'process_peak_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024**2}
    output = ROOT / 'models/athenea-e2b-micro-benchmark.json'
    output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':main()
