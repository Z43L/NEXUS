import tempfile
import unittest
from pathlib import Path

from nra_runtime import NRAMError, initial_state, load_nram, predict, save_nram, try_commit


class NRAMRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "model.nram"
        save_nram(self.path, initial_state())

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_and_target_metadata(self):
        state = load_nram(self.path)
        self.assertEqual(state["model"]["target_model"], "distilbert/distilgpt2")
        self.assertEqual(state["model"]["target_model_params"], 82_000_000)
        self.assertEqual(state["version"], 0)

    def test_validation_improvement_is_persistently_committed(self):
        result = try_commit(self.path, [(1, 2), (2, 4)], [(3, 6), (4, 8)])
        state = load_nram(self.path)
        self.assertTrue(result["accepted"])
        self.assertLess(result["after"], result["before"])
        self.assertEqual(state["version"], 1)
        self.assertAlmostEqual(predict(state, 3), 3.0)
        self.assertEqual(len(state["journal"]), 1)

    def test_regression_is_rejected_without_changing_file(self):
        before = self.path.read_bytes()
        result = try_commit(self.path, [(1, -1), (2, -2)], [(3, 6), (4, 8)])
        self.assertFalse(result["accepted"])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(load_nram(self.path)["version"], 0)

    def test_checksum_detects_corruption(self):
        raw = bytearray(self.path.read_bytes())
        raw[-2] ^= 1
        self.path.write_bytes(raw)
        with self.assertRaises(NRAMError):
            load_nram(self.path)

    def test_bad_magic_is_rejected(self):
        self.path.write_bytes(b"not-nram")
        with self.assertRaises(NRAMError):
            load_nram(self.path)


if __name__ == "__main__":
    unittest.main()
