import unittest
import torch
from prefix_cache import PrefixCache
from test_micro_extensions import MicroExtensionTests

class ExactPrefixTests(unittest.TestCase):
    def setUp(self):
        self.model,_=MicroExtensionTests().fixture()
        self.model.config.max_position_embeddings=256
        self.encoded={'input_ids':torch.tensor([[1,2,3,4]*20]),'attention_mask':torch.ones(1,80,dtype=torch.long)}
    def generate(self,past=None):
        args={'past_key_values':past} if past is not None else {}
        return self.model.generate(**self.encoded,**args,max_new_tokens=3,do_sample=False,
            use_cache=True,pad_token_id=0,eos_token_id=15)
    def test_greedy_output_is_unchanged_and_snapshot_survives_multiple_calls(self):
        cache=PrefixCache(max_tokens=64)
        with torch.inference_mode():
            expected=self.generate()
            first,info=cache.prepare(self.model,self.encoded,64,1)
            self.assertFalse(info['hit'])
            torch.testing.assert_close(self.generate(first),expected)
            self.assertEqual(cache.snapshot.get_seq_length(),64)
            second,info=cache.prepare(self.model,self.encoded,64,1)
            self.assertTrue(info['hit'])
            torch.testing.assert_close(self.generate(second),expected)
            self.assertEqual(cache.snapshot.get_seq_length(),64)
    def test_changed_prefix_or_weight_version_invalidates_the_snapshot(self):
        cache=PrefixCache(max_tokens=64)
        cache.prepare(self.model,self.encoded,64,1)
        changed={**self.encoded,'input_ids':self.encoded['input_ids'].clone()}
        changed['input_ids'][0,2]=5
        _,info=cache.prepare(self.model,changed,64,1);self.assertFalse(info['hit'])
        _,info=cache.prepare(self.model,changed,64,2);self.assertFalse(info['hit'])
    def test_memory_limit_prevents_retaining_an_oversized_snapshot(self):
        cache=PrefixCache(max_tokens=64,max_bytes=1)
        working,info=cache.prepare(self.model,self.encoded,64,1)
        self.assertIsNotNone(working);self.assertFalse(info['retained'])
        self.assertIsNone(cache.snapshot);self.assertEqual(cache.status()['bytes'],0)
    def test_sliding_cache_is_not_cropped_or_reused_after_its_snapshot_is_mutated(self):
        from transformers import Gemma4ForCausalLM
        config=self.model.config
        config.layer_types=['sliding_attention','full_attention'];config.sliding_window=16
        config.rope_parameters={'sliding_attention':{'rope_type':'default','rope_theta':10000.0},
                                'full_attention':{'rope_type':'default','rope_theta':10000.0}}
        self.model=Gemma4ForCausalLM(config).eval()
        cache=PrefixCache(max_tokens=64)
        with torch.inference_mode():
            expected=self.generate()
            for _ in range(2):
                past,_=cache.prepare(self.model,self.encoded,64,1)
                torch.testing.assert_close(self.generate(past),expected)
                self.assertEqual(cache.snapshot.get_seq_length(),64)

    def test_shared_kv_layers_match_uncached_generation(self):
        from transformers import Gemma4ForCausalLM
        config=self.model.config
        config.num_hidden_layers=3;config.num_kv_shared_layers=1
        config.layer_types=['sliding_attention','full_attention','sliding_attention']
        config.sliding_window=16
        config.rope_parameters={'sliding_attention':{'rope_type':'default','rope_theta':10000.0},
                                'full_attention':{'rope_type':'default','rope_theta':10000.0}}
        self.model=Gemma4ForCausalLM(config).eval()
        cache=PrefixCache(max_tokens=64)
        with torch.inference_mode():
            expected=self.generate()
            for _ in range(2):
                past,_=cache.prepare(self.model,self.encoded,64,1)
                torch.testing.assert_close(self.generate(past),expected)
