import unittest

from nram_evolve_generic import select_targets


class AdaptiveTargetSelectionTests(unittest.TestCase):
    def test_initial_feedback_profile_selects_highest_scoring_layers(self):
        adapters = {
            f"model.layers.{layer}.self_attn.q_proj": object()
            for layer in range(4)
        }

        selected, method = select_targets(
            adapters, {}, 0.5, {0: 0.1, 1: 0.9, 2: 0.6, 3: 0.2},
        )

        self.assertEqual(selected, {
            "model.layers.1.self_attn.q_proj",
            "model.layers.2.self_attn.q_proj",
        })
        self.assertEqual(method, "feedback_labeled_gguf_activation_initial_profile")

    def test_existing_gradient_scores_are_modulated_by_feedback_prior(self):
        adapters = {
            f"model.layers.{layer}.self_attn.q_proj": object()
            for layer in range(4)
        }
        manifest = {"inference_attribution": {"layers": [
            {"module": f"model.layers.{layer}.self_attn.q_proj", "score": 1.0}
            for layer in range(4)
        ]}}

        selected, method = select_targets(
            adapters, manifest, 0.5, {0: 0.0, 1: 0.0, 2: 1.0, 3: 0.0},
        )

        self.assertIn("model.layers.2.self_attn.q_proj", selected)
        self.assertEqual(len(selected), 2)
        self.assertEqual(method, "previous_gradient_plus_feedback_labeled_gguf_activation")


if __name__ == "__main__":
    unittest.main()
