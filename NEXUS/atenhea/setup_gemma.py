#!/usr/bin/env python3
"""Install current stable llama.cpp and Gemma 4 MoE, with native 262K context."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / 'third_party/llama-current'
BUILD = ROOT / 'build/llama-current'
MODEL_DIR = ROOT / 'models/gemma4-26b'
MODEL_NAME = 'gemma-4-26B-A4B-it-UD-IQ3_S.gguf'
MODEL_SHA = '878be93f9c238ea853b3fd1eb602637ce3cf1cddea56dc345d9a7bf2d6093e29'
MODEL_URL = 'https://huggingface.co/unsloth/gemma-4-26B-A4B-it-GGUF/resolve/c099eb4/' + MODEL_NAME
CONTEXT = 262144


def run(args, **kwargs):
    print('+ ' + shlex.join([str(a) for a in args]), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    run(['curl', '--fail', '--location', '--retry', '5', '--retry-delay', '3',
         '--continue-at', '-', '--output', target, url])


def install_runtime():
    if not (RUNTIME / 'onram-release.json').exists():
        with urllib.request.urlopen('https://api.github.com/repos/ggml-org/llama.cpp/releases/latest') as response:
            release = json.load(response)
        tag = release['tag_name']
        print('Installing latest stable llama.cpp: ' + tag, flush=True)
        RUNTIME.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=RUNTIME.parent) as temp:
            archive = Path(temp) / 'source.tar.gz'
            download('https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/' + tag, archive)
            unpack = Path(temp) / 'source'
            unpack.mkdir()
            with tarfile.open(archive) as bundle:
                for member in bundle.getmembers():
                    target = (unpack / member.name).resolve()
                    if unpack.resolve() not in target.parents or not (member.isfile() or member.isdir()):
                        raise ValueError('Unsafe archive entry: ' + member.name)
                    bundle.extract(member, unpack)
            source = next(unpack.iterdir())
            if RUNTIME.exists():
                raise RuntimeError('Incomplete runtime directory; inspect ' + str(RUNTIME))
            shutil.move(str(source), RUNTIME)
            (RUNTIME / 'onram-release.json').write_text(json.dumps({
                'tag': tag, 'commit': release['target_commitish'],
                'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))
    cmake = shutil.which('cmake') or str(ROOT / 'third_party/strata/.venv/bin/cmake')
    if not Path(cmake).is_file():
        raise RuntimeError('CMake required: install it or run ./onram strata-setup first')
    release_info = json.loads((RUNTIME / 'onram-release.json').read_text())
    run([cmake, '-S', RUNTIME, '-B', BUILD, '-DCMAKE_BUILD_TYPE=Release',
         '-DLLAMA_BUILD_COMMIT=' + release_info['commit'][:8], '-DLLAMA_BUILD_NUMBER=0',
         '-DGGML_METAL=ON', '-DGGML_METAL_EMBED_LIBRARY=ON', '-DLLAMA_BUILD_TESTS=OFF',
         '-DLLAMA_BUILD_EXAMPLES=OFF', '-DLLAMA_BUILD_SERVER=ON'])
    run([cmake, '--build', BUILD, '--target', 'llama-server', '--parallel', '4'])


def download_model(target):
    """Resume the contiguous prefix, then fetch validated byte ranges in parallel."""
    probe = urllib.request.Request(MODEL_URL + '?download=true', headers={'Range': 'bytes=0-0'})
    with urllib.request.urlopen(probe, timeout=60) as response:
        header = response.headers.get('Content-Range', '')
        if response.status != 206 or not header.startswith('bytes 0-0/'):
            download(MODEL_URL, target)
            return
        total = int(header.split('/')[-1])
    prefix = target.stat().st_size if target.exists() else 0
    if prefix > total:
        raise RuntimeError('Partial download is larger than the model')
    chunk_size = 128 * 1024**2
    chunks = target.with_suffix('.chunks')
    chunks.mkdir(exist_ok=True)
    ranges = [(offset, min(total, offset + chunk_size) - 1) for offset in range(prefix, total, chunk_size)]

    def fetch(bounds):
        first, last = bounds
        output = chunks / f'{first}-{last}'
        expected = last - first + 1
        if output.exists() and output.stat().st_size == expected:
            return output
        temp = output.with_suffix('.part')
        for attempt in range(5):
            try:
                req = urllib.request.Request(MODEL_URL + f'?download=true&range={first}-{last}',
                                             headers={'Range': f'bytes={first}-{last}'})
                with urllib.request.urlopen(req, timeout=120) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {first}-{last}/{total}':
                        raise RuntimeError('Server did not return the requested byte range')
                    with temp.open('wb') as stream:
                        shutil.copyfileobj(response, stream, 1024**2)
                if temp.stat().st_size != expected:
                    raise RuntimeError('Incomplete model range')
                temp.rename(output)
                return output
            except (OSError, RuntimeError):
                if attempt == 4:
                    raise
                time.sleep(2 * (attempt + 1))

    completed = prefix
    print(f'Model: reusing {prefix / 1e9:.2f} GB; downloading remaining ranges with 4 connections.', flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, bounds): bounds for bounds in ranges}
        for future in as_completed(futures):
            future.result()
            first, last = futures[future]
            completed += last - first + 1
            print(f'Model download: {completed / 1e9:.2f} / {total / 1e9:.2f} GB ({completed * 100 / total:.0f}%)', flush=True)
    with target.open('ab') as stream:
        for first, last in ranges:
            with (chunks / f'{first}-{last}').open('rb') as piece:
                shutil.copyfileobj(piece, stream, 8 * 1024**2)
    # Final SHA-256 is checked before the GGUF becomes active.
    shutil.rmtree(chunks)


def install_model():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model = MODEL_DIR / MODEL_NAME
    marker = model.with_suffix('.verified.json')
    if model.is_file() and marker.is_file():
        verified = json.loads(marker.read_text())
        if verified.get('size') == model.stat().st_size and verified.get('sha256') == MODEL_SHA:
            return model
    if not model.exists():
        partial = model.with_suffix('.gguf.part')
        download_model(partial)
        print('Verifying model SHA-256...', flush=True)
        check = hashlib.sha256()
        with partial.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b''):
                check.update(block)
        if check.hexdigest() != MODEL_SHA:
            raise RuntimeError('Model checksum mismatch; preserving partial download for inspection')
        partial.rename(model)
    else:
        check = hashlib.sha256()
        with model.open('rb') as stream:
            for block in iter(lambda: stream.read(8 * 1024**2), b''):
                check.update(block)
        if check.hexdigest() != MODEL_SHA:
            raise RuntimeError('Existing model checksum mismatch')
    marker.write_text(json.dumps({'size': model.stat().st_size, 'sha256': MODEL_SHA}))
    return model


def configure(model):
    extra = ['--flash-attn', 'on', '--cache-type-k', 'q4_0', '--cache-type-v', 'q4_0',
             '--batch-size', '256', '--ubatch-size', '64', '--load-mode', 'mmap',
             '--fit', 'on', '--fit-ctx', str(CONTEXT)]
    args = ['--backend', 'llama.cpp', '--model', str(model), '--llama-server', str(BUILD / 'bin/llama-server'),
            '--model-name', 'gemma4-26b-a4b', '--ctx-size', str(CONTEXT),
            '--no-auto-learn', '--no-inference-debug']
    args += ['--backend-arg=' + value for value in extra]
    config = {'name': 'gemma4-26b-a4b:latest', 'context_size': CONTEXT,
              'args': args, 'backend': 'llama.cpp', 'model_sha256': MODEL_SHA}
    (ROOT / 'models/onram-launch.json').write_text(json.dumps(config, indent=2))
    script = ROOT / 'start-gemma.sh'
    script.write_text('#!/bin/sh\nset -eu\ncd ' + shlex.quote(str(ROOT)) + '\nexec ./onram serve '
                      + shlex.join(args) + ' "$@"\n')
    script.chmod(0o755)
    print('Profile configured: ./start-gemma.sh or ./onram launch pi (context: 262144)', flush=True)
    return script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-start', action='store_true')
    args = parser.parse_args()
    # Download and build are separate resumable steps.
    install_runtime()
    script = configure(install_model())
    print("Gemma installation completed and model checksum verified.", flush=True)
    if not args.no_start:
        os.execv(str(script), [str(script)])


if __name__ == '__main__':
    main()
