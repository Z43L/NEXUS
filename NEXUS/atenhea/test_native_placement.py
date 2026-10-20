import unittest
import torch
from native_placement import place_native
from test_micro_extensions import MicroExtensionTests

class PlacementTests(unittest.TestCase):
    def test_cpu_path_preserves_weights_parameter_names_and_logits(self):
        model,_=MicroExtensionTests().fixture()
        ids=torch.tensor([[1,2,3]])
        with torch.inference_mode():before=model(ids).logits.clone()
        names=set(dict(model.named_parameters()))
        report=place_native(model,'cpu')
        self.assertEqual(report['mode'],'single_device')
        self.assertEqual(set(dict(model.named_parameters())),names)
        with torch.inference_mode():torch.testing.assert_close(model(ids).logits,before)
    @unittest.skipUnless(torch.backends.mps.is_available(),'Metal unavailable')
    def test_metal_lookup_is_cpu_while_outputs_match_full_metal(self):
        model,_=MicroExtensionTests().fixture()
        for p in model.parameters():p.requires_grad_(False)
        ids=torch.tensor([[1,2,3]])
        with torch.inference_mode():expected=model(ids).logits.clone()
        names=set(dict(model.named_parameters()))
        report=place_native(model,'mps')
        lookup=model.model.embed_tokens_per_layer
        self.assertEqual(lookup.weight.device.type,'cpu')
        self.assertEqual(model.model.layers[0].mlp.gate_proj.weight.device.type,'mps')
        self.assertGreater(report['cpu_lookup_bytes'],0)
        self.assertEqual(set(dict(model.named_parameters())),names)
        with torch.inference_mode():actual=model(ids.to('mps')).logits.cpu()
        torch.testing.assert_close(actual,expected,atol=2e-5,rtol=2e-4)
