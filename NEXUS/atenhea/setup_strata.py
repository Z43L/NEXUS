#!/usr/bin/env python3
"""Install a private Strata runtime and model inside this repository."""
import argparse
import json
import hashlib
import tarfile
import tempfile
import urllib.request
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'third_party' / 'strata'
DATA = ROOT / 'models' / 'strata'


def copy_file(source, target):
    # APFS clones avoid duplicating large existing weights; fall back elsewhere.
    if sys.platform == 'darwin':
        result = subprocess.run(['cp', '-c', str(source), str(target)], capture_output=True)
        if result.returncode == 0:
            return str(target)
    return shutil.copy2(source, target)


def download_source(url):
    """Download source without Git; only regular files/directories are extracted."""
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=RUNTIME.parent) as temp:
        archive = Path(temp) / 'strata.tar.gz'
        print('Downloading Strata source archive...', flush=True)
        urllib.request.urlretrieve(url, archive)
        unpack = Path(temp) / 'source'
        unpack.mkdir()
        with tarfile.open(archive) as bundle:
            for member in bundle.getmembers():
                target = (unpack / member.name).resolve()
                if unpack.resolve() not in target.parents or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe source archive entry: ' + member.name)
                bundle.extract(member, unpack)
        roots = list(unpack.iterdir())
        if len(roots) != 1 or not (roots[0] / 'setup.sh').is_file():
            raise ValueError('Archive does not contain Strata source')
        shutil.move(str(roots[0]), RUNTIME)
        (RUNTIME / 'onram-source.json').write_text(json.dumps({
            'url': url, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


def localize_pack(config):
    """Upstream may discover another installation's pack: keep ours independent."""
    cfg = json.loads(config.read_text())
    if sys.platform == 'darwin':
        try:
            memory = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], stderr=subprocess.DEVNULL))
        except (OSError, ValueError, subprocess.CalledProcessError):
            memory = 0
        if 0 < memory <= 20 * 1024**3:
            cfg.setdefault('env', {}).update(STRATA_METAL_PROMPT='window', STRATA_METAL_PROMPT_GEMM='0')
    args = cfg.get('args', [])
    if '--pack' in args:
        index = args.index('--pack') + 1
        original = Path(args[index]).resolve()
        target = DATA / 'packs' / original.name
        if original != target.resolve():
            shutil.copytree(original, target, dirs_exist_ok=True, copy_function=copy_file)
            cfg['args'][index] = str(target)
            cfg['tokenizer'] = str(target / 'tokenizer')
    config.write_text(json.dumps(cfg, indent=2))


def copy_local_source(source):
    print('Copying Strata into third_party/strata (without cloning)...', flush=True)
    shutil.copytree(source, RUNTIME, dirs_exist_ok=True, copy_function=copy_file,
                    ignore=shutil.ignore_patterns('.git', '.venv', '__pycache__', 'Strata-data',
                        'build*', '*.log', '*.gguf', '*.part', '*.experts', 'strata-*.json',
                        'run-*.sh', 'estado-instalacion.txt', 'finalizar-instalacion*'))
    revision = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                              capture_output=True, text=True)
    (RUNTIME / 'onram-source.json').write_text(json.dumps({
        'source': str(source), 'revision': revision.stdout.strip() or None,
        'note': 'Local snapshot, including any local source changes'}, indent=2))


def apply_runtime_patches():
    runtime = RUNTIME / 'metal/src/mtl_rt.mm'
    stream = RUNTIME / 'metal/src/engine/stream.cpp'
    patches = [
        ('strata-metal-io.patch', lambda: runtime.is_file() and stream.is_file() and
            'Context::open_io_file' in runtime.read_text() and 'read_metal_jobs' in stream.read_text()),
        ('strata-moe-cache.patch', lambda: stream.is_file() and
            'demand_frequency_' in stream.read_text() and 'ExpertStream::trace_event' in stream.read_text()),
        ('strata-metal-window-slots.patch', lambda:
            (RUNTIME / 'metal/src/engine/window.cpp').is_file() and
            'pg_on ? 576 : MAXT * TOPK, err' in (RUNTIME / 'metal/src/engine/window.cpp').read_text()),
    ]
    for name, installed in patches:
        patch = ROOT / 'patches' / name
        if not patch.is_file() or installed():
            continue
        command = ['patch', '--batch', '--forward', '-p1', '-i', str(patch)]
        subprocess.run(command + ['--dry-run'], cwd=RUNTIME, check=True)
        subprocess.run(command, cwd=RUNTIME, check=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT.parent / 'strata',
                    help='Local Strata source to copy once (never cloned)')
    ap.add_argument('--archive-url', default='https://codeload.github.com/Niko1221/Strata/tar.gz/refs/heads/main',
                    help='Source archive used when the local source is absent; may be pinned to a commit')
    ap.add_argument('--model', default='Q2_0', choices=['Q2_0', 'IQ3_XXS', 'IQ3_S', 'UD-Q4_K_XL'])
    ap.add_argument('--context', type=int, default=2048)
    ap.add_argument('--io-backend', choices=['pread', 'metal'], default='pread',
                    help='Expert reader: original pread or opt-in batched Metal IO')
    ap.add_argument('--cache-policy', choices=['original', 'demand', 'frequency'], default='original',
                    help='Expert cache eviction/admission policy; candidates need workload validation')
    ap.add_argument('--arena-gb', type=float, help='Explicit expert cache budget in decimal GB; leave unset for upstream automatic sizing')
    ap.add_argument('--no-start', action='store_true')
    args = ap.parse_args(argv)
    if args.arena_gb is not None and args.arena_gb <= 0:
        ap.error('--arena-gb must be positive')
    if args.context < 512:
        ap.error('--context must be at least 512')
    source = args.source.resolve()
    if not (RUNTIME / 'setup.sh').is_file():
        if not (source / 'setup.sh').is_file():
            download_source(args.archive_url)
        else:
            copy_local_source(source)
    apply_runtime_patches()
    # Copy a point-in-time snapshot. Downloaded fragments resume independently;
    # never write to the original installation or share its temporary files.
    original = source / 'Strata-data' / 'models' / args.model
    target = DATA / 'models' / args.model
    if original.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for item in original.iterdir():
            if item.is_file() and ('.gguf' in item.name) and not (target / item.name).exists():
                print('Reusing downloaded file: ' + item.name, flush=True)
                copy_file(item, target / item.name)
    DATA.mkdir(parents=True, exist_ok=True)
    command = ['sh', str(RUNTIME / 'setup.sh'), '--yes', '--model', args.model,
               '--context', str(args.context), '--vision', 'no', '--host', '127.0.0.1',
               '--data-dir', str(DATA), '--models-dir', str(DATA / 'models'), '--no-start']
    print('Installing private Python, Metal engine and model; downloads resume on retry.', flush=True)
    result = subprocess.run(command, cwd=RUNTIME)
    if result.returncode:
        return result.returncode
    config = RUNTIME / ('strata-' + ('unsloth-' if args.model.startswith('UD-') else '') + args.model.lower() + '.json')
    if not config.is_file():
        raise FileNotFoundError('Strata setup did not produce configuration: ' + str(config))
    localize_pack(config)
    cfg = json.loads(config.read_text())
    cfg.setdefault('env', {})['STRATA_METAL_IO'] = args.io_backend
    cfg['env']['STRATA_METAL_CACHE_POLICY'] = args.cache_policy
    if args.arena_gb is not None:
        cfg['env']['STRATA_METAL_ARENA_GB'] = str(args.arena_gb)
    config.write_text(json.dumps(cfg, indent=2))
    if args.io_backend == 'metal':
        fast = dict(cfg)
        fast['env'] = dict(cfg['env'], STRATA_ROUTE_TAIL_SKIP='0')
        (DATA / 'strata-ssd-fast.json').write_text(json.dumps(fast, indent=2))
    start = ROOT / 'start-strata.sh'
    import shlex
    start.write_text('#!/bin/sh\nset -eu\ncd ' + shlex.quote(str(ROOT)) + '\nexec ./onram serve --backend strata --strata-dir '
                     + shlex.quote(str(RUNTIME)) + ' --strata-config ' + shlex.quote(str(config)) + ' "$@"\n')
    start.chmod(0o755)
    print('Installed. Start with ./start-strata.sh', flush=True)
    if not args.no_start:
        os.execv(str(start), [str(start)])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
