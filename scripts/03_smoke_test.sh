#!/usr/bin/env bash
# Quick end-to-end check of the measurement pipeline (a few minutes).
# Runs tiny versions of a few configurations into results_smoke/ (kept apart
# from the real results), parses them and prints the key numbers.
#   * 1-thread runs of each cache type: the W and WM warm-ups must match exactly
#   * one run with MAX_THREADS threads
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"
export RESULTS="$PROJ/results_smoke"
rm -rf "$RESULTS"
mkdir -p "$RESULTS"
R=${SMOKE_READS:-20000}
for ct in lru_cache auto_hyper_clock_cache fixed_hyper_clock_cache; do
  "$PROJ/scripts/run_one.sh" --cache_type="$ct" --cache_mb=64 \
    --shard_bits="$(default_shard_bits "$ct" $((64 * MB)))" --ratio=0.5 \
    --threads=1 --exp_range=0 --reads="$R" --rep=1
done
"$PROJ/scripts/run_one.sh" --cache_type=lru_cache --cache_mb=64 --shard_bits=6 --ratio=0.5 \
  --threads="$MAX_THREADS" --exp_range=10 --reads="$R" --rep=1
python3 "$PROJ/analysis/parse_runs.py" "$RESULTS"
python3 - "$RESULTS/csv/runs.csv" <<'EOF'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
cols = ["cache_type", "threads", "read_random_exp_range", "throughput_ops", "lat_p50_us",
        "lat_p99_us", "lat_p999_us", "data_miss_ratio", "index_miss_ratio",
        "filter_miss_ratio", "block_cache_name", "applied_shard_bits",
        "applied_use_direct_reads", "cache_fill_after_warmup"]
for r in rows:
    print("  ".join(f"{c}={r.get(c, '')[:10]}" for c in cols))
EOF
