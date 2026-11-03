#!/usr/bin/env bash
# Pack the project (code + results, without the DB, the RocksDB tree and binaries)
# into lru_vs_hcc_<host>_<date>.tar.gz next to the project folder.
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"
name="lru_vs_hcc_$(hostname)_$(date +%Y%m%d)"
out="$(dirname "$PROJ")/$name.tar.gz"
tar -C "$(dirname "$PROJ")" -czf "$out" \
  --exclude="$(basename "$PROJ")/rocksdb" \
  --exclude="$(basename "$PROJ")/data" \
  --exclude="$(basename "$PROJ")/results_smoke" \
  --exclude="*.so" \
  --exclude="__pycache__" \
  "$(basename "$PROJ")"
echo "$out ($(du -h "$out" | cut -f1))"
