#!/usr/bin/env python3
"""Replay recorded expert routes to screen cache/prefetch policies, without model weights.

Reads complete immediately in the simulator: hit/miss estimates are NOT latency
predictions. Validate candidates in the actual streaming runtime before promotion.
"""
import argparse
from collections import OrderedDict
import json
from itertools import islice
from pathlib import Path


class CacheReplay:
    def __init__(self, header, policy='original', depth=10):
        self.header, self.policy, self.depth = header, policy, depth
        self.ne = header['experts_per_layer']
        self.queues = [OrderedDict() for _ in header['class_slots']]
        self.pinned = set()
        self.frequency = {}
        self.windows = 0
        self.frequency_scan = 64
        self.lookups = self.misses = self.hits = 0
        self.prefetch_reads = self.prefetch_used = self.prefetch_evicted_unused = 0
        self.required_bytes = self.prefetch_bytes = 0
        # Original warm list is MRU-first; OrderedDict is LRU-first.
        for key in reversed(header['warm']):
            self.queues[self.cls(key)][key] = False

    def cls(self, key):
        return self.header['layer_class'][key // self.ne]

    def touch(self, key):
        self.queues[self.cls(key)].move_to_end(key)

    def admit(self, key, speculative):
        ci = self.cls(key)
        queue = self.queues[ci]
        if len(queue) >= self.header['class_slots'][ci]:
            available = (k for k in queue if k not in self.pinned)
            if self.policy == 'frequency':
                available = islice(available, self.frequency_scan)
                victim = min(available, key=lambda k: self.frequency.get(k, 0), default=None)
            else:
                victim = next(iter(available), None)
            if victim is None:
                return False
            was_prefetch = queue.pop(victim)
            self.prefetch_evicted_unused += int(was_prefetch)
        queue[key] = speculative
        if speculative and self.policy in {'demand', 'frequency'}:
            queue.move_to_end(key, last=False)
        return True

    def event(self, event):
        kind = event['kind']
        if kind not in {'route', 'prefetch'}:
            return
        keys = [event['layer'] * self.ne + e for e in event['ids']]
        if kind == 'route':
            if self.policy == 'frequency':
                if event['layer'] == 0:
                    self.windows += 1
                    if self.windows % 64 == 0:
                        self.frequency = {k:v//2 for k,v in self.frequency.items() if v//2}
                for key in keys:
                    self.frequency[key] = min(65535, self.frequency.get(key, 0) + 1)
            self.pinned = {k for k in keys if k in self.queues[self.cls(k)]}
            for key in keys:
                self.lookups += 1
                queue = self.queues[self.cls(key)]
                if key in queue:
                    self.hits += 1
                    self.prefetch_used += int(queue[key])
                    queue[key] = False
                    self.touch(key)
                else:
                    self.misses += 1
                    self.required_bytes += self.header['expert_bytes'][event['layer']]
                    if not self.admit(key, False):
                        raise ValueError('Cache cannot hold an active expert set')
                self.pinned.add(key)
        else:
            # T=1 is the single-row path. Multi-row prompt warmup remains unchanged.
            if event['tokens'] == 1:
                keys = keys[:self.depth]
            for key in keys:
                if key in self.queues[self.cls(key)]:
                    if self.policy == 'original':
                        self.touch(key)
                    continue
                if not self.admit(key, True):
                    if self.policy == 'frequency':
                        continue
                    break
                self.prefetch_reads += 1
                self.prefetch_bytes += self.header['expert_bytes'][event['layer']]
                self.pinned.add(key)

    def report(self):
        return {'policy': self.policy, 'depth_single_row': self.depth,
                'lookups': self.lookups, 'required_misses': self.misses,
                'hit_rate_instant_reads': self.hits / max(self.lookups, 1),
                'required_read_gb': self.required_bytes / 1e9,
                'prefetch_read_gb': self.prefetch_bytes / 1e9,
                'total_read_gb': (self.required_bytes + self.prefetch_bytes) / 1e9,
                'prefetch_reads': self.prefetch_reads, 'prefetch_used': self.prefetch_used,
                'prefetch_evicted_unused': self.prefetch_evicted_unused}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('trace', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    events = [json.loads(line) for line in args.trace.read_text().splitlines()]
    if not events or events[0].get('kind') != 'header':
        ap.error('Missing trace header')
    reports = []
    for policy in ['original', 'demand', 'frequency']:
        for depth in [0, 2, 4, 6, 8, 10]:
            replay = CacheReplay(events[0], policy, depth)
            for event in events[1:]:
                replay.event(event)
            reports.append(replay.report())
    result = {'trace': str(args.trace), 'candidates': sorted(reports, key=lambda r: r['total_read_gb']),
              'limitations': 'Instant reads, original=Q2_0 MRU prefetch. Does not model async queues, read latency, thermal state, or changing routes. Screen candidates only; real benchmarks are required.'}
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text)
    print(text)


if __name__ == '__main__':
    main()
