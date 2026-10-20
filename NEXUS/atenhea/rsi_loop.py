"""Bounded candidate-only LoRA improvement rounds; original bundle remains recoverable."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from episodic_memory import DEFAULT_MEMORY, ROOT
from self_improvement import validate_separation


def read_rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def run_loop(bundle: Path, output: Path, rounds: int, train_round):
    if not 1 <= rounds <= 3:
        raise ValueError('RSI rounds must be between 1 and 3')
    if output.exists():
        raise ValueError('Use a new output directory for each run')
    if not bundle.is_file():
        raise FileNotFoundError(f'Trainable NRAM bundle missing: {bundle}')
    output.mkdir(parents=True)
    current = bundle.resolve()
    reports = []
    for index in range(1, rounds + 1):
        candidate = output / f'candidate-{index}.nram'
        shutil.copy2(current, candidate)
        report = train_round(candidate, index)
        reports.append(report)
        (output / 'rounds.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
        # Never continue from rejected weights or a non-finite validation result.
        accepted = (report.get('accepted') is True and report.get('finite_metrics') is True
                    and isinstance(report.get('validation_nll_after'), (int, float))
                    and math.isfinite(report['validation_nll_after']))
        if not accepted:
            break
        current = candidate
    result = {'rounds_completed': len(reports), 'accepted_candidate': str(current) if current != bundle.resolve() else None,
              'original_bundle': str(bundle.resolve()), 'runtime_promoted': False,
              'limitation': 'Repeated validation is adaptive; use an untouched final benchmark before deployment.'}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--train', type=Path, required=True)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--guardrail', type=Path, required=True)
    parser.add_argument('--memory', type=Path, default=DEFAULT_MEMORY)
    parser.add_argument('--output', type=Path, default=ROOT / 'models' / ('athenea-rsi-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')))
    parser.add_argument('--rounds', type=int, choices=range(1, 4), default=1)
    parser.add_argument('--specialization', choices=['general', 'self', 'user', 'world', 'code'], default='general')
    parser.add_argument('--epochs', type=int, default=2)
    parser.add_argument('--learning-rate', type=float, default=5e-5)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--runtime-traces', type=Path)
    args = parser.parse_args()
    if args.epochs < 1 or not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
        parser.error('epochs and learning-rate must be positive and finite')
    validate_separation(read_rows(args.train), read_rows(args.validation) + read_rows(args.guardrail))
    # Import only on actual training; help and preparation need no Torch installation.
    try:
        from nram_container import load_bundle
    except ImportError as exc:
        parser.error(f'Training dependencies missing ({exc}); install requirements.txt in a Python environment')
    manifest, _ = load_bundle(args.bundle)
    if manifest.get('model_family') != 'hf-causal-lm-dense-lora':
        parser.error('This RSI loop requires a trainable generic NRAM v2 bundle, not a GGUF')

    def train_round(candidate, index):
        command = [sys.executable, str(ROOT / 'nram_evolve_generic.py'),
                   '--bundle', str(candidate), '--train', str(args.train.resolve()),
                   '--validation', str(args.validation.resolve()), '--guardrail', str(args.guardrail.resolve()),
                   '--chl-memory', str(args.memory.resolve()), '--specialization', args.specialization,
                   '--epochs', str(args.epochs), '--learning-rate', str(args.learning_rate),
                   '--device', args.device, '--local-files-only']
        if args.runtime_traces:
            command.extend(['--runtime-traces', str(args.runtime_traces.resolve())])
        with (args.output / f'round-{index}.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        updated, _ = load_bundle(candidate)
        return updated['last_validation']

    print(json.dumps(run_loop(args.bundle, args.output, args.rounds, train_round), ensure_ascii=False))


if __name__ == '__main__':
    main()
