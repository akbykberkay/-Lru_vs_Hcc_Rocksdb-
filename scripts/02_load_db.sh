#!/usr/bin/env bash
# Bulk-load the database once, verify it, and back it up (setup doc, "Workload").
#
#   filluniquerandom  10M keys (64 B keys, 440 B values) -> ~5 GB tree
#   flush             the WAL is disabled, so the last memtable must be flushed
#                     explicitly; otherwise it is only flushed when the DB
#                     closes, after waitforcompaction has already returned
#   waitforcompaction wait until all compactions are finished
#   levelstats, stats print the final shape of the LSM tree
#
# Then: verify the tree (scripts/verify_db.sh), and copy it to $DB_BACKUP.
# Every measurement run restores $DB_DIR from that backup.
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"

mkdir -p "$RESULTS/load" "$DATA_ROOT"
fs=$(df -T "$DATA_ROOT" | awk 'NR==2{print $2}')
case "$fs" in
  ext4|xfs) ;;
  *) echo "WARNING: $DATA_ROOT is on '$fs'; direct I/O needs ext4 or xfs" >&2 ;;
esac
need=$(( (NUM_KEYS * 504 / 1000000000 + 1) * 2 + 2 ))
avail=$(df -BG --output=avail "$DATA_ROOT" | tail -1 | tr -dc '0-9')
if [ "$avail" -lt "$need" ]; then
  echo "ERROR: need about ${need} GB free in $DATA_ROOT, only ${avail} GB available" >&2; exit 1
fi
# ~5,000 SST files are kept open (max_open_files=-1).
if [ "$(ulimit -n)" -lt 10000 ]; then
  ulimit -n 65536 2>/dev/null || { echo "ERROR: raise the open-file limit (ulimit -n 65536)" >&2; exit 1; }
fi

rm -rf "$DB_DIR" "$DB_BACKUP" "$DB_BACKUP.ok"
mkdir -p "$DB_DIR"

LOAD_CACHE_FLAGS=(  # the cache barely matters for the load, but is still set explicitly
  --cache_type=lru_cache
  --cache_size=$((64 * MB))
  --cache_numshardbits=6
  --cache_high_pri_pool_ratio=0.5
)
cmd=("$DB_BENCH" --db="$DB_DIR" "${COMMON_FLAGS[@]}" "${LOAD_CACHE_FLAGS[@]}"
     --use_existing_db=false --threads=1
     --benchmarks=filluniquerandom,flush,waitforcompaction,levelstats,stats)
printf '%q ' "${cmd[@]}" > "$RESULTS/load/load.cmd"; echo >> "$RESULTS/load/load.cmd"
echo "loading $NUM_KEYS keys into $DB_DIR ..."
python3 "$PROJ/analysis/rusage_run.py" "$RESULTS/load/load.rusage.json" "$RESULTS/load/load.log" "${cmd[@]}"
cp "$(ls -v "$DB_DIR"/OPTIONS-* | tail -1)" "$RESULTS/load/load.OPTIONS"
gzip -c "$DB_DIR/LOG" > "$RESULTS/load/load.LOG.gz"
grep -E "^filluniquerandom|waitforcompaction" "$RESULTS/load/load.log" || true

"$PROJ/scripts/verify_db.sh"

echo "backing up to $DB_BACKUP ..."
rsync -a --delete "$DB_DIR/" "$DB_BACKUP/"
(cd "$DB_BACKUP" && ls -l --time-style=+ | awk 'NR>1{print $5, $NF}' > "$RESULTS/load/backup_manifest.txt")
cp "$RESULTS/load/db_summary.json" "$DB_BACKUP.ok"   # marker: verified backup
echo "backup ready: $(du -sh "$DB_BACKUP" | cut -f1)"
