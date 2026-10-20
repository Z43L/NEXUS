from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from nra_m.to_lora_jsonl import convert


class LoRADataPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "input.jsonl"
        self.source.write_text("\n".join((
            json.dumps({"split": "train", "example_id": "a", "pair_id": "p", "prompt": "Is it true?", "label": True}),
            json.dumps({"split": "test", "prompt": "Is it false?", "label": False}),
        )) + "\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_converts_boolean_labels_and_filters_split(self):
        output = self.root / "train.jsonl"
        report = convert(self.source, output, "train")
        row = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["examples"], 1)
        self.assertEqual(row["completion"], "YES")
        self.assertEqual(row["pair_id"], "p")

    def test_refuses_to_overwrite_output(self):
        output = self.root / "exists.jsonl"
        output.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            convert(self.source, output)

    def test_rejects_unknown_labels(self):
        self.source.write_text(json.dumps({"prompt": "x", "label": "unknown"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported label"):
            convert(self.source, self.root / "bad.jsonl")


if __name__ == "__main__":
    unittest.main()
