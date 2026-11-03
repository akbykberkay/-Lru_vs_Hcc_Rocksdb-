# Requirement trace: setup document → implementation

Every line of `project_LRUvsHCC_setup.pdf`, and the two requirements from the
lecture slides, with where and how this project implements it.

## LSM configuration

| Setup document | db_bench flag used | Where |
|---|---|---|
| Write buffer size = 4 MB | `--write_buffer_size=4194304` | `config/common.sh` (LSM_FLAGS) |
| SST file size = 1 MB | `--target_file_size_base=1048576` | same |
| Files in level 0 = 4 | `--level0_file_num_compaction_trigger=4` | same |
| Size ratio = 2 | `--max_bytes_for_level_multiplier=2` | same |
| Size of L1 = 4 MB × 4 × 2 = 32 MB | `--max_bytes_for_level_base=33554432` | same |
| level_compaction_dynamic_level_bytes = false | `--level_compaction_dynamic_level_bytes=false` | same |
| num_levels (9 should work) | `--num_levels=9` (L1..L8 hold 8 GB > 5 GB; checked after the load) | same, `analysis/verify_db.py` |
| disable_wal = true | `--disable_wal=true` | same |
| cache_index_and_filter_blocks = true | `--cache_index_and_filter_blocks=true` | same |
| Block size = 4 KB | `--block_size=4096` | same |
| Bloom bits per key = 10 | `--bloom_bits=10` | same |
| Compression disabled | `--compression_type=none` | same |
| Direct I/O when measuring | `--use_direct_reads=true --use_direct_io_for_flush_and_compaction=true` | same |

All of these flags are passed on **every** db_bench invocation (load and all
runs). Table options such as `bloom_bits` and `cache_index_and_filter_blocks`
are not stored in the DB; if a run omitted them, the DB would be read without
filters or with index/filter blocks outside the cache.

## Workload

| Setup document | Implementation |
|---|---|
| Key 64 B, value 440 B | `--key_size=64 --value_size=440` |
| Bulk load 10M with filluniquerandom (~5 GB) | `scripts/02_load_db.sh`: `--benchmarks=filluniquerandom,flush,waitforcompaction,levelstats,stats --num=10000000 --threads=1` |
| Then waitforcompaction | as above. `flush` comes first because the WAL is disabled: without it, the last memtable is only flushed when the DB closes, *after* waitforcompaction returned, leaving an un-compacted L0 file. (`WaitForCompact` does not flush by default.) |
| Back up the DB and reuse the same copy for every run (use_existing_db=true, disable_auto_compactions=true) | backup made by `02_load_db.sh` after verification; `scripts/run_one.sh` restores the working copy from it (rsync) before **each** db_bench invocation and passes `--use_existing_db=true --disable_auto_compactions=true` |
| Lookups = readrandom; reads is per thread | `--benchmarks=readrandom`, `--reads=<per thread>`; the parser checks that measured operations = threads × reads. The value is chosen per point (cache size, threads, skew) by `scripts/04_calibrate_reads.sh` so that the warm-up fills the cache and every phase lasts ≥ 10 s; all cache types at a point use the same value |
| Skew = read_random_exp_range (0 uniform; 5, 10, 20) | `--read_random_exp_range`; E4 sweeps 0/5/10/20; "skewed" elsewhere = 10 |

## Cache configurations

| Setup document | Implementation |
|---|---|
| LRU: cache_type=lru_cache, cache_high_pri_pool_ratio=0.5 | every LRU run except the ratio sweep uses 0.5 |
| HCC: auto_hyper_clock_cache / fixed_hyper_clock_cache | both variants are run in every experiment |
| Always set cache_type explicitly | `run_one.sh` refuses to run without one of the three explicit types; the load sets it too |
| Always set cache_numshardbits explicitly | always passed. E3 uses the listed values; elsewhere the value equals RocksDB 11.8's own default for that cache and size (LRU: 6 bits = 64 shards; HCC: one shard per 32 MB, i.e. 32 MB→1, 64 MB→2, 128 MB→4, 512 MB→16, 2 GB→64 shards) |
| Block cache = 64 MB with lru / auto HCC / fixed HCC, ratio 0, 0.5, 1 | experiment E0 (all 3 × 3 combinations, 1 thread, uniform and skewed). HCC has no priority pools, so its three ratio runs should be identical: a built-in sanity check |

## Other

| Setup document | Implementation |
|---|---|
| seed=42 | `--seed=42` on every invocation (also gives the cache hash seed 42) |
| Threads never more than CPU cores | `MAX_THREADS` = physical cores; `run_one.sh` refuses more |
| Repeat each run 3 times | `REPS=3`; repetitions interleaved (all configs once, then again, then again) |
| statistics=1, histogram=1 | on every invocation |

## Metrics

| Setup document | How it is computed |
|---|---|
| Throughput (ops/s) | `ops/sec` of the **second** readrandom (the measured phase) |
| Read latency p50, p99, p99.9 | from the measured readrandom's `--histogram` output (only that phase) |
| Block cache miss ratio split by data, index, filter | `miss / (hit + miss)` from `rocksdb.block.cache.{data,index,filter}.{hit,miss}`, measured phase only (see notes) |

Also recorded: misses per lookup, CPU µs per lookup and context switches per
lookup (rusage, warm-up subtracted), bytes read from disk per lookup, block-cache
usage and its split into data/index/filter blocks after warm-up and after the
measured phase, and the cache settings RocksDB actually applied (from its LOG).

## Experiments

| Setup document | Implementation (`scripts/03_run_experiments.sh`) |
|---|---|
| E1: cache 32 MB, 128 MB, 512 MB, 2 GB; 1 thread; uniform and skewed | as written × 3 cache types |
| E2: threads 1, 2, 4, 8, … up to #cores; 2 GB; uniform and skewed | powers of two below #cores, plus #cores itself |
| E3: LRU 1, 4, 16, 64 shards vs HCC 1 and 4 shards; 1 GB; max threads | as written, both HCC variants, uniform and skewed |
| E4: exp_range 0, 5, 10, 20; 64 MB; threads 1 and max | as written × 3 cache types |

## Notes from the setup document

| Setup document | Implementation |
|---|---|
| Warm-up: run lookups once before measuring | each measurement run is `readrandom,stats,readrandom,stats`; the first readrandom is the warm-up, with the same number of lookups |
| Counters are cumulative and resetstats does not clear them, so subtract the warm-up counts | db_bench prints the tickers only once, when it exits, so the warm-up counts come from a second, warm-up-only invocation (`readrandom,stats`) on the same restored DB with the same seed. Measured = WM − W. With 1 thread the two warm-ups read the same keys in the same order, so the subtraction is exact; with several threads it is approximate (thread interleaving differs), and the spread of the W counts across repetitions is reported to bound the error |

## Lecture slides (Lecture 4, "P1: HyperClockCache vs. LRUCache"; Lecture 5-1)

| Slide | Implementation |
|---|---|
| "Measure: throughput, p99 and p999 latency, hit rate, CPU cycles per operation, and lock wait time. Without the last one you cannot claim contention was the cause." | throughput, p99, p99.9 and miss ratios in every run. CPU per operation: user + system CPU time of the measured phase (rusage, WM − W) per lookup; with `PERF=1` on a machine with hardware counters also cycles and instructions (`perf stat`, WM − W). The cloud VM used for the first runs exposes no hardware counters, so there it is CPU time. Lock wait time: `LOCKSTAT=1` preloads `tools/lockstat/liblockstat.so`, which times every contended `pthread_mutex_lock` per thread (the LRUCache shard mutexes; HyperClockCache lookups take none). db_bench starts new reader threads for each benchmark, so the measured phase's lock waits are the counters of its own reader threads (the last T threads of the WM run); this excludes the DB-open noise. It runs as a separate pass so the instrumentation cannot bias the main measurements |
| "State the RocksDB version and print the full options string into every results file" | every run directory has the db_bench output (starts with `RocksDB: version 11.8.1`), the exact command line, the OPTIONS file of that run and its LOG (which lists the applied block-cache settings); `results/build_info.txt` has the commit and compiler flags |
| "Report both hit rate and throughput" | both are in every table and figure |
