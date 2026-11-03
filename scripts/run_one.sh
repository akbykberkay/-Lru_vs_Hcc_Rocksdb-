#!/usr/bin/env bash
# One repetition of one configuration.
#
#   1. Restore the DB from the backup (every run starts from the same copy).
#   2. W run : --benchmarks=readrandom,stats                   (warm-up only)
#   3. Restore the DB again.
#   4. WM run: --benchmarks=readrandom,stats,readrandom,stats   (warm-up, then measurement)
#
# Throughput and latency (p50/p99/p99.9) are taken from the second readrandom of
# the WM run. The statistics tickers that db_bench prints are cumulative for the
# whole process and "resetstats" does not clear them, so the measured-phase
# counts are  WM - W  (setup doc: "subtract the warm-up counts"). With
# seed=42 the warm-up of both runs reads exactly the same keys.
#
# usage: run_one.sh --cache_type=T --cache_mb=N --shard_bits=B --ratio=R \
#                   --threads=N --exp_range=X --reads=N --rep=K
# env:   FORCE=1 re-runs a finished repetition; PERF=1 wraps db_bench in
#        `perf stat` (if perf is installed) to get cycles and instructions;
#        LOCKSTAT=1 preloads tools/lockstat/liblockstat.so to measure pthread
#        mutex wait time (LRUCache shard locks), also as WM - W.
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"

CACHE_TYPE="" CACHE_MB="" SHARD_BITS="" RATIO="" THREADS="" EXP_RANGE="" READS="" REP=""
for arg in "$@"; do
  case "$arg" in
    --cache_type=*) CACHE_TYPE="${arg#*=}" ;;
    --cache_mb=*)   CACHE_MB="${arg#*=}" ;;
    --shard_bits=*) SHARD_BITS="${arg#*=}" ;;
    --ratio=*)      RATIO="${arg#*=}" ;;
    --threads=*)    THREADS="${arg#*=}" ;;
    --exp_range=*)  EXP_RANGE="${arg#*=}" ;;
    --reads=*)      READS="${arg#*=}" ;;
    --rep=*)        REP="${arg#*=}" ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
for v in CACHE_TYPE CACHE_MB SHARD_BITS RATIO THREADS EXP_RANGE READS REP; do
  [ -n "${!v}" ] || { echo "missing --$(echo "$v" | tr 'A-Z' 'a-z')" >&2; exit 2; }
done
case "$CACHE_TYPE" in
  lru_cache|auto_hyper_clock_cache|fixed_hyper_clock_cache) ;;
  *) echo "cache_type must be set explicitly to lru_cache, auto_hyper_clock_cache or fixed_hyper_clock_cache" >&2; exit 2 ;;
esac
if [ "$THREADS" -gt "$MAX_THREADS" ]; then
  echo "threads=$THREADS is more than the $MAX_THREADS CPU cores (setup doc forbids this)" >&2; exit 2
fi
[ -f "$DB_BACKUP.ok" ] || { echo "no verified backup at $DB_BACKUP (run 02_load_db.sh first)" >&2; exit 1; }
if [ "${LOCKSTAT:-0}" = "1" ] && [ ! -f "$PROJ/tools/lockstat/liblockstat.so" ]; then
  echo "LOCKSTAT=1 but tools/lockstat/liblockstat.so is missing (run 01_build_rocksdb.sh)" >&2; exit 1
fi

CFG="${CACHE_TYPE}__c${CACHE_MB}M__s${SHARD_BITS}__r${RATIO}__t${THREADS}__x${EXP_RANGE}__n${READS}"
OUT="$RESULTS/raw/$CFG/rep$REP"
if [ -f "$OUT/done" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "skip (done): $CFG rep$REP"
  exit 0
fi
rm -rf "$OUT"
mkdir -p "$OUT"

CACHE_FLAGS=(
  --cache_type="$CACHE_TYPE"
  --cache_size=$((CACHE_MB * MB))
  --cache_numshardbits="$SHARD_BITS"
  --cache_high_pri_pool_ratio="$RATIO"
)
READ_FLAGS=(
  --threads="$THREADS"
  --reads="$READS"
  --read_random_exp_range="$EXP_RANGE"
)

restore_db() {
  mkdir -p "$DB_DIR"
  rsync -a --delete "$DB_BACKUP/" "$DB_DIR/"
  sync
  # Not needed with direct I/O, but harmless when allowed.
  if [ -w /proc/sys/vm/drop_caches ]; then echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true; fi
}

PERF_PREFIX=()
if [ "${PERF:-0}" = "1" ] && command -v perf >/dev/null 2>&1; then
  PERF_PREFIX=(perf stat -x, -e task-clock,cycles,instructions,context-switches,cpu-migrations)
fi

run_phase() {  # $1 = tag (w | wm), $2 = benchmark list
  local tag="$1" benchmarks="$2"
  restore_db
  local cmd=("$DB_BENCH" --db="$DB_DIR" "${COMMON_FLAGS[@]}" "${RUN_FLAGS[@]}"
             "${CACHE_FLAGS[@]}" "${READ_FLAGS[@]}" --benchmarks="$benchmarks")
  local full=("${cmd[@]}")
  if [ "${LOCKSTAT:-0}" = "1" ]; then
    full=(env LD_PRELOAD="$PROJ/tools/lockstat/liblockstat.so"
          LOCKSTAT_OUT="$OUT/$tag.lockstat.json" "${full[@]}")
  fi
  if [ "${#PERF_PREFIX[@]}" -gt 0 ]; then
    full=("${PERF_PREFIX[@]}" -o "$OUT/$tag.perf.csv" -- "${full[@]}")
  fi
  printf '%q ' "${cmd[@]}" > "$OUT/$tag.cmd"
  echo >> "$OUT/$tag.cmd"
  python3 "$PROJ/analysis/rusage_run.py" "$OUT/$tag.rusage.json" "$OUT/$tag.log" "${full[@]}" || {
    echo "db_bench failed ($tag), see $OUT/$tag.log" >&2; tail -20 "$OUT/$tag.log" "$OUT/$tag.log.err" >&2; exit 1; }
  # Full options string of this run (slides: print it into every results file).
  local opt
  opt=$(ls -v "$DB_DIR"/OPTIONS-* | tail -1)
  cp "$opt" "$OUT/$tag.OPTIONS"
  gzip -c "$DB_DIR/LOG" > "$OUT/$tag.LOG.gz"
}

start=$(date -Is)
run_phase w  "readrandom,stats"
run_phase wm "readrandom,stats,readrandom,stats"

cat > "$OUT/meta.json" <<EOF
{
  "config_id": "$CFG",
  "rep": $REP,
  "cache_type": "$CACHE_TYPE",
  "cache_mb": $CACHE_MB,
  "shard_bits": $SHARD_BITS,
  "high_pri_pool_ratio": $RATIO,
  "threads": $THREADS,
  "read_random_exp_range": $EXP_RANGE,
  "reads_per_thread": $READS,
  "max_threads": $MAX_THREADS,
  "lockstat": ${LOCKSTAT:-0},
  "host": "$(hostname)",
  "rocksdb_tag": "$ROCKSDB_TAG",
  "db_bench_sha256": "$(sha256sum "$DB_BENCH" | cut -d' ' -f1)",
  "started": "$start",
  "finished": "$(date -Is)"
}
EOF
touch "$OUT/done"
echo "done: $CFG rep$REP"
