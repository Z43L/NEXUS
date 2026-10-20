"""Resume pinned Hugging Face checkpoint files with parallel verified byte ranges."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'models/gemma4-e2b-trainable'
CHUNK = 128 * 1024**2


def file_sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch_file(repo, revision, entry):
    name, total = entry['rfilename'], entry['size']
    target = DEST / name
    expected_sha = entry.get('lfs', {}).get('sha256')
    if target.exists() and target.stat().st_size == total:
        if not expected_sha:
            return
        digest = file_sha256(target)
        if digest == expected_sha:
            print(json.dumps({'file': name, 'state': 'verified_existing'}), flush=True)
            return
        raise ValueError('Existing checksum mismatch: ' + name)
    url = f'https://huggingface.co/{repo}/resolve/{revision}/{name}'
    if total < CHUNK:
        temp = target.with_suffix(target.suffix + '.part')
        with urllib.request.urlopen(url, timeout=120) as response, temp.open('wb') as stream:
            while block := response.read(1024**2):
                stream.write(block)
        if temp.stat().st_size != total:
            raise ValueError('Size mismatch: ' + name)
        if expected_sha and file_sha256(temp) != expected_sha:
            raise ValueError('Checksum mismatch: ' + name)
        temp.replace(target)
        return
    temp = target.with_suffix(target.suffix + '.part')
    progress = target.with_suffix(target.suffix + '.ranges.json')
    done = set(json.loads(progress.read_text())['done']) if progress.exists() and temp.exists() else set()
    fd = os.open(temp, os.O_RDWR | os.O_CREAT, 0o644)
    os.ftruncate(fd, total)
    ranges = [(first, min(first + CHUNK, total) - 1) for first in range(0, total, CHUNK) if first not in done]

    def fetch(bounds):
        first, last = bounds
        for attempt in range(6):
            try:
                request = urllib.request.Request(url + f'?download=true&range={first}-{last}',
                                                headers={'Range': f'bytes={first}-{last}'})
                with urllib.request.urlopen(request, timeout=120) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {first}-{last}/{total}':
                        raise ValueError('Server did not honor byte range')
                    offset = first
                    while block := response.read(1024**2):
                        if offset + len(block) > last + 1:
                            raise ValueError('Range exceeded expected size')
                        view = memoryview(block)
                        while view:
                            written = os.pwrite(fd, view, offset)
                            if written <= 0:
                                raise OSError('Short write')
                            offset += written
                            view = view[written:]
                    if offset != last + 1:
                        raise ValueError('Incomplete range')
                return first
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(min(2 ** attempt, 15))
    started = time.monotonic()
    print(json.dumps({'file': name, 'state': 'downloading', 'bytes': total, 'ranges_remaining': len(ranges)}), flush=True)
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(fetch, bounds) for bounds in ranges]
            for future in as_completed(futures):
                done.add(future.result())
                os.fsync(fd)
                scratch = progress.with_suffix('.tmp')
                scratch.write_text(json.dumps({'revision': revision, 'done': sorted(done)}))
                scratch.replace(progress)
                completed = sum(min(CHUNK, total - first) for first in done)
                print(json.dumps({'file': name, 'downloaded_gb': round(completed / 1e9, 2),
                                  'total_gb': round(total / 1e9, 2), 'percent': round(100 * completed / total, 1),
                                  'seconds': round(time.monotonic() - started)}), flush=True)
    finally:
        os.close(fd)
    print(json.dumps({'file': name, 'state': 'verifying_sha256'}), flush=True)
    with temp.open('rb') as stream:
        actual_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual_sha != expected_sha:
        raise ValueError('Checksum mismatch; preserving partial file: ' + name)
    temp.replace(target)
    progress.unlink(missing_ok=True)
    print(json.dumps({'file': name, 'state': 'verified', 'sha256': actual_sha}), flush=True)


def main():
    global DEST
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='google/gemma-4-E2B-it')
    parser.add_argument('--destination', type=Path, default=DEST)
    args = parser.parse_args()
    DEST = args.destination.resolve()
    DEST.mkdir(parents=True, exist_ok=True)
    source_file = DEST / 'onram-source.json'
    if not source_file.exists():
        with urllib.request.urlopen('https://huggingface.co/api/models/' + args.repo + '?blobs=true', timeout=60) as response:
            info = json.load(response)
        source_file.write_text(json.dumps({'repo_id': args.repo, 'revision': info['sha'], 'files': info['siblings']}, indent=2))
    source = json.loads(source_file.read_text())
    if source['repo_id'] != args.repo:
        raise ValueError('Destination belongs to a different model repository')
    for entry in source['files']:
        if entry['rfilename'].startswith('.'):
            continue
        fetch_file(source['repo_id'], source['revision'], entry)
    (DEST / 'onram-download-verified.json').write_text(json.dumps({'repo_id': source['repo_id'],
        'revision': source['revision'], 'verified': True}, indent=2))
    print('All checkpoint files downloaded and verified.', flush=True)


if __name__ == '__main__':
    main()
