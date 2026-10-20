import json
from pathlib import Path
import tempfile
import unittest

import torch
from torch.nn import functional as F
from transformers import Gemma4TextConfig, Gemma4ForCausalLM
from safetensors.torch import save_file

from micro_extensions import MicroExtensions, attach_extension, bank_tensors, load_extension, grow
from micro_training import CachedTail, cache_examples, train_cached, full_vocabulary_nll
from nram_container import save_bundle, load_bundle


class Tokenizer:
    eos_token_id = 0
    pad_token_id = 0
    chat_template = None
    def __call__(self, text, **kwargs):return {'input_ids':[1,1]}


class MicroExtensionTests(unittest.TestCase):
    def fixture(self):
        torch.manual_seed(8)
        config = Gemma4TextConfig(vocab_size=16, vocab_size_per_layer_input=16,
            hidden_size=8, intermediate_size=16, hidden_size_per_layer_input=4,
            num_hidden_layers=2, num_attention_heads=2, num_key_value_heads=1,
            head_dim=4, global_head_dim=4, layer_types=['full_attention','full_attention'],
            num_kv_shared_layers=0, enable_moe_block=False, use_double_wide_mlp=False,
            rope_parameters={'full_attention':{'rope_type':'default','rope_theta':10000.0}},
            max_position_embeddings=32, use_cache=False)
        model = Gemma4ForCausalLM(config).eval()
        for parameter in model.parameters():parameter.requires_grad_(False)
        bank = MicroExtensions(8,2,3)
        for parameter in bank.parameters():parameter.requires_grad_(False)
        attach_extension(model,bank,'model.layers.1.mlp')
        return model,bank

    def test_zero_residual_is_noop_and_router_executes_only_selected_expert(self):
        bank = MicroExtensions(8,2,3)
        bank.force_expert = 1
        x=torch.randn(4,8)
        self.assertTrue(torch.equal(bank(x),torch.zeros_like(x)))
        self.assertEqual(bank.last_counts,[0,4,0])
        for p in bank.parameters():p.requires_grad_(False)
        for p in bank.experts[1].parameters():p.requires_grad_(True)
        for p in bank.router.parameters():p.requires_grad_(True)
        optimizer=torch.optim.AdamW([p for p in bank.parameters() if p.requires_grad],lr=.1)
        before=bank_tensors(bank)
        loss=F.mse_loss(bank(x),torch.ones_like(x))+.1*bank.routing_loss
        loss.backward();optimizer.step()
        after=bank_tensors(bank)
        self.assertTrue(torch.equal(before['experts.0.up.weight'],after['experts.0.up.weight']))
        self.assertFalse(torch.equal(before['experts.1.up.weight'],after['experts.1.up.weight']))

    def test_growth_preserves_existing_output_until_new_expert_is_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);bank=MicroExtensions(8,2,3)
            with torch.no_grad():
                for expert in bank.experts:expert.up.weight.normal_()
            manifest={'model_family':'onram-external-micro-mlp-v1','version':0,
                'micro_extensions':{'hidden_size':8,'rank':2,'experts':3},'journal':[]}
            original=root/'old.nram';save_bundle(original,manifest,bank_tensors(bank))
            grow(original,root/'grown.nram')
            _,grown=load_extension(root/'grown.nram')
            x=torch.randn(5,8)
            torch.testing.assert_close(bank(x),grown(x))
            self.assertFalse(grown.active_mask[3])

    def test_cached_tail_matches_full_gemma_logits(self):
        model,bank=self.fixture()
        tail=CachedTail.from_model(model,'model.layers.1.mlp')
        cache=cache_examples(model,[{'prompt':'a','completion':'b'}],Tokenizer(),'model.layers.1.mlp',bank)
        ids=torch.tensor([[1,1,1,1,0]])
        mask=torch.tensor([False,True,True,True])
        with torch.no_grad():
            expected=model(input_ids=ids,attention_mask=torch.ones_like(ids),use_cache=False).logits[0,:-1][mask]
            actual=tail(cache,bank)
        torch.testing.assert_close(actual,expected,rtol=1e-5,atol=1e-6)
        with torch.no_grad():
            torch.testing.assert_close(full_vocabulary_nll(tail, cache, bank, chunk_size=5),
                F.cross_entropy(actual,cache['labels'],reduction='sum'),rtol=1e-5,atol=1e-6)

    def test_cached_training_updates_only_small_candidate_and_keeps_active_file(self):
        model,bank=self.fixture()
        tail=CachedTail.from_model(model,'model.layers.1.mlp')
        data=cache_examples(model,[{'prompt':'a','completion':'b'}],Tokenizer(),'model.layers.1.mlp',bank)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);cache=root/'cache';cache.mkdir()
            for name in ('train','validation'):save_file(data,cache/(name+'.safetensors'))
            save_file({k:v.contiguous() for k,v in tail.state_dict().items()},cache/'tail.safetensors')
            (cache/'cache.json').write_text(json.dumps({'tail':tail.spec,'base_weights_sha256':'tiny',
                'bundle_sha256':'not-present','module':'model.layers.1.mlp'}))
            active=root/'active.nram'
            manifest={'model_family':'onram-external-micro-mlp-v1','version':0,
                'base_weights_sha256':'tiny','parent_bundle':str(root/'parent.nram'),
                'micro_extensions':{'hidden_size':8,'rank':2,'experts':3,'module':'model.layers.1.mlp'},'journal':[]}
            save_bundle(active,manifest,bank_tensors(bank));original=active.read_bytes()
            report=train_cached(active,cache,root/'candidate.nram',expert=0,epochs=30,
                                tokens_per_batch=3,learning_rate=.05,sampled_vocabulary=16)
            self.assertEqual(active.read_bytes(),original)
            self.assertTrue(report['other_experts_unchanged'])
            self.assertFalse(report['base_model_loaded_during_training'])
            self.assertTrue(report['accepted'])
            self.assertLess(report['validation_nll_after'],report['validation_nll_before'])

class MetalRoutingTests(unittest.TestCase):
    def test_dense_metal_dispatch_matches_sparse_routing(self):
        from micro_extensions import MicroExtensions
        torch.manual_seed(5)
        bank=MicroExtensions(12,3,3)
        # Ensure nonzero residuals so a broken mask cannot pass trivially.
        for expert in bank.experts:
            for param in expert.parameters():param.data.normal_(0,.1)
        features=torch.randn(7,12)
        expected=bank(features)
        logits=bank.router(features).masked_fill(~bank.active_mask,-torch.inf)
        actual=bank.dense_residual(features,logits.softmax(-1),logits.argmax(-1))
        torch.testing.assert_close(actual,expected)
