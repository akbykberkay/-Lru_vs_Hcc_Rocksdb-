# shellcheck shell=bash
# Experiment matrices of the setup document (sourced by 04_calibrate_reads.sh
# and 05_run_experiments.sh). Each plan_E* function prints one line per
# configuration:  cache_type cache_mb shard_bits ratio threads exp_range
#
#   E0  64 MB cache; lru / auto HCC / fixed HCC; cache_high_pri_pool_ratio 0, 0.5, 1
#       (1 thread, uniform and skewed)
#   E1  cache size 32 MB, 128 MB, 512 MB, 2 GB; threads = 1; uniform and skewed
#   E2  threads 1, 2, 4, 8, ... up to #cores; cache 2 GB; uniform and skewed
#   E3  cache 1 GB, max threads; LRU with 1, 4, 16, 64 shards vs HCC with 1 and 4
#       shards (uniform and skewed)
#   E4  cache 64 MB; read_random_exp_range 0, 5, 10, 20; threads 1 and max

cfg() { echo "$1 $2 $3 $4 $5 $6"; }

plan_E0() {
  for x in 0 "$SKEW"; do
    for ratio in 0 0.5 1; do
      for ct in $CACHE_TYPES; do
        cfg "$ct" 64 "$(default_shard_bits "$ct" $((64 * MB)))" "$ratio" 1 "$x"
      done
    done
  done
}
plan_E1() {
  for x in 0 "$SKEW"; do
    for mb in 32 128 512 2048; do
      for ct in $CACHE_TYPES; do
        cfg "$ct" "$mb" "$(default_shard_bits "$ct" $((mb * MB)))" "$LRU_RATIO_DEFAULT" 1 "$x"
      done
    done
  done
}
plan_E2() {
  for x in 0 "$SKEW"; do
    for t in $(thread_series); do
      for ct in $CACHE_TYPES; do
        cfg "$ct" 2048 "$(default_shard_bits "$ct" $((2048 * MB)))" "$LRU_RATIO_DEFAULT" "$t" "$x"
      done
    done
  done
}
plan_E3() {
  for x in 0 "$SKEW"; do
    for bits in 0 2 4 6; do            # 1, 4, 16, 64 shards
      cfg lru_cache 1024 "$bits" "$LRU_RATIO_DEFAULT" "$MAX_THREADS" "$x"
    done
    for bits in 0 2; do                # 1, 4 shards
      for ct in $CACHE_TYPES; do
        [ "$ct" = lru_cache ] && continue
        cfg "$ct" 1024 "$bits" "$LRU_RATIO_DEFAULT" "$MAX_THREADS" "$x"
      done
    done
  done
}
plan_E4() {
  for t in 1 "$MAX_THREADS"; do
    for x in 0 5 10 20; do
      for ct in $CACHE_TYPES; do
        cfg "$ct" 64 "$(default_shard_bits "$ct" $((64 * MB)))" "$LRU_RATIO_DEFAULT" "$t" "$x"
      done
    done
  done
}

# Unique configuration lines of the given experiments, in plan order.
plan_lines() {
  local e
  for e in "$@"; do "plan_$e"; done | awk '!seen[$0]++'
}
