import json
import tempfile
import unittest
from pathlib import Path

from runtime_attribution import build_runtime_activation_profile


class RuntimeAttributionTests(unittest.TestCase):
    def test_feedback_contrast_prioritizes_layers_seen_in_bad_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.jsonl"
            traces = []
            rows = []
            for index in range(3):
                trace_id = f"bad-{index}"
                traces.append({
                    "trace_id": trace_id,
                    "backend": "llama.cpp-gguf",
                    "callback_events": 16,
                    "layers": [
                        {"layer": 0, "output_rms": 1.0},
                        {"layer": 1, "output_rms": 3.0},
                        {"layer": 2, "output_rms": 2.0},
                    ],
                })
                rows.append({"runtime_trace_id": trace_id, "runtime_feedback": "bad_corrected"})
            traces.append({
                "trace_id": "good-0",
                "backend": "llama.cpp-gguf",
                "callback_events": 16,
                "layers": [
                    {"layer": 0, "output_rms": 3.0},
                    {"layer": 1, "output_rms": 1.0},
                    {"layer": 2, "output_rms": 1.0},
                ],
            })
            rows.append({"runtime_trace_id": "good-0", "runtime_feedback": "good"})
            path.write_text("".join(json.dumps(row) + "\n" for row in traces), encoding="utf-8")

            profile = build_runtime_activation_profile(path, rows)

            self.assertTrue(profile["enabled"])
            self.assertEqual(profile["matched_bad_corrections"], 3)
            self.assertEqual(profile["matched_good_examples"], 1)
            self.assertEqual(profile["comparison"], "bad_minus_good_relative_layer_rms")
            self.assertGreater(profile["layer_scores"]["1"], profile["layer_scores"].get("2", 0.0))

    def test_fewer_than_three_bad_corrections_cannot_steer_training(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traces.jsonl"
            rows = []
            traces = []
            for index in range(2):
                trace_id = f"bad-{index}"
                rows.append({"runtime_trace_id": trace_id, "runtime_feedback": "bad_corrected"})
                traces.append({"trace_id": trace_id, "backend": "llama.cpp-gguf",
                               "callback_events": 2,
                               "layers": [{"layer": 0, "output_rms": 2.0},
                                          {"layer": 1, "output_rms": 1.0}]})
            path.write_text("".join(json.dumps(row) + "\n" for row in traces), encoding="utf-8")

            profile = build_runtime_activation_profile(path, rows)

            self.assertFalse(profile["enabled"])
            self.assertEqual(profile["reason"], "insufficient_bad_corrections")


if __name__ == "__main__":
    unittest.main()
