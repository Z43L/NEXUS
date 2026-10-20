"""Small CPU integration checks: real gradients and NRAM tensors, no model download."""
import argparse
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import torch
from torch import nn

from nram_container import load_bundle, save_bundle
from nram_generic import LoRAProjection, adapter_tensors
from nram_evolve_generic import run, train_epoch
from self_improvement import inspect_adapters


class TinyTokenizer:
    eos_token_id = 0
    pad_token_id = 0
    chat_template = None

    def __call__(self, text, **kwargs):
        return {'input_ids': [1, 1]}


class TinyModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(8, 4)
        self.projection = LoRAProjection(nn.Linear(4, 8), 2, 4, 'linear_out_in')
        self.config = SimpleNamespace(use_cache=True)
        for parameter in self.parameters():
            parameter.requires_grad_(False)
        self.projection.lora_A.requires_grad_(True)
        self.projection.lora_B.requires_grad_(True)

    def forward(self, input_ids, attention_mask=None):
        return SimpleNamespace(logits=self.projection(self.embedding(input_ids)))


class SelfTrainingTests(unittest.TestCase):
    def exercise(self, minimum_improvement):
        torch.manual_seed(4)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = TinyModel()
            adapters = {'projection': model.projection}
            manifest = {'version': 1, 'model_family': 'hf-causal-lm-dense-lora',
                        'base_model': {'source': 'tiny-offline', 'model_type': 'tiny'}}
            bundle = root / 'tiny.nram'
            before = adapter_tensors(adapters)
            save_bundle(bundle, manifest, before)
            for name, question in [('train', 'train-only question'), ('validation', 'independent question'),
                                   ('guardrail', 'regression question')]:
                (root / (name + '.jsonl')).write_text(json.dumps({'prompt': question, 'completion': 'target'}) + '\n')
            args = argparse.Namespace(bundle=bundle, train=root / 'train.jsonl',
                validation=root / 'validation.jsonl', guardrail=root / 'guardrail.jsonl',
                personal_validation=None, runtime_traces=None, model=None, tokenizer=None,
                local_files_only=True, trust_remote_code=False, seed=4, device='cpu', threads=1,
                batch_size=2, max_length=64, adaptive_target_fraction=0.6, epochs=4,
                learning_rate=0.05, weight_decay=0, min_improvement=minimum_improvement,
                max_guardrail_drift=0.05, min_first_token_rank_improvement=0,
                min_behavior_accuracy=0.75, self_knowledge=True, self_analysis=True,
                chl_replay_limit=0, specialization='general')
            with patch('nram_evolve_generic.load_nram_model', return_value=(copy.deepcopy(manifest), model, adapters)), \
                 patch('nram_evolve_generic.load_tokenizer', return_value=TinyTokenizer()), \
                 patch('nram_evolve_generic.EpisodicMemory'), \
                 patch('nram_evolve_generic.request_proposal', return_value={'verified': False, 'text': 'Test proposal', 'applied_to_optimizer': False}) as propose, \
                 redirect_stdout(io.StringIO()):
                report = run(args)
            saved, tensors = load_bundle(bundle)
            propose.assert_called_once()
            self.assertGreater(len(saved['self_knowledge']['sources']), 5)
            self.assertIn('weight_inspection_before', saved['self_knowledge'])
            self.assertTrue((root / 'tiny-analysis/preflight.json').exists())
            self.assertTrue(saved['self_knowledge']['weight_inspection_after']['all_finite'])
            return report, before, tensors, saved

    def test_accepted_candidate_embeds_code_and_commits_real_gradient_update(self):
        report, before, after, saved = self.exercise(1e-5)
        self.assertTrue(report['accepted'])
        self.assertLess(report['validation_nll_after'], report['validation_nll_before'])
        self.assertTrue(any(not torch.equal(before[key], after[key]) for key in before))
        self.assertEqual(saved['version'], 2)

    def test_rejected_candidate_preserves_original_tensors(self):
        report, before, after, saved = self.exercise(1e6)
        self.assertFalse(report['accepted'])
        self.assertTrue(all(torch.equal(before[key], after[key]) for key in before))
        self.assertEqual(saved['version'], 1)
        self.assertFalse(saved['self_knowledge']['candidate_accepted'])

    def test_nonfinite_tensor_is_identified(self):
        model = TinyModel()
        with torch.no_grad():
            model.projection.lora_B[0, 0] = float('nan')
        self.assertFalse(inspect_adapters({'projection': model.projection})['all_finite'])

    def test_nonfinite_loss_stops_before_optimizer_step(self):
        model = TinyModel()
        with torch.no_grad():
            model.projection.lora_B.fill_(float('nan'))
        parameters = [model.projection.lora_A, model.projection.lora_B]
        optimizer = torch.optim.AdamW(parameters)
        step = Mock(wraps=optimizer.step)
        optimizer.step = step
        with self.assertRaisesRegex(ValueError, 'Non-finite training loss'):
            train_epoch(model, TinyTokenizer(), [{'input_ids': [1, 1], 'labels': [-100, 1]}],
                        optimizer, torch.device('cpu'), 1, {'projection': model.projection}, parameters)
        step.assert_not_called()
