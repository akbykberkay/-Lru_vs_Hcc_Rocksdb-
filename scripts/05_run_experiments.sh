#!/usr/bin/env bash
# Run the experiments of the setup document.
#
#   E0  64 MB cache; lru / auto HCC / fixed HCC; cache_high_pri_pool_ratio 0, 0.5, 1
#       (1 thread, uniform and skewed)
#   E1  cache size 32 MB, 128 MB, 512 MB, 2 GB; threads = 1; uniform and skewed
#   E2  threads 1, 2, 4, 8, ... up to #cores; cache 2 GB; uniform and skewed
#   E3  cache 1 GB, max threads; LRU with 1, 4, 16, 64 shards vs HCC with 1 and 4
#       shards (uniform and skewed)
#   E4  cache 64 MB; read_random_exp_range 0, 5, 10, 20; threads 1 and max
#
# Every configuration is repeated $REPS (3) times. Repetitions are interleaved
# (repetition 1 of every configuration, then 2, then 3), configurations shared
# by two experiments run once, and finished repetitions are skipped, so the
# script can be stopped and started again at any time.
#
# usage: 05_run_experiments.sh [--dry-run] [E0 E1 E2 E3 E4]   (default: all)
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"

DRY=0
EXPS=()
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    E0|E1|E2|E3|E4) EXPS+=("$a") ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
[ "${#EXPS[@]}" -gt 0 ] || EXPS=(E0 E1 E2 E3 E4)

source "$(dirname "$0")/../config/plan.sh"

# MIN_THREADS=2 keeps only multi-threaded configurations (used for the lock-wait pass).
mapfile -t PLAN < <(plan_lines "${EXPS[@]}" | awk -v m="${MIN_THREADS:-1}" '$5 >= m')

echo "experiments: ${EXPS[*]}  configurations: ${#PLAN[@]}  repetitions: $REPS  max threads: $MAX_THREADS  skewed=x$SKEW"
if [ "$DRY" = 1 ]; then
  for line in "${PLAN[@]}"; do
    read -r ct mb bits ratio t x <<< "$line"
    printf '%-26s %5s MB  bits=%s  ratio=%-4s threads=%-3s exp_range=%-3s reads=%s\n' \
      "$ct" "$mb" "$bits" "$ratio" "$t" "$x" "$(reads_for_point "$mb" "$t" "$x" 2>/dev/null || echo '?')"
  done
  exit 0
fi

mkdir -p "$RESULTS"
LOGF="$RESULTS/progress.log"
# Optional stop conditions, checked before each run (the current run always
# finishes): STOP_AFTER_MIN=<minutes from now>, or create the file $RESULTS/STOP.
STOP_AT=""
if [ -n "${STOP_AFTER_MIN:-}" ]; then STOP_AT=$(( $(date +%s) + STOP_AFTER_MIN * 60 )); fi
total=$(( ${#PLAN[@]} * REPS )); n=0
for rep in $(seq 1 "$REPS"); do
  for line in "${PLAN[@]}"; do
    read -r ct mb bits ratio t x <<< "$line"
    n=$((n + 1))
    if [ -e "$RESULTS/STOP" ] || { [ -n "$STOP_AT" ] && [ "$(date +%s)" -ge "$STOP_AT" ]; }; then
      echo "$(date -Is) stopping before run $n/$total (time limit or STOP file); rerun to resume" | tee -a "$LOGF"
      exit 0
    fi
    reads=$(reads_for_point "$mb" "$t" "$x")
    echo "$(date -Is) [$n/$total] rep$rep $ct ${mb}MB bits=$bits ratio=$ratio t=$t x=$x reads=$reads" | tee -a "$LOGF"
    "$PROJ/scripts/run_one.sh" --cache_type="$ct" --cache_mb="$mb" --shard_bits="$bits" \
      --ratio="$ratio" --threads="$t" --exp_range="$x" --reads="$reads" --rep="$rep" 2>&1 | tee -a "$LOGF"
  done
done
echo "$(date -Is) all done" | tee -a "$LOGF"
