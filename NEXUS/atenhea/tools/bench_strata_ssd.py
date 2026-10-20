#!/usr/bin/env python3
"""Paired real-generation benchmark for opt-in Metal IO; never modifies model weights."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STRATA = ROOT / 'third_party/strata'
OUT = ROOT / 'benchmarks'
PROMPTS = [
    'Escribe una función Python que devuelva los números pares de una lista. Responde solo con código.',
    'Describe en español cómo funciona una caché LRU, en cuatro frases cortas.',
]


def request(port, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def memory_snapshot():
    output = {}
    for key in ['vm.swapusage', 'kern.memorystatus_vm_pressure_level']:
        result = subprocess.run(['sysctl', '-n', key], capture_output=True, text=True)
        output[key] = result.stdout.strip() if result.returncode == 0 else None
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rounds', type=int, default=2)
    ap.add_argument('--tokens', type=int, default=32)
    ap.add_argument('--arena-gb', type=float, default=1.0)
    ap.add_argument('--prefetch', type=int, default=10)
    ap.add_argument('--modes', nargs='+', choices=['pread', 'metal', 'demand', 'frequency'], default=['pread', 'metal'])
    ap.add_argument('--candidate-prefetch', type=int, help='Prefetch depth for demand-policy candidate only')
    ap.add_argument('--trace', action='store_true', help='Capture expert-only routing traces; do not use these timings as clean benchmarks')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--port', type=int, default=11438)
    args = ap.parse_args()
    if args.rounds < 1 or args.tokens < 1 or args.arena_gb <= 0:
        ap.error('rounds, tokens and arena-gb must be positive')
    if not 0 <= args.prefetch <= 32 or (args.candidate_prefetch is not None and not 0 <= args.candidate_prefetch <= 32):
        ap.error('prefetch depths must be between 0 and 32')
    OUT.mkdir(exist_ok=True)
    base = json.loads((STRATA / 'strata-q2_0.json').read_text())
    output = args.output or OUT / 'strata-ssd-generation.jsonl'
    if not output.is_absolute(): output = ROOT / output
    with output.open('a') as results:
        for round_id in range(args.rounds):
            for mode in (args.modes if round_id % 2 == 0 else list(reversed(args.modes))):
                depth = args.candidate_prefetch if mode == 'demand' and args.candidate_prefetch is not None else args.prefetch
                name = f'{mode}-r{round_id}-arena{args.arena_gb}-pre{depth}'
                cfg = dict(base)
                cfg['env'] = dict(base.get('env', {}), STRATA_METAL_IO='metal' if mode in {'demand', 'frequency'} else mode,
                    STRATA_METAL_CACHE_POLICY=mode if mode in {'demand', 'frequency'} else 'original',
                    STRATA_METAL_ARENA_GB=str(args.arena_gb), STRATA_METAL_PREFETCH=str(depth),
                    STRATA_ROUTE_TAIL_SKIP='0', STRATA_IO_STATS='1')
                cfg['env'].pop('STRATA_METAL_ROUTE_TRACE', None)
                if args.trace:
                    cfg['env']['STRATA_METAL_ROUTE_TRACE'] = str(OUT / (name + '.routes.jsonl'))
                cfg['log'] = str(OUT / (name + '-engine.log'))
                config_path = OUT / (name + '.json')
                config_path.write_text(json.dumps(cfg, indent=2))
                log_path = OUT / (name + '-server.log')
                print('Starting ' + name, flush=True)
                with log_path.open('w') as log:
                    process = subprocess.Popen([str(STRATA / '.venv/bin/python'), '-m', 'serve.server',
                        '--engine', 'strata', '--config', str(config_path), '--host', '127.0.0.1',
                        '--port', str(args.port)], cwd=STRATA, stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True)
                    try:
                        deadline = time.monotonic() + 180
                        while time.monotonic() < deadline:
                            if process.poll() is not None:
                                raise RuntimeError('Server failed; see ' + str(log_path))
                            try:
                                if request(args.port, '/health', timeout=1).get('loaded'):
                                    break
                            except OSError:
                                pass
                            time.sleep(.5)
                        else:
                            raise TimeoutError('Strata startup timed out')
                        for index, prompt in enumerate(PROMPTS):
                            memory_before = memory_snapshot()
                            start = time.monotonic()
                            answer = request(args.port, '/v1/chat/completions', {
                                'model': cfg['model_name'], 'messages': [{'role': 'user', 'content': prompt}],
                                'temperature': 0, 'seed': 42, 'max_tokens': args.tokens, 'reasoning_effort': 'none'})
                            text = answer['choices'][0]['message'].get('content')
                            if not text:
                                raise RuntimeError('Empty generation: ' + json.dumps(answer))
                            record = {'mode': mode, 'round': round_id, 'prompt': index,
                                'arena_gb': args.arena_gb, 'prefetch': depth, 'trace_enabled': args.trace,
                                'wall_seconds': time.monotonic() - start, 'text': text,
                                'usage': answer.get('usage'), 'timings': answer.get('timings'),
                                'engine_log': str(OUT / (name + '-engine.log')),
                                'memory_before': memory_before, 'memory_after': memory_snapshot()}
                            results.write(json.dumps(record, ensure_ascii=False) + '\n')
                            results.flush()
                            print(json.dumps({k:v for k,v in record.items() if k not in {'text','engine_log'}}, ensure_ascii=False), flush=True)
                    finally:
                        # The process group includes its engine, including on a failed startup.
                        import signal
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                        process.wait(timeout=20)


if __name__ == '__main__':
    main()
