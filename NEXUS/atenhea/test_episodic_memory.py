"""Integration tests against the actual CHL checkout, without loading an LLM."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from episodic_memory import EpisodicMemory


@unittest.skipUnless((os.environ.get('ONRAM_NODE') or shutil.which('node')) and
                     (Path(__file__).parent / 'third_party/chl/src/native.js').exists(),
                     'requires CHL checkout and Node.js')
class EpisodicMemoryTests(unittest.TestCase):
    def test_persistence_context_and_verified_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'episodes.memory'
            memory = EpisodicMemory(path)
            prompt = 'El proyecto Atlas utiliza PostgreSQL para guardar pedidos.'
            memory.remember(prompt, 'Usaremos PostgreSQL para Atlas.', verified=True)
            memory.remember('Respuesta sin revisar sobre Atlas', 'Una respuesta inventada.')
            # Each call starts a separate process, so this also tests disk persistence.
            restored = EpisodicMemory(path)
            result = restored.call('recall', query=prompt, top_k=4)
            self.assertTrue(any(c['payload']['prompt'] == prompt for c in result['candidates']))
            augmented = restored.augment(prompt)
            self.assertIn('<episodic_memory>', augmented)
            self.assertIn('current request takes priority', augmented)
            self.assertTrue(augmented.endswith(prompt))
            output = Path(directory) / 'replay.jsonl'
            self.assertEqual(restored.export(output), 1)
            self.assertEqual(json.loads(output.read_text())['prompt'], prompt)
            self.assertEqual(restored.augment(prompt, max_chars=1), prompt)

    def test_empty_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = EpisodicMemory(Path(directory) / 'empty.memory')
            self.assertEqual(memory.augment('Consulta nueva'), 'Consulta nueva')
            with self.assertRaises(ValueError):
                memory.remember('', 'respuesta')
            with self.assertRaises(ValueError):
                memory.augment('consulta', top_k=0)


if __name__ == '__main__':
    unittest.main()
