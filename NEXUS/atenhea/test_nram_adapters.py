"""Per-request .nram adapter selection: verification, scoped swap and restore.

Run from this directory: python3 -m unittest test_nram_adapters -v
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import torch

from micro_extensions import MicroExtensions, bank_tensors
from nram_adapters import MODEL_FAMILY, AdapterError, AdapterSlot
from nram_container import save_bundle

HIDDEN, RANK, EXPERTS = 8, 2, 2
MODULE = "layers.0.mlp"


def extension_manifest(base="base-sha"):
    return {"base_weights_sha256": base,
            "micro_extensions": {"module": MODULE, "hidden_size": HIDDEN,
                                 "rank": RANK, "experts": EXPERTS}}


def write_adapter(folder: Path, seed: int, base="base-sha", shape=(HIDDEN, RANK, EXPERTS)) -> str:
    torch.manual_seed(seed)
    bank = MicroExtensions(*shape)
    with torch.no_grad():
        for expert in bank.experts:
            expert.up.weight.normal_(0, 0.5)
    manifest = {"model_family": MODEL_FAMILY, "base_weights_sha256": base, "version": seed,
                "micro_extensions": {"module": MODULE, "hidden_size": shape[0],
                                     "rank": shape[1], "experts": shape[2]}}
    path = folder / f"pending-{seed}.nram"
    save_bundle(path, manifest, bank_tensors(bank))
    raw = path.read_bytes()
    adapter_id = hashlib.sha256(raw).hexdigest()
    path.rename(folder / f"{adapter_id}.nram")
    return adapter_id


class AdapterSlotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        torch.manual_seed(0)
        self.bank = MicroExtensions(HIDDEN, RANK, EXPERTS)  # up projections start at zero
        self.slot = AdapterSlot(self.bank, extension_manifest(), self.folder)
        self.x = torch.randn(3, HIDDEN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scoped_selection_changes_output_and_restores_slot(self):
        adapter_id = write_adapter(self.folder, seed=1)
        before = self.bank(self.x).detach().clone()
        with self.slot.applied(adapter_id):
            during = self.bank(self.x).detach().clone()
        after = self.bank(self.x).detach().clone()
        self.assertFalse(torch.allclose(before, during))
        self.assertTrue(torch.equal(before, after))

    def test_restores_slot_when_generation_raises(self):
        adapter_id = write_adapter(self.folder, seed=2)
        before = self.bank(self.x).detach().clone()
        with self.assertRaises(RuntimeError):
            with self.slot.applied(adapter_id):
                raise RuntimeError("generation failed")
        self.assertTrue(torch.equal(before, self.bank(self.x).detach()))

    def test_lists_installed_adapters(self):
        adapter_id = write_adapter(self.folder, seed=3)
        self.assertEqual(self.slot.installed(), [adapter_id])

    def test_rejects_malformed_or_path_like_ids(self):
        for bad in ("../secret", "A" * 64, "", None, 7):
            with self.subTest(bad=bad), self.assertRaisesRegex(AdapterError, "SHA-256"):
                with self.slot.applied(bad):
                    pass

    def test_rejects_unknown_adapter(self):
        with self.assertRaisesRegex(AdapterError, "not installed"):
            with self.slot.applied("0" * 64):
                pass

    def test_rejects_bytes_that_do_not_match_id(self):
        adapter_id = write_adapter(self.folder, seed=4)
        path = self.folder / f"{adapter_id}.nram"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(bytes(data))
        with self.assertRaisesRegex(AdapterError, "do not match its id"):
            with self.slot.applied(adapter_id):
                pass

    def test_rejects_adapter_for_another_base_checkpoint(self):
        adapter_id = write_adapter(self.folder, seed=5, base="other-base")
        with self.assertRaisesRegex(AdapterError, "different base checkpoint"):
            with self.slot.applied(adapter_id):
                pass

    def test_rejects_adapter_with_different_shape(self):
        adapter_id = write_adapter(self.folder, seed=6, shape=(HIDDEN, RANK + 1, EXPERTS))
        with self.assertRaisesRegex(AdapterError, "shape"):
            with self.slot.applied(adapter_id):
                pass


if __name__ == "__main__":
    unittest.main()
