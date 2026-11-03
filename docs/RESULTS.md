# First results: 2-core cloud VM (25 Oct 2026)

All numbers: RocksDB 11.8.1 release build, db_bench, the setup document's
configuration, mean of 3 repetitions (± = standard deviation). Full tables are
in `results/tables/`, figures in `results/figures/`, raw logs in `results/raw.zip`.

**Machine.** Cloud VM (KVM), 2 vCPU (Intel Xeon, 2.1 GHz), 7.8 GiB RAM,
virtio disk with ext4 (random 4 KB direct reads: ~36 µs median). Two cores
limit E2 and E3 to 1–2 threads, so contention effects are much weaker than they
would be on a many-core machine. The VM exposes no hardware performance
counters, so "CPU cycles per operation" is reported as CPU time per lookup.
Run-to-run throughput variation: median 3.5 %, max 10.5 %.

## The database after the load

| | |
|---|---|
| SST files | 5,172 (4.80 GiB) |
| keys / data blocks | 10,000,000 / 1,253,338 (8 keys per 4 KB block) |
| index blocks | 22.7 MiB |
| filter blocks | 12.2 MiB |
| index + filter | 34.8 MiB: does not fit in 32 MB, barely fits in 64 MB, fits easily from 128 MB |
| levels (MB) | L0 0.4 · L1 30 · L2 63 · L3 126 · L4 255 · L5 510 · L6 1021 · L7 2048 · L8 868 |
| load | filluniquerandom 334 s, write amplification 19.1 |

The setup document estimates the index at ~60 MB; with RocksDB 11.8.1
(format_version 7, shortened separators) it is 22.7 MiB. Its conclusions still
hold for index + filter together: they do not fit at 32 MB and fit at 128 MB.

A lookup touches on average 4.4 filter blocks, 1.03 index blocks and 1.03 data
blocks. There are 9 levels, but the upper levels cover only part of the key
space, so many lookups skip a level without a filter check.

## E0 — 64 MB cache, 1 thread: `cache_high_pri_pool_ratio` 0 / 0.5 / 1

| | ratio 0 | ratio 0.5 | ratio 1 |
|---|---|---|---|
| LRU index-block miss ratio (uniform) | 18.8 % | 4.9 % | 0.01 % |
| LRU filter-block miss ratio (uniform) | 3.0 % | 0.74 % | 0.00 % |
| LRU throughput, uniform (ops/s) | 12,489 | 14,638 | 15,471 (+24 %) |
| LRU throughput, skewed (ops/s) | 13,805 | 16,192 | 19,197 (+39 %) |
| HCC (auto) throughput, uniform | 12,608 | 12,302 | 12,779 (no effect) |

* HyperClockCache has no priority pools: its miss counts for the three ratios
  differ by at most 1.2e-4 of the accesses, the same as between repetitions.
  Index and filter blocks only start with a higher CLOCK countdown (3 vs 2).
  Its index/filter miss ratios (16.6 % / 2.6 %) are close to LRU with ratio 0.
* With LRU, a larger high-priority pool keeps more of the 35 MB of index and
  filter blocks resident. At ratio 0.5 the pool is 32 MB, a little less than
  the metadata, so 4.9 % of index lookups still miss; at ratio 1 they
  practically never miss.

## E1 — cache size, 1 thread

| cache | uniform: HCC-auto / HCC-fixed vs LRU | skewed (x10) | index miss LRU vs HCC |
|---|---|---|---|
| 32 MB | −8.4 % / −11.3 % | −3.0 % / −3.0 % | 40.5 % vs 48.3 % |
| 128 MB | +0.5 % / −1.1 % | −4.9 % / −10.3 % | 0.01 % vs 1.2 % |
| 512 MB | +3.1 % / +0.6 % | −3.0 % / +3.8 % | ≈ 0 |
| 2 GB | +3.0 % / +8.1 % | −2.5 % / +8.6 % | 0 |

Throughput grows with cache size for all three caches (uniform: ~10K → ~21–23K
ops/s; skewed: ~10K → ~37–42K). The data-block miss ratio is set by the cache
size, not the cache type (uniform: 99.7 % at 32 MB, 60 % at 2 GB; skewed: 95 %
→ 25 %). Note for E2: at 2 GB the cache holds only ~40 % of the 4.8 GiB of data
blocks, so with uniform keys it is not "fully cached" (60 % data misses).

## E2 — threads, 2 GB cache

| | 1 thread | 2 threads | speed-up |
|---|---|---|---|
| uniform: LRU / HCC-auto / HCC-fixed (ops/s) | 21.1K / 21.7K / 22.8K | 42.8K / 43.8K / 45.2K | 2.0× for all |
| skewed: LRU / HCC-auto / HCC-fixed | 38.3K / 37.4K / 41.6K | 72.3K / 73.1K / 76.6K | 1.84–1.96× |

With 64 shards and only 2 threads, LRU's readers wait for a mutex 0.16–0.30 %
of the time, so both caches scale almost linearly here.

## E3 — shards, 1 GB cache, 2 threads (max)

| ops/s | LRU 1 | LRU 4 | LRU 16 | LRU 64 | HCC-auto 1 | HCC-auto 4 | HCC-fixed 1 | HCC-fixed 4 |
|---|---|---|---|---|---|---|---|---|
| uniform | 28.3K | 33.7K | 34.6K | 34.4K | 34.4K | 35.4K | 35.7K | 35.4K |
| skewed | 37.3K | 49.8K | 53.6K | 54.7K | 55.3K | 55.5K | 57.3K | 57.7K |

Lock wait (separate LOCKSTAT pass, reader threads of the measured phase):

| LRU shards | contended acquisitions | wait per lookup | share of thread time waiting |
|---|---|---|---|
| 1 | 16.8 % (uniform) / 15.5 % (skewed) | 4.7 / 5.0 µs | 7.0 % / 10.8 % |
| 4 | 4.5 % / 4.3 % | 1.2 / 1.3 µs | 1.9 % / 3.4 % |
| 16 | 1.4 % / 1.2 % | 0.28 / 0.26 µs | 0.5 % / 0.7 % |
| 64 | 0.46 % / 0.43 % | 0.05 / 0.09 µs | 0.1 % / 0.2 % |

LRUCache takes 13–14 mutex acquisitions per lookup at 1 GB (12–14 across the
whole lock pass): a lookup and a release for each of the ~6.5 block-cache
accesses. HyperClockCache takes none (< 1e-4 per lookup). Even with only 2
threads, a single LRU shard loses 18 % (uniform) to 32 % (skewed) of its
throughput, and the lock-wait measurement shows the contention behind it; a
single HCC shard loses nothing. The measured waiting is a third to a half of
the extra time per lookup. The rest is consistent with the extra CPU time per
lookup with one shard (+6.5 µs uniform, +9.4 µs skewed), most likely the cost
of handing the mutex between the threads. Throughput in the lock pass differed
from the main runs by a median of 2.8 % (largest: 16 %, LRU with one shard and
skewed keys), so the lock pass is used only for the wait measurements.

## E4 — skew, 64 MB cache

HyperClockCache is slower than LRU (ratio 0.5) at every skew level, with 1 and
2 threads: by 12.6–16 % with uniform keys, 6–15 % with skew. The cause is the
same as in E0: LRU's high-priority pool keeps index and filter blocks cached
(index miss ratio 4–7 % vs 7–17 % for HCC). Throughput rises with skew for
all caches from x10 on (x5 changes almost nothing; at x20 the data-block miss
ratio is 43 %).

## Summary so far

1. **Small caches (index + filter do not comfortably fit): LRUCache wins**,
   by 6–16 % at 64 MB, because its priority pool protects index and filter
   blocks; HyperClockCache's only priority mechanism (a higher initial CLOCK
   countdown) protects them much less, and `cache_high_pri_pool_ratio` does
   nothing for it.
2. **Large caches (metadata fully cached): no clear winner on 1–2 threads**;
   differences are within ±10 % and mostly within noise.
3. **Contention: HyperClockCache lookups take no lock.** LRUCache with few
   shards measurably waits on its shard mutexes even with 2 threads; with 64
   shards the wait is small at 2 threads. The many-core run (E2/E3 up to all
   cores) is needed to see where LRU's 64 shards stop being enough.
