"""Real checkpoint conversion using meta structures and CPU adapters."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest

import torch
from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from safetensors.torch import load_file, save_file

from nram_container import load_bundle
from nram_convert import convert
from nram_generic import load_nram_model


class LowMemoryConversionTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'base'
        model = GPT2LMHeadModel(GPT2Config(n_layer=2, n_head=2, n_embd=8, n_positions=32,
                                          vocab_size=16, bos_token_id=0, eos_token_id=1))
        model.save_pretrained(source)
        backend = Tokenizer(WordLevel({'[UNK]': 0, '[EOS]': 1, 'hello': 2}, unk_token='[UNK]'))
        backend.pre_tokenizer = Whitespace()
        PreTrainedTokenizerFast(tokenizer_object=backend, unk_token='[UNK]', eos_token='[EOS]').save_pretrained(source)
        return source

    def args(self, root, source):
        return argparse.Namespace(model=str(source), output=root / 'test.nram', revision=None,
            trust_remote_code=False, dtype='bfloat16', tokenizer=None, tokenizer_revision=None,
            last_k_blocks=1, targets=None, rank=2, alpha=4, low_memory=True)

    def test_meta_conversion_loads_exact_adapter_topology_and_base(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            result = convert(self.args(root, source))
            manifest, tensors = load_bundle(root / 'test.nram')
            self.assertFalse(manifest['conversion']['base_weights_loaded'])
            self.assertTrue(manifest['conversion']['target_shapes_verified'])
            self.assertEqual(manifest['episodic_memory']['path'].split('/')[-1], 'athenea.memory')
            self.assertIn('sources', manifest['self_knowledge'])
            self.assertTrue(all(value.device.type == 'cpu' for value in tensors.values()))
            self.assertTrue(all(value.eq(0).all() for key, value in tensors.items() if key.endswith('lora_B')))
            _, model, _ = load_nram_model(root / 'test.nram', local_files_only=True)
            with torch.inference_mode():
                output = model(input_ids=torch.tensor([[2, 2]]))
            self.assertEqual(tuple(output.logits.shape), (1, 2, 16))
            self.assertGreater(result['trainable_parameters'], 0)

    def test_invalid_checkpoint_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = self.fixture(root)
            file = source / 'model.safetensors'
            weights = load_file(file)
            name = 'transformer.h.1.attn.c_attn.weight'
            weights[name] = weights[name][:1]
            save_file(weights, file)
            with self.assertRaisesRegex(ValueError, 'shape mismatch'):
                convert(self.args(root, source))
            self.assertFalse((root / 'test.nram').exists())
