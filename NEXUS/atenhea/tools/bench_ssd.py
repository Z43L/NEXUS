#!/usr/bin/env python3
"""Build/run the native SSD + shared Metal buffer benchmark (no downloads)."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--experts', type=Path)
    ap.add_argument('--batches', type=int, default=48)
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--repeated-trace', action='store_true', help='Diagnostic for OS cache effects; default uses different regions per case')
    args = ap.parse_args()
    if sys.platform != 'darwin':
        ap.error('Apple Silicon macOS required')
    if args.batches < 1 or args.rounds < 1:
        ap.error('batches and rounds must be positive')
    experts = args.experts or next((ROOT / 'models/strata/models').glob('*/*.gguf.experts'), None)
    if not experts or not experts.is_file():
        ap.error('No expert-contiguous file found; use --experts FILE')
    source = ROOT / 'native/ssd_metal_bench.mm'
    executable = ROOT / 'build/ssd-metal-bench'
    executable.parent.mkdir(exist_ok=True)
    if not executable.exists() or executable.stat().st_mtime < source.stat().st_mtime:
        subprocess.run(['xcrun', 'clang++', '-O3', '-std=c++20', '-fobjc-arc', '-framework', 'Foundation',
                        '-framework', 'Metal', str(source), '-o', str(executable)], check=True)
    folder = ROOT / 'benchmarks'
    folder.mkdir(exist_ok=True)
    output = folder / 'ssd-latest.jsonl'
    with output.open('w') as results:
        subprocess.run([str(executable), str(experts.resolve()), str(args.batches), str(args.rounds),
                        'repeated' if args.repeated_trace else 'disjoint'], stdout=results, check=True)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    groups = {}
    for row in rows:
        groups.setdefault((row['backend'], row['threads']), []).append(row)
    summary = []
    for (backend, threads), records in groups.items():
        summary.append({'backend': backend, 'threads': threads,
            'read_gb_s_median': statistics.median(r['gb_s'] for r in records),
            'io_plus_gpu_gb_s_median': statistics.median(r['bytes'] / (r['read_ms'] + r['consume_gpu_ms']) / 1e6 for r in records),
            'all_gpu_checksums_verified': all(r['verified'] for r in records)})
    print(json.dumps({'results': str(output), 'summary': summary,
        'note': 'Microbenchmark, not inference throughput. Metal IO cache policy is driver-managed; disjoint traces reduce reuse but do not guarantee cold physical SSD reads.'}, indent=2))


if __name__ == '__main__':
    main()
