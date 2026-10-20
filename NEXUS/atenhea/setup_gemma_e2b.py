#!/usr/bin/env python3
"""Download and verify a pinned Gemma 4 E2B GGUF for local text inference."""
import setup_gemma as installer

installer.MODEL_DIR = installer.ROOT / 'models/gemma4-e2b'
installer.MODEL_NAME = 'gemma-4-E2B-it-Q4_K_M.gguf'
installer.MODEL_SHA = '740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8'
installer.MODEL_URL = ('https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF/resolve/'
                       '0314792d7f1f7e229411f620751375812bb9faf2/' + installer.MODEL_NAME)

if __name__ == '__main__':
    print(installer.install_model(), flush=True)
