import unittest

import torch
from torch import nn

from nram_generic import LoRAProjection, discover_targets, merge_adapters, module_layout


class Conv1D(nn.Module):
    """Test double for Transformers GPT-2 Conv1D's [in,out] storage."""
    def __init__(self, in_features, out_features):
        super().__init__()
        self.weight = nn.Parameter(torch.randn(in_features, out_features))
        self.bias = nn.Parameter(torch.randn(out_features))
        self.nf = out_features

    def forward(self, x):
        return x @ self.weight + self.bias


class Attention(nn.Module):
    def __init__(self):
        super().__init__()
        self.q_proj = nn.Linear(4, 4)
        self.k_proj = nn.Linear(4, 4)


class MLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.down_proj = nn.Linear(4, 4)


class Block(nn.Module):
    def __init__(self):
        super().__init__()
        self.self_attn = Attention()
        self.mlp = MLP()


class TinyLlamaLike(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.ModuleList([Block(), Block()])
        self.lm_head = nn.Linear(4, 8)


class GenericNRAMTests(unittest.TestCase):
    def test_auto_discovery_selects_final_dense_block_projections(self):
        model = TinyLlamaLike()
        selected = discover_targets(model, last_k_blocks=1)
        self.assertEqual(set(selected), {
            "layers.1.self_attn.q_proj",
            "layers.1.self_attn.k_proj",
            "layers.1.mlp.down_proj",
        })
        self.assertNotIn("lm_head", selected)

    def test_linear_and_conv1d_zero_adapter_is_exact_noop_and_merges(self):
        for base, layout in ((nn.Linear(5, 3), "linear_out_in"),
                             (Conv1D(5, 3), "conv1d_in_out")):
            self.assertEqual(module_layout(base), layout)
            wrapped = LoRAProjection(base, rank=2, alpha=4, layout=layout)
            x = torch.randn(2, 4, 5)
            expected = base(x)
            self.assertTrue(torch.allclose(wrapped(x), expected, atol=1e-6))
            with torch.no_grad():
                wrapped.lora_B.normal_(0, 0.1)
            before = wrapped(x).detach()
            holder = nn.Module()
            holder.proj = wrapped
            merge_adapters(holder, {"proj": wrapped})
            self.assertTrue(torch.allclose(holder.proj(x), before, atol=1e-5))

    def test_explicit_targets_fail_fast_for_unknown_names(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            discover_targets(TinyLlamaLike(), explicit=["layers.99.attn.q_proj"])


if __name__ == "__main__":
    unittest.main()
