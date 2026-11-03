# shellcheck shell=bash
# -----------------------------------------------------------------------------
# Common configuration for "Performance comparison of RocksDB's HyperClockCache
# and LRUCache" (CS 434/634 project P1).
#
# Every flag below comes from the instructor's setup document
# (project_LRUvsHCC_setup.pdf). Each db_bench invocation (load and every
# measurement run) passes ALL of these flags, because table options such as
# bloom_bits and cache_index_and_filter_blocks are not stored in the DB and
# must be given again on every open.
#
# This file is sourced by the scripts in ../scripts. Paths can be overridden
# from the environment, e.g.  DATA_ROOT=/mnt/nvme/lruhcc ./scripts/02_load_db.sh
# -----------------------------------------------------------------------------

PROJ="${PROJ:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

# RocksDB version under test (latest tagged release when the project started).
ROCKSDB_TAG="${ROCKSDB_TAG:-v11.8.1}"
ROCKSDB_SRC="${ROCKSDB_SRC:-$PROJ/rocksdb}"
DB_BENCH="${DB_BENCH:-$ROCKSDB_SRC/db_bench}"
SST_DUMP="${SST_DUMP:-$ROCKSDB_SRC/sst_dump}"
LDB="${LDB:-$ROCKSDB_SRC/ldb}"

# Data directories. They must be on ext4 or xfs (direct I/O needs O_DIRECT;
# tmpfs does not support it). Needs about 11 GB: the DB (~5.2 GB) + a backup.
DATA_ROOT="${DATA_ROOT:-$PROJ/data}"
DB_DIR="${DB_DIR:-$DATA_ROOT/db}"            # working copy used by every run
DB_BACKUP="${DB_BACKUP:-$DATA_ROOT/db_backup}"  # pristine copy made after the load

RESULTS="${RESULTS:-$PROJ/results}"

# ---------------------------------------------------------------- LSM (setup doc)
LSM_FLAGS=(
  --write_buffer_size=4194304                  # Write buffer = 4 MB
  --target_file_size_base=1048576              # SST file size = 1 MB
  --level0_file_num_compaction_trigger=4       # files in L0 = 4
  --max_bytes_for_level_multiplier=2           # size ratio = 2
  --max_bytes_for_level_base=33554432          # L1 = 4 MB * 4 * 2 = 32 MB
  --level_compaction_dynamic_level_bytes=false
  --num_levels=9
  --disable_wal=true
  --cache_index_and_filter_blocks=true
  --block_size=4096                            # 4 KB blocks
  --bloom_bits=10                              # Bloom filter bits per key
  --compression_type=none
  --use_direct_reads=true                      # direct I/O for reads
  --use_direct_io_for_flush_and_compaction=true
)

# ----------------------------------------------------------- Workload (setup doc)
NUM_KEYS="${NUM_KEYS:-10000000}"               # 10M keys -> ~5 GB tree
WORKLOAD_FLAGS=(
  --num="$NUM_KEYS"
  --key_size=64
  --value_size=440
)

# -------------------------------------------------------------- Other (setup doc)
OTHER_FLAGS=(
  --seed=42                                    # same keys for every cache
  --statistics=1
  --histogram=1
)

COMMON_FLAGS=("${LSM_FLAGS[@]}" "${WORKLOAD_FLAGS[@]}" "${OTHER_FLAGS[@]}")

# Flags for every measurement run on the backed-up DB (setup doc: "reuse the
# same copy for every run (use_existing_db=true, disable_auto_compactions=true)").
RUN_FLAGS=(
  --use_existing_db=true
  --disable_auto_compactions=true
)

# ------------------------------------------------------------- Machine limits
# "Threads never more than the number of CPU cores": physical cores by default.
physical_cores() {
  local n
  n=$(lscpu -p=Core,Socket 2>/dev/null | grep -v '^#' | sort -u | wc -l)
  if [ -z "$n" ] || [ "$n" -eq 0 ]; then n=$(nproc); fi
  echo "$n"
}
MAX_THREADS="${MAX_THREADS:-$(physical_cores)}"

# Thread counts for E2: 1, 2, 4, 8, ... and finally MAX_THREADS itself.
thread_series() {
  local t=1 out=()
  while [ "$t" -lt "$MAX_THREADS" ]; do out+=("$t"); t=$((t * 2)); done
  out+=("$MAX_THREADS")
  echo "${out[@]}"
}

# Repetitions per configuration (setup doc: "Repeat each run 3 times").
REPS="${REPS:-3}"

# The three cache implementations compared in every experiment.
CACHE_TYPES="${CACHE_TYPES:-lru_cache auto_hyper_clock_cache fixed_hyper_clock_cache}"

# LRU high-priority pool ratio used everywhere except the ratio sweep
# (setup doc: "LRU: cache_type=lru_cache, cache_high_pri_pool_ratio=0.5").
LRU_RATIO_DEFAULT=0.5

# Default number of shard bits, set explicitly on every run (setup doc: "Always
# set cache_numshardbits explicitly"). These reproduce RocksDB 11.8's own
# defaults (cache/sharded_cache.cc, GetDefaultCacheShardBits):
#   LRUCache:        one shard per 512 KB, at most 64 shards -> 6 bits for >= 32 MB
#   HyperClockCache: one shard per 32 MB,  at most 64 shards
default_shard_bits() {  # $1 = cache_type, $2 = capacity in bytes
  local type="$1" cap="$2" min_shard bits=0
  if [ "$type" = "lru_cache" ]; then min_shard=$((512 * 1024)); else min_shard=$((32 * 1024 * 1024)); fi
  local n=$((cap / min_shard))
  while [ "$bits" -lt 6 ] && [ "$n" -ge 2 ]; do n=$((n >> 1)); bits=$((bits + 1)); done
  echo "$bits"
}

MB=$((1024 * 1024))
GB=$((1024 * MB))

# "Skewed" in E0-E3 (the setup doc lists 5, 10, 20 as increasing skew; E4 sweeps all).
SKEW="${SKEW:-10}"

# Lookups per thread (db_bench --reads; the warm-up and the measured phase each
# do this many). Chosen per experimental point (cache size, threads, skew) by
# scripts/04_calibrate_reads.sh, which writes $READS_FILE:
#   reads = max(lookups a uniform warm-up needs to fill the cache,
#               fastest throughput at that point x TARGET_SECONDS)
# All cache types at a point get the same value, so they see the same keys.
READS_FILE="${READS_FILE:-$RESULTS/reads.tsv}"
reads_for_point() {  # $1 = cache MB, $2 = threads, $3 = read_random_exp_range
  if [ -n "${READS_FIXED:-}" ]; then echo "$READS_FIXED"; return; fi
  [ -f "$READS_FILE" ] || { echo "missing $READS_FILE: run scripts/04_calibrate_reads.sh" >&2; return 1; }
  local r
  r=$(awk -F'\t' -v m="$1" -v t="$2" -v x="$3" 'NR>1 && $1==m && $2==t && $3==x {print $4}' "$READS_FILE")
  [ -n "$r" ] || { echo "no reads for cache=${1}MB threads=$2 exp_range=$3 in $READS_FILE" >&2; return 1; }
  echo "$r"
}
