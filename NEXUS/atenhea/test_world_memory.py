import tempfile
from pathlib import Path
import unittest
from world_memory import WorldMemory


class WorldMemoryTests(unittest.TestCase):
    def test_polarity_conflicts_are_preserved_and_excluded_from_training(self):
        with tempfile.TemporaryDirectory() as temp:
            memory=WorldMemory(Path(temp)/'world.sqlite')
            positive=memory.add('Atlas','usa','PostgreSQL',source='user-1',verified=True)
            negative=memory.add('Atlas','usa','PostgreSQL',polarity='negative',source='user-2',verified=True)
            self.assertEqual(len(memory.records()),2)
            self.assertTrue(all(row['contradiction'] for row in memory.records()))
            self.assertEqual(memory.training_rows(),[])
            memory.retire(positive)
            rows=memory.training_rows()
            self.assertEqual(len(rows),1)
            self.assertIn('negative',rows[0]['completion'])
            self.assertIn('PostgreSQL',memory.context('Atlas PostgreSQL'))

    def test_unverified_facts_and_undated_events_do_not_become_training_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            memory=WorldMemory(Path(temp)/'world.sqlite')
            memory.add('Atlas','usa','Redis',source='model-output')
            self.assertEqual(memory.training_rows(),[])
            self.assertEqual(memory.context('Redis'),'')
            with self.assertRaises(ValueError):
                memory.add('Atlas','se inició','despliegue',kind='event',source='user')
            memory.add('Atlas','se inició','despliegue',kind='event',event_at='2026-10-17',source='user',verified=True)
            self.assertIn('2026-10-17',memory.training_rows()[0]['completion'])
