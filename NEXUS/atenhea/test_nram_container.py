import tempfile
import unittest
from pathlib import Path

import torch

from nram_container import NRAMContainerError, load_bundle, save_bundle
from nram_evolve import LoRAConv1D
from transformers.pytorch_utils import Conv1D


class NRAMContainerTests(unittest.TestCase):
    def test_safe_tensor_bundle_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.nram"
            manifest = {"version": 3, "graph": ["ENCODE", "LEARN", "COMMIT"]}
            tensors = {"layer.lora_A": torch.arange(12, dtype=torch.float32).reshape(3, 4)}
            save_bundle(path, manifest, tensors)
            loaded_manifest, loaded_tensors = load_bundle(path)
            self.assertEqual(loaded_manifest["version"], 3)
            self.assertTrue(torch.equal(tensors["layer.lora_A"], loaded_tensors["layer.lora_A"]))

    def test_corrupted_tensor_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.nram"
            save_bundle(path, {"version": 1}, {"x": torch.tensor([1.0, 2.0])})
            raw = bytearray(path.read_bytes())
            raw[-1] ^= 1
            path.write_bytes(raw)
            with self.assertRaises(NRAMContainerError):
                load_bundle(path)

    def test_lora_zero_init_preserves_base_output(self):
        torch.manual_seed(11)
        base = Conv1D(12, 8)
        wrapped = LoRAConv1D(base, rank=2, alpha=4)
        inputs = torch.randn(2, 5, 8)
        with torch.no_grad():
            self.assertTrue(torch.equal(base(inputs), wrapped(inputs)))


if __name__ == "__main__":
    unittest.main()
