"""Model catalog routing, lazy loading, LRU eviction and lease safety.

Pure Python: the hub takes an engine factory, so these tests need no torch.
Run from this directory: python3 -m unittest test_model_hub -v
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from model_hub import ModelHub, load_catalog


class FakeEngine:
    instances: list["FakeEngine"] = []

    def __init__(self, name, bundle):
        self.name, self.bundle, self.closed = name, bundle, False
        FakeEngine.instances.append(self)

    def health(self):
        return {"model": self.name, "bundle": self.bundle}

    def close(self):
        self.closed = True


def make_hub(max_resident=1, catalog=None):
    FakeEngine.instances = []
    catalog = catalog or {"gemma4-e2b:latest": "/b/gemma.nram", "qwen-3b": "/b/qwen.nram"}
    return ModelHub(catalog, FakeEngine, max_resident=max_resident)


class RoutingTests(unittest.TestCase):
    def test_empty_request_selects_first_catalog_entry(self):
        hub = make_hub()
        self.assertEqual(hub.resolve(None), "gemma4-e2b:latest")
        self.assertEqual(hub.default, "gemma4-e2b:latest")

    def test_exact_and_latest_alias_resolve(self):
        hub = make_hub()
        self.assertEqual(hub.resolve("qwen-3b"), "qwen-3b")
        self.assertEqual(hub.resolve("qwen-3b:latest"), "qwen-3b")
        self.assertEqual(hub.resolve("gemma4-e2b"), "gemma4-e2b:latest")

    def test_unknown_model_fails_closed(self):
        hub = make_hub()
        with self.assertRaisesRegex(ValueError, "unknown model"):
            hub.resolve("llama-70b")
        with self.assertRaisesRegex(ValueError, "must be a string"):
            hub.resolve(7)

    def test_names_lists_catalog_not_resident_engines(self):
        hub = make_hub()
        self.assertEqual(hub.names(), ["gemma4-e2b:latest", "qwen-3b"])
        self.assertEqual(FakeEngine.instances, [])

    def test_empty_catalog_is_rejected(self):
        with self.assertRaises(ValueError):
            ModelHub({}, FakeEngine)


class ResidencyTests(unittest.TestCase):
    def test_engine_loads_lazily_and_is_reused(self):
        hub = make_hub(max_resident=2)
        with hub.lease("qwen-3b") as first:
            pass
        with hub.lease("qwen-3b") as second:
            pass
        self.assertIs(first, second)
        self.assertEqual(len(FakeEngine.instances), 1)

    def test_least_recently_used_idle_engine_is_released(self):
        hub = make_hub(max_resident=1)
        with hub.lease("gemma4-e2b") as gemma:
            pass
        with hub.lease("qwen-3b") as qwen:
            self.assertIsNot(gemma, qwen)
        self.assertTrue(gemma.closed)
        self.assertFalse(qwen.closed)
        self.assertEqual(hub.health()["resident_models"], ["qwen-3b"])

    def test_leased_engine_is_never_released(self):
        hub = make_hub(max_resident=1)
        with hub.lease("gemma4-e2b") as gemma:
            with self.assertRaisesRegex(ValueError, "in use"):
                with hub.lease("qwen-3b"):
                    pass
            self.assertFalse(gemma.closed)
        with hub.lease("qwen-3b"):
            pass
        self.assertTrue(gemma.closed)

    def test_preload_loads_default_model(self):
        hub = make_hub()
        hub.preload()
        self.assertEqual(hub.health()["resident_models"], ["gemma4-e2b:latest"])

    def test_close_releases_everything(self):
        hub = make_hub(max_resident=2)
        with hub.lease("gemma4-e2b") as gemma, hub.lease("qwen-3b") as qwen:
            pass
        hub.close()
        self.assertTrue(gemma.closed and qwen.closed)
        self.assertEqual(hub.health()["resident_models"], [])

    def test_health_reports_catalog_and_residency(self):
        hub = make_hub(max_resident=2)
        with hub.lease("qwen-3b"):
            pass
        info = hub.health()
        self.assertEqual(info["models"], ["gemma4-e2b:latest", "qwen-3b"])
        self.assertEqual(info["default_model"], "gemma4-e2b:latest")
        self.assertEqual(info["model"], "qwen-3b")
        self.assertEqual(info["max_resident_models"], 2)


class CatalogFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        path = self.folder / "models.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_relative_bundle_paths_resolve_against_catalog_file(self):
        path = self.write({"models": [{"name": "a", "bundle": "bundles/a.nram"},
                                      {"name": "b", "bundle": "/abs/b.nram"}]})
        catalog = load_catalog(path)
        self.assertEqual(list(catalog), ["a", "b"])
        self.assertEqual(catalog["a"], str(self.folder / "bundles" / "a.nram"))
        self.assertEqual(catalog["b"], "/abs/b.nram")

    def test_rejects_malformed_catalogs(self):
        bad = [{"models": []}, {"nope": 1},
               {"models": [{"name": "a"}]},
               {"models": [{"name": "a", "bundle": "x"}, {"name": "a", "bundle": "y"}]}]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                load_catalog(self.write(data))


if __name__ == "__main__":
    unittest.main()
