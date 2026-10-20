import unittest
from tools.replay_moe_cache import CacheReplay


def header(capacity=3):
    return {'experts_per_layer': 16, 'class_slots': [capacity],
            'layer_class': [0], 'expert_bytes': [1024], 'warm': list(range(capacity))}


def event(kind, ids, tokens=1, layer=0):
    return {'kind': kind, 'layer': layer, 'tokens': tokens, 'ids': ids}


class CacheReplayTests(unittest.TestCase):
    def test_speculative_admission_does_not_displace_reused_experts(self):
        trace = [event('route', [0]), event('prefetch', [3]), event('route', [1]),
                 event('prefetch', [4]), event('route', [0])]
        original, demand = CacheReplay(header()), CacheReplay(header(), 'demand')
        for e in trace:
            original.event(e)
            demand.event(e)
        self.assertEqual(original.misses, 1)
        self.assertEqual(demand.misses, 0)
        self.assertEqual(demand.lookups, original.lookups)

    def test_frequency_retains_recurrent_expert_over_older_single_use(self):
        trace = [event('route', [0]), event('route', [0]), event('route', [0]),
                 event('route', [1]), event('route', [2]), event('prefetch', [3]), event('route', [0])]
        original, frequency = CacheReplay(header()), CacheReplay(header(), 'frequency')
        for e in trace:
            original.event(e)
            frequency.event(e)
        self.assertEqual(original.misses, 1)
        self.assertEqual(frequency.misses, 0)

    def test_frequency_ages_between_windows(self):
        replay = CacheReplay(header(), 'frequency')
        replay.frequency[0] = 8
        replay.windows = 63
        replay.event(event('route', [1]))
        self.assertEqual(replay.frequency[0], 4)
        self.assertEqual(replay.frequency[1], 1)

    def test_active_experts_cannot_be_evicted_by_prefetch(self):
        replay = CacheReplay(header(2))
        replay.event(event('route', [0, 1]))
        replay.event(event('prefetch', [2]))
        self.assertEqual(set(replay.queues[0]), {0, 1})
        self.assertEqual(replay.prefetch_reads, 0)

    def test_zero_prefetch_keeps_demand_loading_exact(self):
        replay = CacheReplay(header(2), depth=0)
        replay.event(event('prefetch', [3]))
        replay.event(event('route', [3]))
        self.assertEqual(replay.prefetch_reads, 0)
        self.assertEqual(replay.misses, 1)
        self.assertEqual(replay.required_bytes, 1024)

    def test_size_classes_have_independent_capacity(self):
        h = {'experts_per_layer': 16, 'class_slots': [1, 1],
             'layer_class': [0, 1], 'expert_bytes': [1024, 2048], 'warm': [0, 16]}
        replay = CacheReplay(h)
        replay.event(event('route', [1], layer=0))
        self.assertEqual(set(replay.queues[1]), {16})
        replay.event(event('route', [0], layer=1))
        self.assertEqual(replay.hits, 1)
        self.assertEqual(replay.required_bytes, 1024)


if __name__ == '__main__':
    unittest.main()
