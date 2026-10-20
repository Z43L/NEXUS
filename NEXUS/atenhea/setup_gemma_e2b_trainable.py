#!/usr/bin/env python3
"""Download Google's E2B checkpoint and create the verified Athenea LoRA bundle."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    subprocess.run([sys.executable, str(ROOT / 'tools/download_trainable.py'),
                    '--repo', 'google/gemma-4-E2B-it', '--destination',
                    str(ROOT / 'models/gemma4-e2b-trainable')], cwd=ROOT, check=True)
    output = ROOT / 'models/athenea-e2b.nram'
    if output.exists():
        print('Existing E2B bundle preserved: ' + str(output), flush=True)
        return
    subprocess.run([sys.executable, str(ROOT / 'nram_convert.py'),
                    '--model', str(ROOT / 'models/gemma4-e2b-trainable'),
                    '--output', str(output), '--dtype', 'bfloat16', '--low-memory'],
                   cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
