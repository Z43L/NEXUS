# Apple Silicon SSD streaming: measurements and implementation

Machine: MacBook Air M4, 16 GB unified memory. Date: 2026-10-16.
Base: the local Strata Metal runtime and Qwen3.8-Flash-Next Q2_0. Gemma's
interrupted download remains stopped and is not needed for these measurements.

## Existing data path

Strata already reads quantized experts into anonymous memory wrapped as
`MTLStorageModeShared` with `newBufferWithBytesNoCopy`. Its expert kernels use
those exact bytes. There is no separate CPU-to-GPU staging copy to eliminate.
The contiguous `.experts` layout already puts gate, up and down matrices together.
The GPU signals a shared event after each router; the host resolves cache misses,
waits for reads, updates the shared slot map and releases the GPU. Read-ahead
predicts the following layer's experts while the current layer computes.

## Added native experiment

`native/ssd_metal_bench.mm` compares persistent pread workers (1, 4, 6, 8 threads)
with `MTLIOCommandQueue`, loading 10 experts at a time into the same shared Metal
buffer. A Metal kernel consumes every 32-bit word; checksums are compared against
CPU calculations. Repeated traces expose cache effects. The default disjoint
traces reduce reuse between methods; they cannot guarantee physically cold SSD
reads. pread uses F_NOCACHE and disables readahead; Metal IO's cache policy is
managed by the driver. These are API-path measurements, not raw NAND bandwidth.
GPU-consumption wall time includes CPU command submission and waiting; newer
runs also report the GPU's own timestamp interval separately.

```sh
./onram ssd-bench --batches 48 --rounds 3
```

Median of three disjoint rounds, 48 batches / 480 experts per case:

| Path | Read GB/s | Read + GPU consumer wall GB/s |
|---|---:|---:|
| pread, 1 thread | 1.508 | 1.263 |
| pread, 4 threads | 2.442 | 1.900 |
| pread, 6 threads (upstream default) | 2.552 | 1.983 |
| pread, 8 threads | 2.589 | 1.994 |
| Metal IO, one command buffer per batch | 3.175 | 2.251 |

Read-path throughput: +24.4% over six pread threads. Including the consumer's
submission/wait time: +13.5%. Neither number is an inference speedup.
Raw results: `benchmarks/ssd-metal-m4-disjoint.jsonl`.

## Opt-in runtime patch

`patches/strata-metal-io.patch` changes only the Metal implementation. The normal
pread path remains selected unless the Strata config sets:

```json
"env": { "STRATA_METAL_IO": "metal" }
```

The expert-contiguous file and READ_SPLIT=1 are required; initialization falls
back to pread if unavailable. Once selected, an I/O failure fails the request
rather than publishing an incomplete slot. The shared slot map is updated only
after a completed IO command buffer. Destination ranges are checked.

The first prototype grouped urgent misses only. It preserved response prefixes
but was slower in full generation (4.085 vs 4.473 tokens/s aggregated over four
short requests), so it was not promoted. `benchmarks/strata-ssd-generation-v1.jsonl`
records that unsuccessful version.

The second version also batches background read-ahead and cache warmup. Queued
prefetches can transfer into an urgent batch only before any read starts. Slots
remain pinned during reads; CPU and GPU consume the same quantized weights.
The initial cache fill uses the worker path, avoiding a startup deadlock found
and fixed during development. The installer applies the patch idempotently,
and Strata's source digest triggers rebuilding after installation.

`native/test_metal_io.cpp` exercises the actual no-copy arena path: multiple
source and destination offsets, exact byte comparison, guard regions and
rejection of uninitialized / out-of-bounds requests.

## Real-generation procedure

```sh
python3 tools/bench_strata_ssd.py --rounds 2 --tokens 32 --arena-gb 1
```

ABBA order (pread, Metal IO, Metal IO, pread), two fixed prompts (code and
Spanish explanation), temperature 0, seed 42, identical 1 GB expert arenas,
32-token caps, no MTP, prompt GEMM disabled for this 16 GB Mac. Tail-expert
skipping is explicitly disabled in both modes (`STRATA_ROUTE_TAIL_SKIP=0`),
so the experiment does not purchase speed by skipping experts. Response text,
reported prefill/decode timings, wall time, swap use and memory pressure are
recorded. Servers run on localhost:11438 and their process groups close at the
end. Results are short-workload measurements, not a long-context benchmark.

## Measured second-version generation results

With 1 GB expert arenas, two ABBA rounds and four requests per reader:

| Reader | Aggregate decode tokens/s | Sum of request wall time |
|---|---:|---:|
| pread | 4.390 | 56.149 s |
| Metal IO, urgent + read-ahead batches | 4.814 | 50.524 s |

Decode improved 9.7%; total request wall time fell 10.0%. All eight response
prefixes matched exactly across reader and round for each prompt. No request
increased swap use; the pressure indicator stayed at level 1. These measurements
cover short prompts and responses only. Raw results:
`benchmarks/strata-ssd-generation.jsonl` (filter arena_gb=1.0).

To install/select this optional path from Onram:

```sh
./onram strata-setup --io-backend metal --arena-gb 1 --no-start
./start-strata.sh
# another terminal
./onram launch pi
```

Use `--io-backend pread` to select the original reader. The changes do not
modify CUDA, HIP or SYCL backends, model weights or the macOS wired-memory limit.

## Cache budget result

A follow-up exploratory pair at 2 GB gave pread 5.016 tokens/s, but Metal IO
4.657 tokens/s. With Metal IO the pressure level rose from 1 to 2 and swap use
rose from 1767.88 MB to 1804.38 MB during the code request. It was not selected.
The new profile `models/strata/strata-ssd-fast.json` therefore keeps Metal IO at
1 GB, prefetch 10 and exact expert routing. Launch it with:

```sh
./start-strata-ssd.sh
# another terminal
./onram launch pi
```

This explicit profile does not replace the paused Gemma launch profile or the
normal Strata config. It shares the existing weights. A 2 GB pread arena remains
an interesting candidate, but needs more paired measurements before promotion.
No maximum-performance or long-context claim follows from these short tests.

## Next work, in order

1. Size the resident expert arena from measured total footprint and pressure,
   then compare 1 GB and 2 GB without introducing swap growth. A previous
   automatic arena fell to about 90 MB; a small cache can erase I/O gains.
2. Measure cache hits, bytes per generated token, late / unused prefetches and
   per-layer wait time; optimize saved milliseconds per cached byte instead of
   hit count alone. Separate prompt processing from single-token decoding.
3. Bound speculative reads and prioritize urgent misses. Evaluate prefetch
   depth and cache admission on held-out coding / Spanish traces.
4. Prototype Metal shared-event dependencies between IO and compute queues,
   with double-buffered miss lists, to reduce host handshakes while preserving
   slot lifetimes. Current host waits remain in the correctness baseline.
5. Optimize fused dequantization / expert compute kernels only after profiling
   shows GPU execution is limiting. Reducing an idle kernel's arithmetic cannot
   recover time spent waiting for SSD reads.

Metal IO is documented by Apple under
[Resource loading](https://developer.apple.com/documentation/metal/resource-loading)
and [Load resources faster with Metal 3](https://developer.apple.com/videos/play/wwdc2022/10104/).
Apple describes support for asynchronous resource loading on its unified-memory
architecture; the measured benefit here must still be established by workload.
