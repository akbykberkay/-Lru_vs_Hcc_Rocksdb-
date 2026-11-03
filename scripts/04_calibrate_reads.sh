#!/usr/bin/env bash
# Choose --reads (lookups per thread) for every experimental point on THIS machine.
#
# For each point (cache size, threads, read_random_exp_range) of the plan, run
# readrandom twice in one db_bench process (warm-up, then measure) with
# LRUCache and with auto HyperClockCache, and record the throughput of the
# second phase. analysis/choose_reads.py then sets
#   reads = max(lookups a uniform warm-up needs to fill the cache,
#               fastest throughput at the point x TARGET_SECONDS)
# and writes $READS_FILE. Every cache type at a point uses the same value.
#
# usage: 04_calibrate_reads.sh [E0 E1 E2 E3 E4]      (TARGET_SECONDS=10 by default)
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"
source "$(dirname "$0")/../config/plan.sh"

TARGET_SECONDS="${TARGET_SECONDS:-10}"
EXPS=("$@")
[ "${#EXPS[@]}" -gt 0 ] || EXPS=(E0 E1 E2 E3 E4)
SUMMARY="$RESULTS/load/db_summary.json"
[ -f "$DB_BACKUP.ok" ] && [ -f "$SUMMARY" ] || { echo "run 02_load_db.sh first" >&2; exit 1; }
CAL="$RESULTS/calibration"
mkdir -p "$CAL"

mapfile -t POINTS < <(plan_lines "${EXPS[@]}" | awk '{print $2, $5, $6}' | awk '!seen[$0]++')
echo "calibrating ${#POINTS[@]} points (target ${TARGET_SECONDS}s per phase)"
for p in "${POINTS[@]}"; do
  read -r mb t x <<< "$p"
  fill=$(python3 "$PROJ/analysis/choose_reads.py" fill "$SUMMARY" "$mb")
  reads=$(( (fill + t - 1) / t ))
  for ct in lru_cache auto_hyper_clock_cache; do
    log="$CAL/${mb}_${t}_${x}__${ct}.log"
    if [ -f "$log" ] && grep -q "^STATISTICS:" "$log"; then continue; fi
    rsync -a --delete "$DB_BACKUP/" "$DB_DIR/"
    "$DB_BENCH" --db="$DB_DIR" "${COMMON_FLAGS[@]}" "${RUN_FLAGS[@]}" \
      --cache_type="$ct" --cache_size=$((mb * MB)) \
      --cache_numshardbits="$(default_shard_bits "$ct" $((mb * MB)))" \
      --cache_high_pri_pool_ratio="$LRU_RATIO_DEFAULT" \
      --threads="$t" --reads="$reads" --read_random_exp_range="$x" \
      --benchmarks=readrandom,readrandom > "$log" 2> "$log.err"
    echo "$(date +%T) ${mb}MB t=$t x=$x $ct: $(grep '^readrandom' "$log" | tail -1 | awk '{print $5, "ops/s"}')"
  done
done
python3 "$PROJ/analysis/choose_reads.py" choose "$SUMMARY" "$CAL" "$READS_FILE" "$TARGET_SECONDS"
echo "wrote $READS_FILE"
